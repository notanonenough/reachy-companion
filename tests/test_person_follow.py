import json
import math
import time
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from reachy_companion.autonomous.person_follow import PersonFollow,checked_sample
from reachy_companion.autonomous.contracts import Sensor
from reachy_companion.autonomous.stock_motion_adapter import StockMotionAdapter
from reachy_companion.motion_limits import validate_follow_step,validate_steps
from test_stock_motion_adapter import Hub


def sample(seq,people=None,source='camera'):
    return dict(source=source,seq=seq,people=people if people is not None else [[.2,.5,.2,.4,.8]])


def pose(yaw=0,body=0,pitch=0):
    return dict(head_pose=dict(yaw=math.radians(yaw),pitch=math.radians(pitch)),body_yaw=math.radians(body))


class PlannerTests(unittest.TestCase):
    def test_large_error_converges_in_three_moves_without_overshoot(self):
        for target in (-30,30):
            f=PersonFollow();actual=pose();moves=[]
            for n in range(1,8):
                yaw=math.degrees(actual['head_pose']['yaw'])
                x=max(.01,min(.99,.5+(yaw-target)/60))
                step=f.plan(sample(n,[[x,.6,.2,.4,.9]]),actual,n)
                if step:
                    validate_follow_step(step,actual);f.committed(step);moves.append(step)
                    actual=dict(head_pose=step['head_pose'],body_yaw=step['body_yaw'])
                    self.assertLessEqual(abs(math.degrees(actual['head_pose']['yaw'])),abs(target))
                if abs(math.degrees(actual['head_pose']['yaw'])-target)<4:break
            self.assertLessEqual(len(moves),3)
            self.assertLess(abs(math.degrees(actual['head_pose']['yaw'])-target),4)
            self.assertLess(sum(s['duration'] for s in moves),1.8)

    def test_near_target_is_shorter_and_speed_guard_rejects_rushed_large_step(self):
        steps=[]
        for x in (.42,.1):
            f=PersonFollow();s=sample(1,[[x,.6,.2,.4,.9]])
            f.plan(s,pose(),0);s['seq']=2
            step=f.plan(s,pose(),1);validate_follow_step(step,pose());steps.append(step)
        self.assertLess(steps[0]['duration'],steps[1]['duration'])
        self.assertLess(steps[0]['duration'],.4)
        self.assertGreater(math.degrees(steps[1]['body_yaw']),7)
        with self.assertRaisesRegex(ValueError,'angular (speed|acceleration)'):
            validate_follow_step({**steps[1],'duration':.35},pose())

    def test_detector_jitter_near_quiet_zone_does_not_move_robot(self):
        f=PersonFollow()
        for n in range(40):
            x=.5+(.035,.045,-.035,-.045)[n%4]
            self.assertIsNone(f.plan(sample(n,[[x,.6,.2,.4,.9]]),pose(),n))

    def test_far_turn_faster_with_bounded_minjerk_acceleration(self):
        f=PersonFollow();f.plan(sample(1),pose(),0)
        step=f.plan(sample(2),pose(),1)
        validate_follow_step(step,pose())
        # The former 8-degree body correction took at least 8/14 seconds.
        self.assertLess(step['duration'],.46)
        for angle,rate,accel in ((step['head_pose']['yaw'],26,320),
                                  (step['body_yaw'],20,250)):
            # Sample the quintic motion, including endpoints and acceleration peaks.
            velocities=[];accelerations=[]
            for n in range(1001):
                t=n/1000
                velocities.append(math.degrees(angle)*(30*t*t-60*t**3+30*t**4)/step['duration'])
                accelerations.append(math.degrees(angle)*(60*t-180*t*t+120*t**3)/step['duration']**2)
            self.assertEqual(velocities[0],0);self.assertEqual(velocities[-1],0)
            self.assertLessEqual(max(map(abs,velocities)),1.875*rate)
            self.assertLessEqual(max(map(abs,accelerations)),accel)

    def test_head_body_follow_keep_pose_and_never_return_to_center(self):
        f=PersonFollow();actual=pose()
        self.assertIsNone(f.plan(sample(1),actual,0))
        for n in range(2,13):
            step=f.plan(sample(n),actual,n)
            if step:
                validate_follow_step(step,actual)
                f.committed(step)
                self.assertGreaterEqual(step['head_pose']['yaw'],actual['head_pose']['yaw'])
                actual=dict(head_pose=step['head_pose'],body_yaw=step['body_yaw'])
        self.assertGreater(actual['body_yaw'],math.radians(20))
        self.assertLessEqual(abs(actual['head_pose']['yaw']-actual['body_yaw']),math.radians(15)+1e-12)
        self.assertIsNone(f.plan(sample(14,[]),actual,14))
        self.assertEqual(f.mode,'holding')

    def test_center_deadband_duplicate_frames_and_new_source_confirmation(self):
        f=PersonFollow();center=[[.51,.61,.2,.4,.9]]
        self.assertIsNone(f.plan(sample(1,center),pose(),0))
        self.assertIsNone(f.plan(sample(2,center),pose(),1))
        self.assertEqual(f.mode,'following')
        self.assertIsNone(f.plan(sample(2),pose(),2))
        self.assertIsNone(f.plan(sample(1,source='new'),pose(),3))

    def test_survey_starts_left_and_stops_for_person_or_conversation(self):
        f=PersonFollow();self.assertIsNone(f.plan(sample(1,[]),pose(),0))
        self.assertIsNone(f.plan(sample(2,[]),pose(),6,False))
        step=f.plan(sample(3,[]),pose(),7)
        self.assertGreater(step['head_pose']['yaw'],0);self.assertGreater(step['body_yaw'],0)
        self.assertEqual(f.mode,'surveying')
        self.assertIsNone(f.plan(sample(4),pose(),8))
        self.assertIsNone(f.scan_index)

    def test_survey_uses_existing_rate_and_acceleration_bounds_instead_of_fixed_delay(self):
        f=PersonFollow();f.plan(sample(1,[]),pose(),0)
        step=f.plan(sample(2,[]),pose(),6)
        self.assertEqual(step['duration'],.35)  # was .8 for the same5°/4° target
        self.assertAlmostEqual(math.degrees(step['head_pose']['yaw']),5)
        self.assertAlmostEqual(math.degrees(step['body_yaw']),4)
        validate_follow_step(step,pose())
        # Fresh-pose corrections near both absolute bounds and pitch recovery
        # can need longer than .35; shortening is never an unconditional cap.
        durations=[]
        for body in (-50,-30,0,30,50):
            for twist in (-10,0,10):
                for pitch in (-17.8,-10,0,10,17.8):
                    actual=pose(body+twist,body,pitch)
                    planner=PersonFollow();planner.plan(sample(1,[]),actual,0)
                    step=planner.plan(sample(2,[]),actual,6)
                    if step is None:continue
                    validate_follow_step(step,actual);durations.append(step['duration'])
                    angles=(abs(math.degrees(step['head_pose']['yaw'])-body-twist),
                            abs(math.degrees(step['body_yaw'])-body),
                            abs(math.degrees(step['head_pose']['pitch'])-pitch))
                    for angle,rate,accel in zip(angles,(26,20,12),(320,250,160)):
                        self.assertLessEqual(angle/step['duration'],rate+1e-9)
                        self.assertLessEqual((10/math.sqrt(3))*angle/step['duration']**2,accel+1e-9)
        self.assertGreater(max(durations),.6)

    def test_invalid_coordinates_and_motion_bounds(self):
        for value in (sample(1,[[float('nan'),.5,.1,.1,.8]]),sample(1,[[.5,.5,0,.1,.8]]),sample(True)):
            with self.assertRaises(ValueError):checked_sample(value)
        f=PersonFollow();f.plan(sample(1),pose(),0)
        step=f.plan(sample(2),pose(),1)
        with self.assertRaises(ValueError):validate_follow_step({**step,'body_yaw':math.radians(90)})
        with self.assertRaises(ValueError):validate_follow_step(step,pose(-20,-20))
        settings=dict(max_steps=5,max_head_degrees=12,max_antenna_degrees=20,max_total_seconds=5)
        with self.assertRaises(ValueError):validate_steps([step],settings)

    def test_body_keeps_progressing_when_neck_has_measured_offset(self):
        for offset in (-1.8,-5.6):
            f=PersonFollow();actual=pose(-45+offset,-45);angles=[]
            f.plan(sample(1,[]),actual,0)
            for n in range(2,65):
                step=f.plan(sample(n,[]),actual,n+5)
                if step:
                    validate_follow_step(step,actual)
                    f.committed(step)
                    body=math.degrees(step['body_yaw']);angles.append(body)
                    actual=pose(body+offset,body)
            self.assertGreater(max(angles),40)
            self.assertLess(angles[-1],0) # left dwell finishes and right sweep starts

    def test_feedback_converges_with_calibrated_pose_offset_and_recovers_pitch(self):
        f=PersonFollow();actual=pose(0,0,13.5)
        for n in range(1,65):
            yaw=math.degrees(actual['head_pose']['yaw'])
            x=max(.01,min(.99,.5+(yaw-30)/60))
            step=f.plan(sample(n,[[x,.6,.2,.4,.9]]),actual,n)
            if step:
                validate_follow_step(step,actual);f.committed(step)
                actual=pose(math.degrees(step['head_pose']['yaw'])-5,
                    math.degrees(step['body_yaw']),math.degrees(step['head_pose']['pitch'])+3.5)
        self.assertLess(abs(math.degrees(actual['head_pose']['yaw'])-30),4)
        f=PersonFollow();actual=pose(0,0,17.3);f.plan(sample(1,[]),actual,0)
        for n in range(2,8):
            step=f.plan(sample(n,[]),actual,n+5)
            if step:
                validate_follow_step(step,actual);f.committed(step)
                actual=pose(math.degrees(step['head_pose']['yaw'])-5,math.degrees(step['body_yaw']),
                    math.degrees(step['head_pose']['pitch'])+3.5)
        self.assertLess(math.degrees(actual['head_pose']['pitch']),5)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.hub=Hub();self.hub.robot=Mock(return_value=pose())
        self.hub.expression=Mock(return_value=dict(ok=True,steps_observed=1))
        self.adapter=StockMotionAdapter(self.hub,follow_person=True);self.adapter.refresh()

    def sensor(self,seq,age=0):
        return Sensor('camera.person',json.dumps(sample(seq)),time.monotonic()-age,1.8)

    def test_no_regular_glances_and_fresh_frame_only_after_motion(self):
        a=self.adapter;self.assertFalse(a.refresh()['motion_allowed'])
        r=a.follow_request(self.sensor(1),time.monotonic(),True);self.assertTrue(a.follow(r)['skipped'])
        a.follow_due=0;r=a.follow_request(self.sensor(2),time.monotonic(),True)
        self.assertTrue(a.follow(r)['accepted']);self.assertEqual(self.hub.expression.call_args.kwargs,dict(follow=True))
        a.follow_due=0
        self.assertIsNone(a.follow_request(self.sensor(3,.5),time.monotonic(),True))

    def test_privacy_epoch_and_expired_frame_reject_without_dispatch(self):
        a=self.adapter;r=a.follow_request(self.sensor(1),time.monotonic(),True)
        a.follow_request(None,time.monotonic(),False)
        self.assertFalse(a.follow(r)['accepted']);self.hub.expression.assert_not_called()
        a.follow_due=0;r=a.follow_request(self.sensor(2),time.monotonic(),True)
        self.hub.actual['microphone_epoch']+=1
        self.assertFalse(a.follow(r)['accepted']);self.hub.expression.assert_not_called()
        self.assertIsNone(a.follow_request(self.sensor(3,5),time.monotonic(),True))

    def test_out_of_envelope_pose_latches_tracking_fault_without_retry(self):
        a=self.adapter;self.hub.robot.return_value=pose(pitch=19)
        r=a.follow_request(self.sensor(1),time.monotonic(),True)
        self.assertFalse(a.follow(r)['accepted'])
        self.assertEqual(a.status()['tracking_mode'],'pose_fault')
        a.follow_due=0
        self.assertIsNone(a.follow_request(self.sensor(2),time.monotonic(),True))
        self.hub.expression.assert_not_called()


