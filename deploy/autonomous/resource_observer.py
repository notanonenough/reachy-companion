"""Bounded supervisor-side process observer. Default CLI is probe-free dry-run."""
import argparse
from contextlib import contextmanager
import http.client
import ctypes
import errno
import json
import math
import os
from pathlib import Path
import signal
import select
import threading
import sys
import time

# Same pure parser consumed by the offline report; no runtime owner imports.
from production_baseline import parse_proc_stat
from observer_status import project_status

ROLES=('hub_owner','robot_audio','mac_fast','mac_main','mac_stt','mac_tts','mac_embeddings','mac_provider')
BASES=('linux_start_ticks','mach_start_abstime')
STATES=('ok','missing','identity_changed','timeout','unsupported','error')
ERRORS=('none','not_found','identity','deadline','platform','permission','io','invalid')
MAX_TICKS=180
MAX_TARGETS=8
MAX_BYTES=2*1024*1024
MAX_RECORDS=MAX_TICKS*(MAX_TARGETS+1)+1


class RusageV0(ctypes.Structure):
    _fields_=[('uuid',ctypes.c_uint8*16)]+[(name,ctypes.c_uint64) for name in (
        'user','system','idle','interrupt','pageins','wired','resident','footprint','start','exit')]


class Timebase(ctypes.Structure):
    _fields_=[('numer',ctypes.c_uint32),('denom',ctypes.c_uint32)]


class ProcessReader:
    """No discovery: reads only a PID supplied by the owning supervisor receipt."""
    def __init__(self,platform=None,procroot=Path('/proc')):
        self.platform=platform or sys.platform;self.procroot=Path(procroot)
        if self.platform=='linux':
            self.host_boot=(self.procroot/'sys/kernel/random/boot_id').read_text().strip()
            self.user_hz=os.sysconf('SC_CLK_TCK');self.page_size=os.sysconf('SC_PAGE_SIZE')
            self.basis='linux_start_ticks'
        elif self.platform=='darwin':
            self.lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
            self.lib.proc_pid_rusage.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_void_p]
            self.lib.proc_pid_rusage.restype=ctypes.c_int
            self.lib.mach_timebase_info.argtypes=[ctypes.POINTER(Timebase)]
            self.lib.mach_timebase_info.restype=ctypes.c_int
            tb=Timebase()
            if self.lib.mach_timebase_info(ctypes.byref(tb)) or not tb.numer or not tb.denom:raise OSError('timebase')
            self.numer,self.denom=tb.numer,tb.denom
            self.lib.sysctlbyname.argtypes=[ctypes.c_char_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.c_void_p,ctypes.c_size_t]
            self.lib.sysctlbyname.restype=ctypes.c_int
            buf=ctypes.create_string_buffer(128);size=ctypes.c_size_t(len(buf))
            if self.lib.sysctlbyname(b'kern.bootsessionuuid',buf,ctypes.byref(size),None,0):raise OSError('boot')
            self.host_boot=buf.value.decode('ascii');self.basis='mach_start_abstime'
        else:raise NotImplementedError('platform')
        if not self.host_boot or len(self.host_boot)>128:raise ValueError('boot')

    def read(self,pid):
        if type(pid) is not int or not 1<=pid<2**31:raise ValueError('pid')
        if self.platform=='linux':
            with (self.procroot/str(pid)/'stat').open() as f:raw=f.read(16385)
            if len(raw)>16384:raise ValueError('stat_cap')
            ticks=int(raw.rsplit(')',1)[1].split()[19])
            value=parse_proc_stat(raw,pid=pid,start_ticks=ticks,host_boot=self.host_boot,
                at=time.monotonic(),user_hz=self.user_hz,page_size=self.page_size)
            return dict(process_start_identity=str(ticks),cpu_s=value['cpu_s'],rss_bytes=value['rss_bytes'],
                units=dict(cpu_raw='linux_ticks',cpu_hz=self.user_hz,rss_raw='pages',page_size=self.page_size))
        value=RusageV0()
        if self.lib.proc_pid_rusage(pid,0,ctypes.byref(value)):
            code=ctypes.get_errno();raise OSError(code,'proc_pid_rusage')
        if not value.start or value.exit:raise ProcessLookupError('exited')
        return dict(process_start_identity=str(value.start),cpu_s=(value.user+value.system)*self.numer/self.denom/1e9,
            rss_bytes=value.resident,units=dict(cpu_raw='mach_absolute_ticks',timebase_numer=self.numer,
                timebase_denom=self.denom,rss_raw='bytes'))


