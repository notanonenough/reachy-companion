"""Actual joined production loop with local HTTP/synthetic audio; no hardware evidence."""
import copy
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from reachy_companion.autonomous import companion_session as session


def run_trial(delay=0, *, timeout=.25, repeated=False, speech=False, duration=1.2):
    from test_audio_peer_lease import LeaseProtocolTests
    from test_production_cycle import Models
    from test_companion_session import FixtureTTS
    from reachy_companion.autonomous.audio_peer import AudioPolling, PersistentPeer
    from reachy_companion.autonomous.audio_adapter import AudioAdapter
    from reachy_companion.autonomous.speech_adapter import SpeechAdapter
    from reachy_companion.autonomous.runtime import Scheduler
    from reachy_companion.autonomous.config import load
    from reachy_companion.autonomous.durable import DurableStore
    from reachy_companion.autonomous.voice_chain import model_final

    # Match the production transport set, including a real bound UDP renewal
    # receiver; HTTP fallback renewal would consume another media handler.
    device=LeaseProtocolTests();device.setUp(start_lease=False,datagram=True)
    device.client.timeout=timeout
    stop=threading.Event();active=threading.Event();rows=[];calls=[];delayed=[];handler_times=[];speech_seen=[]
    original=device.peer.dispatch
    def dispatch(path, body):
        began=time.monotonic()
        value=original(path,body)
        if path=='/status':handler_times.append(time.monotonic()-began)
        if path=='/status' and active.is_set() and (repeated or not delayed):
            delayed.append(dict(start=time.monotonic(),ready=value['operator_ready']))
            time.sleep(delay)
            delayed[-1]['end']=time.monotonic()
        return value
    transport=PersistentPeer(device.client);lock=threading.Lock();occupied=0;peak=0
    class Measured:
        def call(self,path,**kwargs):
            nonlocal occupied,peak
            row=dict(start=time.monotonic());calls.append(row)
            with lock:occupied+=1;peak=max(peak,occupied)
            try:
                value=transport.call(path,**kwargs);row['success']=True;return value
            except Exception as exc:
                row.update(success=False,error=type(exc).__name__);raise
            finally:
                row['end']=time.monotonic()
                with lock:occupied-=1
        def close(self):transport.close()
    class STT:
        def transcribe(self,pcm):return 'A synthetic fixture question'
    model=Models();model.call=lambda path:dict(compute_boot_id=model.boot_id,quarantined=[])
    if speech:
        def choose(view):
            if view['ready']:return dict(a='converse',why='fixture commit',commit=view['ready'][0]['alias'])
            if view['candidates'] and view['dialogue'] and not view['pending']:
                return dict(a='think',why='fixture question',start=dict(type='main',input_ref=view['candidates'][0]['alias']))
            return dict(a='wait',why='fixture idle')
        model.choose=choose
        def main(task):
            output='4'
            return dict(request_id=task.attempt_id,compute_boot_id=model.boot_id,output=output,
                        completion_provenance=model_final(task.prompt,output,'completion_http','fixture-model'))
        model.main=main
    audio=AudioAdapter(STT());tts=FixtureTTS()
    speaker=SpeechAdapter(device.local,tts,lambda:copy.deepcopy(device.operator))
    cfg=load(Path(__file__).resolve().parents[1]/'config.autonomous.normal.example.json')
    cfg['context']['enabled']=False;cfg['period_s']=.1
    scheduler=Scheduler(cfg,model,speech_adapter=speaker,audio_adapter=audio)
    poller=AudioPolling(device.client,audio,device.peer.boot_id,persistent=True);sent=[]
    def publish(row):
        rows.append(row)
        if row['stage']=='ACTIVE':active.set()
        if speech and row.get('listening_ready') and not sent:
            sent.append(time.monotonic())
            if not device.peer.publish(b'\x00\x00'*320,sent[0],None):raise AssertionError('Fixture capture rejected')
        if speaker.status()['receipts'] and not speech_seen:speech_seen.append(time.monotonic())
        if row['stage']=='WITHDRAWN':stop.set()
    watchdog=threading.Timer(duration,stop.set);watchdog.start()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            scheduler.enable_production(DurableStore(Path(tmp)/'state.sqlite'))
            with patch.object(device.peer,'dispatch',side_effect=dispatch):
                report=session.run_session(scheduler,poller,device.lease,device.client,
                    device.client.at_port(device.server.stop_address[1]),device.peer.boot_id,
                    stop,None,publish,lifetime='lease',status_transport=Measured())
    finally:
        stop.set();watchdog.cancel();watchdog.join();poller.close();scheduler.close();device.tearDown()
    active_rows=[r for r in rows if r['stage']=='ACTIVE']
    return dict(delay_s=delay,timeout_s=timeout,active=active.is_set(),calls=calls,
        peak_status_jobs=peak,delayed=delayed,first_invalid=report['first_lease_invalid'],
        first_reducer_expiry=report['first_reducer_expiry'],errors=report['errors'],
        max_tick_gap_ms=report['lease']['max_tick_gap_ms'],cleanup_verified=report['cleanup_verified'],
        audio_completed=report['audio']['counts']['completed'],tts_calls=len(tts.calls),
        speech_receipts=report['speech_after']['receipts'],
        max_health_age_s=max((r['runtime']['compute_health_age_s'] for r in active_rows),default=None),
        handler_compute_s=handler_times,
        capture_to_observed_speech_receipt_s=speech_seen[0]-sent[0] if speech_seen and sent else None,
        elapsed_s=report['elapsed_s'])


