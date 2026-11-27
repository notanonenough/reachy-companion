"""Actual stock stop/adapter paths, fixed diagnostics and unchanged writes."""
import copy
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,call,patch
from urllib.error import HTTPError
from reachy_companion.autonomous.stock_motion_adapter import StockMotionAdapter
from reachy_companion.autonomous.stock_diagnostics import project
from reachy_companion.production_logs import report_summary
import test_stock_motion_routing as fixtures


class StockDiagnosticTests(unittest.TestCase):
    setUp=fixtures.StockMotionTests.setUp
    factory=fixtures.StockMotionTests.factory

    def stop_case(self, problem):
        self.hub.stock_owned=fixtures.OWN
        self.active=[dict(uuid=fixtures.OWN)];self.on_poll=lambda:None
        original=self.factory;stopped=False
        def factory(path,payload=None):
            nonlocal stopped
            if payload is not None:
                self.writes.append((path,copy.deepcopy(payload)));stopped=True
                if problem in ('404','500'):raise HTTPError('PRIVATE',int(problem),'SECRET',{},None)
                if problem=='transport':raise OSError('SECRET')
                if problem=='timeout':raise TimeoutError('SECRET')
                self.active=[];return {}
            if stopped and path=='/api/move/running':
                if problem=='malformed':return {'private':'SECRET'}
                if problem=='read_timeout':raise TimeoutError('SECRET')
                if problem=='absence_timeout':return [dict(uuid=fixtures.OWN)]
                return []
            return original(path,payload)
        self.hub.factory.side_effect=factory
        try:self.hub.stock_stop_owned(fixtures.OWN);outcome=None
        except Exception as exc:outcome=type(exc).__name__
        return outcome,self.hub.stock_diagnostic_snapshot()

    def stop_case_on_clock(self, problem):
        # Compare IO under the same elapsed time, not two wall-clock races.
        # Diagnostics may read the clock, but only the actual polling sleep
        # advances it; failed recording cannot gain an extra poll budget.
        clock=SimpleNamespace(now=0.0,sleeps=[])
        clock.monotonic=lambda:clock.now
        def sleep(seconds):
            clock.sleeps.append(seconds);clock.now+=seconds
        clock.sleep=sleep
        with patch('reachy_companion.hub.time',clock), \
                patch('reachy_companion.autonomous.stock_diagnostics.monotonic',clock.monotonic):
            outcome,record=self.stop_case(problem)
        return outcome,record,clock

    def test_normal_and_failure_write_order_flags_and_first_cause(self):
        cases={'normal':(None,None),'404':('stop_post','request_error'),'500':('stop_post','request_error'),
            'transport':('stop_post','request_error'),'timeout':('stop_post','request_error'),
            'malformed':('stop_observation','invalid_observation'),'read_timeout':('stop_observation','request_error'),
            'absence_timeout':('stop_observation','absence_timeout')}
        for problem,(stage,cause) in cases.items():
            with self.subTest(problem=problem):
                self.setUp();outcome,record,clock=self.stop_case_on_clock(problem)
                calls=self.hub.factory.call_args_list;flags=(self.hub.stock_unknown,self.hub.stock_owned,self.hub.stock_stop_observed)
                self.assertEqual(self.writes,[('/api/move/stop',{'uuid':fixtures.OWN})])
                self.assertEqual(record['first_failure'] is None,problem=='normal')
                if stage:
                    self.assertEqual(record['first_failure']['stage'],stage);self.assertEqual(record['first_failure']['cause'],cause)
                stop=record['stop_receipt'];self.assertTrue(stop['completed']);self.assertGreaterEqual(stop['finished_at'],stop['started_at'])
                self.assertEqual(stop['post']['accepted'],problem not in ('404','500','transport','timeout'))
                self.assertNotIn('SECRET',json.dumps(record));self.assertNotIn('PRIVATE',json.dumps(record))
                if problem=='absence_timeout':
                    self.assertEqual(outcome,'TimeoutError')
                    self.assertEqual(flags,(True,fixtures.OWN,False))
                    self.assertFalse(stop['absence_observed'])
                    self.assertEqual(clock.sleeps,[.001]*20)
                    self.assertGreaterEqual(clock.now,self.config['timeouts']['move'])
                    self.assertLess(clock.now-clock.sleeps[-1],self.config['timeouts']['move'])
                    self.assertEqual(calls,[call('/api/daemon/status'),call('/api/daemon/robot-app-lock-status'),
                        call('/api/move/running'),call('/api/move/stop',{'uuid':fixtures.OWN})]
                        +[call('/api/move/running')]*20)
                # Identical actual IO and old outcomes when recording itself fails.
                self.setUp();self.hub.stock_diagnostics=Mock();self.hub.stock_diagnostics.begin_stop.side_effect=OSError('disk')
                self.hub.stock_diagnostics.fail.side_effect=RuntimeError('logger');self.hub.stock_diagnostics.preflight.side_effect=ValueError('diag')
                other,_,other_clock=self.stop_case_on_clock(problem)
                self.assertEqual(other,outcome);self.assertEqual(self.hub.factory.call_args_list,calls)
                self.assertEqual(other_clock.sleeps,clock.sleeps);self.assertEqual(other_clock.now,clock.now)
                self.assertEqual((self.hub.stock_unknown,self.hub.stock_owned,self.hub.stock_stop_observed),flags)

    def test_first_failure_and_its_final_stop_are_immutable(self):
        _,first=self.stop_case('404')
        self.assertTrue(first['stop_receipt']['absence_observed']);self.assertTrue(self.hub.stock_unknown)
        self.hub.factory.side_effect=self.factory;self.active=[]
        with self.assertRaises(RuntimeError):self.hub.stock_stop_owned(fixtures.OWN)
        self.assertEqual(self.hub.stock_diagnostic_snapshot(),first)
        first['first_failure']['cause']='PRIVATE';first['stop_receipt']['post']['accepted']=True
        fresh=self.hub.stock_diagnostic_snapshot()
        self.assertEqual(fresh['first_failure']['cause'],'request_error');self.assertFalse(fresh['stop_receipt']['post']['accepted'])

    def test_stale_empty_preflight_and_invalid_second_read_are_distinct(self):
        for second in ('stale','malformed','timeout'):
            self.setUp();self.hub.stock_owned=fixtures.OWN
            self.hub.stock_dependencies=Mock(side_effect=[[], [] if second=='stale' else ValueError('private') if second=='malformed' else TimeoutError('private')])
            clock=[0,.4,.4,.8] if second=='stale' else [0,.4,.4]
            with patch('reachy_companion.hub.time.monotonic',side_effect=clock):
                with self.assertRaises(RuntimeError):self.hub.stock_stop_owned(fixtures.OWN)
            result=self.hub.stock_diagnostic_snapshot();failure=result['first_failure']
            self.assertEqual(failure['stage'],'stop_preflight')
            self.assertEqual(failure['cause'],{'stale':'freshness_expired','malformed':'invalid_observation','timeout':'request_error'}[second])
            self.assertEqual(len(result['stop_receipt']['preflight']),2);self.assertEqual(self.writes,[])
            self.assertFalse(result['stop_receipt']['post']['attempted']);self.assertTrue(self.hub.stock_unknown)

    def test_preflight_absence_known_and_partial_snapshot_not_completed(self):
        self.hub.stock_owned=fixtures.OWN
        self.hub.stock_diagnostic('begin_stop',fixtures.OWN)
        partial=self.hub.stock_diagnostic_snapshot()['stop_receipt']
        self.assertFalse(partial['completed']);self.assertIsNone(partial['finished_at'])
        self.hub.stock_stop_owned(fixtures.OWN)
        self.assertFalse(self.hub.stock_unknown);self.assertEqual(self.writes,[])
        self.assertTrue(self.hub.stock_diagnostic_snapshot()['stop_receipt']['absence_observed'])

    def test_dispatch_failure_and_invalid_uuid_have_no_stale_stop_join(self):
        for invalid in (False,True):
            self.setUp();self.hub.stock_owned=fixtures.OWN;self.hub.stock_stop_owned(fixtures.OWN)
            original=self.factory
            def factory(path,payload=None):
                if payload is not None:
                    if invalid:return {'uuid':'PRIVATE'}
                    raise OSError('PRIVATE')
                return original(path,payload)
            self.hub.factory.side_effect=factory
            with self.assertRaises((OSError,ValueError)):self.hub.move('/api/move/goto',{})
            result=self.hub.stock_diagnostic_snapshot()
            self.assertEqual(result['first_failure']['stage'],'dispatch_response' if invalid else 'dispatch_post')
            self.assertIsNone(result['first_failure']['owned_uuid']);self.assertIsNone(result['stop_receipt'])

    def test_actual_adapter_join_final_projection_and_no_previous_operation_binding(self):
        self.operator.update(microphone_enabled=True,expression_version=5)
        self.hub.operator_proxy=lambda:(copy.deepcopy(self.operator),time.monotonic())
        adapter=StockMotionAdapter(self.hub)
        original=self.factory
        def factory(path,payload=None):
            if path=='/api/move/stop':
                self.active=[];raise HTTPError('PRIVATE',404,'SECRET',{},None)
            return original(path,payload)
        self.hub.factory.side_effect=factory
        self.on_post=adapter.cancel.set;self.on_poll=lambda:None
        proposal=dict(request_id=fixtures.FOREIGN,motion='attentive',deadline=time.monotonic()+1,actual_binding=adapter.refresh()['binding'])
        report=adapter.execute(proposal)
        self.assertFalse(report['accepted']);diagnostic=report['stock_diagnostics']
        self.assertEqual(diagnostic['request_id'],fixtures.FOREIGN);self.assertEqual(diagnostic['first_failure']['owned_uuid'],fixtures.OWN)
        final=dict(motion_after=adapter.status(),motion_receipts=adapter.receipts)
        self.assertEqual(report_summary(final)['stock_diagnostics'],diagnostic)
        self.assertFalse(final['motion_after']['stop_known'])
        # Actual run_session consumes the already published adapter result.
        from test_lease_diagnostics import Harness
        harness=Harness('user_stop');adapter.cached['binding']['agent_boot_id']='PRIVATE-AGENT'
        harness.scheduler.motion_adapter=adapter
        session_report=harness.run()
        self.assertEqual(session_report['errors'],[],session_report)
        self.assertEqual(session_report['motion_after']['stock_diagnostics'],diagnostic)
        self.assertIn('motion_stop_unknown',session_report['cleanup_issues'])
        self.assertEqual(report_summary(session_report)['stock_diagnostics'],diagnostic)
        unrelated={"request_id":fixtures.OWN};adapter.capture_diagnostic(self.hub.stock_diagnostic_token(),unrelated)
        self.assertNotIn('stock_diagnostics',unrelated)
        diagnostic['first_failure']['cause']='PRIVATE'
        self.assertNotIn('PRIVATE',json.dumps(adapter.status()))
        self.assertEqual(adapter.status()['stock_diagnostics']['first_failure']['cause'],'request_error')

    def test_projection_filters_content_bounds_and_nonfinite_values(self):
        raw=dict(request_id='SECRET',first_failure=dict(stage='stop_post',cause='request_error',at=float('nan'),hub_boot_id='SECRET',error_class='SECRET',http_status=True,owned_uuid='SECRET'),
            stop_receipt=dict(preflight=[dict(elapsed_s=True,absence='SECRET',error_class='SECRET')]*100,post=dict(attempted=True,accepted=None,private='SECRET'),private='SECRET'))
        raw['first_failure']['at']=10**400
        value=project(raw);self.assertNotIn('SECRET',json.dumps(value));self.assertEqual(len(value['stop_receipt']['preflight']),2)
        self.assertIsNone(value['first_failure']['at']);self.assertIsNone(value['first_failure']['http_status'])

    def test_standalone_status_projection_matches_summary(self):
        import subprocess,sys,tempfile
        from pathlib import Path
        from reachy_companion.production_status import REMOTE_PROBE
        _,record=self.stop_case('404')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=root/'data/production-fixture';data.mkdir(parents=True)
            report=dict(accepted=False,motion_after=dict(stock_diagnostics=record))
            (data/'hub.json').write_text(json.dumps(report))
            result=subprocess.run([sys.executable,'-c',REMOTE_PROBE,str(root),'hub'],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['last_session']['stock_diagnostics'],report_summary(report)['stock_diagnostics'])

    def test_actual_follow_failure_join_and_latch_precedes_recording(self):
        from test_person_follow import pose
        self.operator.update(microphone_enabled=True,expression_version=5)
        self.hub.operator_proxy=lambda:(copy.deepcopy(self.operator),time.monotonic())
        adapter=StockMotionAdapter(self.hub,follow_person=True);adapter.follow_admitted=True
        adapter.follower.plan=Mock(return_value=dict(head_pose=dict(x=0,y=0,z=0,roll=0,pitch=0,yaw=.02),
            body_yaw=.01,antennas=None,duration=.35,interpolation='minjerk'))
        original=self.factory
        def factory(path,payload=None):
            if path=='/api/state/full':return dict(pose(),control_mode='enabled')
            if path=='/api/move/stop':self.active=[];raise HTTPError('PRIVATE',500,'SECRET',{},None)
            return original(path,payload)
        self.hub.factory.side_effect=factory;self.on_post=adapter.cancel.set;self.on_poll=lambda:None
        observed=[];fail=self.hub.stock_diagnostics.fail
        def record(*args):observed.append(self.hub.stock_unknown);return fail(*args)
        self.hub.stock_diagnostics.fail=record
        proposal=dict(request_id=fixtures.FOREIGN,sample={},allow_scan=True,captured=time.monotonic(),deadline=time.monotonic()+1,actual_binding=adapter.refresh()['binding'])
        report=adapter.follow(proposal)
        self.assertFalse(report['accepted']);self.assertEqual(report['error_phase'],'dispatch')
        self.assertTrue(observed);self.assertTrue(all(observed))
        self.assertEqual(report['stock_diagnostics']['first_failure']['http_status'],500)
        self.assertEqual(report['stock_diagnostics']['request_id'],fixtures.FOREIGN)
        self.assertFalse(adapter.status()['stop_known'])
