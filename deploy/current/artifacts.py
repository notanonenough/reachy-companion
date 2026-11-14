#!/usr/bin/env python3
"""Fetch or verify exactly pinned model/binary artifacts. Never starts models or robot processes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def fetch(row, destination, repository, *, home=None, artifacts=()):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        raw = Path(temporary) / 'download'
        if row.get('repository_file'):
            source = (repository / row['repository_file']).resolve()
            if not source.is_relative_to(repository.resolve()):
                raise ValueError('Artifact outside repository')
            shutil.copyfile(source, raw)
        else:
            if not row['url'].startswith('https://'):
                raise ValueError('HTTPS artifact URL required')
            request = Request(row['url'], headers={'User-Agent': 'reachy-reproducible-deployment'})
            with urlopen(request, timeout=60) as response, raw.open('wb') as output:
                shutil.copyfileobj(response, output, 4 * 1024 * 1024)
        if row.get('compression') == 'zstd':
            if digest(raw) != row['archive_sha256']:
                raise ValueError('Compressed artifact hash mismatch')
            helper = next(item for item in artifacts if item['path'] == row['decompressor'])
            helper_path = home / helper['path'].removeprefix('@@HOME@@/')
            if digest(helper_path) != helper['sha256']:
                raise ValueError('Pinned decompressor required')
            extracted = Path(temporary) / 'artifact'
            with raw.open('rb') as source, extracted.open('wb') as output:
                subprocess.run([str(helper_path)], stdin=source, stdout=output, check=True, timeout=120)
            raw = extracted
        elif row.get('archive_member'):
            if digest(raw) != row['archive_sha256']:
                raise ValueError('Archive hash mismatch: ' + row['path'])
            with tarfile.open(raw) as archive:
                member = archive.getmember(row['archive_member'])
                if not member.isfile():
                    raise ValueError('Regular archive member required')
                extracted = Path(temporary) / 'artifact'
                with archive.extractfile(member) as source, extracted.open('wb') as output:
                    shutil.copyfileobj(source, output)
            raw = extracted
        if raw.stat().st_size != row['bytes'] or digest(raw) != row['sha256']:
            raise ValueError('Artifact hash mismatch: ' + row['path'])
        raw.chmod(0o755 if '/bin/' in row['path'] or row.get('executable') else 0o644)
        os.replace(raw, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('fetch', 'verify'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--home', type=Path, default=Path.home())
    args = parser.parse_args()
    manifest = json.loads((HERE / 'artifacts.lock.json').read_text())
    failures = []
    for row in manifest['artifacts']:
        if row['path'].startswith('@@HOME@@/'):
            path = args.home / row['path'].removeprefix('@@HOME@@/')
        else:
            path = args.root / row['path']
        matches = path.is_file() and path.stat().st_size == row['bytes'] and digest(path) == row['sha256']
        if not matches and args.action == 'fetch':
            fetch(row, path, HERE.parents[1], home=args.home, artifacts=manifest['artifacts'])
            matches = True
        if not matches:
            failures.append(row['path'])
        print(json.dumps(dict(path=row['path'], verified=matches)))
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
