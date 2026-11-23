"""Normal joined companion: finite by default, or an explicit existing-owner lease.

No device startup, microphone acquisition, automatic reconnect or practice script.
Finite mode retains the 180s lifetime and 32-stream budget.
"""
import argparse
import json
import math
from http.client import HTTPException
from urllib.error import HTTPError
import os
from pathlib import Path
import signal
from .signal_stop import SignalStop
import threading
import time
from .audio_adapter import AudioAdapter,HttpSTT
from .audio_peer import AudioPolling,PeerClient,PersistentPeer,PeerLease,PeerStartup,RemotePCM,lease_authority
from .audio_session_control import create_server
from .config import load
from .lease_datagram import DatagramRenewal
from .motion_adapter import MotionAdapter
from .network_observation import NetworkObservation
from .playback import Playback
from .runtime import Job,RemoteGateway,Scheduler
from .speech_adapter import SpeechAdapter,HttpTTS
from .voice_chain import check_context_task,check_context_view,context_binding
from ..lease_diagnostics import project_first_lease_invalid,ReducerTrace


class SessionFailure(RuntimeError):
    """Stable diagnostic code, without dialogue or remote exception text."""
    def __init__(self,code):
        self.code=code
        super().__init__(code)


def first_lease_invalid_record(peer,current,status_at,authority,now,started,phase,lease):
    """Project only the captured gate inputs, before close. Never inhibit close."""
    try:
        present=peer is not None;has_current=current is not None;seen=status_at is not None
        predicates=dict(peer_receipt_present=present,
            operator_ready=peer.get('operator_ready') is True if present else None,
            status_seen=seen,status_fresh=now-status_at<.3 if seen else None,
            current_present=has_current,current_fresh=now<current['valid_until'] if has_current else None,
            microphone_enabled=current['microphone_enabled'] is True if has_current else None,
            not_quiet=current['quiet'] is False if has_current else None,
            not_privacy=current['privacy_all'] is False if has_current else None,
            binding_matches=tuple(current['binding'])==(authority['agent_boot_id'],authority['microphone_epoch'],authority['policy_epoch']) if has_current else None)
        with lease.lock:
            timing=lease._timing(now)
            timing.update(progress_timeout_ms=lease.progress_timeout_s*1000,max_call_ms=lease.max_call_ms)
            closed=lease.closed;prior=lease.withdrawal_reason
        value=dict(cause='invalid_complete_authority',predicates=predicates,elapsed_ms=(now-started)*1000,
            startup_phase=phase,peer_status_age_ms=(now-status_at)*1000 if seen else None,
            operator_valid_remaining_ms=(current['valid_until']-now)*1000 if has_current else None,
            lease_already_withdrawn=closed,prior_withdrawal_reason=prior,lease_timing=timing)
        return json.dumps(project_first_lease_invalid(value),allow_nan=False)
    except Exception:
        # Unknown diagnostic data is not a reason to change the withdrawal path.
        return json.dumps(project_first_lease_invalid(dict(cause='invalid_complete_authority',diagnostic_unavailable=True)))


def read_speech_operator(hub):
    # The operator receipt lasts only 300 ms. A general-purpose 10 s HTTP
    # wait occupies the sole refresh slot long after that receipt expires.
    # Fail this read promptly; the next scheduled read obtains new authority.
    return hub.agent('/operator', timeout=.1, max_bytes=8192)


class ContextGateway(RemoteGateway):
    def __init__(self,config,binding):
        self.memory_binding=binding
        super().__init__(config)
    def fast(self,request_id,view):
        if self.memory_binding is not None:check_context_view(view,self.memory_binding)
        return super().fast(request_id,view)
    def main(self,task,*,on_transport=None):
        if self.memory_binding is not None:check_context_task(task,self.memory_binding)
        return super().main(task,on_transport=on_transport)


