#!/usr/bin/env python3
"""Render/install/rollback only the Mac managed SSH aliases and pinned host keys.

No connections, service changes, router writes or private keys. Backup journals
are durable before installation and support recovery after a partial operation.
"""
import argparse
import json
import os
from pathlib import Path
import stat
import tempfile

import manage

SOURCES = ('mac/ssh/config.template', 'mac/ssh/robot-known-hosts.template',
           'mac/ssh/hub-known-hosts.template', 'mac/ssh/router-openwrt-known-hosts.template')
BLOCKS = ('reachy local security', 'reachy router via Vuqar')


def render(home, route):
    home = Path(home)
    if not home.is_absolute() or '..' in home.parts or any(c in str(home) for c in '\"\\\n\r\x00'):
        raise ValueError('Absolute normalized home required')
    if route not in ('direct', 'jump'):
        raise ValueError('Unknown access route')
    manifest = manage.load_manifest()
    manifest = dict(manifest, files=[r for r in manifest['files'] if r['source'] in SOURCES])
    return manage.render(manifest, 'mac', {'HOME': str(home),
        'SSH_PROXY_JUMP': 'none' if route == 'direct' else 'reachy-router-vuqar'})


def stage(home, route, output):
    manage.write_stage(render(home, route), output)
    write_atomic(output / 'access.json', json.dumps(dict(home=str(home), route=route)).encode(), 0o600)


def read_stage(path):
    settings = json.loads((path / 'access.json').read_text())
    expected = {row['source']: row for row in render(settings['home'], settings['route'])}
    rows = list(manage.staged_rows(path))
    if len(rows) != len(expected) or {r['source'] for r, _ in rows} != set(expected):
        raise ValueError('Access stage must contain exactly the managed aliases and keys')
    for row, source in rows:
        trusted = expected[row['source']]
        if any(row.get(k) != trusted[k] for k in ('host', 'target', 'mode', 'rendered_sha256')):
            raise ValueError('Access stage differs from pinned template')
    return rows


def merge_config(previous, managed):
    """Keep foreign bytes; reject ambiguous markers rather than guess ownership."""
    remainder = previous
    for name in BLOCKS:
        start = ('# BEGIN ' + name).encode()
        end = ('# END ' + name).encode()
        lines = remainder.splitlines(keepends=True)
        starts = [i for i, line in enumerate(lines) if line.strip() == start]
        ends = [i for i, line in enumerate(lines) if line.strip() == end]
        if not starts and not ends:
            continue
        if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
            raise ValueError('Ambiguous managed SSH markers')
        block = b''.join(lines[starts[0]+1:ends[0]])
        if any(('# BEGIN ' + other).encode() in block or ('# END ' + other).encode() in block for other in BLOCKS):
            raise ValueError('Nested managed SSH markers')
        remainder = b''.join(lines[:starts[0]] + lines[ends[0]+1:])
    return managed.rstrip(b'\n') + b'\n' + remainder


