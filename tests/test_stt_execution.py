"""Real HTTP timeouts cannot enqueue another remote recognition operation."""
import json
import threading
import time
import unittest
import sys
import types
from unittest.mock import patch
from types import SimpleNamespace
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from reachy_companion.autonomous.audio_adapter import HttpSTT
from reachy_companion.transcription import TranscriptionSlot,TranscriptionBusy


class SlotTests(unittest.TestCase):
    def test_settle_fences_a_delayed_post_and_old_tickets_stay_revoked(self):
        slot=TranscriptionSlot();old=slot.reserve()
        self.assertTrue(slot.settle(old)['terminal'])
        current=slot.reserve();calls=[]
        with self.assertRaises(ValueError):slot.run(old,lambda:calls.append('old'))
        self.assertTrue(slot.settle(old)['terminal'])
        self.assertEqual(slot.run(current,lambda:'fresh'),'fresh');self.assertEqual(calls,[])

    def test_reserved_expiry_does_not_expire_running_inference(self):
        now=[0.];slot=TranscriptionSlot(clock=lambda:now[0]);old=slot.reserve();now[0]=3
        current=slot.reserve()
        with self.assertRaises(ValueError):slot.run(old,lambda:self.fail('late reservation'))
        def run():
            now[0]=100
            self.assertFalse(slot.settle(current)['terminal'])
            with self.assertRaises(TranscriptionBusy):slot.reserve()
        slot.run(current,run);self.assertTrue(slot.settle(current)['terminal'])
        foreign=TranscriptionSlot().settle(current)
        self.assertEqual(foreign['state'],'foreign_boot');self.assertFalse(foreign['terminal'])


class HttpTests(unittest.TestCase):
    def setUp(self):
        piper=types.ModuleType('piper');piper.PiperVoice=piper.SynthesisConfig=object
        vosk=types.ModuleType('vosk');vosk.Model=vosk.KaldiRecognizer=vosk.SetLogLevel=object
        with patch.dict(sys.modules,piper=piper,vosk=vosk):
            from reachy_companion.voice import create_server
        self.entered=threading.Event();self.release=threading.Event();self.calls=0
        self.hold=True;self.errors=[];self.done=threading.Event()
        def transcribe(payload):
            self.calls+=1
            if self.hold:self.entered.set();self.release.wait(3)
            return dict(ok=True,transcript='fixture',decision={})
        pipeline=SimpleNamespace(phase='idle',token_ok=lambda header:header=='Bearer '+'t'*32,
                                 transcribe_response=transcribe)
        cfg=dict(timeouts=dict(client=2),limits=dict(max_request_bytes=1048576),
                 servers=dict(worker=dict(listen='127.0.0.1',port=0)))
        self.server=create_server(cfg,True,pipeline=pipeline)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        self.client=HttpSTT(self.url,'t'*32,timeout=.05)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.release.set();self.server.shutdown();self.server.server_close();self.thread.join(1)

    def request(self,path,body):
        q=Request(self.url+path,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+'t'*32})
        with urlopen(q,timeout=1) as r:return json.load(r)

    def wait(self,predicate):
        until=time.monotonic()+2
        while not predicate() and time.monotonic()<until:time.sleep(.002)
        self.assertTrue(predicate())

    def test_timeout_retains_client_and_server_slots_until_actual_completion(self):
        def recognize():
            try:self.client.transcribe(b'\0\0'*160)
            except Exception as exc:self.errors.append(type(exc).__name__)
            finally:self.done.set()
        worker=threading.Thread(target=recognize,daemon=True);worker.start()
        self.wait(self.entered.is_set);self.wait(lambda:self.client.waiting_terminal)
        self.assertFalse(self.done.is_set())
        with self.assertRaises(RuntimeError):self.client.transcribe(b'\0\0'*160)
        with self.assertRaises(HTTPError) as caught:self.request('/transcribe/reserve',{})
        self.assertEqual(caught.exception.code,409);self.assertEqual(self.calls,1)
        self.release.set();worker.join(2);self.assertTrue(self.done.is_set())
        self.assertEqual(self.errors,['TimeoutError']);self.assertFalse(self.client.waiting_terminal)
        self.hold=False;self.client.timeout=1
        self.assertEqual(self.client.transcribe(b'\0\0'*160),'fixture');self.assertEqual(self.calls,2)

    def test_settle_before_late_http_post_never_calls_recognizer(self):
        ticket=self.request('/transcribe/reserve',{})['execution']
        self.assertTrue(self.request('/transcribe/settle',ticket)['terminal'])
        fresh=self.request('/transcribe/reserve',{})['execution']
        with self.assertRaises(HTTPError):self.request('/transcribe',dict(execution=ticket,pcm_base64='AAA='))
        self.assertEqual(self.calls,0);self.hold=False
        answer=self.request('/transcribe',dict(execution=fresh,pcm_base64='AAA='))
        self.assertEqual(answer['execution'],fresh);self.assertEqual(self.calls,1)

    def test_legacy_transcribe_remains_compatible_but_cannot_queue_behind_active(self):
        ticket=self.request('/transcribe/reserve',{})['execution']
        with self.assertRaises(HTTPError) as caught:self.request('/transcribe',dict(pcm_base64='AAA='))
        self.assertEqual(caught.exception.code,409);self.assertEqual(self.calls,0)
        self.request('/transcribe/settle',ticket);self.hold=False
        self.assertNotIn('execution',self.request('/transcribe',dict(pcm_base64='AAA=')))


if __name__=='__main__':unittest.main()
