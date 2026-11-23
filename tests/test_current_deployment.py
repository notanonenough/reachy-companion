"""Audited deployment can be rendered/rehearsed without touching devices."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'deploy/current'
spec = importlib.util.spec_from_file_location('current_deployment', HERE / 'manage.py')
manage = importlib.util.module_from_spec(spec); spec.loader.exec_module(manage)


class CurrentDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest = manage.load_manifest()

    def values(self):
        return {name: 'fixture-value-only' for name in self.manifest['secrets'] if name.startswith('SECRET_')}

    def test_all_hosts_render_and_configuration_is_valid_json(self):
        for host in self.manifest['hosts']:
            rows = manage.render(self.manifest, host, self.values())
            self.assertTrue(rows)
            for row in rows:
                self.assertNotIn(b'@@', row['data'])
                if '.json' in row['source']:
                    json.loads(row['data'])
                if row['kind'] == 'systemd' or 'dispatcher.d/' in row['source']:
                    self.assertNotIn(b'releases/ops-', row['data'])
                    self.assertNotIn(b'releases/continuous-', row['data'])
                    if b'PYTHONPATH=' in row['data']:
                        self.assertIn(b'/current/src', row['data'])

    def test_missing_secret_blocks_render_and_never_leaks_value(self):
        with self.assertRaisesRegex(ValueError, 'Missing deployment value: SECRET_'):
            manage.render(self.manifest, 'router', {})

    def test_example_placeholders_are_not_installable_credentials(self):
        values = json.loads((HERE / 'values.example.json').read_text())
        with self.assertRaisesRegex(ValueError, 'Missing deployment value: SECRET_'):
            manage.render(self.manifest, 'router', values)

    def test_rehearsal_install_backups_and_content_verification(self):
        rows = manage.render(self.manifest, 'hub', self.values(), scopes=['runtime'])
        stage = self.root / 'stage'; manage.write_stage(rows, stage)
        sandbox = self.root / 'sandbox'
        manage.install(stage, self.root / 'backup', scopes=['runtime'], root=sandbox)
        self.assertEqual(manage.verify(stage, root=sandbox), [])
        victim = sandbox / rows[0]['target'].lstrip('/')
        victim.write_text('changed')
        self.assertEqual(manage.verify(stage, root=sandbox), [rows[0]['target']])
        manage.install(stage, self.root / 'backup2', scopes=['runtime'], root=sandbox)
        self.assertEqual((self.root / 'backup2' / rows[0]['target'].lstrip('/')).read_text(), 'changed')
        self.assertEqual(manage.verify(stage, root=sandbox), [])

    def test_network_and_factory_not_installed_by_runtime_scope(self):
        rows = manage.render(self.manifest, 'robot', self.values())
        stage = self.root / 'stage'; manage.write_stage(rows, stage)
        installed = manage.install(stage, self.root / 'backup', scopes=['runtime'], root=self.root / 'sandbox')
        self.assertTrue(installed)
        self.assertTrue(all(row['scope'] == 'runtime' for row in installed))
        self.assertFalse((self.root / 'sandbox/etc/NetworkManager').exists())

    def test_tampered_stage_is_rejected_before_any_install(self):
        rows = manage.render(self.manifest, 'hub', self.values(), scopes=['runtime'])
        stage = self.root / 'stage'; manage.write_stage(rows, stage)
        (stage / 'rootfs' / rows[-1]['target'].lstrip('/')).write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'Staged content changed'):
            manage.install(stage, self.root / 'backup', scopes=['runtime'], root=self.root / 'sandbox')
        self.assertFalse((self.root / 'sandbox').exists())

    def test_path_traversal_and_symlink_targets_are_rejected(self):
        with self.assertRaises(ValueError):
            manage.render(self.manifest, 'hub', dict(self.values(), ROOT='/tmp/../etc'))
        rows = manage.render(self.manifest, 'hub', self.values(), scopes=['runtime'])
        stage = self.root / 'stage'; manage.write_stage(rows, stage)
        target = self.root / 'sandbox' / rows[-1]['target'].lstrip('/')
        target.parent.mkdir(parents=True); target.symlink_to(self.root / 'unrelated')
        with self.assertRaisesRegex(ValueError, 'destination symlink'):
            manage.install(stage, self.root / 'backup', scopes=['runtime'], root=self.root / 'sandbox')
        self.assertFalse((self.root / 'backup').exists())

    def test_artifact_manifest_has_pinned_sources_and_complete_whisper(self):
        manifest = json.loads((HERE / 'artifacts.lock.json').read_text())
        rows = manifest['artifacts']
        self.assertTrue(any(row['path'].endswith('/vocabulary.txt') for row in rows))
        self.assertTrue(any(row['path'].endswith('/tokenizer.json') for row in rows))
        for row in rows:
            self.assertEqual(len(row['sha256']), 64)
            self.assertGreater(row['bytes'], 0)
            self.assertTrue(row.get('url') or row.get('repository_file'))
            self.assertNotIn('/resolve/main/', row.get('url') or '')
            if row.get('repository_file'):
                self.assertEqual(manage.digest((ROOT / row['repository_file']).read_bytes()), row['sha256'])


if __name__ == '__main__':
    unittest.main()
