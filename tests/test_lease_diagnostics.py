"""Deterministic actual run_session gate, with finite collaborator fixtures.

PeerLease tick/close are real; IO Jobs and reducer inputs are controlled. No
network/device timings are claimed by these admission diagnostic vectors.
"""
from collections import Counter
from concurrent.futures import Future
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from reachy_companion.autonomous import companion_session as session
from reachy_companion.autonomous.audio_peer import PeerLease,PeerStartup
from reachy_companion.autonomous.contracts import Authority
from reachy_companion.lease_diagnostics import project_first_lease_invalid
from reachy_companion.production_logs import report_summary
from reachy_companion.production_status import REMOTE_PROBE


class Harness:
    def __init__(self,mode='valid',prior=None):
        self.now=time.monotonic();self.started=self.now;self.steps=0;self.mode=mode
        self.event=threading.Event();self.statuses=[];self.timeline=[];self.prior=prior
        # PeerLease uses the existing complete owner-binding shape.
        from reachy_companion.autonomous.audio_peer import owner_binding
        self.authority=owner_binding(dict(agent_boot_id='PRIVATE-AGENT',owned_microphone_epoch=7,policy_epoch=3,owner_id='PRIVATE-OWNER'))
        self.client=NS(url='http://127.0.0.1:1',timeout=.1,token='PRIVATE-TOKEN',controller='PRIVATE-CONTROLLER',call=self.call)
        with patch.object(PeerLease,'_run',return_value=None):
            self.lease=PeerLease(self.client,source_boot='PRIVATE-SOURCE',authority=self.authority)
        self.lease.worker.join(1);self.lease.last_accepted=self.now-.01
        self.peer=dict(source_boot='PRIVATE-SOURCE',lifetime='lease',lease_binding=self.authority,
                       closed=False,permitted=True,operator_ready=True)
        backend=NS(withdrawn=False,reservation_attempts=0,close_transport=lambda:None)
        playback=NS(backend=backend,status=lambda:dict(quarantined=False,terminal_unknown=False,execution_busy=False),
                    terminal_receipt=lambda:None)
        self.speech=NS(lock=threading.Lock(),operator_receipt=self.current(),playback=playback,
            advance=lambda authority:None,operator_view=lambda:dict(binding=('PRIVATE-AGENT',7,3)),
            status=lambda:dict(execution_busy=False,tts_execution_busy=False,cancellation_execution_busy=False,stop_known=True))
        audio=NS(allowed=True,status=lambda:dict(execution_busy=False))
        state=NS(authority=Authority('PRIVATE-HUB','PRIVATE-COMPUTE'),counts=Counter(),ledger=[],overload='ACTIVE',motion_allowed=False)
        self.scheduler=NS(production=True,config={'production':{}},state=state,speech_adapter=self.speech,audio_adapter=audio,
            motion_adapter=None,services=None,latencies={},advance=self.advance,ingest=lambda *args:None,
            pressure_status=lambda now:{},close=lambda:None,gateway=NS(call=lambda path:dict(compute_boot_id='PRIVATE-COMPUTE',quarantined=False)))
        for name in ('fast','main','actor','motion','context','context_revoke','context_terminal'):
            setattr(self.scheduler,name+'_job',None)
        self.poller=NS(advance=lambda *args:None,close=lambda:None,status=lambda:dict(execution_busy=False))
        self.stop=NS(is_set=self.event.is_set,set=self.event.set,wait=self.wait)
        original=self.lease.close
        def close():self.timeline.append(('close',self.steps));original()
        self.lease.close=close
    def current(self):
        return dict(valid_until=self.now+.2,microphone_enabled=True,quiet=False,privacy_all=False,
                    binding=('PRIVATE-AGENT',7,3),private='PRIVATE-CONTENT')
    def call(self,path,**kwargs):
        if path=='/stop':return dict(stop_known=True,execution_busy=False)
        if self.mode=='peer_receipt_present' and self.steps>=1:raise OSError('PRIVATE-EXCEPTION')
        return self.peer
    def advance(self):
        self.steps+=1;self.speech.operator_receipt=self.current()
        if self.mode=='unarmed':self.peer['operator_ready']=False
        if self.steps<3:return
        mode=self.mode;current=self.speech.operator_receipt
        if mode=='operator_ready':self.peer['operator_ready']=False
        if mode=='status_seen':self.startup.last_status=None
        if mode=='status_fresh':self.startup.last_status=self.now-.4
        if mode=='current_present':self.speech.operator_receipt=None
        if mode=='current_fresh':current['valid_until']=self.now-.025
        if mode=='microphone_enabled':current['microphone_enabled']=False
        if mode=='not_quiet':current['quiet']=True
        if mode=='not_privacy':current['privacy_all']=True
        if mode=='binding_matches':current['binding']=('PRIVATE-FOREIGN',7,3)
        if mode=='malformed_short_circuit':
            self.peer['operator_ready']=False;current['binding']=None
        if mode=='user_stop':self.event.set()
        if mode=='first':
            if self.steps==3:current['quiet']=True
            else:current['privacy_all']=True
        if self.prior:
            with self.lease.lock:self.lease._withdraw(self.prior)
    def wait(self,timeout):
        if self.mode=='status_seen' and self.startup.last_status is None:self.startup.last_status=self.now
        self.now+=.11
        if self.steps>=5:self.event.set()
    def publish(self,value):
        self.statuses.append(copy.deepcopy(value))
        if value.get('first_lease_invalid'):
            value['first_lease_invalid']['predicates']['not_quiet']='PRIVATE-MUTATION'
    def run(self):
        harness=self
        class ImmediateJob:
            def __init__(self,function,*args):
                self.started=harness.now;self.future=Future()
                try:self.future.set_result(function(*args))
                except BaseException as exc:self.future.set_exception(exc)
        def startup(source):
            self.startup=PeerStartup(source,clock=lambda:self.now);return self.startup
        record=session.first_lease_invalid_record
        def captured(*args):
            value=record(*args);self.timeline.append(('record',json.loads(value)));return value
        try:
            with patch.object(session,'Job',ImmediateJob),patch.object(session,'PeerStartup',startup),patch.object(
                    session,'time',NS(monotonic=lambda:self.now,sleep=lambda delay:None)),patch.object(
                    session,'first_lease_invalid_record',captured):
                return session.run_session(self.scheduler,self.poller,self.lease,self.client,self.client,
                    'PRIVATE-SOURCE',self.stop,None,self.publish,lifetime='lease')
        finally:self.lease.connection.close()