def occupied(scheduler,poller,lease,peer_job=None,health_job=None,stop_job=None,retire_job=None,media_close_job=None):
    jobs={name:getattr(scheduler,name+'_job') for name in
          ('fast','main','actor','motion','context','context_revoke','context_terminal')}
    jobs.update(peer_status=peer_job,health=health_job,peer_stop=stop_job,retirement=retire_job,media_close=media_close_job)
    result={name:bool(job and not job.future.done()) for name,job in jobs.items()}
    result['context_terminal_revoke']=result.pop('context_terminal')
    result.update(audio=scheduler.audio_adapter.status()['execution_busy'],
        speech=scheduler.speech_adapter.status()['execution_busy'],
        peer_poll=poller.status()['execution_busy'],lease=lease.status()['execution_busy'])
    if scheduler.services:result['background']=bool(scheduler.services.busy())
    if scheduler.motion_adapter:result['motion']=result['motion'] or scheduler.motion_adapter.status()['execution_busy']
    return result


def session_context(config,*,allow_camera=False,readback=None,readback_sha256=None):
    """Select the existing camera provider or the isolated memory whitelist.

    Camera context uses the gateway's bounded observer, never a device reader
    on the session host. The memory-only readback contract remains separate.
    """
    context=config.get('context',{})
    enabled=context.get('enabled',False)
    if allow_camera:
        if (not enabled or context.get('mode','camera_memory')!='camera_memory'
                or not context.get('video_url') or readback is not None or readback_sha256 is not None):
            raise ValueError('Camera context requires an explicit producer and no memory-only readback')
        return None
    if enabled or readback is not None or readback_sha256 is not None:
        from .voice_memory_fixture import read_json
        if (not enabled or context.get('mode')!='memory_only' or readback is None
                or not readback_sha256):raise ValueError('Reviewed isolated memory-only readback or explicit camera context required')
        artifact,sha=read_json(readback,65536)
        if sha!=readback_sha256:raise ValueError('Readback changed')
        return context_binding(artifact)
    return None


