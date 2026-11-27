"""Synthetic endpoint→real peer HTTP→STT HTTP→normal Scheduler; no hardware."""
import base64
from collections import deque
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from reachy_companion.autonomous.audio_adapter import AudioAdapter,HttpSTT
from reachy_companion.autonomous.audio_turn import segment
from reachy_companion.autonomous.response_endpoint import TurnEndpoint,LegacyEndpoint


class Vad:
    def is_speech(self,frame,rate):return frame[0]!=0


def operator(now):
    return dict(binding=('agent',1,0),microphone_enabled=True,quiet=False,privacy_all=False,valid_until=now+.3)


def meta(index=0,final=False,start=0,samples=320,turn='a'*32):
    return dict(version=1,turn_id=turn,segment_index=index,end_reason='silence' if final else 'deadline',
        final=final,sample_start=start,sample_end=start+samples,clock_basis='source_capture_samples')


class TurnTests(unittest.TestCase):
    def adapter(self,texts):
        self.clock=[0.]
        class STT:
            def transcribe(inner,pcm):return texts.popleft()
        adapter=AudioAdapter(STT(),clock=lambda:self.clock[0],continuous_input=True,endpoint_v1=True,result_ttl_s=8)
        adapter.bind_source('source',0);self.addCleanup(adapter.close);self.tick(adapter)
        return adapter
    def tick(self,adapter):return adapter.advance('scope',operator(self.clock[0]))
    def submit(self,adapter,turn,seq=None,**kwargs):
        return adapter.submit(b'\1\0'*(turn['sample_end']-turn['sample_start']),turn=turn,
            source_boot='source',sequence=turn['segment_index']+1 if seq is None else seq,captured_end=self.clock[0],
            authority='scope',operator_binding=('agent',1,0),**kwargs)
    def finish(self,adapter):
        self.tick(adapter)
        if adapter.job:adapter.job.join(1);self.assertFalse(adapter.job.is_alive())
        return self.tick(adapter)
    def test_empty_silence_tail_finalizes_text_once_and_keeps_first_expiry(self):
        a=self.adapter(deque(['question','']));self.submit(a,meta());self.assertIsNone(self.finish(a))
        self.clock[0]=3;self.tick(a);self.submit(a,meta(1,True,320));event=self.finish(a)
        self.assertEqual(event['text'],'question');self.assertEqual(event['audio']['capture_age_ms'],3000)
        self.assertEqual(event['audio']['earliest_deadline'],8);self.assertEqual(len(event['audio']['segments']),2)
        self.assertIn(':turn:',event['audio']['lineage_id']);self.assertIsNone(self.tick(a))
    def test_short_final_is_immediate(self):
        a=self.adapter(deque(['short']));self.submit(a,meta(final=True));self.assertEqual(self.finish(a)['text'],'short')
    def test_expiry_equality_does_not_refresh_prefix(self):
        a=self.adapter(deque(['prefix','tail']));self.submit(a,meta());self.finish(a)
        self.clock[0]=8;self.tick(a);self.assertFalse(self.submit(a,meta(1,True,320)))
        self.assertIsNone(self.finish(a));self.assertEqual(a.counts['completed'],0)
    def test_gap_reorder_missing_and_wrong_turn_abandon(self):
        for change in (dict(seq=3),dict(seq=1),dict(start=321),dict(turn='b'*32),dict(index=2)):
            with self.subTest(change=change):
                a=self.adapter(deque(['prefix','tail']));self.submit(a,meta());self.finish(a)
                args=dict(index=1,final=True,start=320);args.update({k:v for k,v in change.items() if k!='seq'})
                self.assertFalse(self.submit(a,meta(**args),seq=change.get('seq',2)))
                self.assertIsNone(self.finish(a));self.assertEqual(a.counts['completed'],0)
    def test_caps_and_interruption_never_emit_prefix(self):
        for mode in ('text','segments','privacy','echo','source','stop','overwrite'):
            with self.subTest(mode=mode):
                a=self.adapter(deque(['x'*1024 if mode=='text' else 'prefix','tail','tail']));self.submit(a,meta());self.finish(a)
                if mode=='text':self.submit(a,meta(1,True,320));self.assertIsNone(self.finish(a))
                elif mode=='segments':
                    self.submit(a,meta(1,False,320));self.finish(a)
                    self.assertFalse(self.submit(a,meta(2,False,640)))
                elif mode=='privacy':a.advance('scope',{**operator(0),'privacy_all':True});self.tick(a)
                elif mode=='echo':self.assertFalse(self.submit(a,meta(1,True,320),origin='owned_playback',echo_reference='stream'))
                elif mode=='source':a.bind_source('other',1)
                elif mode=='stop':a.close()
                elif mode=='overwrite':
                    self.submit(a,meta(1,False,320));self.assertFalse(self.submit(a,meta(2,True,640)))
                self.assertFalse(a.turn_capture);self.assertFalse(a.turn_text);self.assertEqual(a.counts['completed'],0)
    def test_late_stt_after_stop_or_changed_capture_authority_is_not_applied(self):
        for mode in ('stop','scope'):
            a=self.adapter(deque(['late']));release=threading.Event();entered=threading.Event()
            def recognize(pcm):entered.set();release.wait(1);return 'late'
            a.stt.transcribe=recognize;self.submit(a,meta(final=True));self.tick(a);self.assertTrue(entered.wait(.5))
            try:
                if mode=='stop':a.interrupt()
                else:a.advance('changed',operator(0))
            finally:release.set();a.job.join(1)
            self.assertIsNone(self.tick(a));self.assertEqual(a.counts['completed'],0)
    def test_private_projection_preserves_bounded_members_without_raw_audio(self):
        from reachy_companion.private_audio_trace import project
        member=dict(meta(),source_boot='source',sequence=1,lineage_id='source:1')
        value=project(dict(endpoint_segment=meta(),aggregation='endpoint_v1',turn_id='a'*32,
            segments=[member],earliest_deadline=8,pcm=b'private',secret='private'))
        self.assertEqual(value['segments'],[member]);self.assertEqual(value['endpoint_segment'],meta())
        self.assertNotIn('private',str(value));self.assertIsNone(project(dict(segments=[member]*4))['segments'])
        member['sample_end']=True;self.assertIsNone(project(dict(segments=[member]))['segments'])

    def test_stt_error_drops_retained_text(self):
        a=self.adapter(deque(['prefix']));self.submit(a,meta());self.finish(a)
        def fail(pcm):raise RuntimeError('private')
        a.stt.transcribe=fail;self.submit(a,meta(1,True,320));self.assertIsNone(self.finish(a))
        self.assertEqual(a.last_turn_drop,'stt_error');self.assertFalse(a.turn_text)

    def test_duration_cap_and_three_complete_segments(self):
        a=self.adapter(deque(['first','second','third']))
        for index in range(3):
            self.submit(a,meta(index,index==2,index*64000,64000))
            event=self.finish(a)
            if index<2:self.assertIsNone(event)
        self.assertEqual(event['text'],'first second third')
        a=self.adapter(deque(['prefix']))
        self.submit(a,meta(samples=128000));self.finish(a)
        self.assertFalse(self.submit(a,meta(1,True,128000,64001)))
        self.assertEqual(a.last_turn_drop,'duration_cap')

    def test_strict_metadata_and_legacy_are_explicit(self):
        a=self.adapter(deque(['wrong']))
        for bad in (None,{},dict(meta(),final=True),dict(meta(),segment_index=True),dict(meta(),sample_end=999)):
            self.assertFalse(a.submit(b'\0\0'*320,turn=bad,source_boot='source',sequence=1,captured_end=0,authority='scope',operator_binding=('agent',1,0)))
        with self.assertRaises(ValueError):segment(dict(meta(),version=True))
        legacy=AudioAdapter(None,clock=lambda:0);legacy.bind_source('source',0);legacy.advance('scope',operator(0))
        self.assertFalse(legacy.submit(b'\0\0'*320,turn=meta(),source_boot='source',sequence=1,captured_end=0,authority='scope',operator_binding=('agent',1,0)))
        legacy.close()
    def test_device_remainder_and_silence_only_continuity(self):
        endpoint=TurnEndpoint(Vad(),max_seconds=4,silence_frames=20)
        endpoint.feed(b'\1\0'*(64000-100),sample_start=0,captured_end=4-100/16000)
        parts=endpoint.feed(b'\1\0'*100+b'\0\0'*640,sample_start=63900,captured_end=4.04)
        self.assertEqual(len(parts),1);self.assertFalse(parts[0]['turn']['final'])
        self.assertEqual(len(endpoint.endpoint.pending)+len(endpoint.endpoint.pcm),1280)
        final=endpoint.feed(b'\0\0'*5760,sample_start=64640,captured_end=4.4)
        self.assertEqual(len(final),1);self.assertTrue(final[0]['turn']['final'])
        self.assertEqual(final[0]['turn']['sample_start'],64000);self.assertEqual(final[0]['turn']['sample_end'],70400)
        self.assertEqual(parts[0]['turn']['turn_id'],final[0]['turn']['turn_id'])
    def test_device_caps_suppress_until_actual_silence(self):
        e=TurnEndpoint(Vad());parts=[]
        for index in range(4):parts+=e.feed(b'\1\0'*64000,sample_start=index*64000,captured_end=(index+1)*4)
        self.assertEqual(len(parts),3);self.assertFalse(any(p['turn']['final'] for p in parts))
        self.assertEqual(e.feed(b'\0\0'*6400,sample_start=256000,captured_end=16.4),[])
        fresh=e.feed(b'\1\0'*3200+b'\0\0'*6400,sample_start=262400,captured_end=17)
        self.assertTrue(fresh[0]['turn']['final']);self.assertNotEqual(fresh[0]['turn']['turn_id'],parts[0]['turn']['turn_id'])


