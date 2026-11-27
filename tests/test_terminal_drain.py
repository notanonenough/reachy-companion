"""Real joined loop, controlled retained workers, no hardware or inference."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import test_companion_session as session_fixtures
from reachy_companion.autonomous import terminal_drain
from reachy_companion.autonomous.durable import DurableStore
from reachy_companion.autonomous.runtime import Job
from reachy_companion.private_audio_trace import PrivateAudioTrace
from reachy_companion.production_logs import report_summary
from reachy_companion.production_status import REMOTE_PROBE


class TerminalDrainTests(unittest.TestCase):
    def exercise(self,*,finish):
        fixture=session_fixtures.SessionTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        entered=threading.Event();background_entered=threading.Event();release=threading.Event()
        closed=threading.Event();reports=[];state_at_close=[];calls=[]
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root=Path(directory.name).resolve();trace=PrivateAudioTrace(root/'trace.jsonl',seconds=20)
        fixture.scheduler.private_trace=trace
        def complete():
            if finish:
                self.assertTrue(closed.wait(3));time.sleep(2)
            else:release.wait(10)
        def stt(pcm):
            calls.append('stt');entered.set();complete();return 'PRIVATE-LATE-TEXT'
        def poll():
            calls.append('poll');background_entered.set();complete()
            return dict(summary='PRIVATE-LATE-SENSOR',ttl_ms=1000)
        original_close=fixture.scheduler.close
        def close():
            original_close()
            state_at_close.append((dict(fixture.scheduler.state.counts),fixture.scheduler.state.revision))
            closed.set()
        fixture.scheduler.close=close
        def run():
            fixture.scheduler.enable_production(DurableStore(root/'state.sqlite3'),
                sensors={'camera':(poll,100,'PRIVATE-SOURCE-NAME')})
            reports.append(fixture.run_normal(5))
        budget=terminal_drain.TERMINAL_GRACE_S if finish else .15
        with patch.object(fixture.stt,'transcribe',side_effect=stt),patch.object(terminal_drain,'TERMINAL_GRACE_S',budget):
            runner=threading.Thread(target=run);runner.start()
            try:
                fixture.wait(lambda:any(row.get('listening_ready') for row in fixture.latest))
                fixture.peer.publish(b'\0\0'*320,time.monotonic(),None)
                self.assertTrue(entered.wait(2));self.assertTrue(background_entered.wait(2))
                stopped_at=time.monotonic();fixture.stop.set()
                self.assertTrue(closed.wait(1))
                # STOP reaches the actual loopback peer before either worker can finish.
                fixture.wait(lambda:fixture.peer.closed,.5)
                self.assertTrue(runner.is_alive());self.assertLess(time.monotonic()-stopped_at,1)
                runner.join(4);self.assertFalse(runner.is_alive())
                report=reports[0];drain=report['terminal_drain']
                self.assertEqual(drain['budget_s'],budget)
                self.assertEqual(drain['completed'],finish)
                self.assertEqual(report['cleanup_verified'],finish)
                self.assertEqual(report['private_audio_trace']['incomplete'],not finish)
                self.assertEqual(state_at_close[0],(dict(fixture.scheduler.state.counts),fixture.scheduler.state.revision))
                self.assertEqual(calls.count('stt'),1);self.assertEqual(calls.count('poll'),1)
                self.assertFalse(fixture.tts.calls);self.assertIsNone(fixture.audio.result)
                self.assertTrue(fixture.scheduler.services.closed)
                if finish:
                    self.assertGreaterEqual(drain['elapsed_s'],2)
                    self.assertEqual(drain['remaining'],[]);self.assertFalse(drain['overrun'])
                else:
                    self.assertTrue(drain['overrun'])
                    self.assertTrue(report['execution_busy']['audio']);self.assertTrue(report['execution_busy']['background'])
                    pending={row['slot']:row['age_s'] for row in drain['remaining']}
                    self.assertIsNone(pending['audio']);self.assertGreater(pending['background.poll:0'],.1)
                    self.assertIn('busy:audio',report['cleanup_issues'])
                    self.assertIn('busy:background',report['cleanup_issues'])
                raw=(root/'trace.jsonl').read_text()
                self.assertNotIn('PRIVATE-LATE',raw)
                rows=[json.loads(line) for line in raw.splitlines()]
                self.assertEqual(rows[-1]['kind'],'trace_end')
                if finish:
                    result=[r for r in rows if r['kind']=='stt_result']
                    self.assertEqual(len(result),1);self.assertTrue(result[0]['content_suppressed'])
                self.assertNotIn('PRIVATE-SOURCE-NAME',json.dumps(drain))
                self.assertEqual(fixture.latest[-1]['terminal_drain'],drain)
            finally:
                release.set();fixture.stop.set();runner.join(4)
                if fixture.audio.job:fixture.audio.job.join(1)
                for _,job in fixture.scheduler.services.owned_jobs():job.thread.join(1)
                trace.close()
        # Even after the held worker finally returns, no late result applies.
        self.assertEqual(state_at_close[0],(dict(fixture.scheduler.state.counts),fixture.scheduler.state.revision))
        self.assertIsNone(fixture.audio.result);self.assertFalse(fixture.tts.calls)
        return report

    def test_two_second_actual_stt_and_services_finish_before_trace_close(self):
        self.assertEqual(terminal_drain.TERMINAL_GRACE_S,8)
        self.exercise(finish=True)

    def test_unknown_workers_remain_owned_at_finite_bound_without_late_effects(self):
        self.exercise(finish=False)

    def test_close_time_consumes_budget_and_overrun_is_not_a_hard_deadline_claim(self):
        fixture=session_fixtures.SessionTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        original=fixture.scheduler.close
        def close():
            # A pre-existing close action can block; the grace does not interrupt it.
            time.sleep(.2);original()
        fixture.scheduler.close=close;fixture.stop.set()
        with patch.object(terminal_drain,'TERMINAL_GRACE_S',.05):report=fixture.run_normal()
        self.assertGreaterEqual(report['terminal_drain']['elapsed_s'],.2)
        self.assertTrue(report['terminal_drain']['overrun'])
        self.assertEqual(report['terminal_drain']['budget_s'],.05)
        self.assertTrue(fixture.peer.closed)

    def test_snapshot_bound_and_public_standalone_projection(self):
        release=threading.Event();job=Job(lambda:release.wait(3))
        try:
            now=time.monotonic()
            value=terminal_drain.snapshot(now-9,now,{'background':True,'audio':True},
                [('background.poll:'+str(i),job) for i in range(40)])
            self.assertEqual(value['remaining_count'],41);self.assertEqual(len(value['remaining']),32)
            self.assertTrue(value['truncated']);self.assertTrue(value['overrun']);self.assertFalse(value['completed'])
            self.assertEqual(report_summary({'terminal_drain':value})['terminal_drain'],value)
            namespace={}
            # Execute only the self-contained projector embedded in actual remote probe.
            exec(REMOTE_PROBE[:REMOTE_PROBE.index('def project_stock_diagnostics')],namespace)
            self.assertEqual(namespace['project_terminal_drain'](value),value)
            malformed={'remaining':[{'slot':'PRIVATE-NAME','age_s':1},{'slot':'audio','age_s':float('nan'),'text':'PRIVATE'}]}
            projected=namespace['project_terminal_drain'](malformed)
            self.assertNotIn('PRIVATE',json.dumps(projected));self.assertIsNone(projected['remaining'][0]['age_s'])
            json.dumps(projected,allow_nan=False)
        finally:release.set();job.thread.join(1)