def run_session(scheduler,poller,lease,client,stop_client,source,stop,duration,publish,*,lifetime='finite',status_transport=None):
    """Reducer-owned loop. Each remote operation keeps one real occupied slot."""
    if lifetime not in ('finite','lease') or type(lifetime) is not str:raise ValueError('Explicit normal lifetime')
    if lifetime=='finite' and (type(duration) not in (int,float) or not math.isfinite(duration) or not 1<=duration<=180):
        raise ValueError('Normal session must fit the existing finite device window')
    if lifetime=='lease' and (duration is not None or lease.source_boot!=source):raise ValueError('Explicit owned lease lifetime without finite duration')
    trace=getattr(lease,'reducer_trace',None)
    if trace is None:trace=ReducerTrace();lease.reducer_trace=trace
    trace.bind_current()
    private_trace=getattr(scheduler,'private_trace',None)
    if private_trace is not None:
        private_trace.start(stop,hub_boot_id=scheduler.state.authority.hub_boot_id)
        for resource in (scheduler.state,scheduler.audio_adapter,scheduler.speech_adapter,scheduler.speech_adapter.playback):
            resource.private_trace=private_trace
    startup=PeerStartup(source);peer_job=health_job=stop_job=None
    retire_job=None;media_close_job=None;retiring_terminal=None;next_retire=0;peer_receipt=None
    next_peer=next_health=next_publish=0;started=time.monotonic();last_health=last_operator=started
    reason='duration';failure_code=None;errors=[];ready_seen=False
    first_lease_invalid=None
    def invalid_view():return json.loads(first_lease_invalid) if first_lease_invalid is not None else None
    health_errors=0;network=NetworkObservation()
    health_timeout=scheduler.config.get('production',{}).get('compute_health_timeout_s',3) if scheduler.production else .5
    report=dict(mode='normal_joined_companion',continuous=lifetime=='lease',continuous_acceptance=False,lifetime=lifetime,accepted=False,
        device_lifetime_cap_s=180 if lifetime=='finite' else None,device_stream_cap=32 if lifetime=='finite' else 1,raw_audio_retained=False,
        transcripts_retained=private_trace is not None,speaker_identity='unknown',automatic_microphone_activation=False,
        automatic_reconnect=False,source_boot=source,hub_boot_id=scheduler.state.authority.hub_boot_id,
        context_enabled=scheduler.config.get('context',{}).get('enabled',False))
    report['lease_transport']='udp' if lease.datagram is not None else 'tcp'
    motion_identity=None
    if scheduler.motion_adapter:
        current=scheduler.motion_adapter.cached
        if current:motion_identity={key:current['binding'][key] for key in ('agent_boot_id','actor_boot_id','session_id')}
    try:
        while not stop.is_set() and (lifetime=='lease' or time.monotonic()-started<duration):
            trace.enter('startup_control')
            now=time.monotonic()
            if peer_job and peer_job.future.done():
                peer_ok=False
                try:
                    peer_receipt=peer_job.future.result()
                    if lifetime=='lease' and (peer_receipt.get('lifetime')!='lease'
                            or lease_authority(peer_receipt.get('lease_binding'))!=lease.authority):
                        raise RuntimeError('Current peer lease authority changed')
                    startup.observe(peer_receipt,lease.last_accepted is not None)
                    peer_ok=True
                except Exception as exc:peer_receipt=None;startup.failure(type(exc).__name__)
                network.observe('robot',peer_job.started,now,peer_ok)
                if scheduler.production:scheduler.ingest(network.event(now),now)
                peer_job=None
            if startup.advance()=='WITHDRAWN' and not scheduler.production:reason=startup.reason;break
            if not peer_job and now>=next_peer:
                peer_job=Job((status_transport or client).call,'/status');next_peer=now+.1
            if health_job and health_job.future.done():
                try:
                    health=health_job.future.result()
                except (OSError,HTTPException) as exc:
                    if isinstance(exc,HTTPError) and exc.code in (401,403):raise SessionFailure('compute_auth_rejected')
                    health_errors+=1
                    network.observe('compute',health_job.started,now,False)
                else:
                    if health.get('compute_boot_id')!=scheduler.state.authority.compute_boot_id or health.get('quarantined'):
                        raise SessionFailure('compute_owner_changed_or_quarantined')
                    last_health=now
                    network.observe('compute',health_job.started,now,True)
                if scheduler.production:scheduler.ingest(network.event(now),now)
                health_job=None
            if now-last_health>=health_timeout:raise SessionFailure('compute_health_expired')
            if lifetime=='lease' and lease.status()['withdrawn'] and not scheduler.production:raise RuntimeError('Lease withdrawal is latched')
            if not health_job and now>=next_health:
                health_job=Job(scheduler.gateway.call,'/health');next_health=now+.2
            trace.enter('speech_advance')
            scheduler.speech_adapter.advance(scheduler.state.authority)
            operator=scheduler.speech_adapter.operator_view()
            if operator is not None:
                last_operator=now
                if motion_identity is not None and operator['binding'][0]!=motion_identity['agent_boot_id']:
                    raise RuntimeError('Speaker and motor belong to different physical operator boots')
            if now-last_operator>=.5:raise SessionFailure('operator_receipt_expired')
            if stop.is_set():reason='controller_stop';break
            if scheduler.production and startup.phase!='ACTIVE':
                trace.enter('scheduler_advance');scheduler.advance()
            if startup.phase=='ACTIVE':
                trace.enter('playback_control')
                if lifetime=='lease':
                    backend=scheduler.speech_adapter.playback.backend
                    if (scheduler.speech_adapter.playback.status()['quarantined']
                            or scheduler.speech_adapter.playback.status()['terminal_unknown'] or backend.withdrawn):
                        raise SessionFailure('audio_completion_unknown')
                    if retire_job and retire_job.future.done():
                        if retire_job.future.result() and not scheduler.speech_adapter.playback.retire_terminal(
                                retiring_terminal['stream_id'],retiring_terminal['generation']):
                            raise RuntimeError('Local terminal references changed')
                        retire_job=None;retiring_terminal=None;next_retire=now+.02
                    speech_status=scheduler.speech_adapter.status()
                    terminal=scheduler.speech_adapter.playback.terminal_receipt()
                    if (terminal is not None and not retire_job and now>=next_retire
                            and not speech_status['tts_execution_busy'] and not speech_status['cancellation_execution_busy']):
                        retiring_terminal=terminal;retire_job=Job(backend.retire,terminal)
                # No synthetic question, echo-reference admission or speaker claim.
                trace.enter('scheduler_advance');scheduler.advance()
                trace.enter('peer_poll')
                poller.advance(scheduler.state.authority,scheduler.speech_adapter.operator_view())
                ready_seen=ready_seen or scheduler.audio_adapter.allowed
                if scheduler.motion_adapter:
                    current=scheduler.motion_adapter.cached
                    if current and motion_identity!={key:current['binding'][key] for key in motion_identity}:
                        raise RuntimeError('Motor owner changed; explicit new admission required')
                if (lifetime=='finite' and scheduler.speech_adapter.playback.backend.reservation_attempts>=31
                        and not scheduler.speech_adapter.status()['execution_busy']):
                    reason='finite_stream_budget';break
            if stop.is_set():reason='controller_stop';break
            trace.enter('lease_gate')
            if lifetime=='finite':lease.tick()
            else:
                with scheduler.speech_adapter.lock:
                    current=scheduler.speech_adapter.operator_receipt
                    current=dict(current) if current else None
                captured_peer=dict(peer_receipt) if peer_receipt is not None else None
                status_at=startup.last_status
                captured_authority=lease.authority
                valid=(captured_peer is not None and captured_peer.get('operator_ready') is True
                    and status_at is not None and now-status_at<.3
                    and current is not None and now<current['valid_until'] and current['microphone_enabled'] is True
                    and current['quiet'] is False and current['privacy_all'] is False
                    and tuple(current['binding'])==(captured_authority['agent_boot_id'],captured_authority['microphone_epoch'],captured_authority['policy_epoch']))
                if valid:lease.tick(lease.authority)
                elif lease.armed:
                    if first_lease_invalid is None:
                        first_lease_invalid=first_lease_invalid_record(captured_peer,current,status_at,captured_authority,
                            now,started,startup.phase,lease)
                    lease.close()
                    if not scheduler.production:raise RuntimeError('Fresh complete lease authority required')
            if now>=next_publish:
                trace.enter('status_publish')
                next_publish=now+.05
                publish(dict(stage=startup.phase,elapsed_s=now-started,counts=dict(scheduler.state.counts),
                    first_lease_invalid=invalid_view(),first_reducer_expiry=trace.view(),
                    audio=scheduler.audio_adapter.status(),peer_poll=poller.status(),lease=lease.status(),
                    motion=dict(allowed=scheduler.state.motion_allowed,receipts=list(scheduler.motion_adapter.receipts)[-4:],
                        **scheduler.motion_adapter.status()) if scheduler.motion_adapter else None,
                    speech=scheduler.speech_adapter.status(),
                    runtime=dict(latency_s=dict(scheduler.latencies),compute_health_age_s=round(now-last_health,4),
                        compute_health_errors=health_errors,compute_health_timeout_s=health_timeout,
                        network=network.status(now),pressure=scheduler.pressure_status(now)),
                    cycle_phase=scheduler.state.overload,background=scheduler.services.status() if scheduler.services else None,
                    listening_ready=startup.phase=='ACTIVE' and scheduler.audio_adapter.allowed
                        and scheduler.speech_adapter.operator_view() is not None,
                    peer=startup.status(),execution_busy=occupied(scheduler,poller,lease,peer_job,health_job,retire_job=retire_job)))
            trace.enter('loop_wait')
            stop.wait(.005)
        if stop.is_set():reason='controller_stop'
    except BaseException as exc:
        import logging
        logging.getLogger(__name__).exception('Production session failed')
        reason='runtime_error';failure_code=getattr(exc,'code',type(exc).__name__);errors.append(type(exc).__name__)
    finally:
        trace.enter('cleanup')
        if private_trace is not None:private_trace.disable('stop')
        stop.set();startup.close()
        # Send explicit withdrawal before local cleanup can outlast the device's
        # short controller lease. Keep its real transport slot until terminal.
        stop_job=Job(lambda:stop_client.call('/stop',source_boot=source))
        # Attempt every owner withdrawal, retaining all actual job references.
        actions=[lease.close,poller.close,scheduler.close]
        if scheduler.motion_adapter:actions.append(scheduler.motion_adapter.close)
        for action in actions:
            try:action()
            except BaseException as exc:errors.append(type(exc).__name__)
        def close_media():
            speech=scheduler.speech_adapter;playback=speech.playback
            while (speech.status()['tts_execution_busy'] or speech.status()['cancellation_execution_busy']
                    or playback.status()['execution_busy']):time.sleep(.005)
            playback.backend.close_transport()
            if status_transport:
                try:
                    if peer_job:peer_job.future.result()
                finally:status_transport.close()
            return True
        media_close_job=Job(close_media)
        deadline=time.monotonic()+1
        while time.monotonic()<deadline and any(occupied(scheduler,poller,lease,peer_job,health_job,stop_job,retire_job,media_close_job).values()):
            time.sleep(.005)
        peer_stop=None
        if stop_job.future.done():
            try:peer_stop=stop_job.future.result()
            except Exception as exc:errors.append(type(exc).__name__)
        report.update(reason=reason,failure_code=failure_code,errors=errors,elapsed_s=time.monotonic()-started,
            first_lease_invalid=invalid_view(),first_reducer_expiry=trace.view(),
            background=scheduler.services.status() if scheduler.services else None,
            listening_ready_seen=ready_seen,
            counts=dict(scheduler.state.counts),peer_stop=peer_stop,
            peer_stop_execution_busy=not stop_job.future.done(),
            execution_busy=occupied(scheduler,poller,lease,peer_job,health_job,stop_job,retire_job,media_close_job),
            speech_stop_known=scheduler.speech_adapter.status()['stop_known'])
        # Bounded metadata for silent-tick acceptance; no dialogue, memory or
        # model reasoning is copied into the session report.
        report['decisions']=[dict(request_id=row['request_id'],activity=row['activity'],at=row['at'])
            for row in scheduler.state.ledger if row['kind']=='decision_accepted']
        report.update(speech_after=scheduler.speech_adapter.status(),audio=scheduler.audio_adapter.status(),
            peer_poll=poller.status(),lease=lease.status(),
            reservation_attempts=scheduler.speech_adapter.playback.backend.reservation_attempts)
        if scheduler.motion_adapter:report['motion_receipts']=list(scheduler.motion_adapter.receipts)
        if media_close_job.future.done():
            try:media_close_job.future.result()
            except BaseException as exc:errors.append(type(exc).__name__)
        if scheduler.context_terminal_job and scheduler.context_terminal_job.future.done():
            try:report['context_terminal_revoke']=scheduler.context_terminal_job.future.result()
            except Exception:report['context_terminal_revoke_unknown']=True
        context_ok=not report['context_enabled'] or (
            report.get('context_terminal_revoke',{}).get('output',{}).get('terminal') is True
            and report.get('context_terminal_revoke',{}).get('output',{}).get('revoked') is True)
        motion_ok=not scheduler.motion_adapter or scheduler.motion_adapter.status()['stop_known'] is True
        report['motion_after']=scheduler.motion_adapter.status() if scheduler.motion_adapter else None
        report['cleanup_issues']=['busy:'+name for name,busy in report['execution_busy'].items() if busy]
        if not motion_ok:report['cleanup_issues'].append('motion_stop_unknown')
        if not context_ok:report['cleanup_issues'].append('context_revoke_unknown')
        if not report['speech_stop_known']:report['cleanup_issues'].append('speech_stop_unknown')
        if not isinstance(peer_stop,dict) or peer_stop.get('stop_known') is not True:
            report['cleanup_issues'].append('peer_stop_unknown')
        report['cleanup_verified']=(not errors and not any(report['execution_busy'].values()) and context_ok and motion_ok
            and report['speech_stop_known'] is True and isinstance(peer_stop,dict)
            and peer_stop.get('stop_known') is True and peer_stop.get('execution_busy') is False)
        report['accepted']=ready_seen and report['cleanup_verified'] and reason in ('duration','controller_stop','finite_stream_budget')
        publish(dict(stage='STOPPED',reason=reason,failure_code=failure_code,first_lease_invalid=invalid_view(),first_reducer_expiry=trace.view(),execution_busy=report['execution_busy'],cleanup_verified=report['cleanup_verified']))
        trace.unbind()
        if private_trace is not None:
            if any(report['execution_busy'].values()):private_trace.drop('occupied_at_close')
            report['private_audio_trace']=private_trace.close()
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('normal',),required=True)
    for name in ('config','companion-config','token-file','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--peer-url',required=True);parser.add_argument('--peer-stop-port',type=int,required=True)
    parser.add_argument('--controller',required=True);parser.add_argument('--source-boot',required=True)
    parser.add_argument('--lifetime',choices=('finite','lease'),default='finite')
    parser.add_argument('--duration',type=float);parser.add_argument('--status-port',type=int,default=8791)
    parser.add_argument('--lease-datagram-port',type=int);parser.add_argument('--trusted-private-lan',action='store_true')
    parser.add_argument('--lease-progress-s',type=float,default=.1)
    parser.add_argument('--allow-capture-output',action='store_true');parser.add_argument('--allow-bounded-motion',action='store_true')
    parser.add_argument('--allow-camera-context',action='store_true')
    parser.add_argument('--memory-readback',type=Path);parser.add_argument('--memory-readback-sha256')
    parser.add_argument('--private-audio-trace',type=Path)
    parser.add_argument('--private-audio-trace-seconds',type=float)
    args=parser.parse_args()
    if args.lifetime=='finite' and args.duration is None:args.duration=60
    if (not args.allow_capture_output or args.output.exists()
            or args.lifetime=='finite' and (not math.isfinite(args.duration) or not 1<=args.duration<=180)
            or args.lifetime=='lease' and args.duration is not None):
        raise ValueError('Fresh explicit finite normal companion opt-in required')
    if not 1<=len(args.source_boot)<=128 or any(port is not None and not 1<=port<=65535
            for port in (args.status_port,args.peer_stop_port,args.lease_datagram_port)):
        raise ValueError('Explicit source binding and valid transport ports required')
    if (args.private_audio_trace is None)!=(args.private_audio_trace_seconds is None):
        parser.error('Private trace requires both explicit path and trace seconds')
    private_trace=None
    if args.private_audio_trace is not None:
        from ..private_audio_trace import PrivateAudioTrace
        private_trace=PrivateAudioTrace(args.private_audio_trace,seconds=args.private_audio_trace_seconds,
            forbidden_roots=(args.config.resolve().parent,args.companion_config.resolve().parent))
    try:return _run_session_cli(args,private_trace)
    finally:
        if private_trace is not None:private_trace.close()


