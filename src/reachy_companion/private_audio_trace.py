"""Explicit one-session private voice evidence; never an authority or log sink."""
from collections import deque
import json
import math
import os
from pathlib import Path
import stat
import threading
import time
import uuid
from .autonomous.voice_chain import digest
from .model_timing import project as project_model_timing

KINDS=('session_begin','stt_result','stt_disposition','input_admission','main_request',
       'main_result','main_checked','speech_commit','speech_terminal','playback_stop','input_retry','main_transport')
FIELDS=('endpoint_segment','aggregation','turn_id','segments','earliest_deadline','source_boot','sequence','lineage_id','audio_s','pcm_sha256','captured_end',
        'capture_basis','started_at','ended_at','disposition','input_ref','task_id','attempt_id',
        'request_id','parent_input_ref','authority','operator_binding','final','stream_id','generation',
        'tts_frames','tts_complete','cancelled','output_sha256','tts_pcm_sha256','deadline',
        'producer_started_at','producer_elapsed_s','tts_first_pcm_s','error_kind',
        'submitted_frames','written_frames','consumed_frames','stop_known','input_finished','complete','verified',
        'model_timing','transport_diagnostic_status','verified_stopped','provenance','content_suppressed','stop_consumed_frames','device_stream_id')
AUTHORITY=('hub_boot_id','compute_boot_id','robot_boot_id','operator_epoch','microphone_epoch','interaction_epoch','speech_epoch')
FINAL=('kind','role','backend','model_id_sha256','request_sha256','output_sha256','utterance_sha256','memory_projection_sha256')


def scalar(value):
    if value is None or type(value) is bool:return value
    if type(value) is str:return value if len(value)<=256 else None
    if type(value) is int:return value if -(2**63)<=value<2**63 else None
    if type(value) is float:return value if math.isfinite(value) and abs(value)<=1e15 else None
    return None


def project(fields):
    result={}
    for key in FIELDS:
        if key not in fields:continue
        value=fields[key]
        if key in ('endpoint_segment','segments'):
            from .autonomous.audio_turn import segment
            try:
                if key=='endpoint_segment':result[key]=segment(value)
                else:
                    if type(value) is not list or not 1<=len(value)<=3:raise ValueError('Segment cap')
                    result[key]=[dict(segment({k:v for k,v in item.items() if k not in ('source_boot','sequence','lineage_id')}),
                        **{k:scalar(item[k]) for k in ('source_boot','sequence','lineage_id')}) for item in value]
            except (ValueError,KeyError,TypeError):result[key]=None
        elif key=='model_timing':result[key]=project_model_timing(value)
        elif key in ('authority','final'):
            keys=AUTHORITY if key=='authority' else FINAL
            result[key]={k:scalar(value[k]) for k in keys if k in value} if type(value) is dict else None
        elif key=='operator_binding':
            result[key]=[scalar(v) for v in value] if type(value) in (tuple,list) and len(value)<=3 else None
        else:result[key]=scalar(value)
    return result