def target(value):
    if type(value) is not dict or set(value)!={'role','pid','process_start_identity','identity_basis'}:raise ValueError('target')
    if value['role'] not in ROLES or type(value['pid']) is not int or not 1<=value['pid']<2**31:raise ValueError('target')
    if value['identity_basis'] not in BASES or type(value['process_start_identity']) is not str or not value['process_start_identity'].isdigit() or len(value['process_start_identity'])>32:raise ValueError('identity')
    return dict(value)


def bind_receipt(reader,*,role,pid):
    """Called once for a known owner/unit/provider PID, never from a PID scan."""
    value=reader.read(pid)
    return target(dict(role=role,pid=pid,identity_basis=reader.basis,process_start_identity=value['process_start_identity']))


def error_state(exc):
    if isinstance(exc,TimeoutError):return 'timeout','deadline'
    if isinstance(exc,(FileNotFoundError,ProcessLookupError)) or isinstance(exc,OSError) and exc.errno in (errno.ESRCH,errno.ENOENT):return 'missing','not_found'
    if isinstance(exc,PermissionError):return 'error','permission'
    if isinstance(exc,NotImplementedError):return 'unsupported','platform'
    return 'error','invalid' if isinstance(exc,(ValueError,IndexError)) else 'io'


@contextmanager
def probe_deadline(seconds=.25):
    # Standalone observer main thread only: never installed in the runtime owner.
    previous=signal.getsignal(signal.SIGALRM)
    if signal.getitimer(signal.ITIMER_REAL)!=(0.0,0.0):raise ValueError('existing_timer')
    def expired(*_):raise TimeoutError('probe')
    signal.signal(signal.SIGALRM,expired);signal.setitimer(signal.ITIMER_REAL,seconds)
    try:yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)


class StatusPoll:
    """Only GET of the fixed local production status endpoint; no action method."""
    def __init__(self,receipt,*,provenance):
        if type(receipt) is not dict or set(receipt)!={'candidate','binding','token_file'}:raise ValueError('status_receipt')
        self.candidate=receipt['candidate'];self.binding=receipt['binding'];self.provenance=provenance
        project_status(None,candidate=self.candidate,binding=self.binding,begin=0,end=0,outcome='error')
        with Path(receipt['token_file']).open() as f:self.token=f.read(4097).strip()
        if not self.token or len(self.token)>4096 or any(c in self.token for c in '\r\n'):raise ValueError('token')
    def __call__(self):
        began=time.monotonic();conn=None;value=None;outcome='response'
        try:
            with probe_deadline():
                if not self.provenance():return project_status(None,candidate=self.candidate,binding=self.binding,begin=began,end=time.monotonic(),outcome='identity_changed')
                conn=http.client.HTTPConnection('127.0.0.1',8791,timeout=.2)
                conn.request('GET','/status',headers={'Authorization':'Bearer '+self.token})
                response=conn.getresponse()
                if response.status!=200:raise OSError('status')
                raw=response.read(262145)
                if len(raw)>262144:outcome='oversize'
                else:
                    value=json.loads(raw)
                    if not self.provenance():outcome='identity_changed'
        except TimeoutError:outcome='timeout'
        except Exception:outcome='error'
        finally:
            if conn is not None:
                try:conn.close()
                except Exception:pass
        return project_status(value,candidate=self.candidate,binding=self.binding,begin=began,end=time.monotonic(),outcome=outcome)


