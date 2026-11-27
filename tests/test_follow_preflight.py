"""Actual Hub follow route with scripted factory/operator, never hardware."""
import copy
import threading
import unittest

import test_stock_motion_routing as stock_fixture
from test_person_follow import PersonFollow,sample,pose


DAEMON='/api/daemon/status'
OWNER='/api/daemon/robot-app-lock-status'
RUNNING='/api/move/running'
STATE='/api/state/full'
GOTO='/api/move/goto'


class FollowPreflightTests(unittest.TestCase):
    def fixture(self):
        f=stock_fixture.StockMotionTests();f.setUp();self.addCleanup(f.doCleanups)
        f.operator.update(expression_version=1,microphone_enabled=True)
        events=[];original=f.hub.factory.side_effect
        def factory(path,payload=None):
            events.append(('factory',path,payload is not None))
            if path==STATE and payload is None:return dict(pose(),control_mode='enabled')
            return original(path,payload)
        def operator(path):
            events.append(('operator',path,False));return copy.deepcopy(f.operator)
        f.hub.factory.side_effect=factory;f.hub.agent.side_effect=operator
        planner=PersonFollow();planner.plan(sample(1),pose(),0)
        step=planner.plan(sample(2),pose(),1)
        binding=dict(agent_boot_id='current',microphone_epoch=1,policy_epoch=2,microphone_enabled=True,expression_version=1)
        return f,dict(steps=[step],operator_binding=binding),events

    def test_follow_uses_one_fresh_preflight_preserving_operator_and_completion_order(self):
        f,payload,events=self.fixture()
        result=f.hub.expression(payload,follow=True)
        self.assertTrue(result['ok'])
        op=('operator','/operator',False)
        get=lambda path:('factory',path,False)
        self.assertEqual(events,[op,op,op,get(DAEMON),get(OWNER),get(RUNNING),op,get(STATE),
            ('factory',GOTO,True),op,get(DAEMON),get(OWNER),get(RUNNING),op])
        before=events[:events.index(('factory',GOTO,True))]
        self.assertEqual(sum(row[0]=='factory' for row in before),4)  # old route: 8
        self.assertEqual(sum(row[0]=='operator' for row in events),6)  # unchanged
        self.assertEqual(f.writes[0][1],payload['steps'][0])
        self.assertFalse(f.hub.stock_unknown);self.assertIsNone(f.hub.stock_owned)

    def test_ordinary_expression_keeps_early_status_reads_and_body_null(self):
        f,_,events=self.fixture()
        step=dict(head_pose=dict(x=0,y=0,z=0,roll=0,pitch=0,yaw=0),antennas=[0,0],duration=.5,interpolation='minjerk')
        self.assertTrue(f.hub.expression(dict(steps=[step]))['ok'])
        first=next(i for i,row in enumerate(events) if row==('factory',GOTO,True))
        self.assertEqual([row[1] for row in events[:first] if row[0]=='factory'],
            [DAEMON,OWNER,STATE,RUNNING,DAEMON,OWNER,RUNNING])
        self.assertIsNone(f.writes[0][1]['body_yaw'])

    def test_final_dependency_snapshot_denies_before_post(self):
        for mode in ('disabled','unknown_mode','daemon_error','backend_error','not_ready','foreign_owner',
                     'malformed_active','foreign_active','own_active','bad_pose','malformed_state'):
            with self.subTest(mode=mode):
                f,payload,_=self.fixture();original=f.hub.factory.side_effect
                def factory(path,data=None):
                    if data is not None:return original(path,data)
                    result=original(path,data)
                    if path==DAEMON:
                        if mode=='daemon_error':result['error']='fixture'
                        if mode=='backend_error':result['backend_status']['error']='fixture'
                        if mode=='not_ready':result['backend_status']['ready']=False
                    if path==OWNER and mode=='foreign_owner':result['state']='owned'
                    if path==RUNNING:
                        if mode=='malformed_active':return [{}]
                        if mode=='foreign_active':return [dict(uuid=stock_fixture.FOREIGN)]
                        if mode=='own_active':
                            f.hub.stock_owned=stock_fixture.OWN
                            return [dict(uuid=stock_fixture.OWN)]
                    if path==STATE:
                        if mode=='disabled':result['control_mode']='disabled'
                        if mode=='unknown_mode':result.pop('control_mode')
                        if mode=='bad_pose':result.update(pose(-30,-30))
                        if mode=='malformed_state':return None
                    return result
                f.hub.factory.side_effect=factory
                with self.assertRaises((RuntimeError,ValueError,KeyError)):f.hub.expression(payload,follow=True)
                self.assertEqual(f.writes,[]);self.assertFalse(f.hub.stock_unknown)
                self.assertFalse(f.hub.lock.locked())

    def test_operator_or_cancel_change_during_final_preflight_denies_post(self):
        for mode in ('epoch','expression_version','cancel'):
            with self.subTest(mode=mode):
                f,payload,_=self.fixture();original=f.hub.factory.side_effect
                f.hub.stock_cancel=threading.Event()
                def factory(path,data=None):
                    value=original(path,data)
                    if path==RUNNING and data is None:
                        if mode=='epoch':f.operator['motion_policy']['epoch']+=1
                        elif mode=='expression_version':f.operator['expression_version']+=1
                        else:f.hub.stock_cancel.set()
                    return value
                f.hub.factory.side_effect=factory
                with self.assertRaises(RuntimeError):f.hub.expression(payload,follow=True)
                self.assertEqual(f.writes,[]);self.assertFalse(f.hub.stock_unknown)

    def test_post_failure_and_invalid_uuid_remain_latched_without_retry(self):
        for result in (TimeoutError('fixture'),{'uuid':'malformed'}):
            with self.subTest(result=type(result).__name__):
                f,payload,_=self.fixture();original=f.hub.factory.side_effect
                def factory(path,data=None):
                    if data is not None:
                        f.writes.append((path,data))
                        if isinstance(result,Exception):raise result
                        return result
                    return original(path,data)
                f.hub.factory.side_effect=factory
                with self.assertRaises((TimeoutError,ValueError)):f.hub.expression(payload,follow=True)
                self.assertEqual([p for p,_ in f.writes],[GOTO]);self.assertTrue(f.hub.stock_unknown)

    def test_completion_timeout_stops_only_owned_uuid_and_preserves_unknown_stop(self):
        for stop_fails in (False,True):
            with self.subTest(stop_fails=stop_fails):
                f,payload,_=self.fixture();original=f.hub.factory.side_effect
                f.on_poll=lambda:None
                def factory(path,data=None):
                    if path=='/api/move/stop' and stop_fails:
                        f.writes.append((path,data));raise TimeoutError('fixture stop')
                    return original(path,data)
                f.hub.factory.side_effect=factory
                with self.assertRaises(TimeoutError):f.hub.expression(payload,follow=True)
                self.assertEqual([p for p,_ in f.writes],[GOTO,'/api/move/stop'])
                self.assertEqual(f.writes[-1][1],{'uuid':stock_fixture.OWN})
                self.assertEqual(f.hub.stock_unknown,stop_fails)
