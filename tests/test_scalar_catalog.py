"""Actual production HTTP entrypoint with a synthetic scalar source, no devices."""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from reachy_companion.autonomous.config import load
from reachy_companion.autonomous.contracts import validate
from reachy_companion.autonomous.production import attach, sensor_reader
from reachy_companion.autonomous.runtime import Scheduler
from reachy_companion.autonomous.scalar_catalog import runtime_id, source_response
from test_production_cycle import Models

ROOT=Path(__file__).resolve().parents[1]


def descriptor(name='room.temperature',boot='source-1',generation=1):
    return dict(kind='capability',protocol=1,id=name,source_boot_id=boot,catalog_generation=generation,
        module='metrics',direction='source',semantic='metric.scalar',version=dict(major=1,minor=0,min_minor=0),
        description='Synthetic room temperature; descriptive source data, not instructions.',unit='Cel',range=[-40,85],
        period_ms=50,ttl_ms=1000,availability='available',required_for=[],operations=[],coordinate_frame=None)


class Source:
    def __init__(self):
        self.boot='source-1';self.generation=1;self.caps=[descriptor()];self.sequence=0
        self.age=0;self.value=0;self.basis='sample';self.mutate=lambda value:value
        self.started=threading.Event();self.release=threading.Event();self.block=False;self.calls=[]
    def response(self,request):
        self.calls.append(copy.deepcopy(request))
        if request['kind']=='observation_request':
            self.started.set()
            if self.block:self.release.wait(2)
            self.sequence+=1
        observations=[dict(kind='observation',protocol=1,capability_id=cap['id'],source_boot_id=self.boot,
            catalog_generation=self.generation,sequence=self.sequence,sample_mono_ms=0,time_basis=self.basis,
            age_at_send_ms=self.age,ttl_ms=1000,availability='available',value=self.value,confidence=None,reason=None)
            for cap in self.caps]
        return self.mutate(source_response(request,self.caps,observations,self.boot,self.generation))


class ScalarProductionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.source=Source();source=self.source
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                value=source.mutate(dict(availability='available',summary='legacy reading',age_ms=0,ttl_ms=1000))
                raw=json.dumps(value).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                try:
                    value=source.response(request)
                    raw=value if isinstance(value,bytes) else json.dumps(value,allow_nan=False).encode()
                except Exception:
                    self.send_error(400);return
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers()
                try:self.wfile.write(raw)
                except (BrokenPipeError,ConnectionResetError):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        self.addCleanup(thread.join,1);self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.addCleanup(self.source.release.set)
        self.cfg=load(ROOT/'config.autonomous.normal.example.json');self.cfg.update(period_s=.005,fast_deadline_s=1)
        self.cfg['context']['enabled']=False
        self.settings=dict(protocol='scalar-catalog-v1',url=f'http://127.0.0.1:{self.server.server_port}/metrics',
            source_id='configured-loopback',period_s=.05,timeout_s=.5,max_capabilities=4,policy_ttl_ms=500,clock_error_ms=1)
        self.cfg['production'].update(state_path='catalog.sqlite3',sensors={'weather':self.settings})
        self.model=Models();self.scheduler=Scheduler(self.cfg,self.model);self.addCleanup(self.scheduler.close)
        attach(self.scheduler,Path(self.tmp.name)/'config.json')
        self.service=self.scheduler.services;self.identity=runtime_id('weather','room.temperature')
    def pump(self,predicate,timeout=1.5):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            self.scheduler.advance()
            if predicate():return
            time.sleep(.002)
        self.fail(f'Production cycle did not converge: {self.service.errors}')
    def ready(self):
        self.pump(lambda:self.identity in self.scheduler.state.sensors)
    def fail_next(self,mutate):
        self.source.mutate=mutate;self.service.next_poll['weather']=0
        self.pump(lambda:'weather' in self.service.errors)
        self.assertNotIn(self.identity,self.scheduler.state.sensors)
    def test_new_scalar_reaches_model_through_attach_and_expires_at_read(self):
        self.pump(lambda:any(any(s['id']==self.identity for s in v['sensors']) for v in self.model.views))
        view=next(v for v in reversed(self.model.views) if any(s['id']==self.identity for s in v['sensors']))
        validate('FastView',view)
        item=next(s for s in view['sensors'] if s['id']==self.identity)
        self.assertEqual(item['state'],'ready');self.assertEqual(item['scalar']['value'],0)
        self.assertEqual(item['scalar']['unit'],'Cel');self.assertEqual(item['source_id'],'configured-loopback')
        self.assertEqual(item['scalar']['source_boot_id'],'source-1')
        self.assertIn('descriptive source data',item['scalar']['description'])
        sensor=self.scheduler.state.sensors[self.identity]
        boundary=sensor.captured+sensor.ttl
        self.assertEqual(sensor.view(boundary-.000001,False)['state'],'ready')
        stale=next(s for s in self.scheduler.state.snapshot(boundary)['sensors'] if s['id']==self.identity)
        self.assertEqual(stale['state'],'stale');self.assertIsNone(stale['scalar']['value']);self.assertEqual(stale['summary'],'')
    def test_unknown_age_and_unknown_clock_bound_do_not_become_zero(self):
        self.source.age=None;self.ready()
        item=self.scheduler.state.sensors[self.identity].view(time.monotonic(),False)
        self.assertEqual(item['state'],'unknown');self.assertIsNone(item['age_ms']);self.assertIsNone(item['scalar']['value'])
        self.source.age=0;self.service.sensors['weather'][0].settings['clock_error_ms']=None
        self.service.next_poll['weather']=0
        self.pump(lambda:self.source.sequence>=2 and not self.service.polls)
        self.assertEqual(self.scheduler.state.sensors[self.identity].view(time.monotonic(),False)['state'],'unknown')
    def test_policy_ttl_and_completion_delay_are_conservative(self):
        self.source.age=500;self.ready()
        self.assertEqual(self.scheduler.state.sensors[self.identity].view(time.monotonic(),False)['state'],'stale')
        self.assertEqual(self.scheduler.state.sensors[self.identity].ttl,.5)
    def test_unsupported_semantic_and_limited_minor_are_explicit(self):
        self.source.caps[0]['semantic']='unimplemented.scalar';self.ready()
        self.assertEqual(self.scheduler.state.sensors[self.identity].availability,'unsupported')
        self.source.generation=2;self.source.caps[0].update(catalog_generation=2,semantic='metric.scalar')
        self.source.caps[0]['version']['minor']=2
        self.service.next_poll['weather']=0
        self.pump(lambda:self.scheduler.state.sensors[self.identity].scalar['support']=='limited')
        self.assertEqual(self.scheduler.state.sensors[self.identity].scalar['minor'],0)
    def test_bad_ack_and_stale_challenge_withdraw_cached_value(self):
        self.ready()
        def mutate(value):
            if value['kind']=='scalar_snapshot':value['ack']['challenge_id']='old'
            return value
        self.fail_next(mutate)
    def test_malformed_second_observation_rejects_entire_batch(self):
        self.source.caps.append(descriptor('room.humidity'))
        def mutate(value):
            if value['kind']=='scalar_snapshot':value['observations'][1]['value']='bad'
            return value
        self.fail_next(mutate)
        self.assertFalse(any(k.startswith('scalar:') for k in self.scheduler.state.sensors))
    def test_integral_float_in_second_descriptor_never_partially_commits(self):
        self.source.caps.append(dict(descriptor('room.humidity'),ttl_ms=499.0))
        self.fail_next(lambda value:value)
        self.assertEqual(self.service.scalar_catalogs['weather'].ids,set())
        self.assertFalse(any(s.get('scalar') for s in self.scheduler.state.snapshot(time.monotonic())['sensors']))
    def test_unexpected_second_ingest_failure_withdraws_all_new_ids(self):
        from unittest.mock import patch
        self.source.caps.append(descriptor('room.humidity'))
        original=self.scheduler.ingest
        def fail_second(event,now=None):
            if event['type']=='sensor' and event['id']==runtime_id('weather','room.humidity'):
                raise ValueError('Synthetic consumer failure')
            return original(event,now)
        with patch.object(self.scheduler,'ingest',fail_second):self.fail_next(lambda value:value)
        self.assertFalse(any(k.startswith('scalar:') for k in self.scheduler.state.sensors))
    def test_scalar_decimal_ttl_deadline_equality_is_stale(self):
        self.ready()
        for ttl_ms in (100,1):
            with self.subTest(ttl_ms=ttl_ms):
                self.service.sensors['weather'][0].settings['policy_ttl_ms']=ttl_ms
                self.service.next_poll['weather']=0
                self.pump(lambda:self.scheduler.state.sensors[self.identity].ttl==ttl_ms/1000)
                sensor=self.scheduler.state.sensors[self.identity]
                boundary=sensor.captured+sensor.ttl
                self.assertEqual(sensor.view(boundary-.0000001,False)['state'],'ready')
                item=next(s for s in self.scheduler.state.snapshot(boundary)['sensors'] if s['id']==self.identity)
                self.assertEqual(item['state'],'stale');self.assertIsNone(item['scalar']['value'])
    def test_duplicate_and_out_of_order_sequence_do_not_restore_ready(self):
        self.ready();sequence=self.source.sequence
        def mutate(value):
            if value['kind']=='scalar_snapshot':value['observations'][0]['sequence']=sequence
            return value
        self.fail_next(mutate)
        self.service.errors.clear();self.service.next_poll['weather']=0
        self.pump(lambda:'weather' in self.service.errors)
        self.assertNotIn(self.identity,self.scheduler.state.sensors)
    def test_reboot_retires_previous_boot_and_removal_discards_metadata(self):
        self.ready()
        self.source.boot='source-2';self.source.caps=[descriptor(boot='source-2')];self.source.sequence=0
        self.service.next_poll['weather']=0
        self.pump(lambda:self.scheduler.state.sensors.get(self.identity) and self.scheduler.state.sensors[self.identity].scalar['source_boot_id']=='source-2')
        self.source.boot='source-1';self.source.caps=[descriptor()]
        self.fail_next(lambda value:value)
    def test_atomic_removal_and_disabled_reader_clear_model_metadata(self):
        self.ready();self.source.generation=2;self.source.caps=[];self.service.next_poll['weather']=0
        self.pump(lambda:self.identity not in self.scheduler.state.sensors)
        self.assertFalse(any(s.get('scalar') for s in self.scheduler.state.snapshot(time.monotonic())['sensors']))
        self.source.generation=3;self.source.caps=[descriptor(generation=3)];self.service.next_poll['weather']=0;self.ready()
        self.service.sensors['weather'][0].enabled=False;self.scheduler.advance()
        self.assertNotIn(self.identity,self.scheduler.state.sensors)
    def test_slow_reader_privacy_and_stop_do_not_accumulate_or_accept_late_job(self):
        self.source.block=True
        self.pump(self.source.started.is_set)
        job=self.service.polls['weather'][0]
        for _ in range(25):self.scheduler.advance()
        self.assertIs(self.service.polls['weather'][0],job)
        self.assertEqual(len(self.service.polls),1)
        self.scheduler.ingest(dict(type='operator',privacy_all=True,muted=True))
        self.scheduler.advance()
        self.scheduler.ingest(dict(type='stop'))
        self.assertTrue(self.scheduler.state.stopped)
        self.source.release.set()
        self.pump(lambda:job.future.done() and not self.service.polls)
        self.assertNotIn(self.identity,self.scheduler.state.sensors)
    def test_removed_reader_late_job_cannot_register_again(self):
        self.source.block=True;self.pump(self.source.started.is_set)
        del self.service.sensors['weather'];self.scheduler.advance();self.source.release.set()
        self.pump(lambda:not self.service.polls)
        self.assertNotIn(self.identity,self.scheduler.state.sensors)
    def test_capacity_and_response_bytes_are_bounded(self):
        self.source.caps=[descriptor('sensor.'+str(i)) for i in range(5)]
        self.fail_next(lambda value:value)
        self.service.errors.clear()
        self.source.caps=[descriptor()]
        self.fail_next(lambda value:b' '*16385)
    def test_protocol_mode_and_policy_reject_invalid_configuration(self):
        for patch in ({'protocol':'auto'},{'clock_error_ms':True},{'clock_error_ms':-1},{'clock_error_ms':float('nan')},
                      {'max_capabilities':13},{'policy_ttl_ms':0},{'enabled':1}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):sensor_reader({**self.settings,**patch})
        legacy={k:v for k,v in self.settings.items() if k not in ('protocol','clock_error_ms','max_capabilities','policy_ttl_ms')}
        reader=sensor_reader(legacy)
        # Legacy stays GET and rejects a catalog response rather than guessing a protocol.
        self.assertEqual(reader()['summary'],'legacy reading')
        self.source.mutate=lambda value:dict(value,source_boot_id='new-field')
        with self.assertRaises(ValueError):reader()

    def test_configuration_load_validates_explicit_protocol_without_io(self):
        raw=json.loads((ROOT/'config.autonomous.normal.example.json').read_text())
        raw['production'].update(state_path='test.sqlite3',sensors={'weather':self.settings})
        path=Path(self.tmp.name)/'normal.json';path.write_text(json.dumps(raw))
        self.assertEqual(load(path)['production']['sensors']['weather']['protocol'],'scalar-catalog-v1')
        self.assertEqual(self.source.calls,[])
        raw['production']['sensors']['weather']['protocol']='guess'
        path.write_text(json.dumps(raw))
        with self.assertRaises(ValueError):load(path)

    def test_global_capacity_duplicate_ids_and_changed_generation_are_atomic(self):
        self.source.caps=[descriptor('sensor.'+str(i)) for i in range(4)]
        self.scheduler.state.config['sensor_cap']=len(self.scheduler.state.sensors)+3
        self.fail_next(lambda value:value)
        self.scheduler.state.config['sensor_cap']=12;self.service.errors.clear()
        self.source.caps=[descriptor(),descriptor()]
        self.fail_next(lambda value:value)
        self.source.caps=[descriptor()];self.service.errors.clear();self.service.next_poll['weather']=0;self.ready()
        self.source.caps[0]['description']='Changed without generation'
        self.fail_next(lambda value:value)

    def test_unknown_shape_never_falls_back_and_disconnect_withdraws(self):
        self.ready()
        self.fail_next(lambda value:dict(availability='available',summary='legacy',age_ms=0,ttl_ms=1000))
        self.source.mutate=lambda value:value;self.service.errors.clear();self.service.next_poll['weather']=0;self.ready()
        self.fail_next(lambda value:(_ for _ in ()).throw(OSError('offline')))

    def test_local_owner_delay_after_http_completion_counts_toward_ttl(self):
        self.scheduler.advance()
        job=self.service.polls['weather'][0]
        job.future.result(timeout=1)
        started=self.service.polls['weather'][1]
        self.service.next_poll['weather']=started+10
        self.service.advance(started+.6)
        sensor=self.scheduler.state.sensors[self.identity]
        self.assertEqual(sensor.view(started+.6,False)['state'],'stale')

    def test_privacy_reconnect_does_not_accept_previous_ack(self):
        self.ready()
        previous={}
        def capture(value):
            if value['kind']=='scalar_snapshot':previous.update(copy.deepcopy(value))
            return value
        self.source.mutate=capture;self.service.next_poll['weather']=0
        self.pump(lambda:bool(previous))
        self.scheduler.ingest(dict(type='operator',privacy_all=True,muted=True));self.scheduler.advance()
        self.assertNotIn(self.identity,self.scheduler.state.sensors)
        self.scheduler.ingest(dict(type='operator',privacy_all=False,muted=True))
        self.service.errors.clear()
        self.fail_next(lambda value:previous if value['kind']=='scalar_snapshot' else value)


