"""Durable permission to consume camera images; never claims hardware power-off."""
import json
from pathlib import Path
import os
import tempfile
import threading


def read_permission(path):
    try:
        raw = Path(path).read_bytes()
        if len(raw) > 4096:
            raise ValueError('Camera permission size')
        value = json.loads(raw)
        if (set(value) != {'version', 'enabled', 'generation'} or type(value['version']) is not int or value['version'] != 1
                or type(value['enabled']) is not bool
                or type(value['generation']) is not int or not 0 <= value['generation'] < 2**63):
            raise ValueError('Camera permission invalid')
        return dict(enabled=value['enabled'], generation=value['generation'], error=None)
    except (OSError, ValueError, KeyError, TypeError):
        return dict(enabled=False, generation=None, error='Camera permission unavailable')


class CameraPermission:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.error = None
        if not self.path.exists():
            try:
                self._write(dict(version=1, enabled=False, generation=0))
            except OSError:
                self.error = 'Camera permission could not be saved'

    def snapshot(self):
        with self.lock:
            value = read_permission(self.path)
            if self.error:
                value.update(enabled=False, error=self.error)
            return value

    def save(self, enabled, generation=None):
        if type(enabled) is not bool:
            raise ValueError('Boolean camera permission required')
        with self.lock:
            current = self.snapshot()
            actual = current['generation']
            if generation is not None and (type(generation) is not int or generation != actual):
                raise RuntimeError('Camera permission changed')
            if actual is None:
                if enabled:
                    raise RuntimeError('Camera permission unavailable')
                actual = 0
            if actual >= 2**63 - 1:
                raise RuntimeError('Camera generation exhausted')
            try:
                self._write(dict(version=1, enabled=enabled, generation=actual + 1))
            except OSError:
                self.error = 'Camera permission could not be saved'
                raise
            self.error = None
            return self.snapshot()

    def _write(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=self.path.name + '.', dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, 'w') as out:
                json.dump(value, out)
                out.flush()
                os.fsync(out.fileno())
            temporary.replace(self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
