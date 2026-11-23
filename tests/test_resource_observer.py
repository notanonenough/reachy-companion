import contextlib
import ctypes
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

DIRECTORY=Path(__file__).resolve().parents[1]/'deploy/autonomous'
sys.path.insert(0,str(DIRECTORY))
import resource_observer as o
import observer_status as status
import production_baseline as baseline


class FakeReader:
    host_boot='boot';basis='linux_start_ticks'
    def __init__(self):self.identity='12';self.cpu=1
    def read(self,pid):return dict(process_start_identity=self.identity,cpu_s=self.cpu,rss_bytes=4096,units={'cpu_raw':'linux_ticks'})


class ObserverTests(unittest.TestCase):
    def item(self,pid=42,role='hub_owner'):return dict(role=role,pid=pid,process_start_identity='12',identity_basis='linux_start_ticks')
    def test_identity_changes_never_substitute_process(self):
        r=FakeReader();item=self.item();r.identity='99';value=o.sample(r,item,'hub')
        self.assertEqual(value['sample_state'],'identity_changed');self.assertIsNone(value['cpu_s'])
        with patch.object(r,'read',side_effect=FileNotFoundError('/PRIVATE')):
            value=o.sample(r,item,'hub');self.assertEqual(value['sample_state'],'missing');self.assertNotIn('PRIVATE',json.dumps(value))
        with patch.object(r,'read',side_effect=[dict(process_start_identity='12'),dict(process_start_identity='99')]):
            self.assertEqual(o.sample(r,item,'hub')['sample_state'],'identity_changed')

    def test_bounded_ticks_no_catchup_and_writer_failure(self):
        now=[0.];r=FakeReader();buffer=io.BytesIO();w=o.Writer(buffer)
        def read(pid):now[0]+=1.1;return dict(process_start_identity='12',cpu_s=now[0],rss_bytes=4096,units={})
        with patch.object(r,'read',side_effect=read):v=o.run(r,[self.item()],'hub',w,ticks=4,clock=lambda:now[0],sleep=lambda x:now.__setitem__(0,now[0]+x))
        self.assertEqual(v['ticks'],2);self.assertLessEqual(w.records,3)
        bad=io.BytesIO()
        with patch.object(bad,'write',side_effect=OSError('private_disk')):
            writer=o.Writer(bad);result=o.run(FakeReader(),[self.item()],'hub',writer,ticks=1)
        self.assertTrue(result['incomplete']);self.assertEqual(result['reason'],'io')
        writer=o.Writer(io.BytesIO(),byte_cap=5);self.assertFalse(writer.write({'some':'value'}));self.assertEqual(writer.reason,'cap')

    def test_footer_only_failure_is_incomplete(self):
        w=o.Writer(io.BytesIO(),record_cap=1)
        result=o.run(FakeReader(),[self.item()],'hub',w,ticks=1)
        self.assertTrue(result['incomplete']);self.assertEqual(result['reason'],'cap')
        class FooterFail(io.BytesIO):
            def write(self,data):
                if b'observer_end' in data:raise OSError('full')
                return super().write(data)
        result=o.run(FakeReader(),[self.item()],'hub',o.Writer(FooterFail()),ticks=1)
        self.assertTrue(result['incomplete']);self.assertEqual(result['reason'],'io')

    def test_probe_timeout_and_mixed_stream_completion(self):
        r=FakeReader()
        with patch.object(r,'read',side_effect=lambda pid:time.sleep(2)):
            began=time.monotonic();row=o.sample(r,self.item(),'hub')
        self.assertEqual(row['sample_state'],'timeout');self.assertLess(time.monotonic()-began,1)
        binding=dict(controller='owner',source_boot='source',session_boot='session')
        buffer=io.BytesIO()
        poll=lambda:status.project_status(dict(binding,stage='ACTIVE',elapsed_s=1),candidate='7'*40,binding=binding,begin=1,end=1.01)
        o.run(FakeReader(),[self.item()],'hub',o.Writer(buffer),ticks=1,status_poll=poll)
        rows=[json.loads(x) for x in buffer.getvalue().splitlines()]
        self.assertEqual(baseline.analyze_resources(rows)['hub']['completion']['state'],'complete')
        self.assertEqual(baseline.analyze_status(rows)['rows'],1)

    def test_status_poll_never_requests_foreign_listener(self):
        with tempfile.TemporaryDirectory() as directory:
            token=Path(directory)/'token';token.write_text('fixture')
            poll=o.StatusPoll(dict(candidate='7'*40,binding=dict(controller='owner',source_boot='source',session_boot='session'),token_file=str(token)),provenance=lambda:False)
            with patch.object(o.http.client,'HTTPConnection',side_effect=AssertionError('foreign network')):
                self.assertEqual(poll()['poll_outcome'],'identity_changed')

    def test_linux_nondefault_units_and_pid_reuse_between_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'sys/kernel/random').mkdir(parents=True);(root/'sys/kernel/random/boot_id').write_text('fixture-boot')
            (root/'42').mkdir();fields=['S']+['0']*21;fields[11]='300';fields[12]='100';fields[19]='12';fields[21]='3'
            (root/'42/stat').write_text('42 (private name with ) delimiter) '+' '.join(fields))
            with patch.object(os,'sysconf',side_effect=lambda key:200 if key=='SC_CLK_TCK' else 16384):reader=o.ProcessReader(platform='linux',procroot=root)
            value=reader.read(42);self.assertEqual(value['cpu_s'],2);self.assertEqual(value['rss_bytes'],49152)
            self.assertNotIn('private',json.dumps(value));self.assertEqual(value['units']['cpu_hz'],200)

    def test_platform_neutral_instances_not_interleaved(self):
        rows=[]
        for at in (1,2):
            for pid,cpu in ((10,at),(11,at*2)):
                rows.append(dict(node='mac',role='mac_provider',host_boot='boot',pid=pid,identity_basis='mach_start_abstime',process_start_identity=str(pid),clock_basis='host_monotonic',at=at,cpu_s=cpu,rss_bytes=pid*1024,sample_state='ok'))
        result=baseline.analyze_resources(rows)['mac'];self.assertEqual([x['cpu_percent_one_core']['max'] for x in result['instances']],[100,200])
        self.assertEqual(result['cpu_percent_one_core']['state'],'missing');self.assertEqual(result['coverage']['process_instances'],2)
        rows.insert(2,dict(rows[0],sample_state='timeout'))
        result=baseline.analyze_resources(rows)['mac'];self.assertEqual(result['instances'][0]['cpu_percent_one_core']['n'],0)
        self.assertEqual(result['instances'][1]['cpu_percent_one_core']['n'],1)

    def test_status_projection_bound_whitelist_and_repeated_elapsed(self):
        binding=dict(controller='owner',source_boot='source',session_boot='session')
        value=dict(binding,stage='ACTIVE',elapsed_s=3,private='secret',runtime=dict(latency_s={'main':7},pressure=dict(queue_depth=2,active_age_s={'main':3,'PRIVATE':999},phase='ACTIVE')),lease=dict(progress_age_ms=12,timing={'worker_scheduling_age_ms':2}),audio={'counts':{'submitted':5}})
        row=status.project_status(value,candidate='7'*40,binding=binding,begin=1,end=1.1)
        self.assertNotIn('PRIVATE',json.dumps(row));self.assertNotIn('secret',json.dumps(row))
        report=baseline.analyze_status([row,row]);self.assertEqual(report['repeated_snapshot_rows'],1);self.assertEqual(report['sampled_queue_depth']['n'],1)
        self.assertEqual(report['sampled_active_age_max_s']['main'],3)
        value['session_boot']='foreign';self.assertEqual(status.project_status(value,candidate='7'*40,binding=binding,begin=1,end=2)['poll_outcome'],'identity_changed')

    def test_consumer_keeps_observer_completion_and_full_session_identity(self):
        row=o.sample(FakeReader(),self.item(),'hub')
        for footer in (None,dict(kind='observer_end',node='hub',incomplete=True,reason='io',records=1)):
            rows=[row]+([footer] if footer else [])
            report=baseline.analyze_resources(rows)['hub'];self.assertEqual(report['completion']['state'],'incomplete')
        footer=dict(kind='observer_end',node='hub',incomplete=False,reason='complete',records=1)
        self.assertEqual(baseline.analyze_resources([row,footer])['hub']['completion']['state'],'complete')
        binding=dict(controller='owner',source_boot='same_source',session_boot='s1')
        def projected(binding,depth):
            return status.project_status(dict(binding,stage='ACTIVE',elapsed_s=1,runtime={'pressure':{'queue_depth':depth}}),candidate='7'*40,binding=binding,begin=1,end=1.1)
        rows=[projected(binding,2),projected(dict(binding,session_boot='s2'),9)]
        result=baseline.analyze_status(rows)
        self.assertEqual(result['repeated_snapshot_rows'],0);self.assertEqual(result['sampled_queue_depth']['max'],9)
        self.assertEqual(result['counter_segments'],2)

    def test_dry_run_no_probe_even_with_target_path(self):
        with patch.object(Path,'open',side_effect=AssertionError('file')),patch.object(ctypes,'CDLL',side_effect=AssertionError('API')),patch.object(subprocess,'Popen',side_effect=AssertionError('child')),patch.object(socket,'socket',side_effect=AssertionError('network')),contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(o.main(['--node','mac','--targets','/PRIVATE']),0)
        self.assertFalse(json.loads(out.getvalue())['probes'])

    @unittest.skipUnless(sys.platform in ('darwin','linux'),'local process platform unsupported')
    def test_real_owned_child_cpu_units_rss_identity_and_exit(self):
        # Only our fixture process is read; no real service discovery or network.
        code='import time,json; mem=bytearray(32*1024*1024); print("ready",flush=True); input(); t=time.process_time();\nwhile time.process_time()-t<.35: pass\nprint(json.dumps({"cpu":time.process_time()-t}),flush=True); input()'
        child=subprocess.Popen([sys.executable,'-u','-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'ready');reader=o.ProcessReader();a=reader.read(child.pid)
            item=o.bind_receipt(reader,role='mac_provider' if sys.platform=='darwin' else 'hub_owner',pid=child.pid)
            child.stdin.write('\n');child.stdin.flush();expected=json.loads(child.stdout.readline())['cpu'];b=reader.read(child.pid)
            self.assertAlmostEqual((b['cpu_s']-a['cpu_s'])/expected,1,delta=.15)
            self.assertGreater(b['rss_bytes'],32*1024*1024);self.assertEqual(a['process_start_identity'],b['process_start_identity'])
            child.terminate();child.wait(timeout=3);self.assertEqual(o.sample(reader,item,'mac' if sys.platform=='darwin' else 'hub')['sample_state'],'missing')
        finally:
            if child.poll() is None:child.kill();child.wait(timeout=3)
            child.stdin.close();child.stdout.close()

    @unittest.skipUnless(sys.platform=='darwin','Mac SDK ABI unavailable')
    def test_mac_sdk_abi(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);c=root/'abi.c';exe=root/'abi'
            c.write_text('#include <stdio.h>\n#include <stddef.h>\n#include <sys/resource.h>\nint main(void){printf("%zu %zu %zu %zu",sizeof(struct rusage_info_v0),offsetof(struct rusage_info_v0,ri_user_time),offsetof(struct rusage_info_v0,ri_resident_size),offsetof(struct rusage_info_v0,ri_proc_start_abstime));}\n')
            subprocess.run(['clang',str(c),'-o',str(exe)],check=True,timeout=20,capture_output=True)
            actual=list(map(int,subprocess.check_output([str(exe)],timeout=3).split()))
            self.assertEqual(actual,[ctypes.sizeof(o.RusageV0),o.RusageV0.user.offset,o.RusageV0.resident.offset,o.RusageV0.start.offset])

if __name__=='__main__':unittest.main()
