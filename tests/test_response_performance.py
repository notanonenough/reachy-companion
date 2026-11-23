"""Controlled scheduler clock/transport: no model or physical latency claims."""
from concurrent.futures import Future
from types import SimpleNamespace
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from reachy_companion.autonomous.runtime import Scheduler, ReplayGateway
from test_autonomous import config


class Jobs:
    def __init__(self): self.calls=[]
    def __call__(self, function, *args):
        job=SimpleNamespace(future=Future(),started=100,function=function,args=args)
        self.calls.append(job)
        return job
    def finish(self, job, choice=None):
        if choice is None: result=job.function(*job.args)
        else:
            result=dict(request_id=job.args[0],compute_boot_id='replay-compute',output=choice)
        job.future.set_result(result)


class ResponsePerformanceTests(unittest.TestCase):
    def setUp(self):
        cfg=config();cfg.update(period_s=1,fast_deadline_s=2,task_timeout_s=30)
        self.scheduler=Scheduler(cfg,ReplayGateway(main_delay=0))
        self.jobs=Jobs();self.patch=patch('reachy_companion.autonomous.runtime.Job',self.jobs)
        self.patch.start();self.addCleanup(self.patch.stop)
        self.scheduler.advance(100)
        self.jobs.finish(self.jobs.calls[-1])
        self.scheduler.advance(100.01)
    def utterance(self, now=100.02):
        self.scheduler.ingest(dict(type='utterance',text='synthetic question'),now)
    def main(self, now=100.02):
        state=self.scheduler.state;ref=next(iter(state.candidates))
        task=state.apply(dict(a='think',why='fixture main',start=dict(type='main',input_ref=ref)),state.bind(now,2),now)
        self.scheduler.main_task=task
        self.scheduler.main_job=SimpleNamespace(future=Future(),started=now)
        return task
    def finish_main(self, task):
        self.scheduler.main_job.future.set_result(dict(output='fixture reply',
            compute_boot_id='replay-compute',request_id=task.attempt_id))

    def test_new_utterance_does_not_wait_for_next_quiet_tick(self):
        self.utterance();self.scheduler.advance(100.02)
        self.assertEqual(len(self.jobs.calls),2)  # formerly only at101: .98s idle
        self.jobs.finish(self.jobs.calls[-1]);self.scheduler.advance(100.03)
        self.assertIsNotNone(self.scheduler.main_job)
        self.assertEqual(self.scheduler.state.counts['task_started'],1)

    def test_ready_completion_refreshes_fast_view_before_commit(self):
        self.utterance();task=self.main();self.finish_main(task)
        self.scheduler.advance(100.02)
        self.assertEqual(task.status,'ready')
        self.assertEqual(len(self.jobs.calls),2)
        self.assertEqual(self.scheduler.state.counts['simulated_speech'],0)
        self.jobs.finish(self.jobs.calls[-1]);self.scheduler.advance(100.03)
        self.assertEqual(self.scheduler.state.counts['simulated_speech'],1)

    def test_superseded_main_keeps_actual_lane_until_completion_then_wakes(self):
        self.utterance();task=self.main()
        self.utterance(100.03);self.scheduler.advance(100.03)
        self.assertEqual(len(self.jobs.calls),1)
        self.assertFalse(self.scheduler.main_job.future.done())
        self.finish_main(task);self.scheduler.advance(100.04)
        self.assertEqual(task.status,'discarded')
        self.assertEqual(len(self.jobs.calls),2)
        self.assertEqual(self.scheduler.state.counts['simulated_speech'],0)
        self.jobs.finish(self.jobs.calls[-1]);self.scheduler.advance(100.05)
        self.assertNotEqual(self.scheduler.main_task.task_id,task.task_id)

    def test_busy_fast_coalesces_and_does_not_accept_superseded_choice(self):
        self.utterance();self.scheduler.advance(100.02)
        old=self.jobs.calls[-1]
        for n in range(100):
            self.utterance(100.03+n*.001);self.scheduler.advance(100.03+n*.001)
        self.assertEqual(len(self.jobs.calls),2)
        self.jobs.finish(old);self.scheduler.advance(100.2)
        self.assertEqual(self.scheduler.state.counts['decision_stale'],1)
        self.assertIsNone(self.scheduler.main_job)
        self.scheduler.advance(101.02)
        self.assertEqual(len(self.jobs.calls),3)
        self.jobs.finish(self.jobs.calls[-1]);self.scheduler.advance(101.03)
        self.assertIsNotNone(self.scheduler.main_job)

    def test_events_cannot_create_unbounded_extra_inference_or_catch_up(self):
        launches=[100]
        for n in range(1,1001):
            now=100+n*.01
            self.utterance(now)
            before=len(self.jobs.calls);self.scheduler.advance(now)
            if len(self.jobs.calls)>before:
                launches.append(now)
                self.jobs.finish(self.jobs.calls[-1],dict(a='wait',why='fixture wait'))
        self.assertLessEqual(len(launches),12)
        self.assertTrue(all(b-a>=.99 for a,b in zip(launches[1:],launches[2:])))
        before=len(self.jobs.calls);self.scheduler.advance(1000)
        self.assertEqual(len(self.jobs.calls),before+1)

    def test_quiet_cycle_unchanged_and_sensor_updates_do_not_wake(self):
        self.scheduler.ingest(dict(type='sensor',id='ambient',summary='fixture'),100.02)
        self.scheduler.advance(100.99);self.assertEqual(len(self.jobs.calls),1)
        self.scheduler.advance(101);self.assertEqual(len(self.jobs.calls),2)
        self.jobs.finish(self.jobs.calls[-1]);self.scheduler.advance(101.01)
        self.scheduler.advance(101.99);self.assertEqual(len(self.jobs.calls),2)
        self.scheduler.advance(102);self.assertEqual(len(self.jobs.calls),3)

    def test_stop_privacy_and_muted_input_cannot_commit_or_start(self):
        for event in (dict(type='stop'),dict(type='operator',muted=True),
                      dict(type='operator',muted=False,privacy_all=True)):
            with self.subTest(event=event):
                cfg=config();cfg.update(period_s=1,fast_deadline_s=2,task_timeout_s=30)
                s=Scheduler(cfg,ReplayGateway())
                if self.scheduler.production:self.enable(s)
                s.ingest(dict(type='utterance',text='fixture'),100)
                s.advance(100);job=self.jobs.calls[-1]
                s.ingest(event,100.01);self.jobs.finish(job);s.advance(100.02)
                self.assertIsNone(s.main_job)
                self.assertEqual(s.state.counts['simulated_speech'],0)


class ProductionResponsePerformanceTests(ResponsePerformanceTests):
    def setUp(self):
        super().setUp()
        self.enable(self.scheduler)

    def enable(self, scheduler):
        from reachy_companion.autonomous.durable import DurableStore
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        scheduler.enable_production(DurableStore(Path(directory.name)/'state.sqlite3'))
        self.addCleanup(scheduler.close)
        scheduler.next_autonomous=2000


if __name__=='__main__':unittest.main()
