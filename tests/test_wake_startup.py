"""Explicit wake belongs to operator start; disabled motors cannot be READY."""
import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from reachy_companion.production_status import summarize

ROOT=Path(__file__).resolve().parents[1]


def load_control():
    loader=importlib.machinery.SourceFileLoader('wake_control',str(ROOT/'scripts/production-control'))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec);loader.exec_module(module)
    return module


class WakeStartupTests(unittest.TestCase):
    def setUp(self):self.control=load_control()

    def test_disabled_motors_wake_once_and_require_terminal_receipt(self):
        states=[dict(motion_required=True,control_mode='disabled'),dict(motion_required=True,control_mode='enabled')]
        with patch.object(self.control,'robot_state',side_effect=states),patch.object(self.control,'command',return_value=SimpleNamespace(stdout='{"ok":true,"completion_observed":true}')) as command:
            self.assertTrue(self.control.ensure_robot_awake())
            command.assert_called_once()
            self.assertIn('/actions/wake',command.call_args.args[-1])

    def test_enabled_or_voice_only_profile_never_moves(self):
        for state in (dict(motion_required=True,control_mode='enabled'),dict(motion_required=False,control_mode=None)):
            with patch.object(self.control,'robot_state',return_value=state),patch.object(self.control,'command') as command:
                self.assertFalse(self.control.ensure_robot_awake());command.assert_not_called()

    def test_unknown_modes_and_unknown_completion_are_not_retried(self):
        for mode in ('gravity_compensation','unknown',None):
            with patch.object(self.control,'robot_state',return_value=dict(motion_required=True,control_mode=mode)),patch.object(self.control,'command') as command:
                with self.assertRaises(RuntimeError):self.control.ensure_robot_awake()
                command.assert_not_called()
        with patch.object(self.control,'robot_state',return_value=dict(motion_required=True,control_mode='disabled')),patch.object(self.control,'command',return_value=SimpleNamespace(stdout='{"ok":true,"completion_observed":false}')) as command:
            with self.assertRaisesRegex(RuntimeError,'completion unknown'):self.control.ensure_robot_awake()
            command.assert_called_once()

    def test_start_wakes_after_device_owner_but_before_autonomous_owner(self):
        order=[]
        def command(*args,**kwargs):
            if args[-1]=='sudo -n systemctl start reachy-production-audio':order.append('device')
            if args[-1]=='sudo -n systemctl restart reachy-production-audio':order.append('fresh_device')
            if args[-1]=='sudo -n systemctl start reachy-production':order.append('hub')
            return SimpleNamespace(returncode=0,stdout='inactive')
        with patch.object(self.control.sys,'argv',['production-control','start']),patch.object(self.control,'command',side_effect=command),patch.object(self.control,'health',return_value={'all':True}),patch.object(self.control,'session',side_effect=[{'stage':'unavailable'},{'stage':'ACTIVE','listening_ready':True}]),patch.object(self.control,'robot_state',return_value=dict(motion_required=True,control_mode='disabled')),patch.object(self.control,'stop_services'),patch.object(self.control,'ensure_robot_awake',side_effect=lambda:order.append('wake') or True),patch.object(self.control,'status'):
            self.control.main()
        self.assertEqual(order,['device','wake','fresh_device','hub'])

    def test_failed_wake_stops_device_and_does_not_start_autonomous_owner(self):
        calls=[]
        def command(*args,**kwargs):calls.append(args);return SimpleNamespace(returncode=0,stdout='inactive')
        with patch.object(self.control.sys,'argv',['production-control','start']),patch.object(self.control,'command',side_effect=command),patch.object(self.control,'health',return_value={'all':True}),patch.object(self.control,'session',return_value={'stage':'unavailable'}),patch.object(self.control,'robot_state',return_value=dict(motion_required=True,control_mode='disabled')),patch.object(self.control,'stop_services') as stop,patch.object(self.control,'ensure_robot_awake',side_effect=RuntimeError('wake unknown')):
            with self.assertRaisesRegex(RuntimeError,'wake unknown'):self.control.main()
        self.assertEqual(stop.call_count,2)
        self.assertFalse(any(args[-1]=='sudo -n systemctl start reachy-production' for args in calls))

    def test_motor_disabled_or_unknown_is_degraded_for_active_motion_profile(self):
        models={'llm':dict(ready=True)}
        hosts={'hub':dict(reachable=True,services={},session=dict(stage='ACTIVE',listening_ready=True),capabilities=dict(motion=True)),
               'robot':dict(reachable=True,services={},firewall=dict(inspected=True,duplicate_rules=0))}
        for mode in ('disabled','unknown','gravity_compensation'):
            hosts['robot']['motor_mode']=mode
            result=summarize(models,hosts)
            self.assertEqual(result['state'],'degraded');self.assertIn('motors:'+mode,result['issues'])
        hosts['robot']['motor_mode']='enabled'
        self.assertEqual(summarize(models,hosts)['state'],'ready')


if __name__=='__main__':unittest.main()
