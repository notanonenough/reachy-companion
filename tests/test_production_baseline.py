import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PATH=Path(__file__).resolve().parents[1]/'deploy/autonomous/production_baseline.py'
spec=importlib.util.spec_from_file_location('production_baseline',PATH)
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
SHA='7'*40


def trace():
    rows=[]
    def add(kind,at,**kw):
        rows.append(dict(version=1,trace_id='trace',hub_boot_id='hub',clock_basis='hub_monotonic',kind=kind,at=at,**kw))
    authority=dict(hub_boot_id='hub',compute_boot_id='pc',robot_boot_id='robot',operator_epoch=1,microphone_epoch=1,interaction_epoch=1,speech_epoch=1)
    source=dict(source_boot='source',sequence=1,lineage_id='source:1')
    task=dict(task_id='task',attempt_id='attempt',input_ref='input',authority=authority)
    add('session_begin',0)
    add('stt_result',3,started_at=1,ended_at=3,disposition='recognized',authority=authority,**source)
    add('input_admission',3.1,input_ref='input',authority=authority,disposition='admitted',**source)
    add('main_request',4,started_at=4,disposition='audio_linked',**task)
    add('main_result',9,started_at=4,ended_at=9,disposition='unchecked',**task)
    add('main_checked',9.1,disposition='ready',**task)
    add('speech_commit',10,request_id='speech',disposition='speech_admitted',**task)
    add('speech_terminal',11,request_id='speech',stream_id='stream',tts_first_pcm_s=.2,producer_elapsed_s=.4,**task)
    add('playback_stop',12,request_id='speech',stream_id='stream',source_boot='source',verified_stopped=True)
    return finish(rows)


def finish(rows):
    rows=[row for row in rows if row['kind']!='trace_end']
    rows.append(dict(version=1,kind='trace_end',at=max(row['at'] for row in rows)+1,clock_basis='hub_monotonic',incomplete=False,dropped=0,records_written=len(rows)))
    return rows