class LeaseDiagnosticTests(unittest.TestCase):
    def test_each_gate_condition_is_captured_before_same_close(self):
        for mode in ('peer_receipt_present','operator_ready','status_seen','status_fresh','current_present',
                     'current_fresh','microphone_enabled','not_quiet','not_privacy','binding_matches'):
            with self.subTest(mode=mode):
                harness=Harness(mode);report=harness.run();record=report['first_lease_invalid']
                self.assertIsNotNone(record,report)
                self.assertIn(mode,record['failed_checks']);self.assertIs(record['predicates'][mode],False)
                self.assertEqual(harness.timeline[0][0],'record');self.assertEqual(harness.timeline[1][0],'close')
                self.assertTrue(harness.lease.closed);self.assertEqual(harness.lease.withdrawal_reason,'controller_stop')
                self.assertEqual(harness.statuses[-1]['first_lease_invalid'],record)
                self.assertEqual(record['elapsed_ms'],220)
                if mode=='status_fresh':self.assertEqual(record['peer_status_age_ms'],400)
                if mode=='current_fresh':self.assertEqual(record['operator_valid_remaining_ms'],-25)
                self.assertNotIn('PRIVATE',json.dumps(record))
                self.assertLess(len(json.dumps(record)),2000)
    def test_valid_unarmed_and_explicit_stop_do_not_invent_invalid_cause(self):
        for mode in ('valid','unarmed','user_stop'):
            with self.subTest(mode=mode):
                harness=Harness(mode);report=harness.run()
                self.assertIsNone(report['first_lease_invalid'])
                self.assertFalse(any(row[0]=='record' for row in harness.timeline))
                self.assertEqual(report['reason'],'controller_stop')
                self.assertTrue(harness.lease.closed)
    def test_first_record_survives_later_invalid_inputs_publish_mutation_and_cleanup(self):
        harness=Harness('first');report=harness.run();record=report['first_lease_invalid']
        self.assertEqual(record['failed_checks'],['not_quiet'])
        self.assertEqual(sum(row[0]=='record' for row in harness.timeline),1)
        self.assertGreater(sum(row[0]=='close' for row in harness.timeline),1)
        self.assertTrue(all(row['first_lease_invalid']==record for row in harness.statuses if row.get('first_lease_invalid')))
        self.assertEqual(record,report_summary(report)['first_lease_invalid'])
    def test_diagnostic_failure_does_not_change_short_circuit_or_close(self):
        harness=Harness('malformed_short_circuit');report=harness.run()
        self.assertTrue(harness.lease.closed)
        self.assertTrue(report['first_lease_invalid']['diagnostic_unavailable'])
        self.assertEqual(report['reason'],'controller_stop')
    def test_prior_reducer_or_transport_withdrawal_is_not_reported_as_user_stop(self):
        for reason in ('reducer_expired','renewal_unknown'):
            with self.subTest(reason=reason):
                harness=Harness('not_quiet',prior=reason);report=harness.run();record=report['first_lease_invalid']
                self.assertTrue(record['lease_already_withdrawn'])
                self.assertEqual(record['prior_withdrawal_reason'],reason)
                self.assertEqual(report['lease']['withdrawal_reason'],reason)
                self.assertEqual(report_summary(report)['lease_withdrawal_reason'],reason)
        for reason in ('reducer_expired','renewal_unknown'):
            with self.subTest(valid_gate=True,reason=reason):
                report=Harness('valid',prior=reason).run()
                self.assertIsNone(report['first_lease_invalid'])
                self.assertEqual(report_summary(report)['lease_withdrawal_reason'],reason)
        for reason in ('PRIVATE-UNKNOWN',True,{'private':'content'},None):
            self.assertIsNone(report_summary({'lease':{'withdrawal_reason':reason}})['lease_withdrawal_reason'])
    def test_projection_rejects_content_and_is_standalone_in_remote_probe(self):
        record=Harness('not_quiet').run()['first_lease_invalid']
        contaminated=copy.deepcopy(record)
        contaminated.update(token='PRIVATE-TOKEN',binding=['PRIVATE-OWNER'],exception='PRIVATE-EXCEPTION')
        contaminated['predicates']['extra']='PRIVATE-CONTENT'
        contaminated['lease_timing']['secret']='PRIVATE-CONTENT'
        expected=project_first_lease_invalid(contaminated)
        self.assertEqual(expected,record)
        self.assertEqual(report_summary({'first_lease_invalid':contaminated})['first_lease_invalid'],expected)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'data/production-fixture';path.mkdir(parents=True)
            (path/'hub.json').write_text(json.dumps(dict(first_lease_invalid=contaminated,reason='controller_stop',lease={'withdrawal_reason':'reducer_expired'})))
            (root/'config.local.json').write_text(json.dumps({'paths':{'token_file':'token'}}))
            (root/'token').write_text('PRIVATE-TOKEN')
            live=json.dumps(dict(stage='ACTIVE',first_lease_invalid=contaminated)).encode()
            stub='import io,urllib.request\nurllib.request.urlopen=lambda *args,**kwargs:io.BytesIO('+repr(live)+')\n'
            result=subprocess.run([sys.executable,'-c',stub+REMOTE_PROBE,str(root),'hub'],capture_output=True,text=True,timeout=5,check=True)
            projected=json.loads(result.stdout)
        self.assertEqual(projected['last_session']['first_lease_invalid'],expected)
        self.assertEqual(projected['last_session']['lease_withdrawal_reason'],'reducer_expired')
        self.assertEqual(projected['session']['first_lease_invalid'],expected)
        self.assertNotIn('PRIVATE',result.stdout)
        bad=copy.deepcopy(record);bad['elapsed_ms']=10**400;bad['operator_valid_remaining_ms']=float('nan')
        cleaned=project_first_lease_invalid(bad)
        self.assertIsNone(cleaned['elapsed_ms']);self.assertIsNone(cleaned['operator_valid_remaining_ms'])

    def test_real_joined_transport_records_expired_speech_receipt_before_close(self):
        from test_audio_peer_lease import LeaseProtocolTests
        from reachy_companion.autonomous.audio_adapter import AudioAdapter,HttpSTT
        from reachy_companion.autonomous.audio_peer import AudioPolling
        from reachy_companion.autonomous.config import load
        from reachy_companion.autonomous.runtime import ReplayGateway,Scheduler
        from reachy_companion.autonomous.speech_adapter import SpeechAdapter
        fixture=LeaseProtocolTests();fixture.setUp(start_lease=False)
        class Gateway(ReplayGateway):
            def call(self,path):return dict(compute_boot_id=self.boot_id,quarantined=[])
        class TTS:
            def stream(self,text,cancel):yield b'\x00\x00'*160
            def cancel(self):pass
        audio=AudioAdapter(HttpSTT('http://127.0.0.1:1','t'*32))
        speech=SpeechAdapter(fixture.local,TTS(),lambda:copy.deepcopy(fixture.operator))
        cfg=load(Path(__file__).resolve().parents[1]/'config.autonomous.example.json')
        scheduler=Scheduler(cfg,Gateway(.01),speech_adapter=speech,audio_adapter=audio)
        poller=AudioPolling(fixture.client,audio,fixture.peer.boot_id);original=poller.advance
        stop=threading.Event();statuses=[]
        def expire(*args):
            original(*args)
            if fixture.lease.armed:
                with speech.lock:
                    if speech.operator_receipt:speech.operator_receipt['valid_until']=0
        poller.advance=expire
        try:
            report=session.run_session(scheduler,poller,fixture.lease,fixture.client,
                fixture.client.at_port(fixture.server.stop_address[1]),fixture.peer.boot_id,stop,None,statuses.append,lifetime='lease')
            self.assertIn('current_fresh',report['first_lease_invalid']['failed_checks'])
            self.assertTrue(fixture.lease.closed)
            self.assertEqual(report['lease']['withdrawal_reason'],'controller_stop')
            self.assertEqual(statuses[-1]['first_lease_invalid'],report['first_lease_invalid'])
            self.assertNotIn('fixture-',json.dumps(report['first_lease_invalid']))
        finally:stop.set();audio.close();speech.close();fixture.tearDown()


if __name__=='__main__':unittest.main()