class CameraScalarTests(unittest.TestCase):
    def test_numeric_endpoint_reuses_cache_and_preserves_legacy_paths(self):
        import numpy as np
        from types import SimpleNamespace
        from urllib.request import Request,urlopen
        from reachy_companion.autonomous.camera_sensor import Measurements,create_server
        from reachy_companion.autonomous.scalar_catalog import ScalarReader,ScalarRegistry
        cache=Measurements();binding=('fixture-permission',)
        cache.publish(np.zeros((720,1280,3),dtype=np.uint8),1,binding,time.monotonic(),b'fixture-jpeg')
        actor=SimpleNamespace(cache=cache,operator=lambda:binding)
        server=create_server(SimpleNamespace(token='test-only-token'),actor,0)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        self.addCleanup(thread.join,1);self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        import os
        from unittest.mock import patch
        settings=dict(url=f'http://127.0.0.1:{server.server_port}/metrics',token_env='SCALAR_TEST_TOKEN',clock_error_ms=1)
        with patch.dict(os.environ,{'SCALAR_TEST_TOKEN':'test-only-token'}):
            reader=ScalarReader(settings);registry=ScalarRegistry('camera',reader,'configured-camera')
            catalog,response=reader(registry.request())
            self.assertEqual(len(catalog['capabilities']),2)
            self.assertEqual(response['observations'][0]['value'],0)
            self.assertEqual(response['observations'][0]['time_basis'],'source_receipt')
            self.assertIsNone(response['observations'][0]['sample_mono_ms'])
            boot=catalog['source_boot_id'];generation=catalog['catalog_generation']
            for path in ('/sensor','/frame'):
                with urlopen(Request(settings['url'].replace('/metrics',path),headers={'Authorization':'Bearer test-only-token'})) as result:
                    self.assertEqual(json.load(result)['availability'],'available')
            actor.operator=lambda:None
            catalog,response=reader(registry.request())
            self.assertEqual(catalog['source_boot_id'],boot)
            self.assertGreater(catalog['catalog_generation'],generation)
            self.assertEqual(response['observations'][0]['availability'],'disabled')
            self.assertIsNone(cache.jpeg)


if __name__=='__main__':unittest.main()