class BaselineTests(unittest.TestCase):
    def test_causal_client_intervals_and_no_sensitive_output(self):
        rows=trace()
        for row in rows:row.update(text='PRIVATE SENTINEL',prompt={'secret':'PRIVATE SENTINEL'},final={'private':'PRIVATE SENTINEL'})
        result=b.report(rows,None,None,SHA)
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertNotIn('source:1',json.dumps(result))
        self.assertEqual(result['trace']['state'],'complete')
        self.assertEqual(result['trace']['audio_playback_chains'],1)
        self.assertEqual(result['trace']['metrics']['main_client_s']['p50'],5)
        self.assertEqual(result['trace']['metrics']['stt_end_to_playback_stop_s']['max'],9)
        self.assertFalse(result['population_tail_claim'])

    def test_empty_stt_not_voice_latency_and_main_background_separate(self):
        rows=trace();empty={**rows[1],'sequence':2,'lineage_id':'source:2','disposition':'empty','started_at':2,'ended_at':2.01}
        background={**rows[3],'task_id':'background','input_ref':'background','disposition':'metadata_only'}
        rows=finish(rows[:-1]+[empty,background])
        result=b.analyze_trace(rows)
        self.assertEqual(result['metrics']['stt_client_s']['n'],1)
        self.assertEqual(result['metrics']['stt_client_s']['max'],2)
        self.assertEqual(result['stt_by_outcome']['empty']['events'],1)
        self.assertEqual(result['main_request_scopes'],{'audio_linked':1,'metadata_only':1})

    def test_duplicates_missing_and_clock_domains_are_not_joined(self):
        for mutation,reason in ((lambda a:a.insert(2,copy.deepcopy(a[1])),'duplicate_event'),
                (lambda a:a[4].update(clock_basis='device_monotonic'),'clock_or_identity'),
                (lambda a:a[4].update(hub_boot_id='other'),'clock_or_identity'),
                (lambda a:a[4].update(attempt_id='other'),'missing_chain'),
                (lambda a:a.pop(),'missing_footer')):
            rows=trace();mutation(rows);result=b.analyze_trace(rows)
            self.assertEqual(result['state'],'incomplete');self.assertIn(reason,result['issues'])
            self.assertEqual(result['audio_playback_chains'],0 if reason!='missing_footer' else 1)

    def test_malformed_times_and_identity_do_not_invent_zero(self):
        for value in (None,True,float('nan'),-1,{},[]):
            rows=trace();rows[4]['ended_at']=value;rows[4]['task_id']=[]
            result=b.analyze_trace(rows)
            self.assertEqual(result['state'],'incomplete')
            self.assertEqual(result['metrics']['main_client_s'],{'state':'missing','n':0})

    def test_missing_incomplete_stale_distinct(self):
        self.assertEqual(b.analyze_trace(None)['state'],'missing')
        rows=trace();rows[-1]['incomplete']=True
        rows=rows[:-1]+[{**rows[1],'kind':'stt_disposition','disposition':'stale'}]+[rows[-1]]
        result=b.analyze_trace(rows)
        self.assertEqual(result['state'],'incomplete');self.assertEqual(result['stale_stt_dispositions'],1)
        self.assertEqual(result['event_counts']['stt_result'],1)

    def test_status_repeated_gauges_not_independent_jobs_and_counter_boundaries(self):
        def row(n,boot='source',at=1):return dict(peer={'source_boot':boot},stage='ACTIVE',elapsed_s=at,
            audio_counts={'submitted':n},lease={'max_tick_gap_ms':80},runtime={'latency_s':{'main':7}})
        rows=[row(10),row(12,at=2),row(12,at=3),{},row(30,at=4),row(31,at=5),row(2,at=6),row(4,at=7),row(99,'new',8)]
        result=b.analyze_status(rows)
        self.assertEqual(result['audio_observed_deltas']['submitted'],5)
        self.assertEqual(result['counter_resets'],1)
        self.assertEqual(result['max_tick_gap_ms'],80)
        self.assertIn('per_job_latency_distribution',result['missing'])
        self.assertNotIn('main',result)

    def test_elapsed_reset_with_same_source_breaks_counter_delta(self):
        rows=[dict(peer={'source_boot':'s'},elapsed_s=t,audio_counts={'submitted':n}) for t,n in ((10,10),(11,11),(1,50),(2,52))]
        self.assertEqual(b.analyze_status(rows)['audio_observed_deltas']['submitted'],3)

    def test_percentiles_are_empirical_and_keep_n(self):
        result=b.distribution(list(range(1,101)))
        self.assertEqual((result['n'],result['p95'],result['p99']),(100,95,99))
        one=b.distribution([7]);self.assertEqual(one['p99'],7);self.assertFalse(one['tail_guarantee'])

    def test_proc_parser_units_identity_and_resource_resets(self):
        fields=['S']+['0']*21;fields[11]='100';fields[12]='50';fields[19]='123';fields[21]='20'
        raw='42 (name with ) brackets) '+' '.join(fields)
        sample=b.parse_proc_stat(raw,pid=42,start_ticks=123,host_boot='boot',at=1,user_hz=100,page_size=4096)
        self.assertEqual(sample['cpu_s'],1.5);self.assertEqual(sample['rss_bytes'],81920)
        with self.assertRaises(ValueError):b.parse_proc_stat(raw,pid=42,start_ticks=999,host_boot='boot',at=1,user_hz=100,page_size=4096)
        rows=[dict(sample,node='hub'),dict(sample,node='hub',at=2,cpu_s=2),dict(sample,node='hub',at=3,cpu_s=8,start_ticks=222)]
        result=b.analyze_resources(rows)
        self.assertEqual(result['hub']['instances'][0]['cpu_percent_one_core']['max'],50)
        self.assertEqual(result['hub']['instances'][0]['cpu_percent_one_core']['n'],1)
        self.assertEqual(result['mac']['state'],'missing')

    def test_dry_run_never_reads_inputs_or_starts_network_process(self):
        with patch.object(Path,'open',side_effect=AssertionError('read')),patch.object(socket,'socket',side_effect=AssertionError('network')),patch.object(subprocess,'Popen',side_effect=AssertionError('process')),contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(b.main(['--candidate',SHA,'--trace','/PRIVATE','--dry-run']),0)
        self.assertNotIn('PRIVATE',out.getvalue());self.assertEqual(json.loads(out.getvalue())['mode'],'dry_run')

    def test_real_format_cli_read_only_and_invalid_input_redaction(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace.jsonl';path.write_text('\n'.join(map(json.dumps,trace())))
            with patch.object(socket,'socket',side_effect=AssertionError('network')),patch.object(subprocess,'Popen',side_effect=AssertionError('process')),contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(b.main(['--candidate',SHA,'--trace',str(path)]),0)
            self.assertEqual(json.loads(out.getvalue())['trace']['audio_playback_chains'],1)
            path.write_text('PRIVATE malformed')
            with contextlib.redirect_stdout(io.StringIO()) as out:self.assertEqual(b.main(['--candidate',SHA,'--trace',str(path)]),2)
            self.assertNotIn('PRIVATE',out.getvalue())

    def test_diagnostics_survive_missing_peer_identity_and_final(self):
        fault=dict(cause='reducer_expired',stage='scheduler_advance',trigger='worker',progress_age_ms=202.47,
            capture_status='captured',stack=[dict(module='/PRIVATE/path',function='PRIVATE',line=1)])
        result=b.analyze_status([dict(first_reducer_expiry=fault)])
        self.assertEqual(result['first_reducer_expiry']['progress_age_ms'],202.47)
        self.assertNotIn('PRIVATE',json.dumps(result))
        final=b.analyze_final([dict(first_reducer_expiry=fault)])
        self.assertEqual(final['first_reducer_expiry']['trigger'],'worker')
        self.assertIsNone(final['any_execution_busy'])

    def test_huge_numbers_and_unknown_counters_are_missing(self):
        self.assertFalse(b.number(10**1000))
        result=b.analyze_status([dict(peer={'source_boot':'s'})])
        self.assertIsNone(result['audio_observed_deltas']['errors'])
        rows=trace();rows[-1]['records_written']=True
        self.assertEqual(b.analyze_trace(rows)['state'],'incomplete')

    def test_attempt_time_authority_and_duplicate_json_are_rejected(self):
        for change in (dict(started_at=8),dict(ended_at=2),dict(authority={}),dict(authority={'hub_boot_id':'other'})):
            rows=trace();rows[4].update(change)
            result=b.analyze_trace(rows)
            self.assertEqual(result['state'],'incomplete');self.assertEqual(result['metrics']['main_client_s']['n'],0)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace';path.write_text('{"ended_at":8,"ended_at":9}')
            with self.assertRaises(ValueError):b.read_rows(path,trace=True)

    def test_retry_keeps_original_audio_anchor_and_separate_candidate_wait(self):
        rows=trace();retry={**rows[2],'kind':'input_retry','input_ref':'retry','parent_input_ref':'input','at':3.5,'disposition':'linked'}
        rows.insert(3,retry)
        for row in rows:
            if row['kind'] in ('main_request','main_result','main_checked','speech_commit','speech_terminal'):row['input_ref']='retry'
        result=b.analyze_trace(finish(rows))
        self.assertEqual(result['state'],'complete')
        self.assertAlmostEqual(result['metrics']['admission_to_main_start_s']['p50'],.9)
        self.assertEqual(result['metrics']['retry_candidate_to_main_start_s']['p50'],.5)

    def test_cancel_stop_can_precede_worker_terminal_and_poll_failure_is_counted(self):
        rows=trace();rows[-2]['at']=10.5;rows[-3]['cancelled']=True
        result=b.analyze_trace(rows)
        self.assertEqual(result['state'],'complete');self.assertEqual(result['terminal_outcomes']['cancelled'],1)
        status=b.analyze_status([dict(stage='unavailable',hub_request_begin=1,hub_request_end=2)])
        self.assertEqual(status['status_request_s']['n'],1);self.assertEqual(status['status_request_s']['max'],1)
        self.assertEqual(status['status_request_outcomes']['unavailable'],1)

    def test_caps_reject_before_parse(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace';path.write_bytes(b' '*(1048576+1))
            with self.assertRaises(ValueError):b.read_rows(path,trace=True)
