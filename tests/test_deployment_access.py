"""Mac access changes are bounded, reversible and resolved by real OpenSSH."""
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1] / 'deploy/current'
sys.path.insert(0, str(HERE))
try:
    spec = importlib.util.spec_from_file_location('deployment_access', HERE / 'access.py')
    access = importlib.util.module_from_spec(spec); spec.loader.exec_module(access)
finally:
    sys.path.pop(0)


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'root'; self.root.mkdir()
        self.home = Path('/Users/fixture user')
        self.config = self.root / str(self.home).lstrip('/') / '.ssh/config'
        self.stage = self.base / 'stage'
        self.backup = self.base / 'backup'
        access.stage(self.home, 'direct', self.stage)

    def original(self, content=b'# private comment\nHost unrelated\n    HostName 127.0.0.2\n'):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_bytes(content); self.config.chmod(0o640)
        return content

    def test_scope_private_backup_absence_restore_and_repeat_rollback(self):
        old = self.original()
        journal = access.install(self.stage, self.backup, self.root)
        self.assertEqual(len(journal['files']), 4)
        self.assertTrue(all('reachy-network-recovery' in r['target'] or r['target'].endswith('/.ssh/config') for r in journal['files']))
        self.assertEqual(access.verify(self.backup), [])
        self.assertTrue((self.config.parent / 'cm').is_dir())
        self.assertTrue(self.config.read_bytes().endswith(old))
        self.assertEqual(stat.S_IMODE(self.backup.stat().st_mode), 0o700)
        self.assertTrue(all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in self.backup.iterdir()))
        access.rollback(self.backup); access.rollback(self.backup)
        self.assertEqual(self.config.read_bytes(), old)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)
        self.assertFalse((self.root / 'Users/fixture user/reachy-network-recovery').exists())

    def test_absent_config_is_removed_and_install_merge_is_idempotent(self):
        access.install(self.stage, self.backup, self.root)
        installed = self.config.read_bytes()
        second = self.base / 'backup2'
        access.install(self.stage, second, self.root)
        self.assertEqual(self.config.read_bytes(), installed)
        access.rollback(second); access.rollback(self.backup)
        self.assertFalse(self.config.exists())

    @unittest.skipUnless(shutil.which('ssh'), 'OpenSSH required')
    def test_real_ssh_direct_jump_strict_keys_and_foreign_options(self):
        include = self.base / 'foreign-include'
        include.write_text('Host *\n ProxyCommand foreign-proxy\n ProxyJump foreign-jump\n ServerAliveInterval 17\n')
        old = self.original(('Include ' + str(include) + '\nHost unrelated\n    HostName example.invalid\n').encode())
        before = subprocess.check_output(['ssh', '-G', '-F', str(self.config), 'unrelated'], stderr=subprocess.DEVNULL)
        for route in ('direct', 'jump'):
            stage = self.base / ('stage-' + route)
            access.stage(self.home, route, stage)
            backup = self.base / ('backup-' + route)
            access.install(stage, backup, self.root)
            for alias, address, key in [('reachy-mini', '192.168.0.184', 'robot'), ('reachy-hub', '192.168.0.186', 'hub'), ('reachy-mini.local', '192.168.0.184', 'robot'), ('reachy-hub.local', '192.168.0.186', 'hub')]:
                result = subprocess.run(['ssh', '-G', '-F', str(self.config), alias], check=True, capture_output=True, text=True)
                values = dict(line.split(' ', 1) for line in result.stdout.splitlines())
                self.assertEqual(values['hostname'], address)
                self.assertEqual(values['user'], 'pollen' if key == 'robot' else 'deploy')
                self.assertEqual(values.get('proxycommand', 'none'), 'none')
                self.assertEqual(values.get('proxyjump', 'none'), 'none' if route == 'direct' else 'reachy-router-vuqar')
                self.assertIn(values['stricthostkeychecking'], ('true', 'yes'))
                self.assertIn(key + '-known-hosts', values['userknownhostsfile'])
                self.assertEqual(values['serveraliveinterval'], '17')
            result = subprocess.run(['ssh', '-G', '-F', str(self.config), 'unrelated'], check=True, capture_output=True, text=True)
            self.assertIn('hostname example.invalid', result.stdout)
            self.assertEqual(result.stdout.encode(), before)
            access.rollback(backup)
            self.assertEqual(self.config.read_bytes(), old)

    def test_old_blocks_replaced_without_losing_foreign_bytes(self):
        old = self.original(b'# leading\n' + access.render(self.home, 'jump')[0]['data'] + b'Host other\n HostName other.invalid\n')
        access.install(self.stage, self.backup, self.root)
        actual = self.config.read_bytes()
        self.assertEqual(actual.count(b'# BEGIN reachy local security'), 1)
        self.assertIn(b'# leading\n', actual)
        self.assertTrue(actual.endswith(b'Host other\n HostName other.invalid\n'))
        self.assertNotIn(b'ProxyJump reachy-router-vuqar', actual)
        access.rollback(self.backup); self.assertEqual(self.config.read_bytes(), old)

    def test_ambiguous_markers_fail_before_backup_or_keys(self):
        self.original(b'# BEGIN reachy local security\nHost foreign\n')
        with self.assertRaisesRegex(ValueError, 'markers'):
            access.install(self.stage, self.backup, self.root)
        self.assertFalse(self.backup.exists())

    def test_tampered_stage_and_parent_symlink_fail_before_backup(self):
        path = self.stage / 'rootfs' / str(self.home).lstrip('/') / '.ssh/config'
        path.write_bytes(path.read_bytes() + b'Host hacked\n')
        with self.assertRaises(ValueError):access.install(self.stage, self.backup, self.root)
        self.assertFalse(self.backup.exists())
        path.write_bytes(access.render(self.home, 'direct')[0]['data'])
        (self.root / 'Users').symlink_to(self.base)
        with self.assertRaisesRegex(ValueError, 'symlink'):access.install(self.stage, self.backup, self.root)
        self.assertFalse(self.backup.exists())

    def test_rollback_preserves_later_edits_and_rejects_changed_preimage(self):
        self.original(); access.install(self.stage, self.backup, self.root)
        self.config.write_bytes(self.config.read_bytes() + b'# later owner edit\n')
        with self.assertRaisesRegex(ValueError, 'changed after'):access.rollback(self.backup)
        self.assertTrue(self.config.read_bytes().endswith(b'# later owner edit\n'))
        (self.backup / '3').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'preimage'):access.rollback(self.backup)

    def test_partial_install_has_complete_journal_and_can_rollback(self):
        old = self.original()
        real = access.write_atomic
        def fail_config(path, data, mode):
            if path == self.config:raise OSError('simulated crash')
            real(path, data, mode)
        with patch.object(access, 'write_atomic', side_effect=fail_config):
            with self.assertRaisesRegex(OSError, 'simulated crash'):access.install(self.stage, self.backup, self.root)
        self.assertTrue((self.backup / 'journal.json').exists())
        self.assertEqual(self.config.read_bytes(), old)
        access.rollback(self.backup)
        self.assertFalse((self.root / 'Users/fixture user/reachy-network-recovery').exists())

    def test_retargeted_stage_cannot_write_unmanaged_files(self):
        rows = json.loads((self.stage / 'rendered.json').read_text())
        row = rows[0]
        old = self.stage / 'rootfs' / row['target'].lstrip('/')
        row['target'] = '/etc/unmanaged'
        moved = self.stage / 'rootfs/etc/unmanaged'; moved.parent.mkdir()
        moved.write_bytes(old.read_bytes())
        (self.stage / 'rendered.json').write_text(json.dumps(rows))
        with self.assertRaisesRegex(ValueError, 'pinned template'):
            access.install(self.stage, self.backup, self.root)
        self.assertFalse(self.backup.exists())
        self.assertFalse((self.root / 'etc').exists())

    def test_duplicate_markers_and_destination_symlink_are_rejected(self):
        block = access.render(self.home, 'direct')[0]['data']
        self.original(block + block)
        with self.assertRaisesRegex(ValueError, 'markers'):
            access.install(self.stage, self.backup, self.root)
        self.config.unlink(); self.config.symlink_to(self.base / 'elsewhere')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            access.install(self.stage, self.backup, self.root)
        self.assertFalse(self.backup.exists())

    def test_partial_rollback_can_resume(self):
        old = self.original(); access.install(self.stage, self.backup, self.root)
        real = access.write_atomic
        def fail_restore(path, data, mode):
            if path == self.config:raise OSError('rollback interruption')
            real(path, data, mode)
        with patch.object(access, 'write_atomic', side_effect=fail_restore):
            with self.assertRaisesRegex(OSError, 'rollback interruption'):
                access.rollback(self.backup)
        access.rollback(self.backup)
        self.assertEqual(self.config.read_bytes(), old)

    def test_invalid_route_or_home_is_rejected(self):
        for home, route in [('/tmp/../etc', 'direct'), ('relative', 'jump'), ('/tmp/x"', 'direct'), ('/tmp/home', 'evil')]:
            with self.assertRaises(ValueError):access.render(home, route)

    def test_cli_roundtrip_without_devices(self):
        backup = self.base / 'cli-backup'
        for arguments in [ ['install', '--stage', str(self.stage), '--backup', str(backup), '--root', str(self.root)],
                           ['verify', '--backup', str(backup)], ['rollback', '--backup', str(backup)] ]:
            result = subprocess.run([sys.executable, str(HERE / 'access.py'), *arguments], check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(result.stdout)['ok'])
        self.assertFalse(self.config.exists())


if __name__ == '__main__':unittest.main()
