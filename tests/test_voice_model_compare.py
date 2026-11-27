import contextlib
import importlib.util
import io
import json
from http.client import IncompleteRead
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch


PATH = Path(__file__).resolve().parents[1] / 'deploy/autonomous/voice_model_compare.py'
spec = importlib.util.spec_from_file_location('voice_model_compare_fixture', PATH)
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


class VoiceModelCompareTests(unittest.TestCase):
    def test_default_has_no_process_network_or_inference(self):
        with patch.object(compare.sys, 'argv', [str(PATH)]), \
             patch.object(compare.subprocess, 'Popen', side_effect=AssertionError('process')), \
             patch.object(compare.subprocess, 'run', side_effect=AssertionError('probe')), \
             patch.object(compare, 'urlopen', side_effect=AssertionError('network')), \
             patch.object(compare.Gateway, 'generate', side_effect=AssertionError('inference')), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            compare.main()
        value = json.loads(out.getvalue())
        self.assertTrue(value['dry_run'])
        self.assertEqual(value['cases'], 12)
        self.assertEqual(value['completion_calls'], 0)

    def test_context_and_policy_settings_equal_except_artifact_identity(self):
        a = compare.config_for('9b', 18941, 'a' * 64)
        b = compare.config_for('0.8b', 18942, 'b' * 64)
        for cfg in (a, b):
            model = cfg['models']['main']
            self.assertTrue(model['structured_reply'])
            for key in ('id', 'base_url'):
                model.pop(key)
            for key in ('weight_sha256', 'tokenizer_sha256'):
                model['audit'].pop(key)
        self.assertEqual(a, b)

    def test_seed_and_cache_change_only_measurement_payload(self):
        backend = compare.MeasuredBackend({'models': {}}, Mock(), 18941)
        original = dict(model='fixture', prompt='synthetic', cache_prompt=True)
        with patch.object(compare, 'listener_owned', return_value=True), \
             patch.object(compare.ModelBackend, 'post', return_value={'content': '{"response":"4"}'}) as post:
            backend.post('http://127.0.0.1:18941/completion', original, 30)
        sent = post.call_args.args[1]
        self.assertFalse(sent['cache_prompt'])
        self.assertEqual(sent['seed'], 1729)
        self.assertTrue(original['cache_prompt'])
        self.assertNotIn('seed', original)

    def test_lost_ownership_never_sends_http(self):
        backend = compare.MeasuredBackend({'models': {}}, Mock(), 18941)
        with patch.object(compare, 'listener_owned', return_value=False), \
             patch.object(compare.ModelBackend, 'post') as post:
            with self.assertRaises(compare.ExecutionUnknown):
                backend.post('http://127.0.0.1:18941/completion', {}, 30)
        post.assert_not_called()

    def test_failure_after_spawn_still_reaps_exact_child(self):
        child = Mock(pid=123, returncode=None)
        child.poll.side_effect = lambda: child.returncode
        child.wait.side_effect = lambda **kw: setattr(child, 'returncode', -15)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(compare, 'file_digest', return_value='fixture'), \
             patch.object(compare.socket, 'socket'), \
             patch.object(compare.subprocess, 'Popen', return_value=child), \
             patch.object(compare, 'listener_owned', side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(RuntimeError):
                compare.run_block('9b', 'model.gguf', 18941, Path(directory), Path('/synthetic/llama'),
                                  {'model.gguf': {'sha256': 'fixture'}}, [], Path(directory))
            receipt = json.loads((Path(directory) / '9b-owner.json').read_text())
        child.terminate.assert_called_once_with()
        child.wait.assert_called_once_with(timeout=10)
        child.kill.assert_not_called()
        self.assertTrue(receipt['known_exit'])
        self.assertEqual(receipt['pid'], 123)

    def test_global_deadline_cannot_be_swallowed_as_case_failure(self):
        self.assertFalse(issubclass(compare.ComparisonDeadline, Exception))

    def test_first_receipt_disk_failure_still_reaps_spawned_child(self):
        child = Mock(pid=123, returncode=None)
        child.poll.side_effect = lambda: child.returncode
        child.wait.side_effect = lambda **kw: setattr(child, 'returncode', -15)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(compare, 'file_digest', return_value='fixture'), \
             patch.object(compare.socket, 'socket'), \
             patch.object(compare.subprocess, 'Popen', return_value=child), \
             patch.object(compare, 'write', side_effect=PermissionError('fixture disk failure')), \
             patch.object(compare, 'listener_owned') as listener:
            with self.assertRaises(PermissionError):
                compare.run_block('9b', 'model.gguf', 18941, Path(directory), Path('/synthetic/llama'),
                                  {'model.gguf': {'sha256': 'fixture'}}, [], Path(directory))
        listener.assert_not_called()
        child.terminate.assert_called_once_with()
        child.wait.assert_called_once_with(timeout=10)
        self.assertEqual(child.returncode, -15)

    def test_unknown_cleanup_keeps_receipt_and_aborts(self):
        child = Mock(pid=123, returncode=None)
        child.poll.return_value = None
        child.wait.side_effect = compare.subprocess.TimeoutExpired('fixture', 5)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(compare, 'file_digest', return_value='fixture'), \
             patch.object(compare.socket, 'socket'), \
             patch.object(compare.subprocess, 'Popen', return_value=child), \
             patch.object(compare, 'listener_owned', side_effect=RuntimeError('fixture failure')):
            with self.assertRaisesRegex(RuntimeError, 'cleanup unknown'):
                compare.run_block('9b', 'model.gguf', 18941, Path(directory), Path('/synthetic/llama'),
                                  {'model.gguf': {'sha256': 'fixture'}}, [], Path(directory))
            receipt = json.loads((Path(directory) / '9b-owner.json').read_text())
        child.kill.assert_called_once_with()
        self.assertFalse(receipt['known_exit'])
        self.assertEqual(receipt['cleanup_error_class'], 'TimeoutExpired')

    def test_incomplete_http_response_blocks_every_later_inference_and_reaps(self):
        child = Mock(pid=123, returncode=None)
        child.poll.side_effect = lambda: child.returncode
        child.wait.side_effect = lambda **kw: setattr(child, 'returncode', -15)
        health = MagicMock()
        health.__enter__.return_value.status = 200
        calls = []
        def transport(url, payload, timeout, token_env=''):
            calls.append(url)
            if url.endswith('/tokenize'):
                return {'tokens': [1]}
            raise IncompleteRead(b'truncated')
        cases, _ = compare.corpus()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(compare, 'file_digest', return_value='a' * 64), \
             patch.object(compare.socket, 'socket'), \
             patch.object(compare.subprocess, 'Popen', return_value=child), \
             patch.object(compare, 'urlopen', return_value=health), \
             patch.object(compare, 'listener_owned', return_value=True), \
             patch.object(compare.ModelBackend, 'post', side_effect=transport):
            report = compare.run_block('9b', 'model.gguf', 18941, Path(directory), Path('/synthetic/llama'),
                                       {'model.gguf': {'sha256': 'a' * 64}}, cases['cases'], Path(directory))
        self.assertEqual(sum(url.endswith('/completion') for url in calls), 1)
        self.assertEqual(report['cases'][0]['error_class'], 'ExecutionUnknown')
        self.assertEqual([v['state'] for v in report['cases'][1:]], ['not_run'] * 12)
        self.assertTrue(report['known_exit'])
        child.terminate.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
