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
import threading
import types
import unittest
from unittest.mock import patch

DIRECTORY=Path(__file__).resolve().parents[1]/'deploy/autonomous';sys.path.insert(0,str(DIRECTORY))
import assemble_observer_harness as assembler
from observer_attachment import ObserverGroup
import observer_runner

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
        group.close();self.assertTrue(group.incomplete);self.assertEqual(events,['terminate',('wait',2),'kill',('wait',1)])

    def test_internal_runner_dry_run_has_no_probes(self):
        with patch.object(observer_runner,'ProcessReader',side_effect=AssertionError('resource')),patch.object(subprocess,'Popen',side_effect=AssertionError('process')),patch.object(socket,'socket',side_effect=AssertionError('network')),contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(observer_runner.main(['--node','hub','--candidate','7'*40]),0)
        self.assertFalse(json.loads(out.getvalue())['probes'])

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
        checks=checks.replace('ns=dict(',"ns=dict(__file__=str(LOCAL),observers=types.SimpleNamespace(close=lambda:None,incomplete=False),")
        namespace={'PosixPath':Path}
        with contextlib.redirect_stdout(io.StringIO()) as output:exec(compile(checks,'original_fault_regressions','exec'),namespace)
        self.assertEqual(output.getvalue().count('PASS:'),7)

    def test_actual_start_and_finally_fault_matrix(self):
        stop_aux=next(n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name=='stop_auxiliary')
        start=next(n for n in self.outer.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=='start' and isinstance(n.value.func.value,ast.Name) and n.value.func.value.id=='observers')
        for fault in ('normal','early_start_failure','hanging_observer','disk_full','ssh_loss'):
            with self.subTest(fault=fault):
                calls=[];directory=self.root/fault;directory.mkdir()
                class Child:
                    def __init__(self,node):self.returncode=255 if fault=='ssh_loss' and node=='hub' else None
                    def poll(self):return self.returncode
                    def terminate(self):calls.append('observer.terminate');self.returncode=0
                    def kill(self):calls.append('observer.kill');self.returncode=-9
                    def wait(self,timeout):
                        calls.append('observer.wait')
                        if fault=='hanging_observer':raise subprocess.TimeoutExpired('observer',timeout)
                        return self.returncode
                def spawn(args,**kw):
                    calls.append('observer.start')
                    if fault=='early_start_failure':raise OSError('spawn')
                    name=Path(kw['stdout'].name).stem.removeprefix('observer-')
                    kw['stdout'].write(b'{"kind":"observer_end","incomplete":false}\n');kw['stdout'].flush();return Child(name)
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
                if 'observer.terminate' in calls:self.assertLess(calls.index('shutdown'),calls.index('observer.terminate'))
                if fault!='normal':self.assertTrue(group.incomplete)
                else:self.assertFalse(group.incomplete)

if __name__=='__main__':unittest.main()