class RouteTests(unittest.TestCase):
    def test_body_only_reaches_stock_route_with_internal_follow_capability(self):
        from test_stock_motion_routing import StockMotionTests
        fixture=StockMotionTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.operator.update(expression_version=1,microphone_enabled=True)
        original=fixture.hub.factory.side_effect
        fixture.hub.factory.side_effect=lambda path,payload=None:dict(pose(),control_mode='enabled') if path=='/api/state/full' and payload is None else original(path,payload)
        f=PersonFollow();f.plan(sample(1),pose(),0);step=f.plan(sample(2),pose(),1)
        binding=dict(agent_boot_id='current',microphone_epoch=1,policy_epoch=2,microphone_enabled=True,expression_version=1)
        payload=dict(steps=[step],operator_binding=binding)
        result=fixture.hub.expression(payload,follow=True)
        self.assertTrue(result['ok']);self.assertGreater(fixture.writes[-1][1]['body_yaw'],0)
        self.assertFalse(fixture.hub.stock_scope.follow_body)
        with self.assertRaises(ValueError):fixture.hub.expression(payload)


class BackgroundTests(unittest.TestCase):
    def test_blocked_follow_io_never_blocks_fast_decisions(self):
        from reachy_companion.autonomous.config import load
        from reachy_companion.autonomous.runtime import Scheduler,ReplayGateway
        from reachy_companion.autonomous.durable import DurableStore
        entered=threading.Event();release=threading.Event();h=Hub()
        def read(_):entered.set();release.wait(2);return pose()
        h.robot=read;a=StockMotionAdapter(h,follow_person=True)
        cfg=load(Path(__file__).parents[1]/'config.autonomous.normal.example.json')
        cfg['context']['enabled']=False;cfg['period_s']=.005
        with tempfile.TemporaryDirectory() as directory:
            model=ReplayGateway();s=Scheduler(cfg,model,motion_adapter=a)
            s.enable_production(DurableStore(Path(directory)/'state.sqlite'))
            s.state.sensors['camera.person']=Sensor('camera.person',json.dumps(sample(1)),time.monotonic(),1.8)
            try:
                until=time.monotonic()+1
                while (not entered.is_set() or model.fast_calls<5) and time.monotonic()<until:s.advance();time.sleep(.002)
                self.assertTrue(entered.is_set());self.assertGreaterEqual(model.fast_calls,5)
                self.assertFalse(s.motion_job.future.done())
            finally:release.set();s.close()


if __name__=='__main__':unittest.main()