def _run_session_cli(args,private_trace):
    cfg=load(args.config)
    if cfg.get('speech',{}).get('enabled'):
        raise ValueError('Normal distributed mode uses the explicit remote peer, not the local ALSA speech profile')
    binding=session_context(cfg,allow_camera=args.allow_camera_context,
        readback=args.memory_readback,readback_sha256=args.memory_readback_sha256)
    motion_enabled=cfg.get('motion',{}).get('enabled',False)
    if motion_enabled!=args.allow_bounded_motion:raise ValueError('Matching explicit bounded antenna17 opt-in required')
    if motion_enabled and (args.config.resolve().parent/cfg['motion']['hub_config_path']).resolve()!=args.companion_config.resolve():
        raise ValueError('Motor profile must bind the same explicitly selected companion configuration')
    from reachy_companion.config import Config
    from reachy_companion.hub import Hub
    companion=Config(args.companion_config);hub=Hub(companion)
    os.environ[cfg['gateway']['token_env']]=args.token_file.read_text().strip()
    gateway=ContextGateway(cfg,binding)
    client=PeerClient(args.peer_url,companion.token,args.controller,trusted_private_lan=args.trusted_private_lan)
    stop_client=client.at_port(args.peer_stop_port)
    initial=client.call('/status')
    if initial.get('source_boot')!=args.source_boot or initial.get('closed') is not False:
        raise ValueError('Exact existing device source owner required')
    authority=None
    if args.lifetime=='lease':
        if initial.get('lifetime')!='lease':raise ValueError('Device must explicitly select the lease protocol')
        authority=lease_authority(initial.get('lease_binding'))
    elif initial.get('lifetime','finite')!='finite':raise ValueError('Do not mix finite and lease protocols')
    motion=None;audio=speech=poller=lease=server=scheduler=datagram=None
    stop=SignalStop();latest={};lock=threading.Lock();report=None;server_thread=None
    def publish(value):
        with lock:latest.clear();latest.update(value)
    def status():
        with lock:return dict(latest)
    previous_signals={}
    try:
        server=create_server(companion.token,args.controller,args.source_boot,stop,status,port=args.status_port)
        server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
        for signum in (signal.SIGTERM,signal.SIGINT):
            previous_signals[signum]=signal.signal(signum,stop.request_signal)
        if motion_enabled:
            # Existing actor owns hardware; this path cannot construct/restart it.
            native=cfg['motion'];motor_hub=Hub(Config(args.companion_config))
            motor_hub.config.data['guarded_motion']['enabled']=True
            motor_hub.config.data['network']['agent_url']=native['agent_url']
            if cfg['actuators']=='bounded_stock':
                from .stock_motion_adapter import StockMotionAdapter
                motor_hub.stock_dependencies()
                motion=StockMotionAdapter(motor_hub,cooldown_s=native['cooldown_s'],follow_person=native.get('follow_person',False))
            else:
                motion=MotionAdapter(motor_hub,cooldown_s=native['cooldown_s'],heartbeat_s=native['heartbeat_s'])
                current=motor_hub.agent('/status');actor=current['motion_actor']
                if (not isinstance(actor.get('hold'),dict) or actor['hold'].get('verified') is not True
                        or actor['hold'].get('trajectory_updates_after_hold')!=0):raise ValueError('Current physical hold proof required')
            ready=motion.refresh()
            if not (ready['motion_allowed'] or ready.get('tracking_ready')):raise ValueError('Current bounded motor owner not ready')
        stt_deadline=cfg.get('production',{}).get('stt_deadline_s',2)
        audio=AudioAdapter(HttpSTT(companion['network']['compute_url'],companion.token,timeout=stt_deadline,
            diagnostics=cfg.get('production',{}).get('stt_diagnostics',False)),
            result_ttl_s=stt_deadline,
            **({'continuous_input':True} if cfg.get('production') else {}))
        pcm=Playback(RemotePCM(client,stop_port=args.peer_stop_port,source_boot=args.source_boot,
            max_streams=32 if args.lifetime=='finite' else None,lifetime=args.lifetime),chunk_frames=4096,
            motion=motion if cfg['actuators']!='bounded_stock' else None)
        speech=SpeechAdapter(pcm,HttpTTS(companion['network']['voice_url'],companion.token,
            gain=cfg.get('speech',{}).get('tts_gain',1)),lambda:read_speech_operator(hub))
        poller=AudioPolling(client,audio,args.source_boot,persistent=True)
        scheduler=Scheduler(cfg,gateway,motion,speech,audio)
        if private_trace is not None:scheduler.private_trace=private_trace
        from .production import attach
        if cfg.get('production'):
            attach(scheduler,args.config)
        datagram=DatagramRenewal(client,args.source_boot,args.lease_datagram_port,authority=authority,
            retries=2 if cfg.get('production') else 0) if args.lease_datagram_port is not None else None
        lease=PeerLease(client,datagram=datagram,progress_timeout_s=args.lease_progress_s,
            **({'source_boot':args.source_boot,'authority':authority} if authority is not None else {}))
        report=run_session(scheduler,poller,lease,client,stop_client,args.source_boot,stop,args.duration,publish,lifetime=args.lifetime,status_transport=PersistentPeer(client))
    except BaseException as exc:
        import logging
        logging.getLogger(__name__).exception('Companion startup failed')
        report=dict(mode='normal_joined_companion',accepted=False,cleanup_verified=False,
            reason='startup_error',errors=[type(exc).__name__],source_boot=args.source_boot,
            raw_audio_retained=False,transcripts_retained=False,continuous=False)
    finally:
        if report is None or report.get('reason')=='startup_error':
            stop.set();cleanup_errors=[]
            for resource in (lease,datagram,poller,scheduler,audio,speech,motion):
                if resource is not None:
                    try:resource.close()
                    except BaseException as exc:cleanup_errors.append(type(exc).__name__)
            startup_stop=Job(lambda:stop_client.call('/stop',source_boot=args.source_boot))
            deadline=time.monotonic()+1
            def startup_busy():
                return dict(peer_stop=not startup_stop.future.done(),
                    audio=audio.status()['execution_busy'] if audio is not None else False,
                    speech=speech.status()['execution_busy'] if speech is not None else False,
                    peer_poll=poller.status()['execution_busy'] if poller is not None else False,
                    lease=lease.status()['execution_busy'] if lease is not None else False,
                    motion=motion.status()['execution_busy'] if motion is not None else False,
                    context_terminal_revoke=bool(scheduler and scheduler.context_terminal_job and not scheduler.context_terminal_job.future.done()))
            while time.monotonic()<deadline and any(startup_busy().values()):time.sleep(.005)
            report['startup_execution_busy']=startup_busy();report['cleanup_errors']=cleanup_errors
            if startup_stop.future.done():
                try:report['peer_stop']=startup_stop.future.result()
                except Exception as exc:cleanup_errors.append(type(exc).__name__)
        final_errors=[]
        if server:
            try:
                if server_thread is not None and server_thread.is_alive():server.shutdown();server_thread.join(1)
            except BaseException as exc:final_errors.append(type(exc).__name__)
            try:server.server_close()
            except BaseException as exc:final_errors.append(type(exc).__name__)
            deadline=time.monotonic()+.5
            while server.transport_status()['execution_busy'] and time.monotonic()<deadline:time.sleep(.005)
            report['control_transport']=server.transport_status()
            report['control_listener_execution_busy']=bool(server_thread and server_thread.is_alive())
            if report['control_transport']['execution_busy'] or report['control_listener_execution_busy']:
                report['accepted']=report['cleanup_verified']=False
        for signum,handler in previous_signals.items():
            try:signal.signal(signum,handler)
            except BaseException as exc:final_errors.append(type(exc).__name__)
        if final_errors:
            report['control_cleanup_errors']=final_errors;report['accepted']=report['cleanup_verified']=False
    if private_trace is not None:
        report['transcripts_retained']=True
        report['private_audio_trace']=private_trace.close()
    report.update(server.session_binding if server is not None else dict(controller=args.controller))
    with args.output.open('x') as file:json.dump(report,file,ensure_ascii=False,indent=2)
    from reachy_companion.production_logs import report_summary
    print(json.dumps(report_summary(report) if args.lifetime=='lease' else report,ensure_ascii=False),flush=True)
    return 0 if report['accepted'] else 2


if __name__=='__main__':raise SystemExit(main())