def open_private(path,forbidden_roots):
    """Same anchored no-follow traversal as IntentLatch; no namespace adoption."""
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts or not path.name:raise ValueError('Absolute private trace path required')
    roots=[Path(root).resolve() for root in forbidden_roots]
    for candidate in (Path.cwd(),*Path(__file__).resolve().parents):
        if (candidate/'.git').exists():roots.append(candidate)
    if any(path.is_relative_to(root) for root in roots):raise ValueError('Private trace must be outside repository/config roots')
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
    directory=os.open('/',flags)
    try:
        for component in path.parent.parts[1:]:
            following=os.open(component,flags,dir_fd=directory);os.close(directory);directory=following
        info=os.fstat(directory)
        if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:raise ValueError('Owned mode0700 private trace directory required')
        fd=os.open(path.name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:
                raise ValueError('Fresh private regular trace file required')
            return fd
        except BaseException:os.close(fd);raise
    finally:os.close(directory)


class PrivateAudioTrace:
    def __init__(self,path,*,seconds,forbidden_roots=(),record_cap=512,byte_cap=1048576,queue_cap=32):
        if (type(seconds) not in (int,float) or not math.isfinite(seconds) or not 1<=seconds<=300
                or type(record_cap) is not int or not 4<=record_cap<=512
                or type(byte_cap) is not int or not 4096<=byte_cap<=1048576
                or type(queue_cap) is not int or not 1<=queue_cap<=32):raise ValueError('Bounded explicit private trace window/caps required')
        self.fd=open_private(path,forbidden_roots)
        self.seconds=seconds;self.record_cap=record_cap;self.byte_cap=byte_cap;self.queue_cap=queue_cap
        self.queue=deque();self.lock=threading.Lock();self.started=None;self.stop=None
        self.trace_id=uuid.uuid4().hex;self.hub_boot_id=None
        self.content=False;self.ending=False;self.closed=False;self.reason=None
        self.dropped=0;self.enqueued=0;self.bytes_enqueued=0;self.written=0;self.audio_refs={}
        self.worker=threading.Thread(target=self._write,daemon=True)
        try:self.worker.start()
        except BaseException:os.close(self.fd);raise
    def start(self,stop,*,hub_boot_id=None):
        if self.started is not None:return
        self.stop=stop;self.hub_boot_id=scalar(hub_boot_id);self.started=time.monotonic();self.content=True
        self.emit('session_begin')
    def disable(self,reason):
        self.content=False
        if self.reason is None:self.reason=reason if reason in ('stop','privacy','duration') else 'stop'
    def drop(self,reason):
        self.dropped=min(1000000000,self.dropped+1)
        if self.reason not in ('writer_failure','drain_timeout'):self.reason=reason
    def emit(self,kind,*,text=None,**fields):
        """Finite projection + immutable bytes; never wait for writer or disk."""
        try:
            if kind not in KINDS or self.ending or self.closed:return
            now=time.monotonic()
            if self.stop is not None and self.stop.is_set():self.disable('stop')
            if self.started is not None and now>=self.started+self.seconds:self.disable('duration')
            value=dict(version=1,kind=kind,at=now,clock_basis='hub_monotonic',trace_id=self.trace_id,
                hub_boot_id=self.hub_boot_id,**project(fields))
            if text is not None:
                if self.content and type(text) is str and len(text)>8192:self.drop('record_cap');return
                if self.content and type(text) is str and len(text)<=8192:
                    value.update(text=text,text_sha256=digest(text))
                else:value['content_suppressed']=True
            raw=(json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n').encode()
            if len(raw)>16384:self.drop('record_cap');return
            if not self.lock.acquire(False):self.drop('queue_busy');return
            try:
                # A concurrent STOP/privacy fence wins over a prepared content record.
                if 'text' in value and (not self.content or self.stop is not None and self.stop.is_set()):
                    self.drop('content_fenced');return
                if self.ending or self.closed:return
                if len(self.queue)>=self.queue_cap:self.drop('queue_full');return
                if self.enqueued>=self.record_cap-1 or self.bytes_enqueued+len(raw)>self.byte_cap-1024:
                    self.drop('total_cap');self.content=False;return
                if (kind=='input_admission' and fields.get('disposition')=='admitted'
                        or kind=='input_retry' and fields.get('disposition')=='linked'):
                    ref=fields.get('input_ref')
                    if type(ref) is str and len(ref)<=256:
                        if len(self.audio_refs)>=128:self.drop('lineage_cap');self.content=False;return
                        self.audio_refs[ref]=dict(lineage_id=scalar(fields.get('lineage_id')),authority=value.get('authority'))
                self.queue.append(raw);self.enqueued+=1;self.bytes_enqueued+=len(raw)
            finally:self.lock.release()
        except Exception:self.drop('projection_failure')
    def retry(self,parent_ref,new_ref,authority):
        try:
            parent=self.audio_refs.get(parent_ref)
            linked=parent is not None and parent['authority']==authority
            if not linked:self.drop('retry_lineage_unavailable')
            self.emit('input_retry',parent_input_ref=parent_ref,input_ref=new_ref,authority=authority,
                lineage_id=parent['lineage_id'] if linked else None,disposition='linked' if linked else 'metadata_only')
        except Exception:self.drop('projection_failure')
    def audio_link(self,ref):
        return type(ref) is str and ref in self.audio_refs
    def _write_bytes(self,raw):
        view=memoryview(raw)
        while view:
            count=os.write(self.fd,view)
            if count<=0:raise OSError('Trace write failed')
            view=view[count:]
    def _write(self):
        try:
            while True:
                with self.lock:
                    raw=self.queue.popleft() if self.queue else None
                    done=self.ending and raw is None
                if raw is not None:self._write_bytes(raw);self.written+=1;continue
                if done:break
                time.sleep(.005)
            footer=dict(version=1,kind='trace_end',at=time.monotonic(),clock_basis='hub_monotonic',**self.summary())
            self._write_bytes((json.dumps(footer,separators=(',',':'))+'\n').encode())
        except Exception:
            self.reason='writer_failure';self.content=False;self.dropped=min(1000000000,self.dropped+1)
        finally:
            self.closed=True
            with self.lock:self.queue.clear()
            os.close(self.fd)
    def summary(self):
        incomplete=self.dropped>0 or self.reason in ('writer_failure','drain_timeout','duration')
        return project_summary(dict(enabled=True,incomplete=incomplete,reason=self.reason,records_written=self.written,dropped=self.dropped))
    def close(self):
        if self.ending:return self.summary()
        if self.started is None:self.drop('startup_aborted')
        self.disable('stop');self.ending=True;self.worker.join(.5)
        if self.worker.is_alive():self.reason='drain_timeout'
        return self.summary()


def emit(owner,kind,*,text=None,**fields):
    trace=getattr(owner,'private_trace',None)
    if trace is not None:trace.emit(kind,text=text,**fields)


def main_call(trace,function,task,transport=None):
    fields=dict(task_id=task.task_id,attempt_id=task.attempt_id,input_ref=task.input_ref,authority=task.authority.wire())
    utterance=task.prompt.get('utterance') if type(task.prompt) is dict else task.prompt
    linked=trace.audio_link(task.input_ref)
    started=time.monotonic();trace.emit('main_request',text=utterance if linked else None,
        disposition='audio_linked' if linked else 'metadata_only',started_at=started,**fields)
    observed=False
    def on_transport(receipt,disposition,status):
        nonlocal observed
        if observed:return
        observed=True
        timing=project_model_timing(receipt,request_id=task.attempt_id,gateway_boot_id=task.authority.compute_boot_id)
        trace.emit('main_transport',disposition=disposition if disposition in ('execution_unknown','observed_error_receipt','transport_failure') else 'transport_failure',
            transport_diagnostic_status=status if status in ('verified_receipt','partial_diagnostic','no_response','missing_diagnostic','malformed_diagnostic','identity_mismatch') else 'malformed_diagnostic',
            model_timing=timing,**fields)
    try:
        result=transport(task,on_transport) if transport is not None else function(task)
    except BaseException as exc:
        timing=project_model_timing(getattr(exc,'model_timing',None),request_id=task.attempt_id,gateway_boot_id=task.authority.compute_boot_id)
        trace.emit('main_result',disposition='transport_error',started_at=started,ended_at=time.monotonic(),model_timing=timing,**fields);raise
    value=result if type(result) is dict else {}
    trace.emit('main_result',text=value.get('output') if linked else None,final=value.get('completion_provenance'),
        disposition='unchecked',started_at=started,ended_at=time.monotonic(),
        model_timing=project_model_timing(value.get('model_timing'),request_id=task.attempt_id,gateway_boot_id=task.authority.compute_boot_id),**fields)
    return result


def project_summary(value):
    """Standalone public metadata; safe to embed in the installed-host probe."""
    if type(value) is not dict or value.get('enabled') is not True:return None
    known=('stop','privacy','duration','queue_busy','queue_full','record_cap','total_cap',
           'content_fenced','projection_failure','lineage_cap','writer_failure','drain_timeout','occupied_at_close','startup_aborted','retry_lineage_unavailable')
    def count(item):return min(1000000000,max(0,item)) if type(item) is int else None
    return dict(enabled=True,incomplete=value.get('incomplete') is True,
        reason=value.get('reason') if type(value.get('reason')) is str and value.get('reason') in known else None,
        records_written=count(value.get('records_written')),dropped=count(value.get('dropped')))
