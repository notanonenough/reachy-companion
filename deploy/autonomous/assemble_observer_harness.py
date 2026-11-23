"""Reproduce an observer attachment to the exact approved private owner harness."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil

BASE={
 'reachy-trace-acceptance.py':'44ee0de5f498a4dcdd3f4da25dbf5eb55f8952f8b663e32f0b7be7eb790486bc',
 'reachy-trace-remote-owner.py':'aa2310807750870c8c2bc3cf205f046e122e3404de40d4cc2999885daac3298d',
 'reachy-review-acceptance.py':'43981e15644f5732106a42a7a35384cfde0d866efcd00bdbff540c5069c62cfa',
 'reachy-final-state-check.py':'871ac0ea6857c85383a9fac1fabad75792dab2f0ae10cf0482604be3e644a4ef',
}
MODULES=('production_baseline.py','resource_observer.py','observer_status.py','observer_runner.py','observer_attachment.py')


def replace_once(source,old,new):
    if source.count(old)!=1:raise ValueError('integration_anchor')
    return source.replace(old,new,1)


def assemble(base,output):
    base=Path(base);output=Path(output)
    originals={name:(base/name).read_bytes() for name in BASE}
    if any(hashlib.sha256(originals[name]).hexdigest()!=digest for name,digest in BASE.items()):raise ValueError('unreviewed_base')
    source=originals['reachy-trace-acceptance.py'].decode()
    source=replace_once(source,"ROOT=pathlib.Path(","from observer_attachment import ObserverGroup\nROOT=pathlib.Path(")
    source=replace_once(source,"REMOTE=pathlib.Path('/tmp/reachy-trace-remote-owner.py')","REMOTE=pathlib.Path(__file__).with_name('reachy-trace-remote-owner.py')")
    source=replace_once(source,"literals('/tmp/reachy-review-acceptance.py')","literals(pathlib.Path(__file__).with_name('reachy-review-acceptance.py'))")
    source=replace_once(source,"pathlib.Path('/tmp/reachy-final-state-check.py')","pathlib.Path(__file__).with_name('reachy-final-state-check.py')")
    dry=" if not a.execute:print('Offline validation PASS: manual Hub supervisor + authenticated stop; no commands executed.');return\n"
    source=replace_once(source,dry,'')
    source=replace_once(source,' compile(REMOTE.read_text()',dry+' compile(REMOTE.read_text()')
    source=replace_once(source," try:\n  event('preflight_begin'", " observers=ObserverGroup(a.output,a.candidate,ROOT,event)\n try:\n  event('preflight_begin'")
    source=replace_once(source,"  event('active_observed');camera_done", "  with lock:observer_owner=dict(owner)\n  observers.start(observer_owner)\n  event('active_observed');camera_done")
    source=replace_once(source,"  stop_auxiliary(sampler,'sampler',event)","  stop_auxiliary(sampler,'sampler',event)\n  try:observers.close()\n  except Exception:event('observer_cleanup_error');observers.incomplete=True")
    source=replace_once(source,'if not owner_known or not trace_copied or evidence_errors:', 'if not owner_known or not trace_copied or evidence_errors or observers.incomplete:')
    # Exact same listener provenance functions, no second ownership implementation.
    remote=originals['reachy-trace-remote-owner.py'].decode();tree=ast.parse(remote)
    functions=[ast.get_source_segment(remote,n) for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('identity','listener_owned')]
    if len(functions)!=2:raise ValueError('listener_functions')
    listener='import pathlib,os\n\n'+'\n\n'.join(functions)+'\n'
    files={**originals,'reachy-trace-acceptance.py':source.encode(),'observer_listener.py':listener.encode()}
    for name in MODULES:files[name]=Path(__file__).with_name(name).read_bytes()
    for name,data in files.items():compile(data,name,'exec')
    output.mkdir(mode=0o700,parents=False,exist_ok=False)
    try:
        for name,data in files.items():
            fd=os.open(output/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as f:f.write(data)
        manifest={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
        p=output/'manifest.json';p.write_text(json.dumps(manifest,indent=2));p.chmod(0o600)
    except Exception:
        shutil.rmtree(output);raise
    return manifest


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args(argv)
    try:print(json.dumps(assemble(a.base,a.output),indent=2));return 0
    except Exception:print(json.dumps({'state':'assembly_failed'}));return 2


if __name__=='__main__':raise SystemExit(main())
