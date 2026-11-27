"""Opt-in isolated local model comparison. Default only validates the frozen corpus."""
import argparse
import copy
import hashlib
import json
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from reachy_companion.autonomous.contracts import validate
from reachy_companion.autonomous.gateway import ExecutionUnknown, Gateway, ModelBackend

MODELS = (
    ('9b', 'models/qwen3.5-9b/Qwen3.5-9B-Q4_K_M.gguf', 18941),
    ('0.8b', 'models/Qwen3.5-0.8B-Q8_0.gguf', 18942),
)
WARMUP = 'Ответь одним словом: готов.'


class ComparisonDeadline(BaseException):
    """Cannot be swallowed as an individual inference failure."""


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def corpus():
    path = ROOT / 'tests/fixtures/voice_compare/cases.json'
    body = json.loads(path.read_text())
    assert len(body['cases']) == 12
    assert len({c['id'] for c in body['cases']}) == 12
    for case in body['cases']:
        assert digest(case['input']) == case['input_sha256']
        for item in case['input']['memory']:
            validate('MemoryItem', item)
        for item in case['input']['observations']:
            validate('FastSensorView', item)
    return body, file_digest(path)


def listener_owned(process, port):
    if process.poll() is not None:
        return False
    result = subprocess.run(['/usr/sbin/lsof', '-nP', '-a', '-p', str(process.pid),
                             '-iTCP:' + str(port), '-sTCP:LISTEN', '-Fp'],
                            capture_output=True, text=True, timeout=2)
    return result.returncode == 0 and result.stdout.splitlines() == ['p' + str(process.pid)]


class MeasuredBackend(ModelBackend):
    def __init__(self, config, process, port):
        super().__init__(config)
        self.process, self.port = process, port
        self.native = None
        self.payload_sha256 = None
        self.ownership_check_s = 0

    def post(self, url, payload, timeout, token_env=''):
        began = time.monotonic()
        owned = listener_owned(self.process, self.port)
        self.ownership_check_s += time.monotonic() - began
        if not owned:
            raise ExecutionUnknown('Own listener lost')
        if url.endswith('/completion'):
            payload = {**payload, 'seed': 1729, 'cache_prompt': False}
            self.payload_sha256 = digest(payload)
        response = super().post(url, payload, timeout, token_env)
        if url.endswith('/completion'):
            self.native = {key: response.get(key) for key in
                           ('content', 'stop_type', 'tokens_predicted', 'tokens_evaluated',
                            'tokens_cached', 'timings', 'generation_settings')}
        return response


