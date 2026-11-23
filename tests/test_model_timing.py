"""Same normal HTTP main path with a local synthetic native server; no inference."""
import copy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import io
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from reachy_companion.autonomous.config import load
from reachy_companion.autonomous.contracts import Authority
from reachy_companion.autonomous.gateway import create_server
from reachy_companion.autonomous.runtime import RemoteGateway
from reachy_companion.model_timing import project,Timing,STAGES
from reachy_companion.private_audio_trace import PrivateAudioTrace,main_call


class ModelTimingTests(unittest.TestCase):
    def fixture(self,*,context=False):
        cfg=load(Path(__file__).resolve().parents[1]/'config.autonomous.example.json')
        calls=[];clock=NS(value=100.0);mode=NS(value='normal')
        class Native(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append((self.path,body))
                if self.path=='/tokenize':
                    index=sum(p=='/tokenize' for p,b in calls)
                    clock.value+=.1 if index%2 else .2
                    value={'tokens':[1,2] if index%2 else [1,2,3]}
                    if mode.value=='bad_tokens':value={'tokens':[True]}
                else:
                    clock.value+=.3
                    value=dict(content='Synthetic answer',stop_type='eos',tokens_predicted=7,
                        timings=dict(prompt_ms=12.5,predicted_ms=80.5,prompt_n=3,predicted_n=7,cache_n=0),
                        tokens_cached=10,tokens_evaluated=3,secret='PRIVATE-RAW-RESPONSE')
                    if mode.value=='bad_output':value['stop_type']='limit'
                    if mode.value=='bad_diagnostics':value['timings']=dict(prompt_ms='unsupported',predicted_ms=1e100,cache_n=True)
                    if mode.value=='missing':value.pop('timings');value.pop('tokens_cached')
                    if mode.value=='bad_container':value['timings']=[]
                raw=json.dumps(value).encode();self.send_response(503 if mode.value=='unknown' and self.path=='/completion' else 200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        native=ThreadingHTTPServer(('127.0.0.1',0),Native)
        nt=threading.Thread(target=native.serve_forever,daemon=True);nt.start()
        cfg['gateway'].update(port=0,token_env='MODEL_TIMING_TEST_TOKEN')
        model=cfg['models']['main'];model.update(id='synthetic-main',base_url='http://127.0.0.1:'+str(native.server_port),
            completion_backend='llama_native',completion_path='/completion',tokenize_path='/tokenize')
        model['audit'].update(verified=True,runtime_build='fixture-build',weight_sha256='a'*64,
            tokenizer_sha256='b'*64,template_sha256='c'*64,runtime_context_tokens=model['context_tokens'])
        env=patch.dict(os.environ,MODEL_TIMING_TEST_TOKEN='x'*32);env.start()
        server=create_server(cfg);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        cfg['gateway']['client_url']='http://127.0.0.1:'+str(server.server_port)
        from reachy_companion.autonomous.companion_session import ContextGateway
        gateway=ContextGateway(cfg,None) if context else RemoteGateway(cfg)
        def cleanup():
            server.shutdown();server.server_close();thread.join(1)
            native.shutdown();native.server_close();nt.join(1);env.stop()
        self.addCleanup(cleanup)
        task=NS(task_id='task',attempt_id='attempt',input_ref='input',kind='main',prompt='Synthetic question',
            authority=Authority('hub',gateway.boot_id))
        return NS(cfg=cfg,calls=calls,clock=clock,mode=mode,server=server,gateway=gateway,task=task)

    def test_actual_http_trace_stages_and_unchanged_calls_results(self):
        fixture=self.fixture(context=True)
        from reachy_companion.autonomous.gateway import model_final
        def final(*args):fixture.clock.value+=.4;return model_final(*args)
        fake_time=NS(monotonic=lambda:fixture.clock.value)
        with patch('reachy_companion.model_timing.time',fake_time),patch('reachy_companion.autonomous.gateway.model_final',final):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory).resolve();root.chmod(0o700)
                trace=PrivateAudioTrace(root/'trace.jsonl',seconds=10);trace.start(threading.Event(),hub_boot_id='hub')
                trace.emit('input_admission',input_ref='input',lineage_id='source',disposition='admitted')
                result=main_call(trace,fixture.gateway.main,fixture.task,fixture.gateway.main_with_transport);trace.close()
                rows=list(map(json.loads,(root/'trace.jsonl').read_text().splitlines()))
        receipt=result['model_timing'];self.assertFalse(receipt['incomplete'])
        self.assertEqual(receipt['request_id'],'attempt');self.assertEqual(receipt['gateway_boot_id'],fixture.gateway.boot_id)
        for name,expected in [('tokenize_text',.1),('tokenize_prompt',.2),('completion',.3),('validation',.4),('backend_total',1),('gateway_total',1),('handler_to_pre_serialize',1)]:
            self.assertAlmostEqual(receipt['stages'][name]['duration_s'],expected)
        self.assertEqual(receipt['usage'],dict(input_tokens=3,text_tokens=2,template_tokens=1,output_reserved=512,output_tokens=7))
        self.assertEqual(receipt['reported_native']['reported_prompt_ms'],12.5)
        self.assertIsNone(receipt['ttft_s']);self.assertIsNone(receipt['cache_hit'])
        row=next(r for r in rows if r['kind']=='main_result');self.assertEqual(row['model_timing'],receipt)
        self.assertNotIn('PRIVATE',json.dumps(rows));self.assertEqual([p for p,b in fixture.calls],['/tokenize','/tokenize','/completion'])
        self.assertFalse(fixture.calls[-1][1]['stream']);self.assertTrue(fixture.calls[-1][1]['cache_prompt'])
        prior_calls=copy.deepcopy(fixture.calls);fixture.calls.clear()
        with patch('reachy_companion.autonomous.gateway.Timing',lambda model:None):plain=fixture.gateway.main(fixture.task)
        self.assertEqual(prior_calls,fixture.calls)
        self.assertEqual({k:v for k,v in result.items() if k!='model_timing'},{k:v for k,v in plain.items() if k!='model_timing'})

    def test_bad_or_missing_native_diagnostics_do_not_change_result(self):
        fixture=self.fixture()
        for mode in ('bad_diagnostics','bad_container','missing'):
            fixture.mode.value=mode;fixture.calls.clear();result=fixture.gateway.main(fixture.task)
            self.assertEqual(result['output'],'Synthetic answer');self.assertEqual(len(fixture.calls),3)
            self.assertEqual(result['model_timing']['incomplete'],mode!='missing')
            self.assertIsNone(result['model_timing']['reported_native']['reported_prompt_ms'])
            json.dumps(result,allow_nan=False)

    def test_actual_http_failure_keeps_partial_trace_and_same_verdict(self):
        fixture=self.fixture()
        for mode,stage,num_calls in [('bad_tokens','tokenize_text',1),('bad_output','validation',3)]:
            fixture.calls.clear();fixture.mode.value=mode
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory).resolve();root.chmod(0o700)
                trace=PrivateAudioTrace(root/'trace',seconds=10);trace.start(threading.Event(),hub_boot_id='hub')
                with self.assertRaises(HTTPError) as failure:main_call(trace,fixture.gateway.main,fixture.task,fixture.gateway.main_with_transport)
                self.assertEqual(failure.exception.code,422);trace.close()
                result=next(r for r in map(json.loads,(root/'trace').read_text().splitlines()) if r['kind']=='main_result')
            receipt=result['model_timing'];self.assertTrue(receipt['incomplete'])
            self.assertEqual(receipt['stages'][stage],dict(state='failed',duration_s=None))
            self.assertEqual(receipt['request_id'],'attempt');self.assertEqual(len(fixture.calls),num_calls)
            self.assertFalse(fixture.server.gateway.health()['busy']['main'])
            if num_calls==3:self.assertEqual(receipt['stages']['completion']['state'],'complete')

    def test_projection_rejects_false_identity_bad_numbers_and_raw_fields(self):
        fixture=self.fixture();good=fixture.gateway.main(fixture.task)['model_timing']
        for field,bad in [('duration_s',True),('duration_s',float('nan')),('duration_s',-1),('duration_s',1e100)]:
            value=copy.deepcopy(good);value['stages']['completion'][field]=bad
            out=project(value);self.assertTrue(out['incomplete']);self.assertIsNone(out['stages']['completion']['duration_s'])
        for bad in (True,1.5,-1,10**100):
            value=copy.deepcopy(good);value['usage']['input_tokens']=bad
            out=project(value);self.assertTrue(out['incomplete']);self.assertIsNone(out['usage']['input_tokens'])
        self.assertIsNone(project(good,request_id='foreign')['request_id'])
        self.assertIsNone(project(good,gateway_boot_id='foreign')['gateway_boot_id'])
        for key in ('usage','reported_native'):
            bad=copy.deepcopy(good);bad[key]=[];self.assertTrue(project(bad)['incomplete'])
        bad=copy.deepcopy(good);bad['version']=True;self.assertEqual(project(bad)['reason'],'invalid_receipt')
        good['prompt']='PRIVATE-PROMPT';good['reported_native']['raw']='PRIVATE-RAW'
        self.assertNotIn('PRIVATE',json.dumps(project(good)))
        self.assertLess(len(json.dumps(project(good))),4096)

    def test_quarantine_receipt_is_retained_before_terminal_without_retry(self):
        for sink in ('trace','broken','disabled'):
            with self.subTest(sink=sink):
                fixture=self.fixture();fixture.cfg['production']=True;fixture.mode.value='unknown'
                polling=threading.Event();release=threading.Event();errors=[];callback=[]
                original=fixture.gateway.call
                class FinishedProbe(BaseException):pass
                def call(path,payload=None):
                    result=original(path,payload)
                    if path=='/health':
                        polling.set();release.wait(3);raise FinishedProbe()
                    return result
                with tempfile.TemporaryDirectory() as directory:
                    root=Path(directory).resolve();root.chmod(0o700)
                    trace=PrivateAudioTrace(root/'trace',seconds=10);trace.start(threading.Event(),hub_boot_id='hub')
                    def broken(receipt,disposition,status):callback.append(receipt);raise RuntimeError('PRIVATE-CALLBACK')
                    def worker():
                        try:
                            if sink=='trace':main_call(trace,fixture.gateway.main,fixture.task,fixture.gateway.main_with_transport)
                            else:fixture.gateway.main(fixture.task,on_transport=broken if sink=='broken' else None)
                        except BaseException as exc:errors.append(exc)
                    with patch.object(fixture.gateway,'call',call):
                        thread=threading.Thread(target=worker);thread.start()
                        try:
                            self.assertTrue(polling.wait(2));self.assertTrue(thread.is_alive())
                            self.assertTrue(fixture.server.gateway.health()['busy']['main'])
                            self.assertEqual(fixture.server.gateway.health()['quarantined'],['main'])
                            self.assertEqual([p for p,b in fixture.calls],['/tokenize','/tokenize','/completion'])
                            if sink=='trace':
                                # The actual immutable queue/file already contains the nonterminal receipt.
                                with trace.lock:queued=b''.join(trace.queue)
                                self.assertIn('main_transport',queued.decode()+(root/'trace').read_text())
                        finally:release.set();thread.join(2)
                    trace.close();rows=list(map(json.loads,(root/'trace').read_text().splitlines()))
                self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],FinishedProbe)
                transport=[r for r in rows if r['kind']=='main_transport']
                self.assertEqual(len(transport),1 if sink=='trace' else 0)
                if transport:
                    r=transport[0];self.assertEqual(r['disposition'],'execution_unknown')
                    self.assertEqual(r['model_timing']['stages']['completion']['state'],'failed')
                    self.assertEqual(r['model_timing']['usage']['input_tokens'],3)
                    self.assertNotIn('text',r)
                if sink=='broken':self.assertEqual(len(callback),1)
                self.assertEqual(len(fixture.calls),3)

    def test_late_dependency_revoke_keeps_measured_receipt_and_422(self):
        from unittest.mock import Mock
        fixture=self.fixture(context=True)
        handler=fixture.server.RequestHandlerClass
        cells=dict(zip(handler.do_POST.__code__.co_freevars,handler.do_POST.__closure__))
        cells['context'].cell_contents=NS(memory=NS(supports=Mock(side_effect=[True,False])),close=lambda:None)
        observed=[]
        with self.assertRaises(HTTPError) as failure:
            fixture.gateway.main(fixture.task,on_transport=lambda *args:observed.append(args))
        self.assertEqual(failure.exception.code,422);self.assertEqual(len(fixture.calls),3)
        receipt=observed[0][0]
        for name in ('tokenize_text','tokenize_prompt','completion','validation','backend_total','gateway_total'):
            self.assertEqual(receipt['stages'][name]['state'],'complete')
        self.assertEqual(receipt['stages']['handler_to_pre_serialize']['state'],'failed')
        self.assertEqual(receipt['usage']['input_tokens'],3);self.assertEqual(receipt['usage']['output_tokens'],7)
        self.assertEqual(receipt['request_id'],'attempt');self.assertFalse(fixture.server.gateway.health()['busy']['main'])

    def test_context_guard_and_native_rejection_precede_any_model_call(self):
        fixture=self.fixture(context=True)
        fixture.gateway.memory_binding=dict(store_id='store',revision=1,memory_projection_sha256='a'*64)
        fixture.task.memory_store_id='different';fixture.task.memory_revision=1
        with self.assertRaisesRegex(ValueError,'whitelist/store/revision changed'):
            fixture.gateway.main_with_transport(fixture.task,lambda *args:None)
        self.assertFalse(fixture.calls)
        from reachy_companion.autonomous.native_agent_session import NativeGateway
        native=NativeGateway.__new__(NativeGateway)
        with self.assertRaisesRegex(ValueError,'exclusively owns'):
            native.main_with_transport(fixture.task,lambda *args:None)

    def test_audited_gateway_forwards_callback_and_retains_existing_audit(self):
        import importlib.util
        path=Path(__file__).resolve().parents[1]/'deploy/autonomous/realtime_audio_session.py'
        spec=importlib.util.spec_from_file_location('timing_realtime',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        fixture=self.fixture();gateway=module.AuditedGateway(fixture.cfg)
        result=gateway.main_with_transport(fixture.task,lambda *args:None)
        self.assertEqual(result['output'],'Synthetic answer')
        self.assertEqual(len(gateway.main_calls),1);self.assertEqual(len(fixture.calls),3)
        self.assertEqual(gateway.main_calls[0]['usage'],result['usage'])
        self.assertEqual(result['model_timing']['request_id'],fixture.task.attempt_id)

    def test_transport_missing_malformed_and_foreign_receipt_preserve_polling(self):
        fixture=self.fixture();good=fixture.gateway.main(fixture.task)['model_timing']
        cases=[('no_response',None),('malformed_diagnostic',b'not-json'),
            ('missing_diagnostic',b'{}'),('identity_mismatch',json.dumps({'model_timing':{**good,'request_id':'other'}}).encode())]
        for expected,body in cases:
            gateway=RemoteGateway.__new__(RemoteGateway);gateway.boot_id=fixture.gateway.boot_id;gateway.config={'production':True}
            calls=[];seen=[]
            def call(path,payload=None):
                calls.append(path)
                if path=='/main':
                    if body is None:raise OSError('PRIVATE-TRANSPORT')
                    raise HTTPError('http://fixture',503,'unavailable',{},io.BytesIO(body))
                return dict(compute_boot_id=gateway.boot_id,executions={'main':{'request_id':'attempt','status':'terminal'}})
            gateway.call=call
            with self.assertRaisesRegex(RuntimeError,'exact remote execution is terminal'):
                gateway.main(fixture.task,on_transport=lambda *args:seen.append(args))
            self.assertEqual(calls,['/main','/health']);self.assertEqual(len(seen),1)
            self.assertEqual(seen[0][2],expected);self.assertIsNone(seen[0][0]['gateway_boot_id'])
            self.assertNotIn('PRIVATE',json.dumps(seen))

    def test_callback_is_one_shot_and_privacy_keeps_only_numeric_metadata(self):
        fixture=self.fixture();receipt=fixture.gateway.main(fixture.task)['model_timing']
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();root.chmod(0o700)
            trace=PrivateAudioTrace(root/'trace',seconds=10);trace.start(threading.Event(),hub_boot_id='hub')
            trace.emit('input_admission',input_ref='input',lineage_id='source',disposition='admitted')
            trace.disable('privacy')
            def transport(task,callback):
                callback(receipt,'observed_error_receipt','verified_receipt')
                callback(receipt,'observed_error_receipt','verified_receipt')
                return {'output':'PRIVATE-LATE','model_timing':receipt}
            main_call(trace,lambda _:None,fixture.task,transport);trace.close()
            raw=(root/'trace').read_text();rows=list(map(json.loads,raw.splitlines()))
            self.assertEqual(sum(row['kind']=='main_transport' for row in rows),1)
            self.assertNotIn('PRIVATE-LATE',raw)
            self.assertEqual(next(r for r in rows if r['kind']=='main_result')['model_timing'],receipt)

    def test_broken_diagnostic_clock_does_not_change_call_return_or_error(self):
        timer=Timing({},clock=lambda:(_ for _ in ()).throw(ValueError('PRIVATE')))
        self.assertEqual(timer.call('completion',lambda:7),7)
        with self.assertRaisesRegex(RuntimeError,'original'):timer.call('completion',lambda:(_ for _ in ()).throw(RuntimeError('original')))
        result={'output':'unchanged'};timer.finish(result=result);self.assertEqual(result['output'],'unchanged')


if __name__=='__main__':unittest.main()
