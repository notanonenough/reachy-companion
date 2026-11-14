import json
import math
import time
import tempfile
import threading
import unittest
from pathlib import Path
from uuid import uuid4

from reachy_companion.autonomous.config import load
from reachy_companion.autonomous.scene_changes import SceneChanges, checked_objects
from reachy_companion.autonomous.state import State
from reachy_companion.autonomous.stock_motion_adapter import StockMotionAdapter
from test_stock_motion_adapter import Hub


def objects(*items):return [dict(label=label,side=side) for label,side in items]


class SceneTests(unittest.TestCase):
    def test_baseline_confirmation_position_jitter_and_disappearance(self):
        tracker=SceneChanges()
        room=objects(('cabinet','left'))
        for n in (0,1):tracker.observe(room,n,n)
        self.assertIsNone(tracker.snapshot(1))
        person=room+objects(('person','right'))
        tracker.observe(person,2,2);self.assertIsNone(tracker.snapshot(2))
        tracker.observe(person,3,3);first=tracker.snapshot(3)[1]
        self.assertEqual(first['label'],'person');self.assertEqual(first['side'],'right')
        tracker.observe(room+objects(('person','left')),4,4)
        self.assertEqual(tracker.snapshot(4)[1]['id'],first['id'])
        self.assertEqual(tracker.snapshot(4)[1]['side'],'left')
        tracker.observe(room,5,5);self.assertIsNone(tracker.snapshot(5))
        for n in (6,7):tracker.observe(room,n,n)
        for n in (8,9):tracker.observe(person,n,n)
        self.assertEqual(tracker.events,1) # brief re-entry does not spam
        for n in (65,66,67):tracker.observe(room,n,n)
        for n in (68,69):tracker.observe(person,n,n)
        self.assertEqual(tracker.events,2)

    def test_second_object_same_category_and_one_frame_hallucination(self):
        tracker=SceneChanges();cup=objects(('cup','left'))
        for n in (0,1):tracker.observe(cup,n,n)
        tracker.observe(cup+objects(('person','right')),2,2)
        tracker.observe(cup,3,3);self.assertIsNone(tracker.snapshot(3))
        for n in (4,5):tracker.observe(cup+objects(('cup','right')),n,n)
        self.assertEqual(tracker.snapshot(5)[1]['label'],'cup')
        self.assertEqual(tracker.snapshot(5)[1]['side'],'right')
        for n in range(6,40):tracker.observe(cup+objects(('cup','right')),n,n)
        self.assertIsNone(tracker.snapshot(40)) # no infinite event TTL
        self.assertEqual(tracker.events,1)

    def test_bounded_untrusted_object_output(self):
        for value in ({'objects':[{'label':'execute shell','side':'left'}]},
                      {'objects':objects(('person','behind'))},
                      {'objects':objects(*[('person','left')]*7)}, {'objects':[],'say':'hello'}):
            with self.assertRaises(ValueError):checked_objects(value)


