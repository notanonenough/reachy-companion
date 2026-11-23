"""Protocol evidence with substituted IO. No device or infrastructure acceptance."""
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from reachy_companion.autonomous.config import load
from reachy_companion.autonomous.contracts import validate
from reachy_companion.autonomous.durable import DurableStore
from reachy_companion.autonomous.runtime import Scheduler

ROOT=Path(__file__).resolve().parents[1]


class Models:
    boot_id='test-mac'
    def __init__(self):self.views=[];self.prompts=[];self.choose=lambda view:dict(a='wait',why='quiet observation')
    def fast(self,request_id,view):
        self.views.append(view)
        return dict(request_id=request_id,compute_boot_id=self.boot_id,output=self.choose(view))
    def main(self,task):
        self.prompts.append(task.prompt)
        return dict(request_id=task.attempt_id,compute_boot_id=self.boot_id,output='model inference')


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cfg=load(ROOT/'config.autonomous.normal.example.json')
        self.cfg.update(period_s=.005,fast_deadline_s=1)
        self.cfg['context']['enabled']=False
        self.model=Models();self.scheduler=Scheduler(self.cfg,self.model)
        self.store=DurableStore(Path(self.temp.name)/'state.sqlite3')
        self.scheduler.enable_production(self.store)
    def tearDown(self):
        self.scheduler.close();self.temp.cleanup()
    def pump(self,predicate,timeout=1):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            self.scheduler.advance()
            if predicate():return
            time.sleep(.002)
        self.fail('Protocol did not reach expected state')

    def test_silence_and_mic_off_keep_calling_model_and_unknown_is_explicit(self):
        self.scheduler.ingest(dict(type='operator',muted=True))
        self.pump(lambda:len(self.model.views)>=4)
        view=self.model.views[-1]
        self.assertFalse(view['op']['microphone_enabled'])
        self.assertEqual({s['id'] for s in view['sensors'] if s['state']=='unknown'},
            {'camera','battery','power','servo.load','network','lidar'})
        self.assertEqual(view['dialogue'],'')
        validate('FastView',view)

    def test_cache_updates_during_blocked_main_and_expires_with_source(self):
        gate=threading.Event();started=threading.Event()
        def main(task):
            started.set();gate.wait(1)
            return dict(output='done',request_id=task.attempt_id,compute_boot_id=self.model.boot_id)
        self.model.main=main
        self.model.choose=lambda view:dict(a='think',why='reflection',start=dict(type='main',input_ref=view['candidates'][0]['alias'])) if view['candidates'] and not view['pending'] else dict(a='wait',why='processing')
        self.scheduler.services.sensors['battery']=(lambda:dict(summary='62%',ttl_ms=20),.01,'robot-power')
        try:
            self.pump(lambda:started.is_set() and self.scheduler.state.sensors['battery'].summary=='62%')
            self.assertFalse(self.scheduler.main_job.future.done())
            sensor=self.scheduler.state.sensors['battery'];now=time.monotonic()
            self.assertEqual(sensor.view(now,False)['source_id'],'robot-power')
            self.assertEqual(sensor.view(now+.1,False)['summary'],'')
            self.assertEqual(sensor.view(now+.1,False)['state'],'stale')
        finally:gate.set()

    def test_goal_cas_timestamp_restart_and_rollback(self):
        state=self.scheduler.state
        revision=state.durable_revision
        choice=dict(a='think',why='new aim',update=dict(expected_revision=revision,reason='changed priorities',patch=dict(goal='Watch the room')))
        now=time.monotonic();state.apply(choice,state.bind(now,1),now)
        goal=state.snapshot(now)['goal']
        self.assertEqual(goal['reason'],'changed priorities');self.assertTrue(goal['changed_at'].endswith('Z'))
        self.assertEqual(goal['origin'],'agent')
        with self.assertRaises(ValueError):self.store.update(dict(memory='stale'),revision,'stale update')
        self.assertEqual(self.store.current()[1]['goal'],goal)
        self.store.rollback(0,revision+1,'operator rollback');self.scheduler.services.reload()
        self.assertIsNone(state.snapshot(now)['goal'])
        other=DurableStore(Path(self.temp.name)/'state.sqlite3')
        try:self.assertEqual(other.current()[0],revision+2)
        finally:other.close()

    def test_outbox_retry_exact_ack_and_reopen(self):
        self.scheduler.config['export_enabled']=True
        self.cfg['production']['delivery']={name:dict(enabled=True) for name in ('s3','vps')}
        self.scheduler.state.record('decision_accepted',request_id='r',activity='wait',text='private')
        event_id,body=self.store.pending('s3')
        self.assertNotIn('private',json.dumps(body))
        calls=[]
        def fail(identity,event):calls.append(identity);raise OSError('offline')
        service=self.scheduler.services;service.deliveries['s3']=fail
        self.pump(lambda:'s3' in service.errors)
        self.assertEqual(self.store.pending('s3')[0],event_id)
        service.deliveries['s3']=lambda identity,event:identity
        service.next_export['s3']=0
        self.pump(lambda:self.store.db.execute('SELECT s3 FROM outbox WHERE id=?',(event_id,)).fetchone()==(1,))
        self.assertIsNotNone(self.store.pending('vps'))
        other=DurableStore(Path(self.temp.name)/'state.sqlite3')
        try:self.assertEqual(other.pending('vps')[0],event_id)
        finally:other.close()

    def test_s3_only_logs_never_wait_for_disabled_vps(self):
        self.cfg['export_enabled']=True
        self.cfg['production']['delivery']={'s3':dict(enabled=True),'vps':dict(enabled=False)}
        self.scheduler.state.record('decision_accepted',activity='wait')
        event_id,_=self.store.pending('s3')
        self.assertIsNone(self.store.pending('vps'))
        self.store.ack('s3',event_id)
        self.assertIsNone(self.store.pending('s3'))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM outbox WHERE id=?',(event_id,)).fetchone()[0],0)

    def test_relay_batches_retry_without_losing_individual_event_ids(self):
        self.cfg['export_enabled']=True
        self.cfg['production']['delivery']={'s3':dict(enabled=True),'vps':dict(enabled=False)}
        ids=[self.store.append(dict(kind='fixture'),destinations=('s3',)) for _ in range(70)]
        calls=[]
        class Relay:
            settings={'relay':True}
            fail=True
            def __call__(inner,identity,body):
                calls.append((identity,body))
                return 'wrong-ack' if inner.fail else identity
        relay=Relay();service=self.scheduler.services;service.deliveries['s3']=relay
        def advance():
            service.advance(time.monotonic())
            service.exports['s3'][0].thread.join(1)
            service.advance(time.monotonic())
        advance()
        self.assertEqual([i for i,_ in self.store.pending_batch('s3')],ids[:32])
        relay.fail=False;service.next_export['s3']=0
        advance()
        self.assertEqual(calls[0],calls[1])
        self.assertEqual([e['id'] for e in calls[1][1]['events']],ids[:32])
        self.assertEqual(self.store.pending('s3')[0],ids[32])

    def test_drain_preserves_ready_answer_and_new_request(self):
        from reachy_companion.autonomous.contracts import Task
        now=time.monotonic();state=self.scheduler.state
        answer='Полный ответ после ожидания. '*20
        task=Task('task','attempt','input','question',state.authority,now,now+30,
                  status='ready',result=answer,expires=now+20)
        task.durable_revision=state.durable_revision
        state.tasks[task.task_id]=task
        state.candidates['new']='new human request';state.candidate_kinds['new']='main'
        state.overload='DRAINING'
        self.scheduler.pressure(now)
        self.assertEqual(state.overload,'CONSOLIDATING')
        self.assertEqual(task.result,answer)
        self.assertEqual(task.status,'ready')
        self.assertEqual(state.candidates['new'],'new human request')
        state.overload='ACTIVE'
        state.apply(dict(a='converse',why='ready',commit='task'),state.bind(now,1),now)
        self.assertEqual(state.ledger[-1]['text'],answer)

    def test_context_is_not_restarted_during_drain_or_after_stop(self):
        from reachy_companion.autonomous.runtime import Job
        release=threading.Event();calls=[]
        self.cfg['context']['enabled']=True
        self.model.context=lambda *args:calls.append(args)
        self.model.revoke_context=lambda *args:None
        self.scheduler.state.overload='DRAINING'
        job=Job(lambda:release.wait(2));self.scheduler.fast_job=job
        self.scheduler.binding=self.scheduler.state.bind(time.monotonic(),5)
        try:
            for _ in range(3):self.scheduler.advance()
            self.assertEqual(calls,[])
            self.scheduler.state.stopped=True
            self.scheduler.advance()
            self.assertEqual(calls,[])
        finally:release.set();job.thread.join(1)

    def test_local_only_log_is_bounded_without_discarding_pending_exports(self):
        self.store.cap=2
        for _ in range(4):self.store.append({'kind':'local'},destinations=())
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM outbox').fetchone()[0],2)
        self.assertIsNone(self.store.pending('s3'))
        self.store.append({'kind':'export'})
        self.store.append({'kind':'export'})
        with self.assertRaises(BufferError):self.store.append({'kind':'export'})

    def test_privacy_revokes_inflight_sensor_tool_and_updates(self):
        gate=threading.Event();service=self.scheduler.services
        service.sensors['camera']=(lambda:(gate.wait(1) or True) and dict(summary='secret',ttl_ms=2000),.5,'camera-one')
        service.tools['web']=lambda value:(gate.wait(1) or True) and dict(secret='result')
        now=time.monotonic();service.start_tool('web','query',self.scheduler.state.bind(now,1),now)
        self.scheduler.advance();self.scheduler.ingest(dict(type='operator',muted=True,privacy_all=True))
        gate.set()
        self.pump(lambda:not service.polls and not service.tool_jobs)
        self.assertFalse(self.scheduler.state.tool_results)
        self.assertNotIn('secret',json.dumps(self.scheduler.state.snapshot(time.monotonic())))
        with self.assertRaises(ValueError):service.update(dict(goal='secret'),self.scheduler.state.durable_revision,'reason',time.monotonic())

    def test_overload_drains_real_execution_once_then_consolidates(self):
        gate=threading.Event();started=threading.Event()
        self.cfg['production']['overload_latency_s']=.03
        def slow(request_id,view):
            started.set();gate.wait(1)
            return dict(output=dict(a='wait',why='done'),request_id=request_id,compute_boot_id=self.model.boot_id)
        self.model.fast=slow
        self.scheduler.advance()
        try:
            self.pump(lambda:self.scheduler.state.overload=='DRAINING')
            self.assertFalse(self.scheduler.fast_job.future.done())
            self.assertEqual(self.scheduler.state.counts['overload_entered'],1)
            self.scheduler.advance();self.assertEqual(self.scheduler.state.counts['overload_entered'],1)
        finally:gate.set()
        self.model.fast=Models.fast.__get__(self.model)
        self.pump(lambda:self.scheduler.state.counts['consolidation_completed']==1)
        self.assertEqual(self.scheduler.state.overload,'ACTIVE')
        self.assertGreaterEqual(self.scheduler.state.counts['decision_stale'],1)

    def test_perception_refreshes_during_drain_and_fresh_poll_does_not_block_resume(self):
        from reachy_companion.autonomous.runtime import Job
        gate=threading.Event();poll_gate=threading.Event();service=self.scheduler.services
        self.cfg['production']['overload_latency_s']=.04
        calls=[]
        def sensor():
            calls.append(len(calls)+1)
            return dict(summary='measured frame '+str(calls[-1]),ttl_ms=2000)
        service.sensors['camera']=(sensor,.005,'real-reader-contract')
        job=Job(lambda:gate.wait(2));job.started=time.monotonic()-1
        self.scheduler.context_job=job
        try:
            self.scheduler.pressure(time.monotonic())
            self.assertEqual(self.scheduler.state.overload,'DRAINING')
            self.assertIn('latency:context',self.scheduler.pressure_status(time.monotonic())['reasons'])
            for _ in range(10):
                service.advance(time.monotonic());time.sleep(.003)
            self.assertGreater(len(calls),1)
            self.assertIn('measured frame',self.scheduler.state.sensors['camera'].summary)
            # Keep a fresh physical read occupied exactly when other work ends.
            gate.set();job.thread.join(1);self.scheduler.context_job=None
            for row in service.polls.values():row[0].thread.join(1)
            service.polls.clear()
            poll=Job(lambda:poll_gate.wait(2))
            service.polls['camera']=(poll,time.monotonic(),self.scheduler.state.authority)
            self.scheduler.pressure(time.monotonic())
            self.assertEqual(self.scheduler.state.overload,'CONSOLIDATING')
            self.assertFalse(poll.future.done())
        finally:
            gate.set();poll_gate.set();job.thread.join(1)
            for row in service.polls.values():row[0].thread.join(1)

    def test_stalled_sensor_retains_one_slot_and_blocks_drain_until_terminal(self):
        from reachy_companion.autonomous.runtime import Job
        release=threading.Event();service=self.scheduler.services;calls=[]
        service.sensors['camera']=(lambda:calls.append('replacement'),.001,'camera')
        self.cfg['production']['overload_latency_s']=.01
        job=Job(lambda:(release.wait(2),dict(summary='frame',ttl_ms=1000))[1])
        job.started=time.monotonic()-1
        service.polls['camera']=(job,job.started,self.scheduler.state.authority)
        try:
            self.scheduler.pressure(time.monotonic())
            self.assertEqual(self.scheduler.state.overload,'DRAINING')
            service.advance(time.monotonic());self.scheduler.pressure(time.monotonic())
            self.assertEqual(calls,[])
            self.assertEqual(self.scheduler.state.overload,'DRAINING')
            self.assertIn('latency:sensor:camera',self.scheduler.pressure_status(time.monotonic())['reasons'])
            release.set();job.thread.join(1)
            service.next_poll['camera']=time.monotonic()+10
            service.advance(time.monotonic());self.scheduler.pressure(time.monotonic())
            self.assertEqual(self.scheduler.state.overload,'CONSOLIDATING')
        finally:release.set();job.thread.join(1)

    def test_stop_rejects_late_outputs_and_preserves_clock_withdrawal(self):
        self.scheduler.advance();self.scheduler.ingest(dict(type='stop'))
        self.pump(lambda:self.scheduler.fast_job is None)
        calls=len(self.model.views)
        for _ in range(10):self.scheduler.advance()
        self.assertEqual(len(self.model.views),calls)
        self.assertEqual(self.scheduler.state.counts['decision_accepted'],0)
        self.assertEqual(self.scheduler.state.snapshot(time.monotonic())['mode'],'WITHDRAWN')

    def test_main_receives_personality_goal_sensors_and_memory_inference(self):
        self.scheduler.ingest(dict(type='sensor',id='battery',summary='62%',source_id='fixture-power',ttl_ms=5000))
        self.model.choose=lambda view:dict(a='think',why='reflection',start=dict(type='main',input_ref=view['candidates'][0]['alias'])) if view['candidates'] and not view['pending'] else dict(a='wait',why='processing')
        self.pump(lambda:bool(self.model.prompts))
        prompt=self.model.prompts[0]
        self.assertEqual(prompt['schema_version'],'companion-1')
        self.assertIn('personality',prompt['state']['character'])
        self.assertTrue(prompt['observations'])
        self.assertTrue(all(sensor['state'] in ('ready','fresh') for sensor in prompt['observations']))

    def test_private_reflection_silence_does_not_become_a_spoken_answer(self):
        self.model.choose=lambda view:dict(a='think',why='request',start=dict(type='main',input_ref=view['candidates'][0]['alias'])) if view['candidates'] and not view['pending'] else dict(a='wait',why='quiet')
        self.model.main=lambda task:dict(output='[SILENT]',request_id=task.attempt_id,compute_boot_id=self.model.boot_id)
        self.pump(lambda:self.scheduler.state.counts.get('private_reflection_completed',0)==1)
        self.assertFalse(self.scheduler.state.speech_proposals)
        self.assertFalse(any(t.status=='ready' for t in self.scheduler.state.tasks.values()))
        self.scheduler.ingest(dict(type='utterance',text='Explain the literal token [SILENT]'))
        self.pump(lambda:self.scheduler.state.counts.get('proposal_ready',0)==1)
        self.assertTrue(any(t.status=='ready' for t in self.scheduler.state.tasks.values()))

    def test_tool_registry_and_late_authority(self):
        service=self.scheduler.services;now=time.monotonic()
        service.start_tool('shell','rm anything',self.scheduler.state.bind(now,1),now)
        self.assertFalse(service.tool_jobs)
        service.tools['search']=lambda argument:dict(answer='a')
        service.start_tool('search','q',self.scheduler.state.bind(now,1),now)
        self.pump(lambda:'search' in self.scheduler.state.tool_results)
        self.assertIn('answer',self.scheduler.state.tool_results['search'])

    def test_vps_update_uses_same_cas_and_periodic_memory_is_versioned(self):
        service=self.scheduler.services;state=self.scheduler.state
        service.update_reader=lambda:dict(expected_revision=state.durable_revision,reason='VPS analysis',patch=dict(goal='Observe quietly'))
        self.pump(lambda:state.character['goal'] is not None)
        self.assertEqual(state.character['goal']['reason'],'VPS analysis')
        self.model.main=lambda task:dict(output='{"memory":"inference: calm room"}',request_id=task.attempt_id,compute_boot_id=self.model.boot_id)
        service.next_memory=0
        self.pump(lambda:state.character.get('memory')=='inference: calm room')
        self.assertGreater(state.durable_revision,1)

    def test_recent_dialogue_defers_memory_and_autonomous_reflection(self):
        now=time.monotonic();service=self.scheduler.services
        service.next_memory=0;self.scheduler.ingest(dict(type='utterance',text='question'),now)
        # Isolate cadence from the ordinary conversation candidate.
        self.scheduler.state.candidates.clear()
        service.advance(now+1)
        self.assertIsNone(service.maintenance)
        self.assertEqual(self.scheduler.next_autonomous,now+30)
        service.advance(now+11)
        self.assertIsNotNone(service.maintenance)
        service.maintenance[0].thread.join(1)

    def test_periodic_memory_cadence_begins_after_slow_inference_completes(self):
        service=self.scheduler.services;release=threading.Event();entered=threading.Event()
        def main(task):
            entered.set();release.wait(1)
            return dict(output='{"memory":"inference: calm"}',request_id=task.attempt_id,compute_boot_id=self.model.boot_id)
        self.model.main=main;service.next_memory=0
        start=time.monotonic();service.advance(start)
        self.assertTrue(entered.wait(1));job=service.maintenance[0]
        release.set();job.thread.join(1)
        service.errors['maintenance']='previous failure'
        service.advance(start+20)
        cadence=self.cfg['production']['memory_refresh_s']
        self.assertEqual(service.next_memory,start+20+cadence)
        self.assertNotIn('maintenance',service.errors)
        service.advance(start+cadence+1)
        self.assertIsNone(service.maintenance)

    def test_same_state_path_refuses_second_runtime_owner(self):
        other=DurableStore(Path(self.temp.name)/'state.sqlite3')
        try:
            with self.assertRaises(RuntimeError):other.claim()
        finally:other.close()

    def test_constrained_mac_protocol_and_main_provenance_without_sockets(self):
        from reachy_companion.autonomous.gateway import ModelBackend, fast_schema, fast_projection, PRODUCTION_SYSTEM
        from jsonschema import Draft202012Validator
        class Backend(ModelBackend):
            def count(self,model,text):return len(text.split())
            def post(inner,url,payload,*args):
                inner.payload=payload
                text='{"a":"wait","why":"quiet"}' if 'json_schema' in payload else 'actual substituted completion'
                return dict(content=text,stop_type='eos')
        for role in ('fast','main'):
            model=self.cfg['models'][role]
            model.update(base_url='http://127.0.0.1:1',completion_backend='llama_native')
            model['audit'].update(verified=True,device='metal_mac',runtime_build='fixture',weight_sha256='x',
                template_sha256='x',tokenizer_sha256='x',runtime_context_tokens=4096)
        backend=Backend(self.cfg)
        view=self.scheduler.state.snapshot(time.monotonic())
        result=backend.generate('fast',view)
        self.assertEqual(result['output']['a'],'wait')
        self.assertIn(PRODUCTION_SYSTEM,backend.payload['prompt'])
        projected,_=fast_projection(view)
        schema=fast_schema(projected)
        Draft202012Validator(schema).validate(dict(a='think',why='goal',update=dict(expected_revision=0,reason='curiosity',patch=dict(goal='look'))))
        ready_schema=fast_schema({**projected,'ready':[dict(alias='r0')],
            'candidates':[dict(alias='c0',kind='main')]})
        Draft202012Validator(ready_schema).validate(dict(a='converse',why='answer ready',commit='r0'))
        with self.assertRaises(Exception):
            Draft202012Validator(ready_schema).validate(dict(a='think',why='answer starvation',
                start=dict(type='main',input_ref='c0'),commit='r0'))
        with self.assertRaises(Exception):Draft202012Validator(schema).validate(dict(a='explore',why='no grant',motion='attentive'))
        result=backend.generate('main',dict(schema_version='companion-1',utterance='think',memory=[],observations=view['sensors'],state=dict(character=self.scheduler.state.character)))
        self.assertEqual(result['completion_provenance']['kind'],'model-final-1')
        with patch.object(backend,'post',return_value=dict(content='{"speak":false,"text":""}',stop_type='eos')):
            private=backend.generate('main',dict(schema_version='companion-1',utterance='private reflection',
                memory=[],observations=[],state=dict(self_directed=True)))
        self.assertEqual(private['output'],'[SILENT]')

    def test_short_speech_and_motion_share_binding_and_keep_guards(self):
        state=self.scheduler.state;now=time.monotonic()
        state.speech_attached=True;state.motion_allowed=True;state.actor_deadline=now+1;state.actor_binding={'owner':'fixture'}
        binding=state.bind(now,1)
        state.apply(dict(a='explore',why='observed sound',say='Хмм',motion='attentive'),binding,now)
        self.assertEqual(state.motion_proposals[0]['request_id'],state.speech_proposals[0]['request_id'])
        self.assertTrue(state.snapshot(now)['runtime']['working']['last_speech_proposal'].endswith('Хмм'))
        state.motion_proposals.clear();state.speech_proposals.clear();state.privacy=True
        state.apply(dict(a='explore',why='ignore privacy',motion='attentive'),state.bind(now,1),now)
        self.assertFalse(state.motion_proposals)
        self.assertEqual(state.counts['motion_capability_rejected'],1)

    def test_main_spoken_envelope_is_unwrapped_before_provenance_and_maintenance_is_separate(self):
        from reachy_companion.autonomous.gateway import ModelBackend
        class Backend(ModelBackend):
            text='{"response":"Меня зовут Ричи."}'
            def count(self,model,text):return 200
            def post(inner,url,payload,*args):
                inner.payload=payload
                return dict(content=inner.text,stop_type='eos')
        model=self.cfg['models']['main']
        model.update(base_url='http://127.0.0.1:1',completion_backend='llama_native',structured_reply=True)
        model['audit'].update(verified=True,device='metal_mac',runtime_build='fixture',weight_sha256='x',
            template_sha256='x',tokenizer_sha256='x',runtime_context_tokens=4096)
        backend=Backend(self.cfg)
        body=dict(schema_version='companion-1',utterance='Как тебя зовут?',memory=[],observations=[],state={})
        result=backend.generate('main',body)
        self.assertEqual(result['output'],'Меня зовут Ричи.')
        self.assertEqual(backend.payload['json_schema']['required'],['response'])
        from reachy_companion.autonomous.voice_chain import digest
        self.assertEqual(result['completion_provenance']['output_sha256'],digest(result['output']))
        backend.text='{"memory":"inference"}'
        body['state']={'maintenance':True};body['utterance']='Return ONLY JSON patch memory'
        self.assertEqual(backend.generate('main',body)['output'],backend.text)
        self.assertNotIn('json_schema',backend.payload)
        body['state']={'maintenance':'memory'}
        self.assertEqual(backend.generate('main',body)['output'],backend.text)
        self.assertEqual(backend.payload['json_schema']['required'],['memory'])
        body['state']={'maintenance':'character'}
        backend.generate('main',body)
        self.assertNotIn('json_schema',backend.payload)
        body['state']={}
        with self.assertRaises(ValueError):backend.generate('main',body)

    def test_router_schema_keeps_ready_answer_compact_and_retains_motion(self):
        from reachy_companion.autonomous.gateway import ModelBackend
        from jsonschema import Draft202012Validator
        class Backend(ModelBackend):
            def count(self,model,text):return 200
            def post(inner,url,payload,*args):
                inner.payload=payload
                return dict(content='{"a":"converse","why":"ready","commit":"r0"}',stop_type='eos')
        model=self.cfg['models']['fast']
        model.update(base_url='http://127.0.0.1:1',completion_backend='llama_native',direct_speech=False)
        model['audit'].update(verified=True,device='metal_mac',runtime_build='fixture',weight_sha256='x',
            template_sha256='x',tokenizer_sha256='x',runtime_context_tokens=4096)
        view=self.scheduler.state.snapshot(time.monotonic())
        view['ready']=[dict(alias='actual-ready',summary='8',expires_at='2099-01-01T00:00:00Z')]
        view['op']['motion_allowed']=True
        backend=Backend(self.cfg);result=backend.generate('fast',view)
        self.assertEqual(result['output']['commit'],'actual-ready')
        schema=backend.payload['json_schema']
        self.assertEqual(schema['required'],['a','why','commit'])
        self.assertEqual(set(schema['properties']),{'a','why','commit','motion','propose_character'})
        validator=Draft202012Validator(schema)
        validator.validate(dict(a='converse',why='ready',commit='r0',motion='attentive'))
        with self.assertRaises(Exception):validator.validate(dict(a='converse',why='ready',commit='r0',say='shortcut'))

    def test_router_only_model_cannot_send_direct_speech(self):
        state=self.scheduler.state;state.speech_attached=True
        self.cfg['models']['fast']['direct_speech']=False
        now=time.monotonic()
        state.apply(dict(a='wait',why='untrusted shortcut',say='internal status'),state.bind(now,1),now)
        self.assertFalse(state.speech_proposals)
        self.assertEqual(state.counts['capability_rejected'],1)

    def test_quiet_level_measurement_reaches_cache_without_an_utterance(self):
        import struct
        from reachy_companion.autonomous.audio_adapter import AudioAdapter
        from reachy_companion.autonomous.audio_peer import AudioPeer
        peer=object.__new__(AudioPeer);peer.lock=threading.RLock();peer.clock=time.monotonic
        peer.permitted=lambda:True
        samples=struct.pack('<'+'h'*320,*([12]*320))
        self.assertTrue(peer.publish_level(samples,time.monotonic()))
        self.assertGreater(peer.audio_level['rms'],0)
        self.assertTrue(peer.publish_level(bytes(640),time.monotonic()))
        self.assertLess(peer.audio_level['delta'],0)
        adapter=AudioAdapter(None);adapter.bind_source('capture',0)
        now=time.monotonic();authority=self.scheduler.state.authority
        op=dict(binding=('agent',0,0),microphone_enabled=True,quiet=False,privacy_all=False,valid_until=now+1)
        self.assertIsNone(adapter.advance(authority,op))
        self.assertTrue(adapter.observe_level(dict(rms=peer.audio_level['rms'],delta=peer.audio_level['delta'],capture_age_s=0),
            started=now,source_boot='capture',authority=authority,operator_binding=op['binding']))
        event=adapter.drain_level(authority);self.scheduler.ingest(event)
        sensor=self.scheduler.state.snapshot(time.monotonic())['sensors'][0]
        self.assertEqual(sensor['id'],'audio.level');self.assertEqual(sensor['source_id'],'capture')
        adapter.advance(authority,dict(op,microphone_enabled=False))
        self.assertIsNone(adapter.drain_level(authority))
        adapter.close()

    def test_unknown_tool_completion_remains_durable_and_blocks_drain(self):
        service=self.scheduler.services
        def lost(request):raise TimeoutError('remote terminal unknown')
        service.tools['shell']=lost
        now=time.monotonic();service.start_tool('shell','approved task',self.scheduler.state.bind(now,1),now)
        self.pump(lambda:self.scheduler.state.overload=='DRAINING')
        self.assertIn('shell',service.unresolved)
        self.assertIn('shell',self.store.tool_pending())
        self.assertNotIn('shell',self.scheduler.state.snapshot(time.monotonic())['runtime']['tools'])
        for _ in range(5):self.scheduler.advance()
        self.assertEqual(self.scheduler.state.overload,'DRAINING')

    def test_joined_production_keeps_clock_after_microphone_peer_withdrawal(self):
        from types import SimpleNamespace
        from reachy_companion.autonomous.companion_session import run_session
        stop=threading.Event();renewals=[]
        def speech_status():return dict(execution_busy=False,tts_execution_busy=False,cancellation_execution_busy=False,stop_known=True)
        backend=SimpleNamespace(close_transport=lambda:None,reservation_attempts=0)
        playback=SimpleNamespace(backend=backend,status=lambda:dict(execution_busy=False))
        receipt=lambda:dict(binding=('agent',1,1),microphone_enabled=False,quiet=False,privacy_all=False,valid_until=time.monotonic()+1)
        self.scheduler.speech_adapter=SimpleNamespace(advance=lambda a:None,operator_view=receipt,status=speech_status,close=lambda:None,playback=playback,lock=threading.RLock(),operator_receipt=receipt())
        self.scheduler.audio_adapter=SimpleNamespace(status=lambda:dict(execution_busy=False,source_boot=None),advance=lambda a,r,**kw:None,close=lambda:None,allowed=False)
        self.model.call=lambda path:dict(compute_boot_id=self.model.boot_id,quarantined=[])
        poller=SimpleNamespace(status=lambda:dict(execution_busy=False),close=lambda:None)
        lease=SimpleNamespace(source_boot='source',authority=dict(agent_boot_id='agent',microphone_epoch=0,policy_epoch=0),
            last_accepted=None,armed=True,datagram=None,status=lambda:dict(execution_busy=False,withdrawn=True),
            close=lambda:None,tick=lambda *a:renewals.append(a))
        def peer_call(path,**kw):
            if path=='/stop':return dict(stop_known=True,execution_busy=False)
            return dict(source_boot='source',closed=True,permitted=False,operator_ready=False,lifetime='lease',lease_binding=lease.authority)
        client=SimpleNamespace(call=peer_call)
        # Binding check rejects this withdrawn peer; the independent clock still runs.
        timer=threading.Timer(.06,stop.set);timer.start()
        try:report=run_session(self.scheduler,poller,lease,client,client,'source',stop,None,lambda value:None,lifetime='lease')
        finally:timer.join()
        self.assertEqual(report['errors'],[],report)
        self.assertGreaterEqual(len(self.model.views),3)
        self.assertEqual(report['reason'],'controller_stop')
        self.assertFalse(renewals)
        self.assertFalse(report['accepted']) # no device acceptance from substitute IO

    def test_deployment_hook_renders_only_existing_production_session(self):
        import importlib.util
        from types import SimpleNamespace
        spec=importlib.util.spec_from_file_location('production_deploy',ROOT/'deploy/autonomous/observer_service.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        args=SimpleNamespace(config='normal.json',token_file='token',companion_config='hub.json',output='report.json')
        argv=module.production_arguments(args,dict(peer_url='https://device.invalid',peer_stop_port=9001,source_boot='known',controller='owner',status_port=9002))
        self.assertIn('--lifetime',argv);self.assertIn('lease',argv)
        self.assertEqual(argv[0],'companion-autonomous')
        self.assertNotIn('--allow-native-observation',argv)

    def test_character_deadline_never_schedules_profile_inference(self):
        service=self.scheduler.services;before=self.store.current()
        now=time.monotonic()+self.cfg['production']['character_refresh_s']+1
        service.next_memory=now+10
        service.advance(now)
        self.assertIsNone(service.maintenance)
        self.assertFalse(self.model.prompts)
        self.assertEqual(self.store.current(),before)
        service.next_memory=0
        service.advance(now)
        service.maintenance[0].thread.join(1)
        self.assertEqual(self.model.prompts[-1]['state']['maintenance'],'memory')
        self.assertEqual(self.store.current(),before)

    def test_model_schema_and_service_reject_profile_and_mixed_updates(self):
        from jsonschema import ValidationError
        from reachy_companion.autonomous.gateway import fast_schema
        state=self.scheduler.state;service=self.scheduler.services
        before=self.store.current();now=time.monotonic()
        schema=fast_schema(state.snapshot(now))
        fields=schema['properties']['update']['properties']['patch']['properties']
        self.assertNotIn('personality',fields);self.assertNotIn('principles',fields)
        for patch_value in ({'personality':'changed'}, {'principles':'changed'},
                            {'personality':'changed','goal':'partial mutation'},
                            {'principles':'changed','memory':'partial mutation'}):
            with self.subTest(patch=patch_value):
                value=dict(a='think',why='model change',update=dict(
                    expected_revision=state.durable_revision,reason='model',patch=patch_value))
                with self.assertRaises(ValidationError):state.apply(value,state.bind(now,1),now)
                with self.assertRaises(ValueError):service.update(patch_value,state.durable_revision,'model',now)
                self.assertEqual(self.store.current(),before)
        service.update({'memory':'inference: quiet room'},state.durable_revision,'reflection',now)
        service.update({'goal':'Watch the room'},state.durable_revision,'reflection',now)
        self.assertEqual(state.character['memory'],'inference: quiet room')
        self.assertEqual(state.character['goal']['text'],'Watch the room')
        self.assertEqual(state.character['personality'],before[1]['personality'])

    def test_vps_profile_patch_is_rejected_atomically(self):
        service=self.scheduler.services;state=self.scheduler.state;before=self.store.current()
        service.update_reader=lambda:dict(patch={'personality':'VPS character','goal':'VPS goal'},
            expected_revision=state.durable_revision,reason='external proposal')
        self.pump(lambda:'updates' in service.errors)
        self.assertEqual(self.store.current(),before)

    def test_late_character_completion_cannot_apply_even_memory(self):
        from concurrent.futures import Future
        from types import SimpleNamespace
        service=self.scheduler.services;state=self.scheduler.state
        before=self.store.current();now=time.monotonic()
        for patch_value in ({'personality':'old result'}, {'principles':'old result'}, {'memory':'old character task'}):
            with self.subTest(patch=patch_value):
                future=Future();future.set_result(dict(output=json.dumps(patch_value),
                    compute_boot_id=state.authority.compute_boot_id,request_id='old-character'))
                service.maintenance_task=SimpleNamespace(attempt_id='old-character')
                service.maintenance=(SimpleNamespace(future=future),now,state.authority,state.durable_revision,True)
                service.advance(now)
                self.assertIsNone(service.maintenance)
                self.assertIn('maintenance',service.errors)
                self.assertEqual(self.store.current(),before)

    def test_mic_off_does_not_poll_audio(self):
        service=self.scheduler.services;calls=[]
        service.sensors['audio.extra']=(lambda:calls.append(1),.01,'capture')
        self.scheduler.ingest(dict(type='operator',muted=True))
        self.pump(lambda:len(self.model.views)>=3)
        self.assertFalse(calls)

    def owner_command(self,path,*arguments):
        return subprocess.run([sys.executable,'-m','reachy_companion.autonomous.production',
            'set-character','--state',str(path),*arguments],cwd=ROOT,
            env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=10)

    def test_owner_cli_cas_bounds_restart_and_runtime_exclusion(self):
        path=Path(self.temp.name)/'owner.sqlite3';store=DurableStore(path)
        original=store.current();store.close()
        result=self.owner_command(path,'--expected','0','--reason','Owner chooses profile',
            '--personality','Дружелюбный и любопытный','--principles','Уважать личные границы')
        self.assertEqual(result.returncode,0,result.stderr)
        accepted=json.loads(result.stdout);self.assertEqual(accepted['revision'],1)
        reopened=DurableStore(path)
        try:
            self.assertEqual(reopened.current()[1],accepted['state'])
            self.assertEqual(accepted['state']['memory'],original[1]['memory'])
            self.assertEqual(accepted['state']['goal'],original[1]['goal'])
            failures=[('--expected','0','--reason','stale','--personality','stale'),
                      ('--expected','1','--reason','long','--principles','x'*513),
                      ('--expected','1','--reason','empty','--personality',''),
                      ('--expected','1','--personality','missing reason'),
                      ('--reason','missing revision','--personality','changed'),
                      ('--expected','1','--reason','missing fields')]
            for args in failures:
                with self.subTest(args=args[:4]):
                    result=self.owner_command(path,*args)
                    self.assertNotEqual(result.returncode,0)
                    self.assertEqual(reopened.current(),(1,accepted['state']))
            reopened.claim()
            result=self.owner_command(path,'--expected','1','--reason','busy','--personality','changed')
            self.assertNotEqual(result.returncode,0)
            self.assertIn('runtime owner',result.stderr)
            self.assertEqual(reopened.current(),(1,accepted['state']))
        finally:reopened.close()
        result=self.owner_command(path,'--expected','1','--reason','Owner correction','--principles','x'*512)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['revision'],2)
        # A restarted production session sees the owner profile in the model snapshot.
        scheduler=Scheduler(self.cfg,Models());store=DurableStore(path)
        try:
            scheduler.enable_production(store)
            view=scheduler.state.snapshot(time.monotonic())
            self.assertEqual(view['personality'],accepted['state']['personality'])
            self.assertEqual(store.current()[1]['principles'],'x'*512)
        finally:scheduler.close()

    def test_s3_sigv4_real_request_shape_and_missing_credentials(self):
        import hashlib
        from unittest.mock import patch
        from reachy_companion.autonomous.durable import Delivery
        sink=Delivery('s3',dict(bucket='reachy-logs',region='eu-central-1',prefix='sessions'))
        with patch.dict('os.environ',{'AWS_ACCESS_KEY_ID':'fixture-access','AWS_SECRET_ACCESS_KEY':'fixture-secret','AWS_SESSION_TOKEN':'fixture-session'},clear=True):
            request=sink.s3_request('event-123',dict(id='event-123',metadata=dict(kind='decision')))
            self.assertEqual(request.get_method(),'PUT')
            self.assertTrue(request.full_url.endswith('/sessions/event-123.json'))
            self.assertEqual(request.get_header('X-amz-content-sha256'),hashlib.sha256(request.data).hexdigest())
            self.assertEqual(request.get_header('X-amz-security-token'),'fixture-session')
            self.assertIn('/eu-central-1/s3/aws4_request',request.get_header('Authorization'))
            self.assertIn('Signature=',request.get_header('Authorization'))
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(ValueError):sink.s3_request('event-123',dict(id='event-123'))

    def test_unavailable_motion_owner_does_not_stop_temporal_decisions(self):
        from types import SimpleNamespace
        self.scheduler.motion_adapter=SimpleNamespace(refresh=lambda:(_ for _ in ()).throw(OSError('offline')),close=lambda:True)
        self.pump(lambda:len(self.model.views)>=3)
        self.assertFalse(self.model.views[-1]['op']['motion_allowed'])

    def test_model_client_timeout_waits_exact_remote_terminal_without_repost(self):
        from reachy_companion.autonomous.runtime import RemoteGateway,Job
        gateway=object.__new__(RemoteGateway);gateway.config=self.cfg;gateway.boot_id='test-mac'
        terminal=threading.Event();queried=threading.Event();calls=[]
        def call(path,payload=None):
            calls.append(path)
            if path=='/decision':raise TimeoutError('response lost')
            queried.set()
            return dict(compute_boot_id='test-mac',executions=dict(fast=dict(request_id='request',status='terminal' if terminal.is_set() else 'running')))
        gateway.call=call
        job=Job(gateway.fast,'request',{})
        self.assertTrue(queried.wait(.5));self.assertFalse(job.future.done())
        terminal.set()
        deadline=time.monotonic()+.5
        while not job.future.done() and time.monotonic()<deadline:time.sleep(.002)
        with self.assertRaises(RuntimeError):job.future.result(timeout=.1)
        self.assertEqual(calls.count('/decision'),1)

    def test_gateway_health_tracks_request_execution_not_transport_deadlines(self):
        from reachy_companion.autonomous.gateway import Gateway
        gate=threading.Event();started=threading.Event()
        class Backend:
            def generate(self,role,data):
                started.set();gate.wait(1)
                return dict(output=dict(a='wait',why='finished'))
        gateway=Gateway(Backend())
        from reachy_companion.autonomous.runtime import Job
        job=Job(gateway.generate,'fast',{},'exact-request')
        try:
            self.assertTrue(started.wait(.5))
            self.assertEqual(gateway.health()['executions']['fast'],dict(request_id='exact-request',status='running'))
        finally:gate.set()
        job.future.result(timeout=.5)
        self.assertEqual(gateway.health()['executions']['fast'],dict(request_id='exact-request',status='terminal'))


if __name__=='__main__':unittest.main()
