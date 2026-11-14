"""Operational regressions: stale health, retention, firewall and failure visibility."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from reachy_companion.firewall import render
from reachy_companion.production_logs import prune_reports, run_logged, report_summary
from reachy_companion.production_status import summarize,normalize_tracking

ROOT=Path(__file__).resolve().parents[1]


class OperationsTests(unittest.TestCase):
    def test_retained_following_mode_does_not_claim_tracking_after_withdrawal(self):
        for stage,lease in [('WITHDRAWN',{}),('ACTIVE',{'withdrawn':True}),('unavailable',{})]:
            s=dict(stage=stage,lease=lease,motion=dict(tracking_enabled=True,tracking_mode='following'))
            normalize_tracking(s)
            self.assertEqual(s['motion']['tracking_mode'],'suspended')
            self.assertEqual(s['motion']['last_tracking_mode'],'following')
        s=dict(stage='ACTIVE',lease={},motion=dict(tracking_enabled=True,tracking_mode='following'))
        self.assertEqual(normalize_tracking(s)['motion']['tracking_mode'],'following')

    def test_runtime_overlay_cleanup_preserves_security_and_is_idempotent(self):
        spec=importlib.util.spec_from_file_location('maintenance_test',ROOT/'deploy/production/install_maintenance.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as t:
            directory=Path(t)/'dropins';directory.mkdir();archive=Path(t)/'archive'
            legacy=directory/'zz-mac-current.conf'
            body='[Service]\nEnvironment=PYTHONPATH=/old/source\nExecStart=\nExecStart=/old/python agent serve\n'
            legacy.write_text(body);legacy.chmod(0o600)
            security=directory/'hardening.conf';security.write_text('[Service]\nNoNewPrivileges=yes\n')
            other=directory/'environment.conf';other.write_text('[Service]\nEnvironment=OTHER=value\n')
            self.assertEqual(module.retire_runtime_overlays(directory,archive),[legacy.name])
            self.assertEqual((archive/legacy.name).read_text(),body)
            self.assertEqual((archive/legacy.name).stat().st_mode&0o777,0o600)
            self.assertTrue(security.exists());self.assertTrue(other.exists())
            self.assertEqual(module.retire_runtime_overlays(directory,archive),[])

    def test_explicit_peer_rules_are_declarative_and_reject_broad_addresses(self):
        c={'security':{'robot':dict(policy='local_ssh',nft_table='reachy_companion',
            service='reachy-companion-firewall',rollback_seconds=180,production_peer_ipv4='192.168.0.186')}}
        a=render(c,recovery_interfaces=[])
        self.assertEqual(a,render(c,recovery_interfaces=[]))
        self.assertEqual(a.count('tcp dport { 8090, 8780, 8781 }'),1)
        self.assertIn('ip saddr 192.168.0.186 udp dport 8782 accept',a)
        self.assertNotIn('flush ruleset',a)
        for value in ('0.0.0.0','127.0.0.1','224.0.0.1','192.168.0.0/24','bad'):
            c['security']['robot']['production_peer_ipv4']=value
            with self.assertRaises(ValueError):render(c,recovery_interfaces=[])

    def test_green_processes_cannot_hide_withdrawn_or_unavailable_session(self):
        models={'llm':dict(ready=True)}
        hosts={role:dict(reachable=True,services={'service':'active'}) for role in ('hub','robot')}
        hosts['robot']['firewall']=dict(inspected=True,duplicate_rules=0)
        hosts['hub']['session']=dict(stage='WITHDRAWN',listening_ready=False)
        s=summarize(models,hosts);self.assertEqual(s['state'],'needs_start')
        self.assertFalse(s['recovery']['automatic_microphone_restart'])
        hosts['hub']['session']=dict(stage='ACTIVE',listening_ready=True,lease={'withdrawn':True})
        self.assertEqual(summarize(models,hosts)['state'],'degraded')
        hosts['hub']['session']['lease']['withdrawn']=False
        self.assertEqual(summarize(models,hosts)['state'],'ready')
        hosts['robot']['disk']={'used_percent':85}
        degraded=summarize(models,hosts)
        self.assertEqual(degraded['state'],'degraded');self.assertIsNone(degraded['recovery']['command'])
        hosts['robot']['disk']={'used_percent':50}
        hosts['hub']['session']['motion']={'stop_known':False,'execution_busy':False}
        unknown=summarize(models,hosts)
        self.assertEqual(unknown['state'],'degraded');self.assertIn('motion:unknown_completion',unknown['issues'])
        hosts['hub']['session']['stage']='unavailable'
        self.assertNotEqual(summarize(models,hosts)['state'],'ready')

    def test_retention_keeps_live_recent_and_foreign_files(self):
        with tempfile.TemporaryDirectory() as t:
            data=Path(t);now=time.time()
            for i in range(5):
                d=data/('production-'+str(i));d.mkdir()
                p=d/'hub.json';p.write_text(json.dumps(dict(accepted=False,elapsed_s=1)))
                os.utime(p,(now-90000-i,now-90000-i))
            live=data/'production-live';live.mkdir();(live/'owner.json').write_text('{}')
            foreign=data/'production-foreign';foreign.mkdir();(foreign/'notes.txt').write_text('keep')
            recent=data/'production-recent';recent.mkdir();(recent/'device.json').write_text(json.dumps(dict(accepted=True,elapsed_s=1)))
            dry=prune_reports(data,keep=2,now=now)
            self.assertEqual(len(dry['removed']),4);self.assertTrue((data/dry['removed'][0]).exists())
            actual=prune_reports(data,keep=2,apply=True,now=now)
            self.assertEqual(actual['removed'],dry['removed']);self.assertTrue(live.exists());self.assertTrue(foreign.exists());self.assertTrue(recent.exists())

    def test_child_output_is_bounded_and_exit_code_preserved(self):
        with tempfile.TemporaryDirectory() as t:
            log=Path(t)/'worker.log'
            code=run_logged(log,[sys.executable,'-c',"import sys;print('x'*20000);sys.exit(7)"],max_bytes=1024,backups=2)
            self.assertEqual(code,7)
            self.assertLessEqual(len(list(Path(t).iterdir())),3)
            self.assertLessEqual(max(p.stat().st_size for p in Path(t).iterdir()),16385)
        summary=report_summary(dict(mode='test',accepted=True,decisions=['private'],output='private'))
        self.assertNotIn('decisions',summary);self.assertNotIn('output',summary)

    def test_stop_attempts_robot_even_if_hub_is_unreachable(self):
        module=importlib.machinery.SourceFileLoader('production_control_test',str(ROOT/'scripts/production-control')).load_module()
        calls=[]
        def command(*args,**kwargs):
            calls.append(args)
            if 'reachy-hub' in args:raise subprocess.TimeoutExpired('ssh',25)
        with patch.object(module,'command',side_effect=command):
            with self.assertRaises(RuntimeError):module.stop_services()
        self.assertEqual(len(calls),2);self.assertIn('reachy-mini',calls[-1])


if __name__=='__main__':unittest.main()
