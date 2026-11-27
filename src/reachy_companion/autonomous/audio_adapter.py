"""Latest-only captured utterances -> one occupied PC STT slot -> fresh events.

Capture clock mapping and source boot binding belong to the authenticated
transport owner. Model output cannot supply them. Unknown audio is dialogue
data, never a confirmed human identity or operator permission.
"""
from collections import deque
import base64
import hashlib
import math
import threading
import time
from urllib.request import Request, build_opener, ProxyHandler
from .contracts import decode,Authority
from ..private_audio_trace import emit


class HttpSTT:
    def __init__(self, url, token, *, timeout=2, diagnostics=False):
        self.url = url.rstrip('/') + '/transcribe'
        self.token, self.timeout = token, timeout
        self.diagnostics=diagnostics;self.last_diagnostics={}
        self.opener=build_opener(ProxyHandler({}))
        self.execution_lock=threading.Lock();self.waiting_terminal=False

    def request(self,path,payload,timeout):
        request = Request(self.url+path, data=__import__('json').dumps(payload).encode(),
            headers={'Authorization': 'Bearer ' + self.token,
                     'Content-Type': 'application/json'})
        with self.opener.open(request, timeout=timeout) as response:
            raw = response.read(8193)
        if len(raw) > 8192:
            raise ValueError('STT receipt cap')
        return decode(raw)

    def transcribe(self, pcm):
        if not self.execution_lock.acquire(False):raise RuntimeError('STT client execution busy')
        try:return self.transcribe_owned(pcm)
        finally:self.execution_lock.release()

    def transcribe_owned(self,pcm):
        from ..transcription import checked_execution
        self.last_diagnostics={}
        ticket=checked_execution(self.request('/reserve',{},min(2,self.timeout))['execution'])
        try:
            receipt=self.request('',dict(execution=ticket,pcm_base64=base64.b64encode(pcm).decode(),
                **({'diagnostics':True} if self.diagnostics else {})),self.timeout)
            if receipt.get('execution')!=ticket:raise ValueError('STT execution receipt mismatch')
            return self.receipt_text(receipt)
        except Exception:
            self.waiting_terminal=True
            try:
                while True:
                    try:
                        state=self.request('/settle',ticket,1)
                        if (state.get('execution')==ticket and state.get('terminal') is True
                                and state.get('state') in ('terminal','revoked')):break
                    except Exception:pass
                    # This remains the same occupied AudioAdapter worker. A newer
                    # utterance can replace pending input, never launch more STT.
                    time.sleep(.1)
            finally:self.waiting_terminal=False
            raise

    def receipt_text(self,receipt):
        text = receipt['transcript']
        diagnostic=receipt.get('diagnostics',{})
        if isinstance(diagnostic,dict):
            for key in ('segments_seen','segments_accepted','segments_rejected','rejected_logprob','rejected_no_speech','prefilter_skip','recognizer_invoked','whisper_invoked','vad_filter','decoder_budget_exceeded'):
                value=diagnostic.get(key)
                if type(value) is bool or type(value) is int and 0<=value<=100000:self.last_diagnostics[key]=value
            outcome=diagnostic.get('outcome')
            if outcome in ('recognized','whisper_empty','recognizer_empty','music_prefilter_skipped_whisper'):self.last_diagnostics['outcome']=outcome
        if not isinstance(text, str) or len(text) > 1024:
            raise ValueError('Bounded STT text required')
        return text


