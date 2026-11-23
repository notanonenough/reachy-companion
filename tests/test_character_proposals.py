"""Draft -> real GitHub API protocol -> explicit owner apply, without live credentials."""
import base64
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from urllib.parse import urlsplit

from reachy_companion.autonomous.character_proposals import CharacterProposals,GitHub,canonical
from reachy_companion.autonomous.config import load
from reachy_companion.autonomous.durable import DurableStore
from reachy_companion.autonomous.runtime import Scheduler
from reachy_companion.autonomous.gateway import fast_schema
from jsonschema import Draft202012Validator,ValidationError

ROOT=Path(__file__).resolve().parents[1]
REPO='owner/companion'


class Remote(GitHub):
    def __init__(self):
        self.refs={};self.files={};self.pr=None;self.calls=[];self.fail_after=None

    def api(self,route,*,method='GET',body=None):
        self.calls.append((route,method,copy.deepcopy(body)))
        path=urlsplit(route).path;prefix='repos/'+REPO
        if path==prefix+'/git/ref/heads/main':result={'object':{'sha':'a'*40}}
        elif '/git/matching-refs/' in path:
            result=[{'ref':'refs/heads/'+key,'object':{'sha':value}} for key,value in self.refs.items()]
        elif path==prefix+'/git/refs':
            branch=body['ref'].removeprefix('refs/heads/')
            if branch in self.refs:raise AssertionError('Duplicate branch')
            self.refs[branch]=body['sha'];result={}
        elif '/contents/' in path:
            filename=path.split('/contents/')[1]
            if method=='PUT':
                if filename in self.files:raise AssertionError('Duplicate file commit')
                self.files[filename]=base64.b64decode(body['content']);self.refs[body['branch']]='b'*40
                result={'commit':{'sha':'b'*40}}
            else:result={'encoding':'base64','size':len(self.files[filename]),'content':base64.b64encode(self.files[filename]).decode()}
        elif path==prefix+'/pulls':
            if method=='POST':
                if self.pr:raise AssertionError('Duplicate PR')
                self.pr={'number':42,'merged':False,'state':'open',
                    'head':{'sha':self.refs[body['head']],'ref':body['head'],'repo':{'full_name':REPO}},
                    'base':{'ref':'main','repo':{'full_name':REPO}}}
                result=self.pr
            else:result=[self.pr] if self.pr else []
        elif path==prefix+'/pulls/42':result=self.pr
        elif path==prefix+'/pulls/42/files':result=[{'filename':name,'status':'added'} for name in self.files]
        else:raise AssertionError(route)
        if self.fail_after==method+':'+path:
            self.fail_after=None;raise TimeoutError('Remote completed but response was lost')
        return copy.deepcopy(result)


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.sqlite3'
        self.store=DurableStore(self.path);self.addCleanup(self.store.close)
        self.proposals=CharacterProposals(self.store);self.remote=Remote()
        self.proposal={'patch':{'personality':'Curious companion'},'reason':'Proposed conversational style'}

    def draft(self):return self.proposals.draft(self.proposal)

    def merged(self):
        identity=self.draft();self.proposals.publish(identity,REPO,self.remote)
        self.remote.pr['merged']=True;self.remote.pr['state']='closed'
        return identity

    def test_model_path_creates_only_bounded_local_draft(self):
        cfg=load(ROOT/'config.autonomous.normal.example.json')
        scheduler=Scheduler(cfg,SimpleNamespace(boot_id='test-mac'));scheduler.enable_production(self.store)
        try:
            now=time.monotonic();state=scheduler.state;before=self.store.current()
            value={'a':'think','why':'a proposal','propose_character':self.proposal}
            Draft202012Validator(fast_schema(state.snapshot(now))).validate(value)
            state.apply(value,state.bind(now,1),now)
            self.assertEqual(self.store.current(),before)
            rows=self.proposals.listing();self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['status'],'draft')
            self.assertEqual(self.draft(),rows[0]['id'])
            for bad in ({'patch':{'memory':'private'},'reason':'wrong capability'},
                        {'patch':{'personality':'x'*513},'reason':'too long'},
                        {'patch':{'personality':'x'},'reason':'ok','owner':True}):
                with self.assertRaises(ValidationError):self.proposals.draft(bad)
            state.privacy=True
            with self.assertRaises(ValueError):scheduler.services.propose_character(self.proposal)
            self.assertNotIn('propose_character',fast_schema(state.snapshot(now))['properties'])
        finally:
            # The store has its own cleanup; release the runtime lock without closing twice.
            self.store.owner.close();self.store.owner=None

    def test_publish_is_real_pr_protocol_and_exports_only_proposal(self):
        self.store.update({'memory':'PRIVATE MEMORY','principles':'PRIVATE PRINCIPLES'},0,'owner seed')
        before=self.store.current();identity=self.draft()
        item=self.proposals.publish(identity,REPO,self.remote)
        self.assertEqual(item['status'],'published');self.assertEqual(item['pr'],42)
        self.assertEqual(self.store.current(),before)
        content=json.loads(next(iter(self.remote.files.values())))
        self.assertEqual(content,{'id':identity,**self.proposal})
        wire=json.dumps(self.remote.calls)
        for excluded in ('PRIVATE MEMORY','PRIVATE PRINCIPLES','base_digest','expected_revision','reviewers','merge'):
            # The static PR body explains that the owner may merge; no merge API is issued.
            if excluded!='merge':self.assertNotIn(excluded,wire)
        self.assertFalse(any('/merge' in route or '/requested_reviewers' in route for route,_,_ in self.remote.calls))
        count=len(self.remote.calls);self.proposals.publish(identity,REPO,self.remote)
        self.assertEqual(len(self.remote.calls),count)
        with self.assertRaises(ValueError):self.proposals.publish(identity,'someone/else',self.remote)

    def test_unknown_publication_outcomes_reconcile_without_duplicates(self):
        for stage in ('branch','file','pr'):
            with self.subTest(stage=stage):
                # Each proposal gets an isolated remote but uses the same durable lifecycle.
                self.proposal['reason']='retry '+stage;identity=self.draft();remote=Remote()
                route={'branch':'POST:repos/'+REPO+'/git/refs',
                       'file':'PUT:repos/'+REPO+'/contents/'+remote.path(identity),
                       'pr':'POST:repos/'+REPO+'/pulls'}[stage]
                remote.fail_after=route
                with self.assertRaises(TimeoutError):self.proposals.publish(identity,REPO,remote)
                self.assertEqual(self.proposals.get(identity)['status'],'publishing')
                reopened=DurableStore(self.path)
                try:item=CharacterProposals(reopened).publish(identity,REPO,remote)
                finally:reopened.close()
                self.assertEqual(item['pr'],42)
                self.assertEqual(len(remote.refs),1);self.assertEqual(len(remote.files),1)
                self.assertEqual(sum(method=='POST' and path=='repos/'+REPO+'/pulls' for path,method,_ in remote.calls),1)

    def test_apply_preserves_new_memory_goal_and_unaffected_profile_and_is_idempotent(self):
        identity=self.merged()
        goal={'id':'goal','version':0,'text':'Watch room','changed_at':'2026-11-23T17:00:00Z',
              'reason':'owner','evidence_ids':[],'origin':'agent'}
        self.store.update({'memory':'new memory','principles':'owner changed another field','goal':goal},0,'ongoing session')
        revision=self.proposals.apply(identity,self.remote)
        self.assertEqual(revision,2)
        profile=self.store.current()[1]
        self.assertEqual(profile['personality'],self.proposal['patch']['personality'])
        self.assertEqual(profile['memory'],'new memory');self.assertEqual(profile['goal'],goal)
        self.assertEqual(profile['principles'],'owner changed another field')
        calls=len(self.remote.calls)
        self.assertEqual(self.proposals.apply(identity,self.remote),2)
        self.assertEqual(len(self.remote.calls),calls);self.assertEqual(self.store.current()[0],2)

    def test_rejects_open_closed_unmerged_head_content_extra_files_and_stale_profile(self):
        identity=self.merged();original=copy.deepcopy(self.remote.pr);before=self.store.current()
        for mutation in ('open','closed','head','content','extra','base','repo'):
            with self.subTest(mutation=mutation):
                self.remote.pr=copy.deepcopy(original);files=copy.deepcopy(self.remote.files)
                if mutation in ('open','closed'):
                    self.remote.pr.update(merged=False,state=mutation)
                elif mutation=='head':self.remote.pr['head']['sha']='c'*40
                elif mutation=='base':self.remote.pr['base']['ref']='other'
                elif mutation=='repo':self.remote.pr['head']['repo']['full_name']='other/repo'
                elif mutation=='extra':self.remote.files['extra.txt']=b'no'
                else:self.remote.files[self.remote.path(identity)]=canonical({'id':identity,'patch':{'personality':'changed'},'reason':'tampered'})
                with self.assertRaises(ValueError):self.proposals.apply(identity,self.remote)
                self.assertEqual(self.store.current(),before)
                self.remote.files=files
        self.remote.pr=original
        self.store.update({'personality':'owner correction'},0,'owner')
        with self.assertRaisesRegex(ValueError,'stale'):self.proposals.apply(identity,self.remote)
        self.assertEqual(self.store.current()[1]['personality'],'owner correction')
        self.assertEqual(self.proposals.get(identity)['status'],'published')

    def test_runtime_lock_and_atomic_apply_marker(self):
        identity=self.merged();before=self.store.current()
        owner=DurableStore(self.path);owner.claim()
        try:
            with self.assertRaises(RuntimeError):self.proposals.apply(identity,self.remote)
            self.assertEqual(self.store.current(),before)
        finally:owner.close()
        self.store.db.execute("CREATE TRIGGER fail_apply BEFORE UPDATE OF status ON character_proposals WHEN NEW.status='applied' BEGIN SELECT RAISE(ABORT,'fixture disk failure'); END")
        with self.assertRaises(Exception):self.proposals.apply(identity,self.remote)
        self.assertEqual(self.store.current(),before)
        self.assertEqual(self.proposals.get(identity)['status'],'published')
        self.store.db.execute('DROP TRIGGER fail_apply')
        self.store.owner.close();self.store.owner=None
        self.assertEqual(self.proposals.apply(identity,self.remote),1)

    def test_publication_lock_and_saved_head_reject_tampered_retry(self):
        identity=self.draft();other=CharacterProposals(self.store)
        with self.proposals.publication_lock():
            with self.assertRaises(RuntimeError):other.publish(identity,REPO,self.remote)
        self.remote.fail_after='POST:repos/'+REPO+'/pulls'
        with self.assertRaises(TimeoutError):self.proposals.publish(identity,REPO,self.remote)
        self.assertEqual(self.proposals.get(identity)['head'],'b'*40)
        self.remote.pr['head']['sha']='c'*40
        with self.assertRaisesRegex(ValueError,'head changed'):self.proposals.publish(identity,REPO,self.remote)

    def test_capacity_and_cli_listing_do_not_publish_or_change_profile(self):
        import os,subprocess,sys
        before=self.store.current();identity=self.draft()
        for index in range(127):
            self.proposals.draft({'patch':{'principles':'Suggested value'},'reason':'bounded draft '+str(index)})
        with self.assertRaisesRegex(ValueError,'capacity'):self.proposals.draft({'patch':{'principles':'One more'},'reason':'over cap'})
        self.assertEqual(self.draft(),identity)
        result=subprocess.run([sys.executable,'-m','reachy_companion.autonomous.production',
            'list-character-proposals','--state',str(self.path)],cwd=ROOT,
            env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(json.loads(result.stdout)),128)
        self.assertEqual(self.store.current(),before)
        self.assertFalse(self.remote.calls)

    def test_gh_adapter_uses_argv_and_json_stdin(self):
        from types import SimpleNamespace
        with patch('reachy_companion.autonomous.character_proposals.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='{}')) as run:
            GitHub().api('repos/owner/repo/pulls',method='POST',body={'title':'literal $(touch nope)'})
        args,kwargs=run.call_args
        self.assertEqual(args[0],['gh','api','repos/owner/repo/pulls','--method','POST','--input','-'])
        self.assertNotIn('shell',kwargs);self.assertIn('$(touch nope)',kwargs['input'])


if __name__=='__main__':unittest.main()
