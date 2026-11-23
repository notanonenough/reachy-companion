import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from reachy_companion.private_audio_trace import PrivateAudioTrace,main_call
from reachy_companion.autonomous.contracts import Authority


class PrivateTraceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.path=self.root/'private.jsonl'
    def trace(self,**kw):
        trace=PrivateAudioTrace(self.path,seconds=kw.pop('seconds',30),**kw)
        self.addCleanup(trace.close);trace.start(threading.Event());return trace
    def test_private_immutable_records_and_stop_privacy_redaction(self):
        trace=self.trace();authority={'hub_boot_id':'hub','secret':'PRIVATE-SECRET'}
        trace.emit('stt_result',text='known raw result',authority=authority,token='PRIVATE-TOKEN')
        authority['hub_boot_id']='MUTATED'
        trace.disable('privacy');trace.emit('stt_result',text='PRIVATE-LATE',lineage_id='source:2')
        summary=trace.close();raw=self.path.read_text();rows=[json.loads(v) for v in raw.splitlines()]
        self.assertFalse(summary['incomplete']);self.assertEqual(rows[-1]['kind'],'trace_end')
        self.assertEqual(rows[1]['text'],'known raw result');self.assertEqual(rows[1]['authority'],{'hub_boot_id':'hub'})
        self.assertTrue(rows[2]['content_suppressed']);self.assertNotIn('PRIVATE',raw);self.assertNotIn('MUTATED',raw)
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)
    def test_only_admitted_audio_ref_can_capture_main_text_not_background(self):
        trace=self.trace();authority=Authority('hub','compute')
        def task(ref):return NS(task_id='task',attempt_id='attempt',input_ref=ref,authority=authority,
            prompt={'utterance':'known question','memory':['PRIVATE-MEMORY'],'state':{'character':'PRIVATE-PROFILE'}})
        function=lambda task:dict(output='PRIVATE-BACKGROUND' if task.input_ref=='background' else 'known answer',secret='PRIVATE-TOKEN')
        main_call(trace,function,task('background'))
        trace.emit('input_admission',input_ref='audio',lineage_id='source:1',disposition='admitted',text='known question')
        main_call(trace,function,task('audio'));trace.close();raw=self.path.read_text()
        self.assertNotIn('PRIVATE',raw);self.assertIn('known answer',raw)
        requests=[v for v in map(json.loads,raw.splitlines()) if v['kind']=='main_request']
        self.assertNotIn('text',requests[0]);self.assertEqual(requests[1]['text'],'known question')
    def test_stop_fences_late_audio_linked_model_result(self):
        trace=self.trace();trace.emit('input_admission',input_ref='audio',lineage_id='source:1',disposition='admitted')
        task=NS(task_id='task',attempt_id='attempt',input_ref='audio',authority=Authority('hub','compute'),prompt='known request')
        def response(task):trace.stop.set();return dict(output='PRIVATE-LATE-MODEL')
        result=main_call(trace,response,task);self.assertEqual(result['output'],'PRIVATE-LATE-MODEL')
        trace.close();raw=self.path.read_text();self.assertNotIn('PRIVATE-LATE',raw)
        row=next(r for r in map(json.loads,raw.splitlines()) if r['kind']=='main_result')
        self.assertTrue(row['content_suppressed'])
    def test_record_and_byte_limits_drop_whole_records_without_truncation(self):
        trace=self.trace(record_cap=4,byte_cap=4096)
        for _ in range(10):trace.emit('stt_result',text='x'*1000)
        trace.close();raw=self.path.read_bytes();rows=list(map(json.loads,raw.splitlines()))
        self.assertLessEqual(len(raw),4096);self.assertLessEqual(len(rows),4)
        self.assertTrue(trace.summary()['incomplete'])
        self.assertTrue(all(row.get('text') is None or row['text']=='x'*1000 for row in rows))
    def test_public_summary_and_standalone_probe_never_export_text_or_path(self):
        import subprocess,sys
        from reachy_companion.private_audio_trace import project_summary
        from reachy_companion.production_logs import report_summary
        from reachy_companion.production_status import REMOTE_PROBE
        bad=dict(enabled=True,incomplete=True,reason='PRIVATE-ERROR',records_written=True,dropped=10**100,
            path='/PRIVATE-PATH',text='PRIVATE-CONTENT')
        expected=project_summary(bad)
        self.assertIsNone(expected['reason']);self.assertIsNone(expected['records_written'])
        self.assertEqual(expected['dropped'],1000000000)
        self.assertEqual(report_summary({'private_audio_trace':bad})['private_audio_trace'],expected)
        report=self.root/'data/production-fixture';report.mkdir(parents=True)
        (report/'hub.json').write_text(json.dumps({'private_audio_trace':bad}))
        process=subprocess.run([sys.executable,'-c',REMOTE_PROBE,str(self.root),'hub'],capture_output=True,text=True,timeout=5,check=True)
        self.assertEqual(json.loads(process.stdout)['last_session']['private_audio_trace'],expected)
        self.assertNotIn('PRIVATE',process.stdout)

    def test_lineage_limit_is_incomplete_and_does_not_invent_link(self):
        trace=self.trace()
        for i in range(129):
            trace.emit('input_admission',input_ref='ref-'+str(i),lineage_id='source:'+str(i),disposition='admitted')
            if i%8==0:
                deadline=time.monotonic()+1
                while trace.queue and time.monotonic()<deadline:time.sleep(.001)
        trace.close()
        self.assertTrue(trace.audio_link('ref-127'));self.assertFalse(trace.audio_link('ref-128'))
        self.assertEqual(trace.summary()['reason'],'lineage_cap');self.assertTrue(trace.summary()['incomplete'])
    def test_cli_default_off_and_invalid_trace_are_pre_runtime(self):
        import sys
        from reachy_companion.autonomous import companion_session as session
        argv=['session','--mode','normal','--config',str(self.root/'cfg.json'),
            '--companion-config',str(self.root/'companion.json'),'--token-file',str(self.root/'token'),
            '--output',str(self.root/'report.json'),'--peer-url','http://127.0.0.1:1',
            '--peer-stop-port','2','--controller','controller','--source-boot','source','--allow-capture-output']
        with patch.object(sys,'argv',argv),patch.object(session,'_run_session_cli',return_value=0) as run:
            self.assertEqual(session.main(),0);self.assertIsNone(run.call_args.args[1])
        with patch.object(sys,'argv',argv+['--private-audio-trace',str(self.path),'--private-audio-trace-seconds','30']),patch.object(session,'_run_session_cli') as run:
            with self.assertRaises(ValueError):session.main() # inside the forbidden config root
            run.assert_not_called();self.assertFalse(self.path.exists())

    def test_exclusive_owned_private_path_caps_and_no_follow(self):
        self.path.write_text('existing')
        with self.assertRaises(FileExistsError):self.trace()
        self.path.unlink();self.path.symlink_to(self.root/'target')
        with self.assertRaises(FileExistsError):self.trace()
        self.path.unlink();self.root.chmod(0o755)
        with self.assertRaises(ValueError):self.trace()
        self.root.chmod(0o700)
        with self.assertRaises(ValueError):self.trace(forbidden_roots=[self.root])
        for kw in ({'seconds':True},{'seconds':301},{'record_cap':513},{'byte_cap':1048577},{'queue_cap':33}):
            with self.assertRaises(ValueError):self.trace(**kw)
        self.assertFalse(self.path.exists())
    def test_slow_writer_and_lock_contention_never_wait_on_reducer(self):
        held=threading.Event();release=threading.Event();original=PrivateAudioTrace._write_bytes
        def slow(sink,raw):held.set();release.wait(3);original(sink,raw)
        with patch.object(PrivateAudioTrace,'_write_bytes',slow):
            trace=self.trace(queue_cap=1)
            try:
                self.assertTrue(held.wait(1))
                finished=threading.Event()
                def producer():
                    for _ in range(100):trace.emit('stt_result',text='bounded')
                    finished.set()
                worker=threading.Thread(target=producer);worker.start()
                self.assertTrue(finished.wait(.2));worker.join(1)
                self.assertGreater(trace.summary()['dropped'],0)
                with trace.lock:trace.emit('stt_result',text='must not wait')
            finally:release.set();trace.close()
        self.assertTrue(trace.summary()['incomplete'])
    def test_storage_failure_and_duration_caps_do_not_escape_into_callers(self):
        with patch.object(PrivateAudioTrace,'_write_bytes',side_effect=OSError('PRIVATE-ERROR')):
            trace=self.trace();trace.worker.join(1)
            trace.emit('stt_result',text='PRIVATE-LATE');summary=trace.close()
        self.assertEqual(summary['reason'],'writer_failure');self.assertTrue(summary['incomplete'])
        self.assertNotIn('PRIVATE',self.path.read_text())
        self.path.unlink();trace=self.trace(seconds=1,record_cap=4)
        trace.started=time.monotonic()-2
        trace.emit('stt_result',text='PRIVATE-EXPIRED');trace.close()
        self.assertTrue(trace.summary()['incomplete']);self.assertNotIn('PRIVATE',self.path.read_text())