def sample(reader,item,node,*,clock=time.monotonic):
    begin=clock();row=dict(version=1,kind='resource',node=node,host_boot=reader.host_boot,
        clock_basis='host_monotonic',probe_begin=begin,**item,cpu_s=None,rss_bytes=None,
        sample_state='ok',error_kind='none')
    try:
        with probe_deadline():
            a=reader.read(item['pid']);b=reader.read(item['pid'])
        if reader.basis!=item['identity_basis'] or a['process_start_identity']!=item['process_start_identity'] or b['process_start_identity']!=item['process_start_identity']:
            row.update(sample_state='identity_changed',error_kind='identity')
        else:row.update(cpu_s=b['cpu_s'],rss_bytes=b['rss_bytes'],units=b['units'])
    except Exception as exc:
        state,error=error_state(exc);row.update(sample_state=state,error_kind=error)
    row['probe_end']=clock();row['at']=row['probe_end'];return row


class Writer:
    """Finite nonthrowing evidence IO; failure is not allowed to inhibit owner cleanup."""
    def __init__(self,stream,byte_cap=MAX_BYTES,record_cap=MAX_RECORDS):
        self.stream=stream;self.byte_cap=byte_cap;self.record_cap=record_cap
        self.bytes=0;self.records=0;self.incomplete=False;self.reason='complete'
    def write(self,row):
        if self.incomplete:return False
        try:
            data=(json.dumps(row,allow_nan=False,separators=(',',':'))+'\n').encode()
            if len(data)>65536 or self.records>=self.record_cap or self.bytes+len(data)>self.byte_cap:
                self.incomplete=True;self.reason='cap';return False
            self.stream.write(data);self.stream.flush();self.bytes+=len(data);self.records+=1;return True
        except Exception:
            self.incomplete=True;self.reason='io';return False


class FinishControl:
    """One observer-only command. EOF/loss never means successful finish."""
    def __init__(self,stream,clock=time.monotonic):
        self.stream=stream;self.clock=clock;self.event=threading.Event();self.done=threading.Event()
        self.reason=None;self.at=None;self.finish_accepted=False;self.worker=None
    def accept(self,reason):
        if self.event.is_set():return
        self.reason=reason;self.at=self.clock();self.finish_accepted=reason=='finish';self.event.set()
    def start(self):
        def read():
            data=b''
            try:
                while not self.done.is_set() and not self.event.is_set():
                    ready,_,_=select.select([self.stream],[],[],.1)
                    if not ready:continue
                    chunk=os.read(self.stream.fileno(),64-len(data))
                    if not chunk:self.accept('eof');return
                    data+=chunk
                    if b'\n' in data:
                        self.accept('finish' if data==b'finish\n' else 'invalid');return
                    if len(data)>=64:self.accept('invalid');return
            except Exception:self.accept('io')
        self.worker=threading.Thread(target=read,daemon=True);self.worker.start()
    def close(self):
        self.done.set()
        if self.worker is not None:self.worker.join(.2)
    def ended_during(self,end):return self.event.is_set() and self.at is not None and end>=self.at