def config_for(label, port, expected_hash):
    original = json.loads((ROOT / 'deploy/current/mac/config/config.autonomous.mac.local.json.template').read_text())
    model = copy.deepcopy(original['models']['main'])
    model.update(id='voice-compare-' + label, base_url='http://127.0.0.1:' + str(port))
    model['audit'].update(weight_sha256=expected_hash, tokenizer_sha256=expected_hash)
    return dict(models={'main': model}, http_timeout_s=30)


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def run_block(label, model_rel, port, installed_root, binary, lock, cases, output):
    model_path = installed_root / model_rel
    expected = lock[model_rel]['sha256']
    if file_digest(model_path) != expected:
        raise ValueError('Pinned model hash mismatch')
    # Readiness cannot accidentally attach to a running service on this port.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    argv = [str(binary), 'serve', '-m', str(model_path), '--host', '127.0.0.1',
            '--port', str(port), '-c', '8192', '-np', '1', '-ngl', '99',
            '--alias', 'voice-compare-' + label, '--reasoning', 'off', '--cache-ram', '512']
    summary = dict(model=label, model_sha256=expected, argv=argv,
                   planned_case_ids=[case['id'] for case in cases], cases=[], known_exit=False)
    begin = time.monotonic()
    with (output / (label + '-server.log')).open('wb') as log:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        summary['pid'] = process.pid
        write(output / (label + '-owner.json'), summary)
        try:
            deadline = begin + 90
            while True:
                if process.poll() is not None:
                    raise RuntimeError('Own server exited before readiness')
                if time.monotonic() >= deadline:
                    raise TimeoutError('Server readiness deadline')
                if listener_owned(process, port):
                    try:
                        with urlopen('http://127.0.0.1:' + str(port) + '/health', timeout=1) as response:
                            if response.status == 200:
                                break
                    except (URLError, TimeoutError):
                        pass
                time.sleep(.1)
            summary['load_to_ready_s'] = time.monotonic() - begin
            cfg = config_for(label, port, expected)
            summary['effective_config'] = cfg
            backend = MeasuredBackend(cfg, process, port)
            gateway = Gateway(backend)
            warm = copy.deepcopy(cases[0]['input'])
            warm['utterance'] = WARMUP
            warm['state']['working']['last_input'] = 'Synthetic warmup (speaker unknown): ' + WARMUP
            scheduled = [dict(id='warmup', input=warm, input_sha256=digest(warm))] + cases
            blocked = False
            for case in scheduled:
                record = dict(case_id=case['id'], input_sha256=case['input_sha256'],
                              measured=case['id'] != 'warmup', state='not_run')
                if not blocked:
                    backend.native = None
                    backend.payload_sha256 = None
                    backend.ownership_check_s = 0
                    start = time.monotonic()
                    try:
                        record['result'] = gateway.generate('main', case['input'],
                                                            request_id=label + '-' + case['id'])
                        record['state'] = 'terminal_valid'
                    except Exception as exc:
                        record.update(state='failed', error_class=type(exc).__name__,
                                      model_timing=getattr(exc, 'model_timing', None))
                        blocked = isinstance(exc, ExecutionUnknown)
                    finally:
                        record.update(client_s=time.monotonic() - start, native=backend.native,
                                      included_ownership_check_s=backend.ownership_check_s,
                                      completion_payload_sha256=backend.payload_sha256)
                summary['cases'].append(record)
                write(output / (label + '-results.json'), summary)
            summary['listener_owned_at_end'] = listener_owned(process, port)
        finally:
            # A live unreaped Popen child cannot have its PID reused by another process.
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            summary.update(known_exit=process.poll() is not None, returncode=process.returncode,
                           total_block_s=time.monotonic() - begin)
            write(output / (label + '-results.json'), summary)
            write(output / (label + '-owner.json'), {k: v for k, v in summary.items() if k != 'cases'})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--installed-root', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    body, corpus_hash = corpus()
    if not args.execute:
        print(json.dumps(dict(dry_run=True, cases=12, corpus_sha256=corpus_hash,
                              subprocesses=0, network_calls=0, completion_calls=0)))
        return
    if args.installed_root is None or args.output is None:
        parser.error('--execute requires --installed-root and --output')
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    binary = Path.home() / '.local/bin/llama'
    lock = {x['path']: x for x in json.loads((ROOT / 'deploy/current/artifacts.lock.json').read_text())['artifacts']}
    expected_binary = lock['@@HOME@@/.local/bin/llama']['sha256']
    if file_digest(binary) != expected_binary:
        raise ValueError('Pinned binary hash mismatch')
    def expired(signum, frame):
        raise ComparisonDeadline('Comparison total deadline')
    old = signal.signal(signal.SIGALRM, expired)
    signal.alarm(900)
    report = dict(corpus_sha256=corpus_hash, binary_sha256=expected_binary,
                  runner_sha256=file_digest(Path(__file__)),
                  gateway_source_sha256=file_digest(ROOT / 'src/reachy_companion/autonomous/gateway.py'),
                  planned_models=[label for label, _, _ in MODELS],
                  planned_cases=[case['id'] for case in body['cases']],
                  warmup_utterance=WARMUP, blocks=[])
    try:
        for label, model, port in MODELS:
            report['blocks'].append(run_block(label, model, port, args.installed_root,
                                              binary, lock, body['cases'], args.output))
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)
        write(args.output / 'comparison.json', report)


if __name__ == '__main__':
    main()
