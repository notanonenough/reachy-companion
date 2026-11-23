import ast
import contextlib
import datetime
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import threading
import types
import unittest
from unittest.mock import patch

DIRECTORY=Path(__file__).resolve().parents[1]/'deploy/autonomous';sys.path.insert(0,str(DIRECTORY))
import assemble_observer_harness as assembler
from observer_attachment import ObserverGroup
import observer_runner
import resource_observer

BASE=Path(os.environ.get('REACHY_APPROVED_HARNESS',str(Path.home()/'reachy-release-backups/20261123-private-trace-harness-approved')))


def compiled(nodes):return compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'actual_assembled_path','exec')


class GroupTests(unittest.TestCase):
    def test_failed_spawn_logging_and_hanging_child_are_bounded(self):
        events=[]
        def fail(*a,**kw):raise OSError('PRIVATE')
        with tempfile.TemporaryDirectory() as directory:
            group=ObserverGroup(directory,'7'*40,'/fixture',fail,popen=fail)
            # Mac spawn fails; remote module bundle absent in source is also safely incomplete.
            group.start({'pid':42});group.close();self.assertTrue(group.incomplete)
        class Hanging:
            returncode=None
            def poll(self):return None
            def terminate(self):events.append('terminate')
            def kill(self):events.append('kill')
            def wait(self,timeout):events.append(('wait',timeout));raise subprocess.TimeoutExpired('fixture',timeout)
        group=ObserverGroup('/fixture','7'*40,'/fixture',fail);group.children=[('hub',Hanging(),Path('/nonexistent'))]
        group.close();self.assertTrue(group.incomplete);self.assertEqual(events,[('wait',2),'terminate',('wait',1),'kill',('wait',1)])

    def test_internal_runner_dry_run_has_no_probes(self):
        with patch.object(observer_runner,'ProcessReader',side_effect=AssertionError('resource')),patch.object(subprocess,'Popen',side_effect=AssertionError('process')),patch.object(socket,'socket',side_effect=AssertionError('network')),contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(observer_runner.main(['--node','hub','--candidate','7'*40]),0)
        self.assertFalse(json.loads(out.getvalue())['probes'])

    def test_actual_runner_all_acquisition_branches_keep_finish_control(self):
        for node in ('mac','hub','robot'):
            with self.subTest(node=node),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);(root/'current').mkdir();(root/'current/release.json').write_text(json.dumps({'commit':'7'*40}))
                (root/'token').write_text('fixture');(root/'config.local.json').write_text(json.dumps({'paths':{'token_file':'token'}}))
                read_fd,write_fd=os.pipe();stream=os.fdopen(read_fd,'rb',buffering=0);buffer=io.BytesIO();calls=[]
                binding=dict(controller='owner',source_boot='source',session_boot='session')
                class Reader:
                    host_boot='fixture';basis='linux_start_ticks'
                    def read(self,pid):
                        calls.append(('read',pid));return dict(process_start_identity='12',cpu_s=1,rss_bytes=4096,units={})
                helpers={'mac_owned_processes':lambda domain:{42:'known-receipt'},'process_identity':lambda pid:'known-receipt'}
                def path(value):
                    if str(value) in ('/home/deploy/reachy-companion','/home/pollen/reachy-companion'):return root
                    return Path(value)
                def run(reader,targets,node,writer,**kw):
                    self.assertIsInstance(kw['control'],resource_observer.FinishControl)
                    self.assertTrue(kw['control'].worker.is_alive())
                    timer=threading.Timer(.05,lambda:os.write(write_fd,b'finish\n'));timer.start()
                    try:return resource_observer.run(reader,targets,node,writer,ticks=2,**kw)
                    finally:timer.join(1)
                def status_factory(receipt,*,provenance):
                    self.assertTrue(provenance());self.assertEqual(receipt['binding'],binding)
                    return lambda:dict(kind='status',poll_outcome='response',hub_request_end=time.monotonic())
                original_handlers={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP)}
                try:
                    with patch.object(observer_runner,'Path',side_effect=path),patch.object(observer_runner,'ProcessReader',Reader),patch.object(observer_runner.runpy,'run_path',return_value=helpers),patch.object(observer_runner.subprocess,'check_output',return_value='42\n') as commands,patch.object(observer_runner,'run',side_effect=run),patch.object(observer_runner,'StatusPoll',side_effect=status_factory),patch.dict(sys.modules,{'observer_listener':types.SimpleNamespace(listener_owned=lambda pid,start:pid==42 and start=='12')}),patch.object(sys,'stdin',types.SimpleNamespace(buffer=stream)),patch.object(sys,'stdout',types.SimpleNamespace(buffer=buffer)):
                        result=observer_runner.main(['--execute','--node',node,'--root',str(root),'--candidate','7'*40,'--owner',json.dumps(dict(pid=42,start_ticks='12',binding=binding))])
                    self.assertEqual(result,0)
                    rows=[json.loads(x) for x in buffer.getvalue().splitlines()];self.assertTrue(rows[-1]['finish_accepted']);self.assertFalse(rows[-1]['incomplete'])
                    self.assertTrue(any(x.get('kind')=='resource' for x in rows));self.assertTrue(calls)
                    if node=='robot':self.assertEqual(commands.call_count,2)
                finally:
                    for sig,handler in original_handlers.items():signal.signal(sig,handler)
                    stream.close();os.close(write_fd)

    def test_unknown_base_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);base=p/'base';base.mkdir()
            for name in assembler.BASE:(base/name).write_text('unreviewed')
            with self.assertRaises(ValueError):assembler.assemble(base,p/'out')
            self.assertFalse((p/'out').exists())