def safe_target(root, target, *, directory=False):
    target = Path(target)
    if not target.is_absolute() or '..' in target.parts:
        raise ValueError('Invalid access target')
    actual = root / str(target).lstrip('/')
    for part in (actual, *actual.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError('Access destination symlink refused')
    if actual.exists() and not (actual.is_dir() if directory else actual.is_file()):
        raise ValueError('Access destination has the wrong file type')
    return actual


def write_atomic(path, data, mode):
    fd, temp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
        sync_directory(path.parent)
    finally:
        Path(temp).unlink(missing_ok=True)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def current(path):
    if not path.exists():
        return None
    return dict(sha256=manage.digest(path.read_bytes()), mode=stat.S_IMODE(path.stat().st_mode))


def install(stage_path, backup, root=Path('/')):
    root = root.resolve()
    rows = read_stage(stage_path)
    records = []
    # Keys precede config: a crash cannot leave a new route before its keys.
    rows.sort(key=lambda item: item[0]['source'] == SOURCES[0])
    for row, source in rows:
        target = safe_target(root, row['target'])
        before = current(target)
        data = source.read_bytes()
        if row['source'] == SOURCES[0]:
            data = merge_config(target.read_bytes() if before else b'', data)
        records.append(dict(target=row['target'], before=before,
            after=dict(sha256=manage.digest(data), mode=int(row['mode'], 8)), data=data))
    missing_dirs = set()
    required_dirs = {str(Path(r['target']).parent) for r in records}
    config_target = next(r['target'] for r, _ in rows if r['source'] == SOURCES[0])
    required_dirs.add(str(Path(config_target).parent / 'cm'))
    for directory in required_dirs:
        actual = safe_target(root, directory, directory=True)
        for parent in (actual, *actual.parents):
            if parent == root or parent.exists():
                break
            missing_dirs.add(str(parent.relative_to(root)))
    backup = backup.absolute()
    if backup.exists() or backup.is_symlink():
        raise ValueError('Backup must be a new private directory')
    backup.mkdir(parents=True, mode=0o700)
    backup.chmod(0o700)
    for index, record in enumerate(records):
        if record['before'] is not None:
            write_atomic(backup / str(index), (root / record['target'].lstrip('/')).read_bytes(), 0o600)
    journal = dict(version=1, root=str(root), created_dirs=sorted(missing_dirs),
                   files=[{k: v for k, v in r.items() if k != 'data'} for r in records])
    write_atomic(backup / 'journal.json', json.dumps(journal, indent=2).encode(), 0o600)
    sync_directory(backup.parent)
    # Every preimage and absence marker is persisted before the first target write.
    for directory in required_dirs:
        safe_target(root, directory, directory=True).mkdir(parents=True, exist_ok=True, mode=0o700)
    for record in records:
        target = safe_target(root, record['target'])
        if current(target) != record['before']:
            raise ValueError('Access target changed during installation; use rollback')
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_atomic(target, record['data'], record['after']['mode'])
    return journal


def read_backup(backup):
    journal = json.loads((backup / 'journal.json').read_text())
    if journal.get('version') != 1:
        raise ValueError('Unsupported access journal')
    root = Path(journal['root'])
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError('Invalid journal root')
    for relative in journal['created_dirs']:
        if Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise ValueError('Invalid created directory')
        safe_target(root, '/' + relative, directory=True)
    seen = set()
    for index, record in enumerate(journal['files']):
        target = safe_target(root, record['target'])
        if target in seen:
            raise ValueError('Duplicate access target')
        seen.add(target)
        before = record['before']
        if before is not None and manage.digest((backup / str(index)).read_bytes()) != before['sha256']:
            raise ValueError('Backup preimage changed')
    return journal, root


def verify(backup):
    journal, root = read_backup(backup)
    return [r['target'] for r in journal['files'] if current(safe_target(root, r['target'])) != r['after']]


def rollback(backup):
    journal, root = read_backup(backup)
    # Validate all files before any restoration, including partial install/rollback.
    for record in journal['files']:
        if current(safe_target(root, record['target'])) not in (record['before'], record['after']):
            raise ValueError('Access file changed after installation; refusing rollback')
    for index, record in enumerate(journal['files']):
        target = safe_target(root, record['target'])
        if current(target) == record['before']:
            continue
        if record['before'] is None:
            target.unlink(); sync_directory(target.parent)
        else:
            write_atomic(target, (backup / str(index)).read_bytes(), record['before']['mode'])
    for relative in sorted(journal['created_dirs'], key=lambda value: len(Path(value).parts), reverse=True):
        directory = root / relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts or directory.is_symlink():
            raise ValueError('Invalid created directory')
        try:
            directory.rmdir()
            sync_directory(directory.parent)
        except OSError:
            pass  # Keep directories containing later unrelated files.
    return journal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('render'); p.add_argument('--home', type=Path, required=True)
    p.add_argument('--route', choices=('direct', 'jump'), required=True)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('install'); p.add_argument('--stage', type=Path, required=True)
    p.add_argument('--backup', type=Path, required=True); p.add_argument('--root', type=Path, default=Path('/'))
    for action in ('verify', 'rollback'):
        p = sub.add_parser(action); p.add_argument('--backup', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'render':
        stage(args.home, args.route, args.output)
    elif args.action == 'install':
        install(args.stage, args.backup, args.root)
    elif args.action == 'rollback':
        rollback(args.backup)
    else:
        errors = verify(args.backup)
        print(json.dumps(dict(ok=not errors, mismatches=errors)))
        return int(bool(errors))
    print(json.dumps(dict(ok=True, action=args.action, services_started=False)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