class JoinedPrivateTraceTests(unittest.TestCase):
    def test_actual_audio_polling_http_stt_model_tts_and_stale_result(self):self.exercise('normal')
    def test_default_off_has_same_voice_path_without_trace_file(self):self.exercise('off')
    def test_blocked_writer_overflow_does_not_stop_actual_voice_or_lease_progress(self):self.exercise('slow')
    def test_failed_writer_does_not_stop_actual_voice_or_lease_progress(self):self.exercise('failed')
    def test_operator_privacy_fences_late_real_stt_content(self):self.exercise('privacy')
    def test_stop_fences_late_real_stt_content(self):self.exercise('stop')

    def exercise(self,mode):
        import base64,copy,hashlib,os
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from test_companion_session import SessionTests
        from reachy_companion.autonomous.audio_adapter import HttpSTT
        from reachy_companion.autonomous.speech_adapter import HttpTTS
        from reachy_companion.autonomous.runtime import RemoteGateway,Scheduler
        from reachy_companion.autonomous.config import load
        from reachy_companion.autonomous.durable import DurableStore
        from reachy_companion.autonomous.voice_chain import model_final,digest
        from reachy_companion.transcription import TranscriptionSlot
        fixture=SessionTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        from collections import deque
        captures=deque();dispatch=fixture.peer.dispatch
        def observe(path,body):
            # Produce PCM at a real observation request, before its age receipt;
            # do not race an unrelated in-flight empty poll or fabricate State input.
            if path=='/observation' and captures:
                if not fixture.peer.publish(captures.popleft(),time.monotonic(),None):raise RuntimeError('Fixture capture withdrawn')
            return dispatch(path,body)
        fixture.peer.dispatch=observe
        def capture(pcm):
            # Start a positive capture vector within an observed fresh operator
            # receipt, rather than accidentally testing its expiry boundary.
            fixture.wait(lambda:fixture.audio.allowed and fixture.audio.operator_deadline-time.monotonic()>.2
                and fixture.speech.policy_deadline-time.monotonic()>.2,2)
            captures.append(pcm)
        slot=TranscriptionSlot();utterances={1:'Two plus',2:'two equals what?',3:'A later separate question',4:'Stale recognition'}
        stt_entered=threading.Event();stt_release=threading.Event();calls=[];tts_pcm=b'\x03\0'*160
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def answer(self,value):
                raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_GET(self):self.answer(dict(compute_boot_id='fixture-compute',quarantined=[]))
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path=='/transcribe/reserve':self.answer({'execution':slot.reserve()});return
                if self.path=='/transcribe':
                    pcm=base64.b64decode(data['pcm_base64']);index=pcm[0]
                    def recognize():
                        if index==4:stt_entered.set();stt_release.wait(3)
                        return utterances[index]
                    self.answer(dict(execution=data['execution'],transcript=slot.run(data['execution'],recognize)));return
                if self.path=='/decision':
                    view=data['data'];choice=dict(a='wait',why='fixture waiting')
                    if view['ready']:choice=dict(a='converse',why='fixture commit',commit=view['ready'][0]['alias'])
                    elif view['candidates'] and view['dialogue']:
                        choice=dict(a='think',why='fixture voice',start=dict(type='main',input_ref=view['candidates'][0]['alias']))
                    self.answer(dict(request_id=data['request_id'],compute_boot_id='fixture-compute',output=choice));return
                if self.path=='/main':
                    prompt=data['data'];text=prompt['utterance'] if type(prompt) is dict else prompt
                    output='Answer to '+text;calls.append(text)
                    self.answer(dict(request_id=data['request_id'],compute_boot_id='fixture-compute',output=output,
                        completion_provenance=model_final(prompt,output,'completion_http','fixture-model')));return
                if self.path=='/stream/say':
                    raw=(json.dumps(dict(type='audio',sample_rate=16000,format='S16_LE',channels=1,
                        pcm_base64=base64.b64encode(tts_pcm).decode()))+'\n'+json.dumps(dict(type='done',ok=True))+'\n').encode()
                    self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
                self.send_error(404)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);listener=threading.Thread(target=server.serve_forever,daemon=True);listener.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        url='http://127.0.0.1:'+str(server.server_address[1]);token='PRIVATE-TOKEN-'*4
        fixture.audio.stt=HttpSTT(url,token);fixture.audio.result_ttl_s=.5;fixture.audio.continuous_input=True
        fixture.speech.tts=HttpTTS(url,token)
        cfg=load(Path(__file__).resolve().parents[1]/'config.autonomous.normal.example.json');cfg['context']['enabled']=False
        cfg.update(period_s=.02,fast_deadline_s=1);cfg['gateway']['client_url']=url
        with patch.dict(os.environ,{cfg['gateway']['token_env']:token}):gateway=RemoteGateway(cfg)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            scheduler=Scheduler(cfg,gateway,speech_adapter=fixture.speech,audio_adapter=fixture.audio)
            fixture.scheduler=scheduler;fixture.gateway.health_release=None
            writer_release=threading.Event();original_write=PrivateAudioTrace._write_bytes
            def write(sink,raw):
                if mode=='slow':writer_release.wait(5)
                if mode=='failed':raise OSError('PRIVATE-STORAGE-ERROR')
                original_write(sink,raw)
            writer_patch=patch.object(PrivateAudioTrace,'_write_bytes',write);writer_patch.start()
            trace=None
            if mode!='off':
                trace=PrivateAudioTrace(root/'private.jsonl',seconds=20,queue_cap=1 if mode=='slow' else 32)
                scheduler.private_trace=trace
            results=[]
            def run():
                scheduler.enable_production(DurableStore(root/'state.sqlite3'))
                results.append(fixture.run_normal(8))
            runner=threading.Thread(target=run);runner.start()
            try:
                fixture.wait(lambda:any(row.get('listening_ready') for row in fixture.latest),3)
                for index in (1,2,3):
                    fixture.wait(lambda:not fixture.speech.status()['execution_busy'],2)
                    capture(bytes([index,0])*320)
                    fixture.wait(lambda:len(fixture.speech.receipts)>=index,3)
                    fixture.wait(lambda:not fixture.speech.status()['execution_busy'],3)
                capture(b'\x04\0'*320)
                self.assertTrue(stt_entered.wait(2),(mode,fixture.audio.status(),fixture.peer.closed,fixture.lease.status(),fixture.poller.status(),fixture.peer.sequence,len(captures),fixture.latest[-1] if fixture.latest else None))
                if mode=='privacy':
                    fixture.operator['motion_policy'].update(privacy_all=True,epoch=2)
                    fixture.wait(lambda:not trace.content,2)
                elif mode=='stop':fixture.stop.set()
                else:time.sleep(.55)
                stt_release.set()
                if mode in ('privacy','stop'):
                    fixture.wait(lambda:slot.finished==4,2)
                    fixture.wait(lambda:fixture.audio.job is None or not fixture.audio.job.is_alive(),2)
                else:fixture.wait(lambda:fixture.audio.counts['stale']>0,2)
                fixture.stop.set();runner.join(3);self.assertFalse(runner.is_alive())
            finally:
                stt_release.set();fixture.stop.set();runner.join(3);writer_release.set()
                if trace is not None:trace.close();trace.worker.join(1)
                writer_patch.stop()
            self.assertEqual(calls,[utterances[i] for i in (1,2,3)])
            self.assertEqual(results[0]['counts']['new_turn'],3)
            self.assertTrue(results[0]['cleanup_verified'],results[0])
            self.assertGreater(fixture.lease.calls,10)
            if mode=='off':
                self.assertFalse((root/'private.jsonl').exists())
                self.assertNotIn('private_audio_trace',results[0]);self.assertFalse(results[0]['transcripts_retained']);return
            if mode in ('slow','failed'):
                self.assertTrue(results[0]['private_audio_trace']['incomplete']);return
            raw=(root/'private.jsonl').read_text();rows=list(map(json.loads,raw.splitlines()))
            raw_stt=[r for r in rows if r['kind']=='stt_result'];admitted=[r for r in rows if r['kind']=='input_admission']
            if mode in ('privacy','stop'):
                self.assertNotIn(utterances[4],raw);self.assertTrue(raw_stt[-1]['content_suppressed'])
                self.assertEqual([r['text'] for r in raw_stt[:3]],[utterances[i] for i in (1,2,3)])
            else:self.assertEqual([r['text'] for r in raw_stt],[utterances[i] for i in (1,2,3,4)])
            if mode not in ('privacy','stop'):self.assertEqual(raw_stt[-1]['disposition'],'stale')
            self.assertEqual(len(admitted),3)
            for index,event in enumerate(admitted,1):
                source=next(r for r in raw_stt if r['lineage_id']==event['lineage_id'])
                self.assertEqual(source['pcm_sha256'],hashlib.sha256(bytes([index,0])*320).hexdigest())
                self.assertEqual(source['audio_s'],.02);self.assertEqual(event['text'],source['text'])
                request=next(r for r in rows if r['kind']=='main_request' and r['input_ref']==event['input_ref'])
                self.assertEqual(request['text'],source['text']);self.assertEqual(request['authority'],event['authority'])
                checked=next(r for r in rows if r['kind']=='main_checked' and r['input_ref']==event['input_ref'])
                self.assertEqual(checked['disposition'],'ready');self.assertEqual(checked['final']['utterance_sha256'],digest(source['text']))
                speech=next(r for r in rows if r['kind']=='speech_terminal' and r['input_ref']==event['input_ref'])
                self.assertEqual(speech['tts_pcm_sha256'],hashlib.sha256(tts_pcm).hexdigest())
                terminal=next(r for r in rows if r['kind']=='playback_stop' and r['stream_id']==speech['stream_id'])
                self.assertTrue(terminal['verified_stopped']);self.assertEqual(terminal['consumed_frames'],160)
                self.assertEqual(terminal['stop_consumed_frames'],160);self.assertEqual(terminal['source_boot'],fixture.peer.boot_id)
                self.assertIsInstance(terminal['device_stream_id'],str)
            self.assertTrue(results[0]['transcripts_retained']);self.assertFalse(results[0]['private_audio_trace']['incomplete'])
            self.assertNotIn('PRIVATE-TOKEN',raw)
            public=json.dumps([fixture.latest,results])
            for value in utterances.values():self.assertNotIn(value,public)


if __name__=='__main__':unittest.main()
