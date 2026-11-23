"""Permission controls: persisted OFF, stale ON, concurrent owners, no actuators."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import test_conversation_mode as fixtures
from reachy_companion.camera_permission import CameraPermission, read_permission
from reachy_companion.autonomous.camera_sensor import CameraSensor
from reachy_companion import snapshot_vision


class PanelDevicesTests(unittest.TestCase):
    setUp=fixtures.ConversationModeTests.setUp
    agent=fixtures.ConversationModeTests.agent
    def on(self, a, action):
        s=a.panel_state()
        body=dict(action=action,binding=s['binding'])
        if action=='camera_on':body['camera_generation']=s['camera']['generation']
        return a.panel_control(body)

    def test_motion_permission_does_not_capture_or_move_and_stale_on_loses(self):
        a=self.agent();a.microphone.enabled=False;a.listening.clear()
        binding=a.panel_state()['binding']
        self.on(a,'motion_on')
        self.assertTrue(a.motion_policy.snapshot()['motor_enabled'])
        self.assertFalse(a.microphone.enabled);a.play.assert_not_called();a.request.assert_not_called()
        a.panel_control(dict(action='motion_off'))
        with self.assertRaises(RuntimeError):a.panel_control(dict(action='motion_on',binding=binding))
        self.assertFalse(a.motion_policy.snapshot()['motor_enabled'])

    def test_motion_on_cannot_steal_owner_but_off_preserves_owner(self):
        a=self.agent();a.microphone_owner_id='session'
        with self.assertRaises(RuntimeError):self.on(a,'motion_on')
        a.motion_policy.save(dict(motor_enabled=True,quiet=False,privacy_all=False),expected_epoch=0,owner_id='session')
        a.panel_control(dict(action='motion_off'))
        self.assertFalse(a.motion_policy.snapshot()['motor_enabled'])
        self.assertEqual(a.motion_policy.owner_id,'session')

    def test_camera_controls_work_with_owner_and_off_fences_old_on(self):
        a=self.agent();a.microphone_owner_id='session'
        s=a.panel_state();old=dict(action='camera_on',binding=s['binding'],camera_generation=s['camera']['generation'])
        self.on(a,'camera_on')
        self.assertTrue(a.camera_permission.snapshot()['enabled'])
        a.panel_control(dict(action='camera_off'))
        with self.assertRaises(RuntimeError):a.panel_control(old)
        self.assertFalse(a.camera_permission.snapshot()['enabled'])
        self.assertEqual(a.microphone_owner_id,'session')
        self.assertTrue(a.microphone.enabled);a.request.assert_not_called()

    def test_camera_ON_rejects_privacy_and_stale_binding(self):
        a=self.agent();s=a.panel_state()
        a.motion_policy.save(dict(motor_enabled=False,quiet=False,privacy_all=True))
        with self.assertRaises(RuntimeError):self.on(a,'camera_on')
        with self.assertRaises(RuntimeError):a.panel_control(dict(action='camera_on',binding=s['binding'],camera_generation=0))
        self.assertFalse(a.camera_permission.snapshot()['enabled'])

    def test_STOP_revokes_camera_and_motion_and_prior_ON(self):
        a=self.agent();self.on(a,'camera_on');self.on(a,'motion_on')
        s=a.panel_state()
        a.sounds=Mock();a.audio_lock=__import__('threading').Lock()
        a.stop_speaker=Mock()
        a.panel_control(dict(action='stop'))
        self.assertFalse(a.camera_permission.snapshot()['enabled'])
        self.assertFalse(a.motion_policy.snapshot()['motor_enabled'])
        self.assertFalse(a.microphone.enabled)
        with self.assertRaises(RuntimeError):a.panel_control(dict(action='motion_on',binding=s['binding']))
        with self.assertRaises(RuntimeError):a.panel_control(dict(action='camera_on',binding=s['binding'],camera_generation=s['camera']['generation']))


class CameraPermissionTests(unittest.TestCase):
    def test_persistence_corruption_and_off_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'camera.json';c=CameraPermission(path)
            self.assertFalse(c.snapshot()['enabled'])
            c.save(True,0);self.assertTrue(CameraPermission(path).snapshot()['enabled'])
            path.write_text('{broken')
            self.assertFalse(read_permission(path)['enabled'])
            with self.assertRaises(RuntimeError):c.save(True)
            c.save(False);self.assertIsNone(c.snapshot()['error'])
            self.assertFalse(c.snapshot()['enabled'])

    def test_closed_camera_never_fetches_operator_or_captures(self):
        with tempfile.TemporaryDirectory() as directory:
            class Config(dict):
                def path(self,value):return Path(directory)/value
            c=Config(paths={'data_dir':'data'});sensor=CameraSensor(c)
            sensor.opener=Mock()
            self.assertIsNone(sensor.operator());sensor.opener.open.assert_not_called()
            with patch.object(snapshot_vision,'select_model') as model,patch.object(snapshot_vision,'capture_png') as capture:
                with self.assertRaises(ValueError):snapshot_vision.caption_checked(
                    dict(camera_permission_path=str(Path(directory)/'absent')),100,'hello',Mock())
                model.assert_not_called();capture.assert_not_called()

    def test_snapshot_rechecks_permission_before_image_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            c=CameraPermission(Path(directory)/'camera.json');c.save(True,0)
            def capture():c.save(False);return b'image',10
            connection=Mock()
            with patch.object(snapshot_vision,'native_address',return_value=('localhost',1)),patch.object(snapshot_vision,'get_models'),patch.object(snapshot_vision,'select_model',return_value=({'capabilities':{}},'model')),patch.object(snapshot_vision,'capture_png',side_effect=capture),patch.object(snapshot_vision.http.client,'HTTPConnection',return_value=connection):
                with self.assertRaises(ValueError):snapshot_vision.caption_checked(
                    dict(camera_permission_path=str(c.path),llm={'model':'model'}),100,'hello',Mock(return_value=10))
                connection.request.assert_not_called()


if __name__=='__main__':unittest.main()