class InitiativeTests(unittest.TestCase):
    def setUp(self):
        cfg=load(Path(__file__).parents[1]/'config.autonomous.normal.example.json')
        cfg['context']['enabled']=False
        self.state=State(config=cfg);self.state.production=True
        self.hub=Hub();self.adapter=StockMotionAdapter(self.hub)
        self.state.set_actor(self.adapter.refresh())
        self.now=time.monotonic();self.state.visual.refresh(self.state,self.now)

    def scene(self,side='right',identity=None,age=0,available=True):
        identity=identity or str(uuid4())
        self.state.ingest(dict(type='sensor',id='camera.change',source_id='mac-vlm',
            availability='available' if available else 'unknown',ttl_ms=20000,age_ms=age,
            summary=json.dumps(dict(id=identity,label='person',side=side))),self.now)
        return identity

    def test_unsolicited_candidate_and_direction_before_main_finishes(self):
        identity=self.scene()
        s=self.state;s.visual.advance(s,self.now,True)
        ref=next(iter(s.candidates));self.assertIn(identity,ref)
        binding=s.bind(self.now,1)
        task=s.apply(dict(a='think',why='new person',motion='attentive',
            start=dict(type='main',input_ref=ref)),binding,self.now)
        self.assertTrue(task.prompt['state']['self_directed'])
        self.assertEqual(task.status,'running')
        proposal=s.motion_proposals.popleft()
        result=self.adapter.execute(proposal)
        self.assertTrue(result['accepted']);self.assertEqual(result['gaze_side'],'right')
        self.assertAlmostEqual(self.hub.calls[0]['steps'][0]['head_pose']['yaw'],-math.radians(8))
        self.assertIsNone(s.visual.target(s,self.now))
        s.visual.advance(s,self.now,True);self.assertFalse(s.candidates)

    def test_gone_target_revokes_pending_comment_and_old_motion(self):
        self.scene();s=self.state;s.visual.advance(s,self.now,True)
        binding=s.bind(self.now,1)
        task=s.apply(dict(a='think',why='appearance',start=dict(type='main',input_ref=next(iter(s.candidates)))),binding,self.now)
        binding=s.bind(self.now,1)
        self.scene(available=False)
        s.visual.refresh(s,self.now)
        self.assertEqual(task.status,'discarded')
        s.apply(dict(a='explore',why='old appearance',motion='attentive'),binding,self.now)
        self.assertFalse(s.motion_proposals)
        self.assertEqual(s.counts['visual_motion_stale'],1)

    def test_silence_busy_main_and_user_turn(self):
        self.scene();s=self.state
        s.visual.advance(s,self.now,False)
        self.assertFalse(s.candidates);self.assertIsNotNone(s.visual.target(s,self.now))
        s.ingest(dict(type='utterance',text='Привет'),self.now)
        s.visual.advance(s,self.now,True)
        self.assertEqual(list(s.candidates.values()),['Привет'])
        self.assertIsNone(s.visual.target(s,self.now))

    def test_privacy_quiet_staleness_and_comment_cooldown(self):
        s=self.state
        for field in ('privacy','quiet'):
            self.scene();setattr(s,field,True);s.visual.advance(s,self.now,True)
            self.assertFalse(s.candidates);self.assertIsNone(s.visual.target(s,self.now))
            setattr(s,field,False)
        self.scene(age=20001);s.visual.advance(s,self.now,True);self.assertFalse(s.candidates)
        self.scene();s.visual.advance(s,self.now,True)
        self.assertEqual(len(s.candidates),1)
        s.candidates.clear();s.candidate_kinds.clear()
        self.scene(side='left');s.visual.advance(s,self.now+1,True)
        self.assertFalse(s.candidates)

    def test_side_is_sealed_to_fast_snapshot_and_stock_only(self):
        identity=self.scene();s=self.state;binding=s.bind(self.now,1)
        self.scene(side='left',identity=identity)
        s.apply(dict(a='explore',why='look',motion='attentive'),binding,self.now)
        self.assertFalse(s.motion_proposals)
        s.actor_binding['transport']='native'
        self.assertIsNone(s.visual.target(s,self.now))


class AsyncInitiativeTests(unittest.TestCase):
    def test_busy_main_does_not_block_visual_motion_or_fast_loop(self):
        from reachy_companion.autonomous.runtime import Scheduler, ReplayGateway
        from reachy_companion.autonomous.durable import DurableStore
        entered=threading.Event();release=threading.Event()
        class Model(ReplayGateway):
            def main(self,task):
                entered.set();release.wait(3)
                return dict(request_id=task.attempt_id,compute_boot_id=self.boot_id,output='[SILENT]')
            def fast(self,request_id,view):
                result=super().fast(request_id,view)
                if view['runtime']['working'].get('visual_attention') and view['op']['motion_allowed']:
                    result['output']['motion']='attentive'
                return result
        cfg=load(Path(__file__).parents[1]/'config.autonomous.normal.example.json')
        cfg['context']['enabled']=False;cfg['period_s']=.005
        with tempfile.TemporaryDirectory() as directory:
            adapter=StockMotionAdapter(Hub());model=Model()
            scheduler=Scheduler(cfg,model,motion_adapter=adapter)
            scheduler.enable_production(DurableStore(Path(directory)/'state.sqlite'))
            try:
                end=time.monotonic()+1
                while not entered.is_set() and time.monotonic()<end:scheduler.advance();time.sleep(.002)
                self.assertTrue(entered.is_set())
                # A new event and another pending reflection arrive while main runs.
                scheduler.ingest(dict(type='sensor',id='camera.change',summary=json.dumps(
                    dict(id=str(uuid4()),label='person',side='left')),ttl_ms=20000))
                scheduler.state.candidates['autonomous:queued']='Pending reflection'
                scheduler.state.candidate_kinds['autonomous:queued']='main'
                initial=model.fast_calls;end=time.monotonic()+1
                while (model.fast_calls-initial<5 or not adapter.receipts) and time.monotonic()<end:
                    scheduler.advance();time.sleep(.002)
                self.assertGreaterEqual(model.fast_calls-initial,5)
                self.assertTrue(adapter.receipts[0]['accepted'])
                self.assertEqual(adapter.receipts[0]['gaze_side'],'left')
                self.assertFalse(scheduler.main_job.future.done())
                self.assertEqual(scheduler.state.counts['visual_motion_proposed'],1)
            finally:release.set();scheduler.close()


if __name__=='__main__':unittest.main()
