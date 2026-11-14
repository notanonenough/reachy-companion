#!/usr/bin/env python3
"""Apply/verify the single audited factory SDK change, without starting hardware."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('apply', 'verify'))
    parser.add_argument('--site-packages', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((HERE / 'manifest.json').read_text())
    target = args.site_packages / manifest['target']
    actual = digest(target)
    if actual == manifest['installed_sha256']:
        print('Factory SDK patch verified'); return 0
    if args.action == 'verify':
        raise SystemExit('Factory SDK hash differs')
    if actual != manifest['preimage_sha256']:
        raise SystemExit('Unexpected SDK preimage; refusing patch')
    patch = HERE / manifest['patch']
    if digest(patch) != manifest['patch_sha256']:
        raise SystemExit('Patch hash differs')
    with tempfile.TemporaryDirectory(dir=target.parent) as directory:
        candidate = Path(directory) / target.name
        shutil.copy2(target, candidate)
        subprocess.run(['patch', '--batch', str(candidate), str(patch)], check=True)
        if digest(candidate) != manifest['installed_sha256']:
            raise SystemExit('Patched SDK hash differs')
        backup = target.with_suffix('.py.before-companion-status')
        if backup.exists():
            raise SystemExit('Backup already exists; refusing overwrite')
        shutil.copy2(target, backup)
        candidate.replace(target)
    print('Factory SDK patch installed; daemon was not restarted')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
