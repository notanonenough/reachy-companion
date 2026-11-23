"""Character drafts and explicit owner publication/application through GitHub PRs.

Only id, proposed fields and reason leave the local store. Publishing never
changes the profile or merges a PR. Network retries reconcile stable identities.
"""
import base64
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import quote

from .contracts import decode, uid, validate


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def digest(value):return hashlib.sha256(canonical(value)).hexdigest()


def profile_digest(profile,patch):return digest({key:profile[key] for key in patch})


class CharacterProposals:
    def __init__(self,store):self.store=store;self.db=store.db

    def draft(self,proposal):
        validate('CharacterProposal',proposal)
        proposal=decode(canonical(proposal))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            baseline=profile_digest(self.store.current()[1],proposal['patch'])
            for identity,body in self.db.execute('SELECT id,body FROM character_proposals WHERE base_digest=?',(baseline,)):
                old=decode(body)
                if old['patch']==proposal['patch'] and old['reason']==proposal['reason']:return identity
            if self.db.execute('SELECT count(*) FROM character_proposals').fetchone()[0]>=128:
                raise ValueError('Character proposal capacity reached')
            identity=uid();body=dict(id=identity,**proposal)
            self.db.execute('INSERT INTO character_proposals(id,body,base_digest,digest,status) VALUES (?,?,?,?,?)',
                (identity,canonical(body).decode(),baseline,digest(body),'draft'))
            return identity

    def get(self,identity):
        if not isinstance(identity,str) or not re.fullmatch('[0-9a-f-]{36}',identity):raise ValueError('Proposal id required')
        row=self.db.execute('SELECT body,base_digest,digest,status,repo,base_commit,head,pr,applied_revision FROM character_proposals WHERE id=?',(identity,)).fetchone()
        if row is None:raise ValueError('Unknown character proposal')
        result=dict(zip(('body','base_digest','digest','status','repo','base_commit','head','pr','applied_revision'),row))
        result['body']=decode(result['body'])
        validate('CharacterProposal',{key:result['body'][key] for key in ('patch','reason')})
        if set(result['body'])!={'id','patch','reason'} or result['body']['id']!=identity or digest(result['body'])!=result['digest']:
            raise ValueError('Local proposal content changed')
        return result

    def listing(self):
        return [dict(id=identity,status=status,proposal=decode(body))
                for identity,status,body in self.db.execute('SELECT id,status,body FROM character_proposals ORDER BY rowid')]

    @contextmanager
    def publication_lock(self):
        # Separate from the runtime owner: publication can run while perception continues.
        import fcntl
        path=self.db.execute('PRAGMA database_list').fetchone()[2]+'.character-publication'
        with open(path,'a') as lock:
            Path(path).chmod(0o600)
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as exc:raise RuntimeError('Character publication already in progress') from exc
            yield

    def publish(self,identity,repo,github):
        if not isinstance(repo,str) or not re.fullmatch('[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):
            raise ValueError('Explicit GitHub owner/repository required')
        with self.publication_lock():
            item=self.get(identity)
            if item['repo'] is not None and item['repo']!=repo:raise ValueError('Proposal repository is immutable')
            if item['status'] in ('published','applied'):return item
            if item['status']=='draft':
                # This read has no side effects. Persist its exact base before the first write.
                base=github.base(repo)
                with self.db:
                    self.db.execute("UPDATE character_proposals SET status='publishing',repo=?,base_commit=? WHERE id=? AND status='draft'",
                        (repo,base,identity))
                item=self.get(identity)
            def bind_head(head):
                current=self.get(identity)
                if current['head'] is not None and current['head']!=head:raise ValueError('Published proposal head changed')
                with self.db:self.db.execute('UPDATE character_proposals SET head=? WHERE id=?',(head,identity))
            head,number=github.publish(repo,item,bind_head)
            with self.db:
                self.db.execute("UPDATE character_proposals SET status='published',head=?,pr=? WHERE id=? AND status='publishing'",
                    (head,number,identity))
            return self.get(identity)

    def apply(self,identity,github):
        item=self.get(identity)
        if item['status']=='applied':return item['applied_revision']
        if item['status']!='published':raise ValueError('Published character PR required')
        github.verify_merged(item)
        self.store.claim()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            item=self.get(identity)
            if item['status']=='applied':return item['applied_revision']
            revision,profile=self.store.current()
            if profile_digest(profile,item['body']['patch'])!=item['base_digest']:
                raise ValueError('Character proposal is stale: an affected profile field changed')
            revision=self.store._update(item['body']['patch'],revision,item['body']['reason'])
            self.db.execute("UPDATE character_proposals SET status='applied',applied_revision=? WHERE id=?",
                (revision,identity))
            return revision


class GitHub:
    """Narrow gh API adapter. Uses JSON stdin and argv, never a shell or local checkout."""
    def api(self,route,*,method='GET',body=None):
        argv=['gh','api',route,'--method',method]
        if body is not None:argv+=['--input','-']
        result=subprocess.run(argv,input=canonical(body).decode() if body is not None else None,
            capture_output=True,text=True,timeout=30)
        if result.returncode:
            # gh may include remote response content; do not echo it into diagnostics.
            raise RuntimeError('GitHub API failed; retry the same proposal id to reconcile')
        return decode(result.stdout) if result.stdout.strip() else None

    def base(self,repo):return self.api(f'repos/{repo}/git/ref/heads/main')['object']['sha']

    @staticmethod
    def branch(identity):return 'codex/character-'+identity

    @staticmethod
    def path(identity):return 'proposals/character/'+identity+'.json'

    def contents(self,repo,head,path):
        value=self.api(f'repos/{repo}/contents/{path}?ref={quote(head,safe="")}')
        if value.get('encoding')!='base64' or value.get('size',100000)>8192:raise ValueError('Unexpected proposal file')
        return decode(base64.b64decode(value['content']))

    def find_pr(self,repo,branch):
        rows=self.api(f'repos/{repo}/pulls?state=all&head={quote(repo.split("/")[0]+":"+branch,safe="")}&base=main&per_page=100')
        if len(rows)>1:raise ValueError('Ambiguous character PR identity')
        return rows[0] if rows else None

    def publish(self,repo,item,bind_head):
        identity=item['body']['id'];branch=self.branch(identity);path=self.path(identity)
        pr=self.find_pr(repo,branch)
        if pr is not None:
            head=pr['head']['sha']
            if digest(self.contents(repo,head,path))!=item['digest']:raise ValueError('Published proposal content changed')
            bind_head(head)
            self.verify_files(repo,pr['number'],path)
            return head,pr['number']
        # Matching refs avoids treating authorization/network failure as absence.
        refs=self.api(f'repos/{repo}/git/matching-refs/heads/{branch}')
        exact=[ref for ref in refs if ref['ref']=='refs/heads/'+branch]
        if len(exact)>1:raise ValueError('Ambiguous proposal branch')
        if not exact:
            self.api(f'repos/{repo}/git/refs',method='POST',body={'ref':'refs/heads/'+branch,'sha':item['base_commit']})
            head=item['base_commit']
        else:head=exact[0]['object']['sha']
        if head==item['base_commit']:
            result=self.api(f'repos/{repo}/contents/{path}',method='PUT',body={
                'message':'Propose character change '+identity,'branch':branch,
                'content':base64.b64encode(canonical(item['body'])+b'\n').decode()})
            head=result['commit']['sha']
        if digest(self.contents(repo,head,path))!=item['digest']:raise ValueError('Published proposal content changed')
        bind_head(head)
        pr=self.find_pr(repo,branch)
        if pr is None:
            pr=self.api(f'repos/{repo}/pulls',method='POST',body={
                'title':'Character proposal '+identity,'head':branch,'base':'main',
                'body':'Proposed character fields are in the single JSON file. The owner may merge or close this PR. Submission does not change the active profile; application is explicit.'})
        if pr['head']['sha']!=head:raise ValueError('PR head changed during publication')
        self.verify_files(repo,pr['number'],path)
        return head,pr['number']

    def verify_files(self,repo,number,path):
        files=self.api(f'repos/{repo}/pulls/{number}/files?per_page=100')
        if len(files)!=1 or files[0]['filename']!=path or files[0]['status']!='added':
            raise ValueError('Character PR must add exactly its proposal JSON')

    def verify_merged(self,item):
        repo=item['repo'];number=item['pr'];identity=item['body']['id']
        pr=self.api(f'repos/{repo}/pulls/{number}')
        if (pr.get('merged') is not True or pr['head']['sha']!=item['head']
                or pr['head']['ref']!=self.branch(identity) or pr['base']['ref']!='main'
                or pr['head']['repo']['full_name']!=repo or pr['base']['repo']['full_name']!=repo):
            raise ValueError('Owner-merged PR with the exact published head required')
        path=self.path(identity);self.verify_files(repo,number,path)
        if digest(self.contents(repo,item['head'],path))!=item['digest']:
            raise ValueError('Accepted character proposal content changed')