class AudioAdapter:
    def __init__(self, stt, *, clock=time.monotonic,continuous_input=False,result_ttl_s=2,endpoint_v1=False):
        if type(continuous_input) is not bool:raise ValueError('Explicit continuous input mode')
        if type(result_ttl_s) not in (int,float) or not math.isfinite(result_ttl_s) or not .5<=result_ttl_s<=15:
            raise ValueError('Bounded recognition result TTL required')
        if type(endpoint_v1) is not bool:raise ValueError('Explicit endpoint protocol mode')
        self.endpoint_v1=endpoint_v1
        self.turn_capture=None;self.turn_text=[];self.turn_segments=[]
        self.turn_dropped=0;self.last_turn_drop=None
        self.result_ttl_s=result_ttl_s
        self.continuous_input=continuous_input
        self.stt, self.clock = stt, clock
        self.lock = threading.RLock()
        self.source = None
        self.source_generation = -1
        self.sequence = self.latest_utterance_sequence = -1
        self.authority = self.operator_signature = None
        self.operator_deadline = 0
        self.allowed = False
        self.processing_paused = False
        self.closed = False
        self.generation = 0
        self.level=None
        self.pending = self.result = self.job = None
        self.counts = dict(submitted=0, overwritten=0, stale=0, echo=0,
                           started=0, completed=0, no_response=0, empty=0, errors=0, timeouts=0)
        self.diagnostics = deque(maxlen=32)
        self.last_error = None

    def same_capture_scope(self,left,right):
        if self.continuous_input and isinstance(left,Authority) and isinstance(right,Authority):
            fields=('hub_boot_id','compute_boot_id','robot_boot_id','operator_epoch','microphone_epoch')
            return all(getattr(left,key)==getattr(right,key) for key in fields)
        return left==right

    def bind_source(self, boot, generation):
        if not isinstance(boot, str) or not 1 <= len(boot) <= 128 or type(generation) is not int:
            raise ValueError('Authenticated capture source required')
        with self.lock:
            if self.closed or generation <= self.source_generation:
                return False
            self.source, self.source_generation, self.sequence = boot, generation, -1
            self.latest_utterance_sequence=-1
            self._withdraw('source_changed')
            return True

    def abandon_turn(self, reason):
        # Local owner/mailbox operation. In-flight STT remains occupied but its
        # generation can no longer contribute text to a later turn.
        with self.lock:
            self.turn_dropped+=1;self.last_turn_drop=reason
            self._withdraw()

    def _withdraw(self, reason=None):
        if reason and self.turn_capture:
            self.turn_dropped+=1;self.last_turn_drop=reason
        self.turn_capture=None;self.turn_text=[];self.turn_segments=[]
        if self.result and getattr(self,'private_trace',None) is not None:
            observation=self.result[0]
            emit(self,'stt_disposition',lineage_id=observation['lineage_id'],
                source_boot=observation['source_boot'],sequence=observation['sequence'],disposition='withdrawn')
        self.generation += 1
        self.pending = self.result = None
        self.level=None

    def advance(self, authority, operator, *, allow_start=True):
        """Only local mailbox work; no HTTP/capture/STT waits on scheduler."""
        with self.lock:
            now = self.clock()
            self.processing_paused = not allow_start
            signature = None
            allowed = False
            if operator:
                signature = (tuple(operator['binding']), operator['microphone_enabled'],
                             operator['quiet'], operator['privacy_all'])
                allowed = (operator['microphone_enabled'] is True and operator['quiet'] is False
                           and operator['privacy_all'] is False and now < operator['valid_until'])
            if not self.same_capture_scope(authority,self.authority) or signature != self.operator_signature or not allowed:
                self._withdraw('authority_or_permission')
            self.authority, self.operator_signature, self.allowed = authority, signature, allowed
            self.operator_deadline = operator['valid_until'] if allowed else 0
            if self.turn_capture and now>=self.turn_capture['deadline']:self.abandon_turn('expired')
            event = None
            if self.job and not self.job.is_alive():
                self.job = None
                result, self.result = self.result, None
                if result:
                    observation, generation, text, error = result
                    fresh_for_admission=self._fresh(observation,generation)
                    if getattr(self,'private_trace',None) is not None:
                        emit(self,'stt_disposition',lineage_id=observation['lineage_id'],source_boot=observation['source_boot'],
                            sequence=observation['sequence'],disposition='fresh' if fresh_for_admission else 'stale')
                    if fresh_for_admission:
                        if self.endpoint_v1:
                            text=self.finish_segment(observation,text,error)
                        if text is None:
                            pass  # A recognized nonfinal segment is not a no-response.
                        elif error or not text.strip():
                            self.counts['no_response'] += 1
                            if not error and text is not None:self.counts['empty'] += 1
                            self.last_error = error
                        else:
                            self.counts['completed'] += 1
                            self.last_error = None
                            event = dict(type='utterance', text=text, audio=dict(
                                source_boot=observation['source_boot'], sequence=observation['sequence'],
                                operator_binding=list(observation['operator_signature'][0]),
                                lineage_id=observation['lineage_id'], pcm_sha256=observation['pcm_sha256'],
                                origin='unknown', speaker_identity='unknown', speaker_confidence=0,
                                echo_reference=observation['echo_reference'],
                                capture_age_ms=(math.ceil if self.endpoint_v1 else int)((now-observation['captured_end'])*1000),
                                ttl_ms=int(self.result_ttl_s*1000), confirmed=False))
                            if 'aggregation' in observation:event['audio'].update(observation['aggregation'])
                            event['audio']['stt_provenance']='pc_http_stt' if type(self.stt) is HttpSTT else 'fixture_or_unverified_stt'
                    else:
                        self.counts['stale'] += 1
            if self.pending and not self.job and allow_start:
                observation, self.pending = self.pending, None
                # A deferred next turn starts only after the protected final's
                # result was consumed above. Never refresh its capture deadline.
                if observation.get('deferred_turn'):
                    if self.turn_capture is not None:
                        self.abandon_turn('unfinished_turn');return event
                    self.latest_utterance_sequence=observation['sequence']
                    self.begin_turn(observation['turn'],observation['sequence'],
                        observation['captured_end'],observation['deadline'])
                if self._fresh(observation, self.generation):
                    generation = self.generation
                    self.counts['started'] += 1
                    started = self.clock()
                    def work():
                        text, error = '', None
                        pcm = observation.pop('pcm')
                        try:
                            text = self.stt.transcribe(pcm)
                            if not isinstance(text, str) or len(text) > 1024:
                                raise ValueError('STT text cap')
                        except Exception as exc:
                            error = type(exc).__name__
                        finally:
                            del pcm
                        with self.lock:
                            fresh = self._fresh(observation, generation)
                            if getattr(self,'private_trace',None) is not None:
                                emit(self,'stt_result',text=text if not error else None,lineage_id=observation['lineage_id'],
                                    source_boot=observation['source_boot'],sequence=observation['sequence'],
                                    audio_s=observation['audio_s'],pcm_sha256=observation['pcm_sha256'],
                                    captured_end=observation['captured_end'],capture_basis='hub_monotonic_conservative_mapping',
                                    started_at=started,ended_at=self.clock(),authority=observation['authority'].wire() if isinstance(observation['authority'],Authority) else None,
                                    disposition='stale' if not fresh else 'error' if error else 'recognized' if text.strip() else 'empty',error_kind=error,
                                    **({'endpoint_segment':observation['turn']} if self.endpoint_v1 else {}))
                            if error:
                                self.counts['errors'] += 1
                                if error in ('TimeoutError','socket.timeout'):self.counts['timeouts'] += 1
                                self.last_error=error
                            self.diagnostics.append(dict(lineage_id=observation['lineage_id'],
                                outcome='stale' if not fresh else 'error' if error else 'recognized' if text.strip() else 'empty',
                                error_class=error, stt_s=round(max(0,self.clock()-started),4),
                                capture_to_result_s=round(max(0,self.clock()-observation['captured_end']),4),
                                audio_s=observation['audio_s'],
                                worker=dict(self.stt.last_diagnostics) if type(self.stt) is HttpSTT else {}))
                            if fresh:
                                self.result = observation, generation, text, error
                            else:
                                self.counts['stale'] += 1
                    self.job = threading.Thread(target=work, daemon=True)
                    self.job.start()
                else:
                    self.counts['stale'] += 1
            return event

    def _fresh(self, observation, generation):
        now = self.clock()
        return (not self.closed and self.allowed and now < self.operator_deadline
                and generation == self.generation and self.same_capture_scope(observation['authority'],self.authority)
                and observation['operator_signature'] == self.operator_signature
                and observation['source_boot'] == self.source
                and (self.continuous_input or observation['sequence']==self.latest_utterance_sequence)
                and now < observation['deadline'])

    def observe_level(self, level, *, started, source_boot, authority, operator_binding):
        with self.lock:
            now=self.clock()
            age=level.get('capture_age_s');rms=level.get('rms');delta=level.get('delta')
            if (type(age) not in (int,float) or not 0<=age<=.25 or type(rms) not in (int,float) or not 0<=rms<=1
                    or delta is not None and (type(delta) not in (int,float) or not -1<=delta<=1)):
                raise ValueError('Measured audio level contract')
            if (not self.allowed or now>=self.operator_deadline or source_boot!=self.source or authority!=self.authority
                    or tuple(operator_binding)!=self.operator_signature[0] or now-started+age>.5):return False
            self.level=(dict(type='sensor',id='audio.level',summary=f'rms={rms:.5f}; delta={delta}',
                source_id=source_boot,ttl_ms=1000),started-age,authority)
            return True

    def drain_level(self, authority):
        with self.lock:
            level,self.level=self.level,None
            if not level or not self.allowed or authority!=level[2] or self.clock()>=self.operator_deadline:return None
            event,captured,_=level
            event['age_ms']=max(0,int((self.clock()-captured)*1000))
            return event

    def submit(self, pcm, *, source_boot, sequence, captured_end, authority,
               operator_binding, origin='unknown', echo_reference=None, turn=None):
        """Called by trusted source adapter after conservative capture-clock mapping."""
        if (not isinstance(pcm, bytes) or not pcm or len(pcm) % 2 or len(pcm) > 16000*2*8
                or type(sequence) is not int or sequence < 0
                or type(captured_end) not in (int, float) or not math.isfinite(captured_end)
                or origin not in ('unknown', 'owned_playback')):
            raise ValueError('Bounded captured PCM/provenance required')
        if echo_reference is not None and (not isinstance(echo_reference, str) or not 1 <= len(echo_reference) <= 128):
            raise ValueError('Bounded owned playback reference')
        if origin == 'owned_playback' and echo_reference is None:
            raise ValueError('Owned echo requires reference')
        if self.endpoint_v1:
            from .audio_turn import segment
            try:turn=segment(turn,len(pcm)//2)
            except ValueError:
                self.abandon_turn('invalid_segment');return False
        elif turn is not None:
            # Legacy mode never silently reclassifies a typed deadline as final.
            return False
        with self.lock:
            now = self.clock()
            if (self.closed or not self.allowed or now >= self.operator_deadline
                    or source_boot != self.source or sequence <= self.sequence
                    or not 0 <= now-captured_end <= .25 or authority != self.authority
                    or tuple(operator_binding) != self.operator_signature[0]):
                self.counts['stale'] += 1
                if self.endpoint_v1:self.abandon_turn('stale_or_reordered')
                return False
            previous_sequence=self.sequence
            self.sequence = sequence
            if origin == 'owned_playback':
                self.counts['echo'] += 1
                if self.endpoint_v1:self.abandon_turn('echo')
                return False
            deferred=False
            if self.endpoint_v1:
                disposition=self.accept_segment(turn,sequence,captured_end,previous_sequence,now)
                if disposition is None:return False
                deferred=disposition=='deferred'
            if not deferred:self.latest_utterance_sequence=sequence
            if self.pending:
                self.counts['overwritten'] += 1
            self.pending = dict(pcm=pcm, audio_s=len(pcm)/32000, pcm_sha256=hashlib.sha256(pcm).hexdigest(),
                source_boot=source_boot, sequence=sequence, captured_end=captured_end,
                deadline=captured_end+self.result_ttl_s, authority=authority,
                operator_signature=self.operator_signature, echo_reference=echo_reference,
                lineage_id=source_boot+':'+str(sequence),**({'turn':turn,'deferred_turn':deferred} if self.endpoint_v1 else {}))
            self.counts['submitted'] += 1
            return True

    def begin_turn(self, turn, sequence, captured_end, deadline):
        self.turn_capture=dict(turn=turn,sequence=sequence,deadline=deadline,
            captured_end=captured_end,start=turn['sample_start'])

    def discard_pending_turn(self, reason):
        # A newer raw capture is not a recognized replacement of the finishing
        # utterance. Dropping this sole next-turn slot must not revoke the worker
        # or retained text of an already received final segment.
        self.turn_dropped+=1;self.last_turn_drop=reason
        if self.pending:
            self.counts['overwritten']+=1
            self.pending=None

    def accept_segment(self, turn, sequence, captured_end, previous_sequence, now):
        current=self.turn_capture
        if current and current['turn']['final'] and turn['turn_id']!=current['turn']['turn_id']:
            if now>=current['deadline']:
                self.abandon_turn('expired');return None
            if self.pending and not self.pending.get('deferred_turn'):
                # The final itself still owns the one pending PCM slot. It is
                # already a complete captured turn; do not replace it with noise.
                self.turn_dropped+=1;self.last_turn_drop='finishing_capacity'
                return None
            if turn['segment_index']!=0 or turn['sample_start']<current['turn']['sample_end']:
                self.discard_pending_turn('pending_discontinuity');return None
            if self.pending:self.discard_pending_turn('pending_overwritten')
            return 'deferred'
        if self.pending:
            self.counts['overwritten']+=1;self.abandon_turn('overwritten')
        current=self.turn_capture
        if turn['segment_index']==0:
            if current:self.abandon_turn('replaced_turn')
            self.begin_turn(turn,sequence,captured_end,captured_end+self.result_ttl_s)
        elif (current is None or turn['turn_id']!=current['turn']['turn_id']
                or turn['segment_index']!=current['turn']['segment_index']+1
                or sequence!=current['sequence']+1 or sequence!=previous_sequence+1
                or turn['sample_start']!=current['turn']['sample_end']):
            self.abandon_turn('discontinuity');return None
        else:
            if now>=current['deadline']:
                self.abandon_turn('expired');return None
            if turn['sample_end']-current['start']>192000:
                self.abandon_turn('duration_cap');return None
            current.update(turn=turn,sequence=sequence,deadline=min(current['deadline'],captured_end+self.result_ttl_s))
        if turn['segment_index']==2 and not turn['final']:
            self.abandon_turn('segment_cap');return None
        return 'active'

    def finish_segment(self, observation, text, error):
        turn=observation['turn']
        if error:
            self.abandon_turn('stt_error');return None
        if turn['segment_index']!=len(self.turn_segments):
            self.abandon_turn('missing_result');return None
        self.turn_segments.append(dict(source_boot=observation['source_boot'],sequence=observation['sequence'],
            lineage_id=observation['lineage_id'],**turn))
        if text.strip():self.turn_text.append(text.strip())
        combined=' '.join(self.turn_text)
        if len(combined)>1024:
            self.abandon_turn('text_cap');return None
        if not turn['final']:return None
        current=self.turn_capture
        if current is None or self.clock()>=current['deadline']:
            self.abandon_turn('expired');return None
        # Keep the first capture/deadline for the existing Sensor freshness
        # projection. A later segment must never refresh the retained prefix.
        observation['captured_end']=current['deadline']-self.result_ttl_s
        observation['lineage_id']=observation['source_boot']+':turn:'+turn['turn_id']
        observation['aggregation']=dict(aggregation='endpoint_v1',turn_id=turn['turn_id'],
            segments=list(self.turn_segments),earliest_deadline=current['deadline'])
        self.turn_capture=None;self.turn_text=[];self.turn_segments=[]
        return combined

    def interrupt(self):
        with self.lock:
            self._withdraw('interrupted')

    def close(self):
        with self.lock:
            self.closed = True
            self.allowed = False
            self._withdraw('closed')

    def status(self):
        with self.lock:
            return dict(execution_busy=bool(self.job and self.job.is_alive()),
                        pending=self.pending is not None, source_boot=self.source,
                        last_sequence=self.sequence,latest_utterance_sequence=self.latest_utterance_sequence, counts=dict(self.counts),
                        last_error=self.last_error, recent=list(self.diagnostics),
                        waiting_terminal=bool(type(self.stt) is HttpSTT and self.stt.waiting_terminal),
                        allowed=self.allowed, processing_paused=self.processing_paused, result_ttl_s=self.result_ttl_s,
                        endpoint_v1=self.endpoint_v1,turn_dropped=self.turn_dropped,last_turn_drop=self.last_turn_drop)
