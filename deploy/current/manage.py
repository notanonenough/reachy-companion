#!/usr/bin/env python3
"""Render, install and verify the audited deployment; never starts services.

Network/factory configuration requires an explicit scope. Secret values are
read from a separate JSON file, never printed or stored in the repository.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

HERE = Path(__file__).resolve().parent
TOKEN = re.compile(r'@@([A-Z0-9_]+)@@')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_manifest(directory=HERE):
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest.get('version') != 1:
        raise ValueError('Unsupported deployment manifest')
    for row in manifest['files']:
        path = (directory / row['source']).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            raise ValueError('Template outside deployment directory')
        if digest(path.read_bytes()) != row['sha256']:
            raise ValueError('Template hash changed: ' + row['source'])
    return manifest


def render(manifest, host, values, directory=HERE, scopes=None):
    settings = dict(manifest['hosts'][host])
    defaults = dict(ROOT=settings['root'], HOME=settings['home'], SOURCE_ROOT=settings['source_root'],
                    SSH_PROXY_JUMP='reachy-router-vuqar')
    defaults.update(values)
    if defaults['SSH_PROXY_JUMP'] not in ('none', 'reachy-router-vuqar'):
        raise ValueError('SSH_PROXY_JUMP must be none or reachy-router-vuqar')
    output = []
    def substitute(text, *, uci=False):
        def replace(match):
            key = match[1]
            if key not in defaults or not isinstance(defaults[key], str) or not defaults[key] or defaults[key] == 'REPLACE_FROM_PRIVATE_STORE':
                raise ValueError('Missing deployment value: ' + key)
            value = defaults[key]
            if '\x00' in value or '\r' in value or ('\n' in value and not key.endswith('_PUBLIC_KEYS')):
                raise ValueError('Invalid deployment value: ' + key)
            if uci and key.startswith('SECRET_'):
                value = value.replace('\\', '\\\\').replace("'", "'\\''")
            return value
        return TOKEN.sub(replace, text)
    for row in manifest['files']:
        if row['host'] != host or scopes and row['scope'] not in scopes:
            continue
        target = Path(substitute(row['destination']))
        if not target.is_absolute() or '..' in target.parts:
            raise ValueError('Absolute normalized destination required')
        data = substitute((directory / row['source']).read_text(), uci=row['kind'] == 'uci').encode()
        output.append(dict(row, target=str(target), data=data, rendered_sha256=digest(data)))
    return output


def write_stage(rows, output):
    output.mkdir(parents=True, exist_ok=False)
    os.chmod(output, 0o700)
    records = []
    for row in rows:
        relative = row['target'].lstrip('/')
        path = output / 'rootfs' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(row['data'])
        path.chmod(int(row['mode'], 8))
        records.append({k: v for k, v in row.items() if k != 'data'})
    (output / 'rendered.json').write_text(json.dumps(records, indent=2) + '\n')
    (output / 'rendered.json').chmod(0o600)


def staged_rows(stage):
    rows = json.loads((stage / 'rendered.json').read_text())
    seen = set()
    for row in rows:
        destination = Path(row['target'])
        if not destination.is_absolute() or '..' in destination.parts or str(destination) in seen:
            raise ValueError('Invalid/duplicate staged destination')
        seen.add(str(destination))
        path = stage / 'rootfs' / str(destination).lstrip('/')
        if not path.resolve().is_relative_to((stage / 'rootfs').resolve()):
            raise ValueError('Staged source outside rootfs')
        if digest(path.read_bytes()) != row['rendered_sha256']:
            raise ValueError('Staged content changed: ' + row['source'])
        yield row, path


def install(stage, backup, *, scopes, root=Path('/')):
    rows = [(row, path) for row, path in staged_rows(stage) if row['scope'] in scopes]
    if not rows:
        raise ValueError('No files selected')
    for row, _ in rows:
        target = root / row['target'].lstrip('/')
        if target.is_symlink():
            raise ValueError('Refusing to replace a destination symlink: ' + row['target'])
        if not 0 <= int(row['mode'], 8) <= 0o777:
            raise ValueError('Invalid file mode')
    # Validate every input before the first mutation. Backups never overwrite.
    backup.mkdir(parents=True, exist_ok=False)
    backup.chmod(0o700)
    installed = []
    for row, source in rows:
        target = root / row['target'].lstrip('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        previous = None
        if target.exists():
            previous = target.stat()
            old = backup / row['target'].lstrip('/')
            old.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, old)
        fd, name = tempfile.mkstemp(prefix='.' + target.name + '.', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(source.read_bytes()); out.flush(); os.fsync(out.fileno())
            os.chmod(name, int(row['mode'], 8))
            if previous:
                os.chown(name, previous.st_uid, previous.st_gid)
            elif root == Path('/') and os.geteuid() == 0:
                import pwd
                account = pwd.getpwnam(row['owner'])
                os.chown(name, account.pw_uid, account.pw_gid)
            os.replace(name, target)
        finally:
            Path(name).unlink(missing_ok=True)
        installed.append(row)
    (backup / 'installed.json').write_text(json.dumps(installed, indent=2) + '\n')
    return installed


def verify(stage, *, root=Path('/'), scopes=None):
    errors = []
    for row, _ in staged_rows(stage):
        if scopes and row['scope'] not in scopes:
            continue
        target = root / row['target'].lstrip('/')
        if not target.is_file() or digest(target.read_bytes()) != row['rendered_sha256']:
            errors.append(row['target'])
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('render'); p.add_argument('host', choices=('mac', 'hub', 'robot', 'router'))
    p.add_argument('--values', type=Path, help='Private JSON: secrets plus optional ROOT/HOME/SOURCE_ROOT')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--scope', action='append', choices=('runtime', 'network', 'factory'))
    for name in ('install', 'verify'):
        p = sub.add_parser(name); p.add_argument('--stage', type=Path, required=True)
        p.add_argument('--scope', action='append', choices=('runtime', 'network', 'factory'), default=None)
        p.add_argument('--root', type=Path, default=Path('/'), help='Alternate filesystem root for rehearsal')
        if name == 'install':p.add_argument('--backup', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'render':
        values = json.loads(args.values.read_text()) if args.values else {}
        rows = render(load_manifest(), args.host, values, scopes=args.scope)
        write_stage(rows, args.output)
        print(json.dumps(dict(rendered=len(rows), secrets_printed=False)))
    elif args.action == 'install':
        rows = install(args.stage, args.backup, scopes=args.scope or ['runtime'], root=args.root)
        print(json.dumps(dict(installed=len(rows), services_started=False, daemon_reload_required=True)))
    else:
        errors = verify(args.stage, root=args.root, scopes=args.scope or ['runtime'])
        print(json.dumps(dict(ok=not errors, mismatches=errors)))
        return int(bool(errors))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