@unittest.skipUnless(all((BASE/name).is_file() for name in assembler.BASE),'approved private harness not installed; exact assembly tested on author Mac')
class AssembledTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.snapshot=self.root/'snapshot'
        assembler.assemble(BASE,self.snapshot);self.local=self.snapshot/'reachy-trace-acceptance.py'
        self.tree=ast.parse(self.local.read_text());self.main=next(n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        self.outer=next(n for n in self.main.body if isinstance(n,ast.Try))
    def tearDown(self):self.tmp.cleanup()

    def test_actual_assembled_dry_run_zero_file_process_network(self):
        namespace={'__file__':str(self.local),'__name__':'assembled_fixture'}
        exec(compile(self.local.read_text(),str(self.local),'exec'),namespace)
        with patch.object(Path,'open',side_effect=AssertionError('file')),patch.object(Path,'read_text',side_effect=AssertionError('file')),patch.object(socket,'socket',side_effect=AssertionError('network')),patch.object(subprocess,'Popen',side_effect=AssertionError('process')),patch.object(sys,'argv',[str(self.local)]),contextlib.redirect_stdout(io.StringIO()) as out:
            namespace['main']()
        self.assertIn('Offline validation PASS',out.getvalue())

    def test_original_seven_fault_regressions_against_assembled_owner(self):
        checks=(BASE/'reachy-trace-lifecycle-checks.py').read_text()
        checks=checks.replace("pathlib.Path('/tmp/reachy-trace-acceptance.py')",repr(self.local))
        checks=checks.replace("pathlib.Path('/tmp/reachy-trace-remote-owner.py')",repr(self.snapshot/'reachy-trace-remote-owner.py'))
        checks=checks.replace('ns=dict(',"ns=dict(__file__=str(LOCAL),observers=types.SimpleNamespace(close=lambda:None,request_finish=lambda:None,incomplete=False),")
        namespace={'PosixPath':Path}
        with contextlib.redirect_stdout(io.StringIO()) as output:exec(compile(checks,'original_fault_regressions','exec'),namespace)
        self.assertEqual(output.getvalue().count('PASS:'),7)

    def test_actual_start_and_finally_fault_matrix(self):
        stop_aux=next(n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name=='stop_auxiliary')
        start=next(n for n in self.outer.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=='start' and isinstance(n.value.func.value,ast.Name) and n.value.func.value.id=='observers')
        for fault in ('normal','early_start_failure','hanging_observer','disk_full','ssh_loss'):
            with self.subTest(fault=fault):
                calls=[];directory=self.root/fault;directory.mkdir()
                def spawn(args,**kw):
                    calls.append('observer.start')
                    if fault=='early_start_failure':raise OSError('spawn')
                    name=Path(kw['stdout'].name).stem.removeprefix('observer-')
                    if fault=='ssh_loss' and name=='hub':code='import sys;sys.exit(255)'
                    elif fault=='hanging_observer' and name=='hub':code='import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("started",flush=True);time.sleep(20)'
                    else:
                        role={'mac':'mac_provider','hub':'hub_owner','robot':'robot_audio'}[name]
                        code="""import sys
from resource_observer import FinishControl,run,Writer
class Reader:
 host_boot='fixture';basis='linux_start_ticks'
 def read(self,pid):return dict(process_start_identity='12',cpu_s=1,rss_bytes=4096,units={})
c=FinishControl(sys.stdin.buffer);c.start()
r=run(Reader(),[dict(role=ROLE,pid=42,process_start_identity='12',identity_basis='linux_start_ticks')],NODE,Writer(sys.stdout.buffer),stopped=c.event.is_set,control=c)
c.close();raise SystemExit(2 if r['incomplete'] else 0)
""".replace('ROLE',repr(role)).replace('NODE',repr(name))
                    child=subprocess.Popen([sys.executable,'-u','-c',code],env=dict(os.environ,PYTHONPATH=str(DIRECTORY)+os.pathsep+str(DIRECTORY.parents[1]/'src')),**kw)
                    # Observe an actual first child record, not a prewritten terminal fixture.
                    deadline=time.monotonic()+2
                    while child.poll() is None and not Path(kw['stdout'].name).stat().st_size and time.monotonic()<deadline:time.sleep(.01)
                    return child
                class Hub:
                    returncode=0
                    def poll(self):return 0
                    def wait(self,timeout):calls.append('hub.wait')
                class Sock:
                    def __enter__(self):return self
                    def __exit__(self,*a):pass
                    def settimeout(self,x):pass
                    def connect_ex(self,x):return 111
                def event(kind,**kw):calls.append(kind)
                group=ObserverGroup(directory,'7'*40,'/fixture',event,popen=spawn)
                # Use actual generated bundle, so all three start branches execute.
                import observer_attachment
                owner={'pid':42,'start_ticks':'12','binding':{'controller':'owner','source_boot':'source','session_boot':'session'}}
                ns=dict(__file__=str(self.local),observers=group,observer_owner=owner,player=None,capture=None,sampler=None,hub=Hub(),auth_stop=lambda:calls.append('auth_stop'),device_started=True,mac_started=True,control={'shutdown':lambda:calls.append('shutdown')},event=event,owner_known=False,trace_copied=False,lock=threading.Lock(),owner=dict(pid=42,start_ticks='12',exited={'pid':42,'start_ticks':'12'}),reader=types.SimpleNamespace(join=lambda _:None),camera=lambda x:calls.append(x),sshcode=lambda *a,**k:{},a=types.SimpleNamespace(output=directory),private_remote='/fixture',json=json,pathlib=__import__('pathlib'),signal=signal,socket=types.SimpleNamespace(socket=Sock),subprocess=types.SimpleNamespace(run=lambda args,**kw:Path(args[-1]).write_text('fixture'),check_output=lambda *a,**kw:''))
                exec(compiled([stop_aux]),ns)
                with patch.object(observer_attachment,'__file__',str(self.snapshot/'observer_attachment.py')):
                    if fault=='disk_full':
                        # Evidence failure in actual group's start does not escape into owner control.
                        with patch.object(Path,'open',side_effect=OSError('disk')):exec(compiled([start]),ns)
                    else:exec(compiled([start]),ns)
                    exec(compiled([ast.Try(body=[ast.Pass()],handlers=[],orelse=[],finalbody=self.outer.finalbody)]),ns)
                self.assertTrue(all(x in calls for x in ('auth_stop','hub.wait','shutdown','trial_finished')),calls)
                self.assertLess(calls.index('auth_stop'),calls.index('hub.wait'));self.assertLess(calls.index('hub.wait'),calls.index('shutdown'))
                self.assertLess(calls.index('observer_finish_requested'),calls.index('auth_stop'))
                if fault!='normal':self.assertTrue(group.incomplete)
                else:self.assertFalse(group.incomplete)

if __name__=='__main__':unittest.main()
