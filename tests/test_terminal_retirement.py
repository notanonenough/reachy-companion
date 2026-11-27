"""Real joined-loop ACK/local-ref interleaving; synthetic PCM, no hardware."""
import copy
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_audio_peer_lease as protocol
from test_audio_peer_lease import wait
from test_companion_session import FixtureTTS, FixtureGateway
from reachy_companion.autonomous import companion_session as session, playback as playback_module
from reachy_companion.autonomous.audio_adapter import AudioAdapter, HttpSTT
from reachy_companion.autonomous.audio_peer import AudioPolling, PersistentPeer
from reachy_companion.autonomous.config import load
from reachy_companion.autonomous.runtime import Scheduler
from reachy_companion.autonomous.speech_adapter import SpeechAdapter


class TerminalRetirementTests(unittest.TestCase):
    def run_interleaving(self, mode):
        fixture=protocol.LeaseProtocolTests();fixture.setUp(start_lease=False,datagram=True)
        audio=AudioAdapter(HttpSTT('http://127.0.0.1:1','t'*32))
        speech=SpeechAdapter(fixture.local,FixtureTTS(),lambda:copy.deepcopy(fixture.operator))
        cfg=load(Path(__file__).resolve().parents[1]/'config.autonomous.example.json');cfg['period_s']=.02
        scheduler=Scheduler(cfg,FixtureGateway(),speech_adapter=speech,audio_adapter=audio)
        poller=AudioPolling(fixture.client,audio,fixture.peer.boot_id,persistent=True)
        stop=threading.Event();release=threading.Event();pending=threading.Event();reports=[]
        playback=fixture.local;remote=fixture.remote;original_remote=remote.retire
        original_commit=session.commit_retired_terminal;thread_type=threading.Thread
        armed=False;remote_calls=[];commits=[];pending_checks=[]
        def spawn(*args,**kwargs):
            target=kwargs.get('target')
            if armed and target and target.__name__=='complete':
                def held():release.wait();target()
                kwargs['target']=held
            return thread_type(*args,**kwargs)
        def retire(terminal):
            nonlocal armed
            value=original_remote(terminal);remote_calls.append(value)
            if value:
                armed=True
                try:playback.interrupt('operator',preserve=False,wait=False)
                finally:armed=False
                if mode=='mismatch':
                    with playback.lock:playback.terminal=dict(playback.terminal,generation=terminal['generation']+1)
            return value
        def commit(owner,terminal):
            try:value=original_commit(owner,terminal)
            except Exception:
                pending.set();raise
            commits.append(value)
            if not value:
                pending_checks.append((remote.pending_stream['phase'],remote.admission_ready(),
                    playback.terminal['stream_id']==terminal['stream_id'],playback.status()['execution_busy']))
                pending.set()
            return value
        def run():
            reports.append(session.run_session(scheduler,poller,fixture.lease,fixture.client,
                fixture.client.at_port(fixture.server.stop_address[1]),fixture.peer.boot_id,
                stop,None,lambda value:None,lifetime='lease',status_transport=PersistentPeer(fixture.client)))
        runner=thread_type(target=run)
        # Only the fixture's blocked-worker test shortens terminal observation;
        # actual owner STOP/lease/transport bounds and the held worker stay real.
        grace=.08 if mode=='stop' else session.terminal_drain.TERMINAL_GRACE_S
        try:
            with patch.object(playback_module,'threading',SimpleNamespace(Thread=spawn,RLock=threading.RLock,Event=threading.Event)), \
                    patch.object(remote,'retire',retire),patch.object(session,'commit_retired_terminal',commit), \
                    patch.object(audio.stt,'transcribe',return_value='Neutral retirement fixture'), \
                    patch.object(session.terminal_drain,'TERMINAL_GRACE_S',grace):
                runner.start();wait(lambda:audio.allowed)
                self.assertTrue(fixture.peer.publish(b'\x00\x00'*320,time.monotonic(),None))
                self.assertTrue(pending.wait(2),reports)
                self.assertGreater(fixture.datagram_server.accepted,0)
                self.assertEqual(fixture.lease.datagram.authority,fixture.authority)
                self.assertFalse(remote.admission_ready())
                if mode=='finish':
                    release.set();wait(remote.admission_ready)
                    self.assertEqual(commits[-1],True)
                stop.set()
                if mode=='mismatch':release.set()
                runner.join(2);self.assertFalse(runner.is_alive())
                self.assertEqual(remote_calls,[True])
                self.assertEqual(fixture.remote.reservation_attempts,1)
                if mode!='mismatch':
                    self.assertTrue(pending_checks)
                    self.assertTrue(all(row==('ACK',False,True,True) for row in pending_checks))
                if mode=='stop':
                    self.assertFalse(release.is_set());self.assertTrue(playback.joint_job.is_alive())
                    self.assertTrue(fixture.lease.closed);self.assertTrue(playback.closed)
                    self.assertFalse(remote.admission_ready())
                return reports[0],commits
        finally:
            release.set();stop.set()
            if runner.ident is not None:runner.join(3)
            poller.close();scheduler.close();fixture.tearDown()

    def test_ack_is_retained_until_actual_joint_stop_returns_then_committed_once(self):
        report,commits=self.run_interleaving('finish')
        self.assertIn(False,commits);self.assertEqual(commits.count(True),1)
        self.assertEqual(report['errors'],[]);self.assertTrue(report['cleanup_verified'])
        self.assertIsNone(report['first_lease_invalid']);self.assertIsNone(report['first_reducer_expiry'])

    def test_stop_does_not_wait_for_pending_commit_or_reopen_admission(self):
        report,commits=self.run_interleaving('stop')
        self.assertNotIn(True,commits);self.assertEqual(report['reason'],'controller_stop')
        self.assertFalse(report['cleanup_verified']);self.assertTrue(report['execution_busy']['speech'])
        self.assertFalse(report['terminal_drain']['completed'])
        self.assertTrue(report['peer_stop']['stop_known'])

    def test_wrong_identity_fails_even_while_new_stop_reference_is_busy(self):
        report,commits=self.run_interleaving('mismatch')
        self.assertEqual(commits,[]);self.assertEqual(report['failure_code'],'RuntimeError')
        self.assertFalse(report['cleanup_verified'])

    def test_missing_malformed_or_unexpected_local_owner_never_defers(self):
        terminal=dict(stream_id='retained',generation=3)
        for field,value in (('terminal',None),('terminal',dict(stream_id='other',generation=3)),
                ('terminal',dict(stream_id='retained',generation=True)),('active',{}),('paused',{}),('reservation_busy',True)):
            with self.subTest(field=field,value=value):
                owner=SimpleNamespace(lock=threading.RLock(),terminal=dict(terminal),active=None,paused=None,
                    reservation_busy=False,worker=SimpleNamespace(is_alive=lambda:True),stop_jobs=[])
                setattr(owner,field,value)
                with self.assertRaisesRegex(RuntimeError,'references changed'):session.commit_retired_terminal(owner,terminal)

    def test_returned_references_still_require_original_terminal_receipt_validation(self):
        fixture=protocol.LeaseProtocolTests();fixture.setUp()
        try:
            terminal=fixture.complete();wait(lambda:not fixture.device.status()['execution_busy'])
            self.assertTrue(fixture.remote.retire(terminal))
            operation=fixture.local.audio_stops[terminal['stream_id']]
            operation[1]['receipt']['verified_stopped']=False
            with self.assertRaisesRegex(RuntimeError,'stop receipt unknown'):
                session.commit_retired_terminal(fixture.local,terminal)
            self.assertFalse(fixture.remote.admission_ready())
        finally:fixture.tearDown()


if __name__=='__main__':unittest.main()
