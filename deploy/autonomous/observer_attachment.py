"""Owned auxiliary children only. Never controls or signals a runtime process."""
import base64
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

FILES=('production_baseline.py','observer_status.py','resource_observer.py','observer_runner.py','observer_listener.py')


class ObserverGroup:
    def __init__(self,output,candidate,root,event,popen=subprocess.Popen):
        self.output=Path(output);self.candidate=candidate;self.root=Path(root);self.event=event;self.popen=popen
        self.children=[];self.files=[];self.incomplete=False;self.started=False;self.finish_requested=False
    def note(self,kind):
        self.incomplete=True
        try:self.event('observer_incomplete',reason=kind)
        except Exception:pass
    def start(self,owner):
        if self.started:self.note('duplicate_start');return
        self.started=True
        for node in ('mac','hub','robot'):
            stream=None
            try:
                directory=Path(__file__).parent
                if node=='mac':
                    args=[sys.executable,'-u',str(directory/'observer_runner.py'),'--execute','--node','mac','--root',str(self.root),'--candidate',self.candidate]
                else:
                    # Diagnostic-only ephemeral bundle, outside installed source/config.
                    payload={name:(directory/name).read_text() for name in FILES}
                    encoded=base64.b64encode(json.dumps(payload).encode()).decode()
                    bootstrap="import base64,json,pathlib,tempfile,sys,runpy; d=tempfile.TemporaryDirectory(prefix='reachy-readonly-observer-'); p=pathlib.Path(d.name); payload=json.loads(base64.b64decode("+repr(encoded)+")); [(p/n).write_text(s) for n,s in payload.items()]; sys.path.insert(0,str(p)); sys.argv=['observer_runner','--execute',"+repr('--node')+","+repr(node)+",'--candidate',"+repr(self.candidate)+",'--owner',"+repr(json.dumps(owner))+ "]; runpy.run_path(str(p/'observer_runner.py'),run_name='__main__')"
                    root='/home/deploy/reachy-companion' if node=='hub' else '/home/pollen/reachy-companion'
                    python=root+('/.venv-router/bin/python' if node=='hub' else '/.venv/bin/python')
                    command='PYTHONPATH='+shlex.quote(root+'/current/src')+' '+shlex.quote(python)+' -u -c '+shlex.quote(bootstrap)
                    args=['ssh','-S','none','-o','BatchMode=yes','-o','ConnectTimeout=5','reachy-hub' if node=='hub' else 'reachy-mini',command]
                path=self.output/('observer-'+node+'.jsonl');stream=path.open('xb');path.chmod(0o600)
                child=self.popen(args,stdin=subprocess.PIPE,stdout=stream,stderr=subprocess.DEVNULL)
                self.children.append((node,child,path));self.files.append(stream);stream=None
            except Exception:self.note('start_failed')
            finally:
                if stream is not None:
                    try:stream.close()
                    except Exception:self.note('io')
    def request_finish(self):
        if self.finish_requested:return
        self.finish_requested=True
        for node,child,path in self.children:
            try:
                if child.poll() is not None:self.note('early_exit');continue
                fd=child.stdin.fileno();os.set_blocking(fd,False)
                if os.write(fd,b'finish\n')!=7:self.note('partial_finish')
            except Exception:self.note('finish_send')
        try:self.event('observer_finish_requested')
        except Exception:pass

    def close(self):
        # Called AFTER owner authenticated stop/exit/device shutdown. Every child independent.
        for node,child,path in self.children:
            try:child.wait(timeout=2)
            except Exception:
                self.note('join')
                try:child.terminate()
                except Exception:self.note('terminate')
                try:child.wait(timeout=1)
                except Exception:
                    self.note('terminate_join')
                    try:child.kill()
                    except Exception:self.note('kill')
                    try:child.wait(timeout=1)
                    except Exception:self.note('exit_unknown')
            try:
                if child.returncode!=0:self.note('child_exit')
                with path.open('rb') as f:raw=f.read(2*1024*1024+1)
                if len(raw)>2*1024*1024:raise ValueError('cap')
                lines=raw.splitlines();last=json.loads(lines[-1])
                if (last.get('kind')!='observer_end' or last.get('incomplete') is not False
                        or last.get('finish_accepted') is not True):self.note('footer')
            except Exception:self.note('evidence')
            try:child.stdin.close()
            except Exception:self.note('pipe_close')
        if len(self.children)!=3:self.note('node_coverage')
        for stream in self.files:
            try:stream.close()
            except Exception:self.note('io')