class PeerStatusScheduleTests(unittest.TestCase):
    def test_timeout_budget_floor_cap_and_malformed_values(self):
        for timeout,expected in ((.25,.025),(.2,.075),(.1,.1),(.001,.1),(.5,.025)):
            self.assertAlmostEqual(session.peer_status_interval(timeout),expected)
        for value in (None,True,False,0,-1,float('nan'),float('inf'),'0.25'):
            with self.subTest(value=value),self.assertRaises(ValueError):session.peer_status_interval(value)

    def test_successful_delayed_status_does_not_spend_freshness_in_idle_gap(self):
        value=run_trial(.22,speech=True,duration=1.5)
        self.assertTrue(value['active']);self.assertIsNone(value['first_invalid'],value)
        self.assertIsNone(value['first_reducer_expiry']);self.assertEqual(value['errors'],[])
        self.assertTrue(all(c['success'] for c in value['calls']))
        self.assertEqual(value['peak_status_jobs'],1);self.assertTrue(value['cleanup_verified'])
        self.assertEqual(value['audio_completed'],1);self.assertEqual(value['tts_calls'],1)
        self.assertTrue(value['speech_receipts'],value)

    def test_fast_success_rate_is_bounded_and_has_no_catch_up_burst(self):
        value=run_trial()
        self.assertIsNone(value['first_invalid']);self.assertTrue(value['cleanup_verified'])
        starts=[c['start'] for c in value['calls']]
        self.assertTrue(all(b-a>=.025 for a,b in zip(starts,starts[1:])),starts)
        self.assertLessEqual(len(starts),1+int((starts[-1]-starts[0])/.025))
        self.assertEqual(value['peak_status_jobs'],1)

    def test_repeated_slow_success_keeps_one_actual_slot(self):
        value=run_trial(.2,repeated=True)
        self.assertIsNone(value['first_invalid'],value)
        self.assertIsNone(value['first_reducer_expiry']);self.assertEqual(value['errors'],[])
        self.assertTrue(all(c['success'] for c in value['calls']))
        self.assertGreaterEqual(len(value['delayed']),3)
        self.assertEqual(value['peak_status_jobs'],1);self.assertTrue(value['cleanup_verified'])

    def test_genuinely_late_success_still_withdraws_despite_larger_timeout(self):
        value=run_trial(.35,timeout=.5)
        self.assertEqual(value['first_invalid']['failed_checks'],['status_fresh'],value)
        self.assertIsNone(value['first_reducer_expiry']);self.assertEqual(value['errors'],[])
        self.assertTrue(all(c['success'] for c in value['calls']))
        self.assertEqual(value['peak_status_jobs'],1)
        self.assertFalse(value['first_invalid']['lease_already_withdrawn'])


if __name__=='__main__':unittest.main()