class SourceQueueTests(unittest.TestCase):
    def peer(self):
        from test_audio_peer import PeerTests
        fixture=PeerTests();peer,_=fixture.setup_peer();self.addCleanup(fixture.doCleanups)
        fixture.call(peer,'/lease')
        return peer,fixture
    def publish(self,peer,turn,at=None):
        return peer.publish(b'\1\0'*(turn['sample_end']-turn['sample_start']),
            time.monotonic() if at is None else at,None,turn=turn)
    def take(self,peer):return peer.dispatch('/observation',dict(controller='controller'))['observation']
    def test_fifo_timestamps_sequences_and_byte_accounting(self):
        peer,_=self.peer();at=time.monotonic()
        for index in range(3):self.assertTrue(self.publish(peer,meta(index,index==2,index*64000,64000),at))
        self.assertEqual(peer.observation_samples,192000);self.assertEqual(len(peer.observation_queue),3)
        for index in range(3):
            item=self.take(peer);self.assertEqual(item['sequence'],index+1)
            self.assertEqual(item['turn']['segment_index'],index)
            self.assertGreaterEqual(item['capture_age_s'],0)
            self.assertEqual(peer.observation_samples,(2-index)*64000)
        self.assertIsNone(self.take(peer));self.assertFalse(peer.observation_queue)
    def test_cap_clears_all_pcm_and_blocks_remaining_turn(self):
        peer,_=self.peer();self.assertTrue(self.publish(peer,meta(samples=128000)))
        self.assertFalse(self.publish(peer,meta(1,False,128000,128000)))
        self.assertEqual(peer.observation_drop_reason,'turn_cap');self.assertEqual(peer.observation_samples,0)
        self.assertFalse(self.publish(peer,meta(2,True,256000)))
        self.assertIsNone(self.take(peer));self.assertFalse(peer.observation_queue)
    def test_new_turn_abandons_old_fifo_and_legacy_cannot_mix(self):
        peer,_=self.peer();self.publish(peer,meta());self.publish(peer,meta(1,True,320))
        self.assertTrue(self.publish(peer,meta(final=True,turn='b'*32)))
        self.assertEqual(peer.observation_drop_reason,'new_turn');self.assertEqual(len(peer.observation_queue),1)
        self.assertEqual(self.take(peer)['turn']['turn_id'],'b'*32)
        self.publish(peer,meta(turn='c'*32));peer.publish(b'\0\0'*320,time.monotonic(),None)
        self.assertEqual(peer.observation_samples,0);self.assertNotIn('turn',self.take(peer))
        self.assertFalse(self.publish(peer,meta(1,True,320,turn='c'*32)))
    def test_invalid_fourth_index_cannot_leave_retained_prefix(self):
        peer,_=self.peer();self.publish(peer,meta())
        with self.assertRaises(ValueError):self.publish(peer,meta(3,True,320))
        self.assertFalse(peer.observation_queue);self.assertEqual(peer.observation_samples,0)
        self.assertFalse(self.publish(peer,meta(1,True,320)))
    def test_stale_oldest_clears_tail_without_refresh(self):
        peer,_=self.peer();self.publish(peer,meta(),time.monotonic()-.3)
        self.publish(peer,meta(1,True,320))
        self.assertIsNone(self.take(peer));self.assertEqual(peer.observation_drop_reason,'stale_capture')
        self.assertEqual(peer.observation_samples,0);self.assertFalse(peer.observation_queue)
    def test_close_and_privacy_release_queued_pcm(self):
        for privacy in (False,True):
            peer,fixture=self.peer();self.publish(peer,meta())
            if privacy:
                fixture.actual['motion_policy']['privacy_all']=True
                deadline=time.monotonic()+1
                while not peer.closed and time.monotonic()<deadline:time.sleep(.002)
                self.assertTrue(peer.closed)
            else:peer.close()
            self.assertFalse(peer.observation_queue);self.assertEqual(peer.observation_samples,0)
            self.assertFalse(self.publish(peer,meta(1,True,320)))