def run(reader,targets,node,writer,*,ticks=180,clock=time.monotonic,sleep=time.sleep,stopped=lambda:False,status_poll=None,control=None):
    if node not in ('mac','hub','robot') or type(ticks) is not int or not 1<=ticks<=MAX_TICKS:raise ValueError('scope')
    targets=[target(x) for x in targets]
    if not 1<=len(targets)<=MAX_TARGETS or len({(x['role'],x['pid']) for x in targets})!=len(targets):raise ValueError('targets')
    if any((node=='hub' and x['role']!='hub_owner') or (node=='robot' and x['role']!='robot_audio') or (node=='mac' and not x['role'].startswith('mac_')) for x in targets):raise ValueError('node_role')
    began=clock();deadline=began+ticks;count=0;failures=0;dropped_inflight=0;sample_count=0
    while count<ticks and clock()<deadline and not stopped() and not writer.incomplete:
        tick=clock()
        for item in targets:
            if stopped() or clock()>=deadline:break
            row=sample(reader,item,node,clock=clock)
            if control is not None and control.ended_during(row['probe_end']):dropped_inflight+=1;break
            failures+=row['sample_state']!='ok';sample_count+=1
            if not writer.write(row):break
        if status_poll is not None and not writer.incomplete and clock()<deadline and not stopped():
            try:
                projected=status_poll();projected.update(node=node,host_boot=reader.host_boot)
                if control is not None and control.ended_during(projected['hub_request_end']):dropped_inflight+=1
                else:failures+=projected['poll_outcome']!='response';writer.write(projected)
            except Exception:
                failures+=1;writer.incomplete=True;writer.reason='status_error'
        count+=1
        # No catch-up: an overrun schedules the next tick after this one completes.
        next_at=max(tick+1,clock()+(.001 if clock()>tick+1 else 0))
        if next_at<deadline and not stopped():
            delay=max(0,next_at-clock())
            if control is not None:control.event.wait(delay)
            else:sleep(delay)
    summary=dict(version=1,kind='observer_end',node=node,ticks=count,records=writer.records,
        incomplete=writer.incomplete or bool(failures),reason=writer.reason if writer.incomplete else 'samples' if failures else 'stopped' if stopped() else 'complete',sample_failures=failures,sample_count=sample_count,dropped_inflight=dropped_inflight)
    if control is not None:
        summary.update(finish_accepted=control.finish_accepted,window_end=control.at,control_reason=control.reason)
        if not control.finish_accepted or not sample_count:summary.update(incomplete=True,reason='control')
        elif not summary['incomplete']:summary['reason']='stopped'
    if not writer.write(summary):summary.update(incomplete=True,reason=writer.reason)
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true')
    p.add_argument('--node',choices=('hub','robot','mac'),required=True);p.add_argument('--targets',type=Path)
    p.add_argument('--ticks',type=int,default=180);p.add_argument('--status-receipt',type=Path);a=p.parse_args(argv)
    if not 1<=a.ticks<=180:p.error('ticks must be 1..180')
    if not a.execute:print(json.dumps(dict(mode='dry_run',node=a.node,max_ticks=a.ticks,max_targets=8,probes=False)));return 0
    if a.targets is None:p.error('targets receipt required')
    try:
        with a.targets.open('rb') as f:raw=f.read(16385)
        if len(raw)>16384:raise ValueError('manifest_cap')
        manifest=json.loads(raw);reader=ProcessReader()
        if manifest['host_boot']!=reader.host_boot:raise ValueError('host_boot')
        status_poll=None
        if a.status_receipt:
            if a.node!='hub':raise ValueError('status_node')
            with a.status_receipt.open('rb') as f:raw=f.read(16385)
            if len(raw)>16384:raise ValueError('status_cap')
            from observer_listener import listener_owned
            owners=[x for x in manifest['targets'] if x['role']=='hub_owner']
            if len(owners)!=1:raise ValueError('owner')
            owner=owners[0]
            status_poll=StatusPoll(json.loads(raw),provenance=lambda:listener_owned(owner['pid'],owner['process_start_identity']))
        stopped=[False]
        def stop(*_):stopped[0]=True
        for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,stop)
        result=run(reader,manifest['targets'],a.node,Writer(sys.stdout.buffer),ticks=a.ticks,stopped=lambda:stopped[0],status_poll=status_poll)
        return 2 if result['incomplete'] else 0
    except Exception:
        try:print(json.dumps(dict(kind='observer_end',incomplete=True,reason='invalid_input')))
        except Exception:pass
        return 2


if __name__=='__main__':raise SystemExit(main())
