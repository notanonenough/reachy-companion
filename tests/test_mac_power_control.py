"""Manual Mac lifecycle: no login autostart and no orphaned compute children."""
import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import plistlib
import signal
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def load(name,path):
    loader=importlib.machinery.SourceFileLoader(name,str(path))
    spec=importlib.util.spec_from_loader(name,loader)
    module=importlib.util.module_from_spec(spec);loader.exec_module(module)
    return module


class MacPowerTests(unittest.TestCase):
    def setUp(self):
        self.control=load('mac_power_control',ROOT/'scripts/production-control')

    def test_remote_failure_still_unloads_mac_and_is_reported(self):
        with patch.object(self.control,'stop_services',side_effect=RuntimeError('remote unavailable')),patch.object(self.control,'stop_mac') as stop:
            with self.assertRaisesRegex(RuntimeError,'remote unavailable'):self.control.shutdown()
            stop.assert_called_once()

    def test_shutdown_tracks_only_owned_children_and_disables_all_jobs(self):
        alive={100:'birth-parent',101:'birth-child'};loaded=[True];calls=[];killed=[]
        def command(*args,**kwargs):
            calls.append(args)
            if args[:2]==('ps','-axo'):return SimpleNamespace(returncode=0,stdout='100 1\n101 100\n999 1\n')
            if args[:2]==('launchctl','print'):
                exists=loaded[0] and args[-1].endswith('.llm')
                return SimpleNamespace(returncode=0 if exists else 113,stdout=' pid = 100\n' if exists else '')
            if args[:2]==('launchctl','bootout'):loaded[0]=False;alive.pop(100,None)
            return SimpleNamespace(returncode=0,stdout='')
        def kill(pid,sig):killed.append((pid,sig));alive.pop(pid,None)
        with patch.object(self.control,'command',side_effect=command),patch.object(self.control,'process_identity',side_effect=lambda pid:alive.get(pid)),patch.object(self.control.os,'kill',side_effect=kill):
            self.control.stop_mac()
        self.assertEqual(killed,[(101,signal.SIGTERM)])
        self.assertEqual(sum(args[:2]==('launchctl','disable') for args in calls),len(self.control.labels()))
        self.assertFalse(loaded[0])

    def test_process_identity_ignores_running_state_but_rejects_zombies(self):
        values=['Mon Nov 2 12:00:00 2026 S','Mon Nov 2 12:00:00 2026 R','Mon Nov 2 12:00:00 2026 Z']
        with patch.object(self.control,'command',side_effect=[SimpleNamespace(returncode=0,stdout=v) for v in values]):
            a=self.control.process_identity(1);b=self.control.process_identity(1);z=self.control.process_identity(1)
        self.assertEqual(a,b);self.assertIsNone(z)

    def test_installer_moves_jobs_out_of_login_directory_and_installs_commands(self):
        installer=load('mac_power_installer',ROOT/'deploy/production/install_maintenance.py')
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary)/'home';root=Path(temporary)/'project';root.mkdir();(root/'scripts').mkdir()
            for name in ('reachy-on','reachy-off'):(root/'scripts'/name).write_text('fixture')
            legacy=home/'Library/LaunchAgents';legacy.mkdir(parents=True)
            for name in self.control.LABELS:
                p=legacy/('local.reachy.'+name+'.plist')
                p.write_bytes(plistlib.dumps(dict(Label='local.reachy.'+name,ProgramArguments=['/bin/echo',name],RunAtLoad=True,KeepAlive=True)))
            with patch.object(installer.Path,'home',return_value=home),contextlib.redirect_stdout(io.StringIO()):
                installer.install_mac(root,root)
                installer.install_mac(root,root)
            manual=home/'Library/Application Support/Reachy Companion/LaunchAgents'
            self.assertEqual(list(legacy.glob('*.plist')),[])
            self.assertEqual(len(list(manual.glob('*.plist'))),5)
            for p in manual.glob('*.plist'):
                data=plistlib.loads(p.read_bytes());self.assertFalse(data['RunAtLoad']);self.assertTrue(data['KeepAlive'])
                self.assertEqual(data['ProgramArguments'].count('reachy_companion.production_logs'),1)
            for name in ('reachy-on','reachy-off'):
                self.assertEqual((home/'.local/bin'/name).resolve(),(root/'scripts'/name).resolve())


if __name__=='__main__':unittest.main()
