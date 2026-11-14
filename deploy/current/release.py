#!/usr/bin/env python3
"""Build a committed source archive or verify an extracted immutable release."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(root, output):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args])
    if git('status', '--porcelain').strip():
        raise RuntimeError('Commit the complete working tree before building a release')
    commit = git('rev-parse', 'HEAD').decode().strip()
    archive = git('archive', '--format=tar', 'HEAD')
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as source, tarfile.open(output, 'w:gz') as target:
        for member in source:
            if member.isfile():
                data = source.extractfile(member).read()
                files[member.name] = sha(data)
                target.addfile(member, io.BytesIO(data))
            elif member.isdir():
                target.addfile(member)
            else:
                raise ValueError('Release supports regular files/directories only: ' + member.name)
        manifest = dict(version=1, commit=commit, files=files,
                        content_sha256=sha(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()))
        data = (json.dumps(manifest, indent=2) + '\n').encode()
        member = tarfile.TarInfo('release.json'); member.size = len(data); member.mode = 0o644
        target.addfile(member, io.BytesIO(data))
    return manifest


def verify(root):
    manifest = json.loads((root / 'release.json').read_text())
    files = manifest['files']
    if sha(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()) != manifest['content_sha256']:
        raise ValueError('Release manifest content digest differs')
    errors = []
    for name, expected in files.items():
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()) or not path.is_file() or sha(path.read_bytes()) != expected:
            errors.append(name)
    known = set(files)
    for path in (root / 'src').rglob('*.py'):
        if str(path.relative_to(root)) not in known:
            errors.append('unexpected:' + str(path.relative_to(root)))
    return manifest, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'verify'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.action == 'build':
        if args.output is None:parser.error('build needs --output')
        manifest = build(args.root, args.output)
        errors = []
    else:
        manifest, errors = verify(args.root)
    print(json.dumps(dict(commit=manifest['commit'], files=len(manifest['files']),
                         content_sha256=manifest['content_sha256'], ok=not errors, mismatches=errors)))
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
