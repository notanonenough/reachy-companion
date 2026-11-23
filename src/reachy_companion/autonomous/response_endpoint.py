"""Finite speech endpoint for a captured response, without speaker identity.

This is an utterance boundary only. It cannot establish a trusted negative
speech window for resuming an interrupted output.
"""
import math
import uuid


class ResponseEndpoint:
    rate = 16000
    frame_bytes = 640  # 20 ms, mono S16LE

    def __init__(self, vad, *, max_seconds=8, silence_frames=30, preserve_remainder=False):
        if (type(max_seconds) not in (int,float) or not math.isfinite(max_seconds) or not 1<=max_seconds<=8
                or type(silence_frames) is not int or not 10<=silence_frames<=50):
            raise ValueError('Finite endpoint bounds required')
        self.vad = vad
        self.preserve_remainder=preserve_remainder
        self.limit = int(max_seconds * 50)
        self.silence_frames = silence_frames
        self.pending = bytearray()
        self.frames = self.run = self.silence = 0
        self.started = False
        self.reason = None
        self.pcm = bytearray()

    def feed(self, pcm):
        if self.reason:
            return
        if len(pcm) % 2:
            raise ValueError('Complete S16LE samples required')
        # Reject oversized input before retaining it. A pipe read can include
        # the end of the utterance plus a bounded backlog.
        if len(pcm) > self.limit * self.frame_bytes:
            raise ValueError('Endpoint input exceeds finite bound')
        self.pending.extend(pcm)
        while len(self.pending) >= self.frame_bytes and not self.reason:
            frame = bytes(self.pending[:self.frame_bytes])
            del self.pending[:self.frame_bytes]
            speech = self.vad.is_speech(frame, self.rate)
            self.frames += 1
            self.pcm.extend(frame)
            self.run = self.run + 1 if speech else 0
            if self.run >= 5:
                self.started = True
            self.silence = 0 if speech else self.silence + 1
            if self.started and self.silence >= self.silence_frames:
                self.reason = 'speech_then_silence'
            elif self.frames >= self.limit:
                self.reason = 'response_deadline'
        if self.reason and not self.preserve_remainder:
            self.pending.clear()

    def receipt(self):
        return dict(reason=self.reason, speech_started=self.started,
                    processed_frames=self.frames,
                    elapsed_s=self.frames * .02,
                    trusted_resume_window=False)

    def clear(self):
        self.pending.clear()
        self.pcm.clear()


class TurnEndpoint:
    """Device-side contiguous segments, bounded PCM remainder and VAD turn state.

    Sample offsets count captured source samples, not wall clock or Hub time.
    After a cap, suppress the remainder of that speech turn until actual silence.
    """
    def __init__(self, vad, *, max_seconds=4, silence_frames=20):
        self.vad=vad;self.settings=dict(max_seconds=max_seconds,silence_frames=silence_frames,preserve_remainder=True)
        self.received=0;self.dropped=0;self.last_drop=None;self.no_response=0;self.clear()

    def clear(self):
        self.endpoint=ResponseEndpoint(self.vad,**self.settings)
        self.turn_id=uuid.uuid4().hex;self.index=0;self.start=self.received
        self.turn_start=self.start;self.suppressed=False

    def feed(self, pcm, *, sample_start, captured_end):
        if type(sample_start) is not int or sample_start<0:raise ValueError('Source sample offset required')
        if sample_start!=self.received:
            self.received=sample_start;self.clear();self.dropped+=1;self.last_drop='capture_discontinuity'
        self.received+=len(pcm)//2
        self.endpoint.feed(pcm)
        ready=[]
        while self.endpoint.reason:
            old=self.endpoint;end=self.start+len(old.pcm)//2
            final=old.reason=='speech_then_silence'
            if old.started and not self.suppressed:
                if self.index>=3 or end-self.turn_start>192000:
                    self.suppressed=True;self.dropped+=1;self.last_drop='turn_cap'
                else:
                    ready.append(dict(pcm=bytes(old.pcm),captured_end=captured_end-(self.received-end)/16000,
                        turn=dict(version=1,turn_id=self.turn_id,segment_index=self.index,
                            end_reason='silence' if final else 'deadline',final=final,
                            sample_start=self.start,sample_end=end,clock_basis='source_capture_samples')))
                    self.index+=1
            if not old.started:self.no_response+=1
            remainder=bytes(old.pending)
            self.endpoint=ResponseEndpoint(self.vad,**self.settings);self.start=end
            if final or not old.started:
                self.turn_id=uuid.uuid4().hex;self.index=0;self.turn_start=end;self.suppressed=False
            else:
                self.endpoint.started=True;self.endpoint.run=old.run;self.endpoint.silence=old.silence
            self.endpoint.feed(remainder)
        return ready
