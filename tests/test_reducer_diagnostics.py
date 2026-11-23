"""Real reducer/renewal-worker stall, plus bounded content-free projections."""
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

from reachy_companion import lease_diagnostics as diagnostics
from reachy_companion.autonomous import companion_session as session
from reachy_companion.autonomous.audio_peer import PeerLease,owner_binding
from reachy_companion.production_logs import report_summary
from reachy_companion.production_status import REMOTE_PROBE


class ReducerDiagnosticTests(unittest.TestCase):
    def lease(self):
        authority=owner_binding(dict(agent_boot_id='PRIVATE-AGENT',owned_microphone_epoch=1,policy_epoch=0,owner_id='PRIVATE-OWNER'))
        client=NS(url='http://127.0.0.1:1',timeout=.1,token='PRIVATE-TOKEN',controller='PRIVATE-CONTROLLER')
        with patch.object(PeerLease,'_run',return_value=None):
            lease=PeerLease(client,source_boot='PRIVATE-SOURCE',authority=authority,progress_timeout_s=.2)
        lease.worker.join(1);self.addCleanup(lease.connection.close)
        return lease

    def test_tick_detection_is_after_latch_and_not_a_blocker_claim(self):
        lease=self.lease();lease.reducer_trace.bind_current();lease.reducer_trace.enter('lease_gate')
        self.assertTrue(lease.tick(lease.authority));self.assertIsNone(lease.status()['first_reducer_expiry'])
        lease.last_tick=time.monotonic()-.21
        frames=sys._current_frames;observed=[]
        def capture():
            observed.append((lease.closed,lease.withdrawal_reason,copy.deepcopy(lease.first_close)))
            return frames()
        with patch.object(diagnostics.sys,'_current_frames',capture):
            self.assertFalse(lease.tick(lease.authority))
        record=lease.status()['first_reducer_expiry']
        self.assertEqual(record['trigger'],'tick');self.assertEqual(record['stage'],'lease_gate')
        self.assertEqual(record['capture_status'],'captured')
        self.assertTrue(observed[0][0]);self.assertEqual(observed[0][1],'reducer_expired')
        self.assertGreaterEqual(observed[0][2]['reducer_progress_age_ms'],200)
        self.assertEqual(record['progress_age_ms'],round(observed[0][2]['reducer_progress_age_ms'],3))
        lease.reducer_trace.enter('cleanup');lease.close();lease.tick(lease.authority)
        record['stack'].clear()
        self.assertTrue(lease.status()['first_reducer_expiry']['stack'])
        self.assertEqual(lease.status()['first_reducer_expiry']['stage'],'lease_gate')

    def test_other_reasons_valid_progress_unarmed_and_capture_failures(self):
        for reason in ('controller_stop','authority_changed','initial_authority_timeout','late_renewal_ack','renewal_unknown'):
            lease=self.lease()
            with lease.lock:lease._withdraw(reason)
            with lease.lock:lease._withdraw('reducer_expired',trigger='worker')
            self.assertIsNone(lease.status()['first_reducer_expiry'])
            self.assertEqual(lease.withdrawal_reason,reason)
        lease=self.lease();self.assertIsNone(lease.status()['first_reducer_expiry'])
        self.assertTrue(lease.tick(lease.authority));self.assertTrue(lease.tick(lease.authority))
        self.assertIsNone(lease.status()['first_reducer_expiry'])
        for mode in ('unregistered','thread_missing','capture_failed'):
            lease=self.lease()
            if mode!='unregistered':lease.reducer_trace.bind_current()
            effect=RuntimeError('PRIVATE-EXCEPTION') if mode=='capture_failed' else None
            with patch.object(diagnostics.sys,'_current_frames',return_value={},side_effect=effect) as capture:
                lease.last_tick=time.monotonic()-.21;lease.armed=True
                self.assertFalse(lease.tick(lease.authority))
                before=lease.status()['first_reducer_expiry']
                self.assertTrue(lease.closed);self.assertEqual(lease.withdrawal_reason,'reducer_expired')
                self.assertEqual(before['capture_status'],mode)
                lease.close();self.assertFalse(lease.tick(lease.authority))
                self.assertEqual(lease.status()['first_reducer_expiry'],before)
                self.assertEqual(capture.call_count,0 if mode=='unregistered' else 1)
                self.assertNotIn('PRIVATE',json.dumps(before))

    def test_actual_valid_unarmed_user_stop_have_no_stall_snapshot(self):
        from test_lease_diagnostics import Harness
        for mode in ('valid','unarmed','user_stop'):
            with self.subTest(mode=mode):
                harness=Harness(mode);report=harness.run()
                self.assertIsNone(report['first_reducer_expiry'])
                self.assertTrue(all(row['first_reducer_expiry'] is None for row in harness.statuses))

    def test_bounded_stack_and_stage_change_during_sampling(self):
        trace=diagnostics.ReducerTrace();trace.bind_current();trace.enter('scheduler_advance')
        frame=None
        for _ in range(30):
            frame=NS(f_code=NS(co_filename='/PRIVATE-HOME/PRIVATE-TOKEN.py',co_name='PRIVATE-TOKEN'),f_lineno=42,f_back=frame)
        def frames():
            trace.enter('lease_gate');return {trace.thread_id:frame}
        with patch.object(diagnostics.sys,'_current_frames',frames):trace.capture('worker',201,time.monotonic())
        record=trace.view();self.assertEqual(len(record['stack']),16)
        self.assertTrue(record['stack_truncated']);self.assertTrue(record['stage_changed_during_capture'])
        self.assertEqual(record['stage'],'scheduler_advance');self.assertNotIn('PRIVATE',json.dumps(record))
        self.assertTrue(all(item==dict(module='external',function='external',line=None) for item in record['stack']))

    def test_actual_run_session_worker_expiry_identifies_blocked_stage(self):
        from test_audio_peer_lease import LeaseProtocolTests
        from reachy_companion.autonomous.audio_adapter import AudioAdapter,HttpSTT
        from reachy_companion.autonomous.audio_peer import AudioPolling
        from reachy_companion.autonomous import audio_peer
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
        poller=AudioPolling(fixture.client,audio,fixture.peer.boot_id)
        stop=threading.Event();entered=threading.Event();release=threading.Event();reports=[];statuses=[]
        between=threading.Event();resume_worker=threading.Event()
        def worker_pause(delay):
            if threading.current_thread() is fixture.lease.worker and fixture.lease.last_accepted is not None:
                between.set();resume_worker.wait(3)
            else:time.sleep(delay)
        original=scheduler.advance
        def held_advance():
            original()
            if between.is_set() and not entered.is_set():
                entered.set();release.wait(3)
        scheduler.advance=held_advance
        def run():
            reports.append(session.run_session(scheduler,poller,fixture.lease,fixture.client,
                fixture.client.at_port(fixture.server.stop_address[1]),fixture.peer.boot_id,stop,None,statuses.append,lifetime='lease'))
        thread=threading.Thread(target=run)
        clock_patch=patch.object(audio_peer,'time',NS(monotonic=time.monotonic,sleep=worker_pause))
        clock_patch.start()
        try:
            thread.start();self.assertTrue(entered.wait(2))
            # Force detection at the next worker loop, not an in-flight ACK.
            # Both threads keep real monotonic time and the unchanged budget.
            remaining=fixture.lease.last_tick+fixture.lease.progress_timeout_s-time.monotonic()
            release.wait(max(0,remaining)+.01);resume_worker.set()
            fixture.lease.worker.join(2)
            self.assertFalse(fixture.lease.worker.is_alive());self.assertTrue(thread.is_alive())
            self.assertFalse(release.is_set());self.assertTrue(fixture.lease.closed)
            self.assertEqual(fixture.lease.withdrawal_reason,'reducer_expired')
            record=fixture.lease.status()['first_reducer_expiry']
            self.assertEqual(record['trigger'],'worker');self.assertEqual(record['stage'],'scheduler_advance')
            self.assertEqual(record['capture_status'],'captured');self.assertFalse(record['stage_changed_during_capture'])
            self.assertGreaterEqual(record['progress_age_ms'],fixture.lease.progress_timeout_s*1000)
            self.assertTrue(any(f['module']=='reachy_companion.autonomous.companion_session' and f['function']=='run_session' for f in record['stack']))
            stop.set();release.set();thread.join(3);self.assertFalse(thread.is_alive())
            self.assertEqual(reports[0]['errors'],[],reports[0]);self.assertEqual(reports[0]['first_reducer_expiry'],record)
            self.assertEqual(statuses[-1]['first_reducer_expiry'],record)
            self.assertEqual(report_summary(reports[0])['first_reducer_expiry'],record)
            self.assertNotIn('fixture-',json.dumps(record));self.assertNotIn(str(Path.home()),json.dumps(record))
            self.assertIsNone(fixture.lease.reducer_trace.thread_id)
        finally:
            stop.set();release.set();resume_worker.set();thread.join(3);clock_patch.stop()
            audio.close();speech.close();fixture.tearDown()

    def test_projection_bounds_redaction_and_standalone_probe_parity(self):
        raw=dict(cause='reducer_expired',stage='/PRIVATE-STAGE',trigger='PRIVATE-TOKEN',capture_status='PRIVATE-EXCEPTION',
            stage_age_ms=True,progress_age_ms=10**400,capture_delay_ms=float('nan'),private='PRIVATE-CONTENT',
            stack=[dict(module='/PRIVATE-HOME/file.py',function='PRIVATE-FUNCTION',line=True,locals='PRIVATE-LOCALS')]*40)
        expected=diagnostics.project_first_reducer_expiry(raw)
        self.assertEqual(len(expected['stack']),16);self.assertLess(len(json.dumps(expected)),8192)
        self.assertNotIn('PRIVATE',json.dumps(expected))
        for key in ('stage_age_ms','progress_age_ms','capture_delay_ms'):self.assertIsNone(expected[key])
        self.assertEqual(report_summary({'first_reducer_expiry':raw})['first_reducer_expiry'],expected)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'data/production-fixture';path.mkdir(parents=True)
            (path/'hub.json').write_text(json.dumps(dict(first_reducer_expiry=raw,reason='controller_stop')))
            (root/'config.local.json').write_text(json.dumps({'paths':{'token_file':'token'}}));(root/'token').write_text('PRIVATE-TOKEN')
            live=json.dumps(dict(stage='ACTIVE',first_reducer_expiry=raw,lease={'first_reducer_expiry':raw})).encode()
            stub='import io,urllib.request\nurllib.request.urlopen=lambda *a,**k:io.BytesIO('+repr(live)+')\n'
            result=subprocess.run([sys.executable,'-c',stub+REMOTE_PROBE,str(root),'hub'],capture_output=True,text=True,timeout=5,check=True)
        projected=json.loads(result.stdout)
        self.assertEqual(projected['session']['first_reducer_expiry'],expected)
        self.assertEqual(projected['session']['lease']['first_reducer_expiry'],expected)
        self.assertEqual(projected['last_session']['first_reducer_expiry'],expected)
        self.assertNotIn('PRIVATE',result.stdout)


if __name__=='__main__':unittest.main()