class ActualTurnPipelineTests(unittest.TestCase):
    def test_normal_fullpath_deadline_question_and_format_yields_one_main(self):self.exercise(False)
    def test_normal_fullpath_empty_silence_tail_yields_one_main(self):self.exercise(True)
    def test_normal_fullpath_short_silence_ended_input_has_no_extra_wait(self):self.exercise(False,short=True)
    def test_normal_read_deadline_and_silence_burst_delivers_both_segments(self):self.exercise(True,burst=True)
    def test_finite_legacy_producer_preserves_existing_single_pcm_lineage(self):self.exercise(False,short=True,legacy=True)
    def exercise(self,empty_tail,short=False,burst=False,legacy=False):
        from test_companion_session import SessionTests
        from reachy_companion.transcription import TranscriptionSlot
        fixture=SessionTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        fixture.audio.endpoint_v1=not legacy;fixture.audio.continuous_input=not legacy;fixture.audio.result_ttl_s=2 if legacy else 8
        captures=deque();dispatch=fixture.peer.dispatch;endpoint=(LegacyEndpoint if legacy else TurnEndpoint)(Vad(),max_seconds=4,silence_frames=20);offset=0
        def observe(path,body):
            nonlocal offset
            if path=='/observation' and captures:
                pcm=captures.popleft();parts=[];captured_end=time.monotonic()
                # Actual ALSA maximum read is 1024 frames. Speech ending at
                # 3.62s makes deadline+silence end in the same normal read.
                chunks=[pcm[i:i+2048] for i in range(0,len(pcm),2048)] if burst else [pcm]
                unread=len(pcm)//2
                for chunk in chunks:
                    unread-=len(chunk)//2
                    parts+=endpoint.feed(chunk,sample_start=offset,captured_end=captured_end-unread/16000)
                    offset+=len(chunk)//2
                if burst:self.assertEqual(len(parts),2)
                for part in parts:
                    if not fixture.peer.publish(part['pcm'],part['captured_end'],None,turn=part.get('turn')):raise AssertionError('fixture permission')
            return dispatch(path,body)
        fixture.peer.dispatch=observe
        texts=deque(['What is two plus two?'] if short else ['What is two plus two?','' if empty_tail else 'Answer with one number.']);stt_calls=[];main_calls=[]
        slot=TranscriptionSlot();stt_entered=threading.Event();stt_release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path=='/transcribe/reserve':value={'execution':slot.reserve()}
                else:
                    pcm=base64.b64decode(data['pcm_base64']);stt_calls.append(len(pcm))
                    def recognize():
                        if burst and len(stt_calls)==1:stt_entered.set();stt_release.wait(2)
                        return texts.popleft()
                    value=dict(execution=data['execution'],transcript=slot.run(data['execution'],recognize))
                raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        fixture.audio.stt=HttpSTT('http://127.0.0.1:'+str(server.server_port),'t'*32,timeout=8)
        audio_events=[];ingest=fixture.scheduler.ingest
        def ingest_event(event,now=None):
            if event.get('audio'):audio_events.append(event)
            return ingest(event,now)
        fixture.scheduler.ingest=ingest_event
        original=fixture.gateway.main
        def main(task):main_calls.append(task.prompt);return original(task)
        fixture.gateway.main=main;reports=[]
        runner=threading.Thread(target=lambda:reports.append(fixture.run_normal(5)));runner.start()
        try:
            fixture.wait(lambda:any(row.get('listening_ready') for row in fixture.latest))
            if burst:captures.append(b'\1\0'*57920+b'\0\0'*7680)
            elif short:captures.append(b'\1\0'*3200+b'\0\0'*6400)
            else:
                captures.append(b'\1\0'*64000)
                fixture.wait(lambda:len(fixture.audio.turn_segments)==1)
                self.assertEqual(main_calls,[]);self.assertEqual(fixture.scheduler.state.counts.get('new_turn',0),0)
                captures.append((b'' if empty_tail else b'\2\0'*3200)+b'\0\0'*6400)
            if burst:
                self.assertTrue(stt_entered.wait(1))
                fixture.wait(lambda:fixture.audio.pending is not None)
                self.assertEqual(fixture.audio.pending['turn']['segment_index'],1)
                self.assertTrue(fixture.audio.status()['execution_busy']);self.assertEqual(main_calls,[])
                self.assertEqual(fixture.peer.sequence,2);self.assertFalse(fixture.peer.observation_queue)
                stt_release.set()
            fixture.wait(lambda:len(fixture.tts.calls)==1,3)
            fixture.wait(lambda:fixture.speech.status()['receipts'] and not fixture.speech.status()['execution_busy'])
            fixture.stop.set();runner.join(3);self.assertFalse(runner.is_alive())
        finally:stt_release.set();fixture.stop.set();runner.join(3)
        self.assertEqual(main_calls,['What is two plus two?'+('' if empty_tail or short else ' Answer with one number.')])
        self.assertEqual(len(stt_calls),1 if short else 2);self.assertEqual(reports[0]['counts']['new_turn'],1)
        self.assertEqual(reports[0]['counts']['task_started'],1);self.assertTrue(reports[0]['cleanup_verified'])
        if legacy:
            import hashlib
            audio=audio_events[0]['audio']
            self.assertEqual(audio['lineage_id'],fixture.peer.boot_id+':'+str(audio['sequence']))
            self.assertEqual(audio['pcm_sha256'],hashlib.sha256(b'\1\0'*3200+b'\0\0'*6400).hexdigest())
            self.assertNotIn('aggregation',audio);self.assertLess(audio['capture_age_ms'],2000)
            self.assertEqual(len(audio_events),1)


if __name__=='__main__':unittest.main()
