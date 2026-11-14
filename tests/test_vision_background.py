import base64
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from reachy_companion.autonomous.vision import Vision


def frame(seq=1,source='camera',age=0):
    return dict(availability='available',source_id=source,sequence=seq,age_ms=age,ttl_ms=1500,
                exposure_age_known=False,jpeg=base64.b64encode(b'\xff\xd8fixture\xff\xd9').decode())


class VisionTests(unittest.TestCase):
    def test_person_coordinates_are_fresh_bounded_and_cleared_on_owner_change(self):
        clock=[10.];v=Vision({},clock=lambda:clock[0]);v.submit(frame())
        value=dict(source='camera',seq=1,people=[[.2,.4,.2,.4,.8]])
        v.people=(9.5,value)
        result=v.person_snapshot();self.assertEqual(result['age_ms'],500)
        self.assertLessEqual(len(result['summary']),256)
        clock[0]=12.6;v.submit(frame(2))
        self.assertEqual(v.person_snapshot()['availability'],'unknown')
        v.people=(12.6,value);v.submit(frame(3,'another-owner'))
        self.assertEqual(v.person_snapshot()['availability'],'unknown')

    def test_latest_pending_does_not_starve_running_caption_and_cache_expires(self):
        clock=[10.];release=threading.Event();entered=threading.Event();calls=[]
        def describe(value):calls.append(value['sequence']);entered.set();release.wait(2);return 'A red mug on a table.'
        v=Vision(dict(interval_s=.01,ttl_s=12),describe=describe,clock=lambda:clock[0])
        v.submit(frame(1));thread=threading.Thread(target=v.run,daemon=True);v.threads=[thread];thread.start()
        try:
            self.assertTrue(entered.wait(1))
            for seq in range(2,20):v.submit(frame(seq))
            self.assertEqual(v.status()['pending_frames'],1)
            self.assertEqual(v.status()['counts']['coalesced'],17)
            # Cache reads never wait for inference.
            began=time.monotonic();self.assertEqual(v.snapshot()['availability'],'unknown')
            self.assertLess(time.monotonic()-began,.1)
            clock[0]=10.5;release.set()
            until=time.monotonic()+1
            while v.status()['counts']['completed']==0 and time.monotonic()<until:time.sleep(.002)
            self.assertEqual(v.snapshot()['availability'],'available')
            self.assertIn('red mug',v.snapshot()['summary'])
            self.assertTrue(set(calls)<={1,19})
            clock[0]=23;v.submit(frame(20))
            self.assertNotEqual(v.snapshot()['availability'],'available')
        finally:release.set();v.close();thread.join(1)

    def test_withdrawal_and_source_change_fence_late_inference(self):
        for replacement in (dict(availability='disabled'),frame(2,'new-owner')):
            with self.subTest(replacement=replacement.get('source_id')):
                release=threading.Event();entered=threading.Event()
                def describe(_):entered.set();release.wait(2);return 'Old scene'
                v=Vision(dict(interval_s=10),describe=describe)
                v.submit(frame());thread=threading.Thread(target=v.run,daemon=True);v.threads=[thread];thread.start()
                try:
                    self.assertTrue(entered.wait(1));v.submit(replacement);release.set()
                    until=time.monotonic()+1
                    while v.status()['execution_busy'] and time.monotonic()<until:time.sleep(.002)
                    self.assertEqual(v.snapshot()['availability'],'unknown')
                    self.assertEqual(v.status()['counts']['completed'],0)
                finally:release.set();v.close();thread.join(1)

    def test_invalid_or_duplicate_frames_and_latency_included_in_ttl(self):
        v=Vision({})
        self.assertTrue(v.submit(frame()))
        self.assertFalse(v.submit(frame()))
        for bad in (frame(age=1501),dict(frame(),jpeg='not-base64'),dict(frame(),exposure_age_known=True)):
            with self.assertRaises(ValueError):v.submit(bad)
        clock=[10.];v=Vision(dict(ttl_s=12),clock=lambda:clock[0])
        v.submit(frame(age=1000));v.current=(9.,'Desk')
        clock[0]=10.25
        self.assertEqual(v.snapshot()['age_ms'],1250)
        clock[0]=12
        self.assertEqual(v.snapshot()['availability'],'unknown') # source heartbeat expired

    def test_model_timeout_waits_for_real_backend_idle_before_releasing_slot(self):
        from unittest.mock import Mock
        v=Vision({})
        v.settings['model_url']='http://127.0.0.1:18099'
        v.request=Mock(side_effect=[TimeoutError('still running'),[dict(is_processing=True)],[dict(is_processing=False)]])
        v.done.wait=Mock(return_value=False)
        with self.assertRaises(TimeoutError):v.describe_frame(frame())
        self.assertEqual(v.request.call_count,3)

    def test_blocked_vision_does_not_stop_scheduler_decisions(self):
        from reachy_companion.autonomous.config import load
        from reachy_companion.autonomous.runtime import Scheduler,ReplayGateway
        from reachy_companion.autonomous.durable import DurableStore
        release=threading.Event();entered=threading.Event()
        def describe(_):entered.set();release.wait(2);return 'A table'
        v=Vision(dict(interval_s=10),describe=describe)
        v.submit(frame());thread=threading.Thread(target=v.run,daemon=True);v.threads=[thread];thread.start()
        try:
            self.assertTrue(entered.wait(1))
            with tempfile.TemporaryDirectory() as directory:
                cfg=load(Path(__file__).parents[1]/'config.autonomous.normal.example.json')
                cfg['context']['enabled']=False;cfg['period_s']=.01
                model=ReplayGateway();scheduler=Scheduler(cfg,model)
                scheduler.enable_production(DurableStore(Path(directory)/'state.sqlite'),
                    sensors={'camera.scene':(v.snapshot,.01,'mac-vlm')})
                try:
                    end=time.monotonic()+1
                    while model.fast_calls<5 and time.monotonic()<end:scheduler.advance();time.sleep(.002)
                    self.assertGreaterEqual(model.fast_calls,5)
                    self.assertTrue(v.status()['execution_busy'])
                    self.assertEqual(scheduler.state.overload,'ACTIVE')
                finally:scheduler.close()
        finally:release.set();v.close();thread.join(1)

    def test_frame_endpoint_cache_clears_pixels_on_withdrawal(self):
        import numpy as np
        from reachy_companion.autonomous.camera_sensor import Measurements
        cache=Measurements();pixels=np.zeros((720,1280,3),dtype=np.uint8)
        cache.publish(pixels,1,'owner',10,b'\xff\xd8fixture\xff\xd9')
        self.assertEqual(cache.frame(10.2)['sequence'],1)
        self.assertEqual(cache.frame(10.2,'other-owner')['availability'],'disabled')
        generation=cache.frame(10.2)['source_id']
        self.assertEqual(cache.frame(12)['availability'],'unknown')
        cache.clear();self.assertEqual(cache.frame(10.3)['availability'],'unknown')
        cache.publish(pixels,2,'other',11,b'\xff\xd8fixture\xff\xd9')
        self.assertNotEqual(cache.frame(11)['source_id'],generation)
