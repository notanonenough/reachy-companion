"""Inference-free hub scheduler. One actual request per available clock tick."""
from concurrent.futures import Future
import json
import os
import threading
import time
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from http.client import HTTPException
from .contracts import decode, uid, validator, validate
from .state import State
from ..private_audio_trace import emit,main_call
from ..model_timing import project as project_model_timing,attach_error


class Job:
    """A daemon transport job; deadline expiry never implies execution completion."""
    def __init__(self, function, *args):
        self.future = Future()
        self.started=time.monotonic()
        def work():
            try:
                self.future.set_result(function(*args))
            except BaseException as exc:
                self.future.set_exception(exc)
        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()


class RemoteGateway:
    def __init__(self, config):
        self.config = config
        self.url = config['gateway']['client_url']
        if not self.url:
            raise ValueError('Set separate PC gateway client_url')
        self.token = os.environ.get(config['gateway']['token_env'], '')
        if len(self.token) < 32:
            raise ValueError('Set gateway token environment variable')
        self.opener = build_opener(ProxyHandler({}))
        self.boot_id = self.call('/health')['compute_boot_id']

    def call(self, path, payload=None):
        headers = {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'}
        request = Request(self.url.rstrip('/') + path,
                          data=None if payload is None else json.dumps(payload).encode(), headers=headers)
        with self.opener.open(request, timeout=min(1,self.config['http_timeout_s'] + 1) if path=='/health' else self.config['http_timeout_s'] + 1) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError('Oversized gateway response')
        return decode(raw)

    def inference(self,path,payload,role,on_transport=None):
        try:return self.call(path,payload)
        except (OSError,HTTPException):
            import sys
            failure=sys.exception()
            if path=='/main' and on_transport is not None:
                receipt=project_model_timing(None);diagnostic_status='no_response'
                if isinstance(failure,HTTPError):
                    diagnostic_status='malformed_diagnostic'
                    try:
                        raw=failure.read(65537)
                        if len(raw)<=65536:
                            supplied=decode(raw).get('model_timing')
                            if supplied is None:diagnostic_status='missing_diagnostic'
                            else:
                                receipt=project_model_timing(supplied,request_id=payload['request_id'],gateway_boot_id=self.boot_id)
                                if receipt['reason']!='invalid_receipt':
                                    diagnostic_status='partial_diagnostic' if receipt['incomplete'] else 'verified_receipt'
                                elif type(supplied) is dict and (supplied.get('request_id')!=payload['request_id'] or supplied.get('gateway_boot_id')!=self.boot_id):
                                    diagnostic_status='identity_mismatch'
                    except Exception:pass
                attach_error(failure,receipt)
                disposition=('execution_unknown' if isinstance(failure,HTTPError) and failure.code==503
                    and diagnostic_status in ('verified_receipt','partial_diagnostic') else
                    'observed_error_receipt' if isinstance(failure,HTTPError) else 'transport_failure')
                try:on_transport(receipt,disposition,diagnostic_status)
                except Exception:pass
            if isinstance(failure,HTTPError) and failure.code in (401,403,404,409,422):raise
            if not self.config.get('production'):raise
            # A client-side timeout is not backend terminal evidence. Keep this
            # actual Job occupied; never repost inference. Authenticated exact-ID
            # terminal metadata may retire it. Unknown/restarted compute remains
            # occupied for the external controller's audit/STOP path.
            while True:
                try:
                    health=self.call('/health')
                    execution=health.get('executions',{}).get(role,{})
                    if (health.get('compute_boot_id')==self.boot_id and execution.get('request_id')==payload['request_id']
                            and execution.get('status')=='terminal'):
                        error=RuntimeError('Inference response lost; exact remote execution is terminal')
                        attach_error(error,getattr(failure,'model_timing',None))
                        raise error
                except (OSError,HTTPException):pass
                time.sleep(.1)

    def fast(self, request_id, view):
        result = self.inference('/decision', dict(request_id=request_id, data=view),'fast')
        if result['request_id'] != request_id:
            raise ValueError('request identity mismatch')
        return result

    def main_with_transport(self,task,callback):
        return self.main(task,on_transport=callback)

    def main(self, task, *, on_transport=None):
        if task.kind == 'research':
            from .workflows import WorkflowClient
            output = WorkflowClient(self.config['workflows']).run(task)
            return dict(output=output,compute_boot_id=task.authority.compute_boot_id,request_id=task.attempt_id)
        result = self.inference('/main', dict(request_id=task.attempt_id, data=task.prompt),'main',on_transport)
        if result['request_id'] != task.attempt_id:
            raise ValueError('attempt identity mismatch')
        return result

    def context(self,request_id,query,privacy_all,authority):
        return self.call('/context',dict(request_id=request_id,data=dict(query=query,privacy_all=privacy_all,
                        hub_boot_id=authority.hub_boot_id,operator_epoch=authority.operator_epoch)))
    def revoke_context(self,authority,terminal=False):
        request_id=uid();data=dict(hub_boot_id=authority.hub_boot_id,operator_epoch=authority.operator_epoch,terminal=terminal)
        result=self.call('/context/revoke',dict(request_id=request_id,data=data))
        if result.get('request_id')!=request_id or result.get('compute_boot_id')!=authority.compute_boot_id or result.get('output')!=dict(revoked=True,**data):
            raise ValueError('Context revoke acknowledgement')
        return result



class ReplayGateway:
    """Explicit deterministic fixture backend; never represented as model inference."""
    boot_id = 'replay-compute'
    def __init__(self, main_delay=0.1):
        self.main_delay = main_delay
        self.fast_calls = 0
    def fast(self, request_id, view):
        self.fast_calls += 1
        choice = dict(a='wait', why='Replay: no new task')
        if view['op']['microphone_enabled']:
            if view['ready']:
                choice = dict(a='converse', why='Replay: accept ready proposal', commit=view['ready'][0]['alias'])
            elif view['candidates']:
                choice = dict(a='think', why='Replay: start background task',
                              start=dict(type=view['candidates'][0]['kind'], input_ref=view['candidates'][0]['alias']))
        return dict(output=choice, compute_boot_id=self.boot_id, request_id=request_id)
    def main(self, task):
        time.sleep(self.main_delay)
        return dict(output=task.prompt if task.kind == 'research' else 'Replay fixture response.', compute_boot_id=self.boot_id, request_id=task.attempt_id)


class Scheduler:
    def __init__(self, config, gateway, motion_adapter=None, speech_adapter=None, audio_adapter=None):
        # Compile/import schema machinery before admitting clock ticks.
        for name in ('FastView','FastChoice','MemoryItem'):validator(name)
        self.config, self.gateway = config, gateway
        self.state = State(gateway.boot_id, config)
        self.motion_adapter=motion_adapter
        self.speech_adapter=speech_adapter;self.state.speech_attached=speech_adapter is not None
        self.audio_adapter=audio_adapter
        self.actor_job=self.motion_job=None;self.next_actor=0
        if motion_adapter:
            self.state.muted=True
            motion_adapter.hub.boot_id=self.state.authority.hub_boot_id
        self.fast_job = self.main_job = None
        self.binding = self.main_task = None
        self.next_tick = 0
        self.decision_pending = False
        self.next_reaction = 0
        self.next_autonomous = 0
        self.expiry_logged = False
        self.context_job=None;self.context_revoke_job=None;self.context_terminal_job=None
        self.context_binding=None
        self.next_context=0
        self.closed=False
        self.services=None;self.production=False;self.latencies={};self.overload_since=None;self.overload_notice_pending=False;self.audio_busy_since=None
        self.last_dialogue_at=None
        self.pressure_report={};self.overload_trigger={}

    def enable_production(self, store, sensors=None, deliveries=None, tools=None):
        if self.services:raise ValueError('One production owner only')
        if self.config.get('native_agent',{}).get('enabled'):
            raise ValueError('Production Scheduler exclusively owns decisions; native orchestration must be disabled')
        from .services import Services
        store.claim()
        self.production=self.state.production=True
        self.services=Services(self,store,sensors,deliveries,tools)
        self.state.services=self.services;self.state.log_sink=self.services.log
        for name in ('audio.level','audio.transcript','camera','battery','power','servo.load','network','lidar'):
            self.state.ingest(dict(type='sensor',id=name,availability='unknown',source_id='unconfigured'),time.monotonic())

    def pressure_status(self,now):
        return dict(phase=self.state.overload,
                    elapsed_s=round(max(0,now-self.overload_since),3) if self.overload_since is not None and self.state.overload!='ACTIVE' else 0,
                    **self.pressure_report,last_trigger=dict(self.overload_trigger))

    def pressure(self,now):
        if not self.production:return
        state=self.state
        if state.stopped:return
        settings=self.config.get('production',{})
        named={name:job for name in ('fast','main','motion','context')
               if (job:=getattr(self,name+'_job')) and not job.future.done()}
        sensors={}
        if self.services:
            named.update({'tool:'+name:row[0] for name,row in self.services.tool_jobs.items() if not row[0].future.done()})
            sensors={'sensor:'+name:row[0] for name,row in self.services.polls.items() if not row[0].future.done()}
            if self.services.maintenance and not self.services.maintenance[0].future.done():named['maintenance']=self.services.maintenance[0]
            if self.services.update_job and not self.services.update_job[0].future.done():named['updates']=self.services.update_job[0]
        audio_busy=False
        if self.speech_adapter:
            status=self.speech_adapter.status()
            audio_busy=any(status.get(k,False) for k in ('execution_busy','tts_execution_busy','cancellation_execution_busy','pending_proposal'))
        if self.audio_adapter:audio_busy=audio_busy or self.audio_adapter.status().get('execution_busy',False)
        if audio_busy and self.audio_busy_since is None:self.audio_busy_since=now
        if not audio_busy:self.audio_busy_since=None
        ages={name:max(0,now-job.started) for name,job in {**named,**sensors}.items()}
        if self.audio_busy_since is not None:ages['audio']=max(0,now-self.audio_busy_since)
        limit=settings.get('overload_latency_s',10)
        overdue=[name for name,age in ages.items() if age>limit]
        ages={name:round(age,3) for name,age in ages.items()}
        queued=len(state.candidates)+sum(t.status=='ready' for t in state.tasks.values())
        unresolved=sorted(self.services.unresolved) if self.services else []
        reasons=['latency:'+name for name in overdue]
        if queued>settings.get('overload_queue',6):reasons.append('queue_depth')
        if unresolved and not self.services.tool_jobs:reasons.append('unknown_tool_completion')
        self.pressure_report=dict(active_age_s=ages,queue_depth=queued,latency_limit_s=limit,
                                  queue_limit=settings.get('overload_queue',6),reasons=reasons,unresolved_tools=unresolved)
        if state.overload=='ACTIVE' and reasons:
            state.overload='DRAINING';self.overload_since=now
            self.overload_trigger=dict(reasons=list(reasons),active_age_s=dict(ages),queue_depth=queued)
            state.motion_proposals.clear();state.speech_proposals.clear()
            state.record('overload_entered')
            self.overload_notice_pending=bool(self.speech_adapter and not (state.muted or state.privacy or state.quiet))
            if self.speech_adapter:
                self.speech_adapter.interrupt('overload',False)
                audio_busy=True
        if state.overload=='DRAINING' and self.overload_notice_pending and not audio_busy:
            self.overload_notice_pending=False
            if not (state.muted or state.privacy or state.quiet):
                try:
                    self.speech_adapter.execute(dict(text='Я перегрузился. Подожду завершения задач и соберу мысли.',
                        request_id=uid(),authority=state.authority,deadline=now+10))
                    audio_busy=True;state.record('overload_notice_proposed')
                except Exception:state.record('overload_notice_rejected')
        # Fresh sensor reads keep running during drain and must not prevent its
        # completion. A reader that exceeded the threshold remains accounted
        # until its actual return; neither timeouts nor retries free that slot.
        sensor_stalled=any(name in sensors for name in overdue)
        if state.overload=='DRAINING' and not named and not sensor_stalled and not audio_busy and self.fast_job is None and self.main_job is None and self.motion_job is None and not unresolved:
            # Ready results retain their original expiry/authority and remain
            # committable after consolidation. Do not erase a human request
            # received while draining, or replace an answer with 128 characters.
            state.previous.append('Drain completed; review ready answers, pending inputs and tool results.')
            state.overload='CONSOLIDATING';state.record('drain_completed')

    def ingest(self, event, now=None):
        if self.closed:return
        trace=getattr(self,'private_trace',None)
        if trace is not None:self.state.private_trace=trace
        if trace is not None and (event.get('type')=='stop' or event.get('type')=='operator' and event.get('privacy_all') is True):
            trace.disable('privacy' if event.get('privacy_all') is True else 'stop')
        if self.audio_adapter and event.get('type')=='operator':self.audio_adapter.interrupt()
        if self.speech_adapter and event.get('type') in ('operator','utterance'):
            self.speech_adapter.interrupt('human_utterance' if event['type']=='utterance' else 'operator',False)
        if event.get('type')=='utterance':
            self.last_dialogue_at=time.monotonic() if now is None else now
            self.next_autonomous=self.last_dialogue_at+30
        old_authority=self.state.authority
        self.state.ingest(event, time.monotonic() if now is None else now)
        if (event.get('type')=='utterance'
                and self.state.authority.interaction_epoch==old_authority.interaction_epoch+1):
            self.decision_pending = True
        if trace is not None and event.get('type')=='utterance' and event.get('audio'):
            audio=event['audio'];admitted=self.state.authority.interaction_epoch==old_authority.interaction_epoch+1
            refs=list(self.state.candidates) if admitted else []
            emit(self,'input_admission',text=event['text'] if admitted else None,
                input_ref=refs[0] if len(refs)==1 else None,authority=self.state.authority.wire(),
                lineage_id=audio.get('lineage_id'),source_boot=audio.get('source_boot'),sequence=audio.get('sequence'),
                disposition='admitted' if admitted else 'blocked',
                **({key:audio[key] for key in ('aggregation','turn_id','segments','earliest_deadline')} if audio.get('aggregation')=='endpoint_v1' else {}))
        if event.get('type')=='operator' and self.state.privacy:self.revoke_context(old_authority)
        if event.get('type')=='stop':
            if self.speech_adapter:self.speech_adapter.interrupt('stop',False)
            if self.audio_adapter:self.audio_adapter.interrupt()
            if self.motion_adapter:self.motion_adapter.close()

    def revoke_context(self,authority,terminal=False):
        if not self.config.get('context',{}).get('enabled'):return
        if not hasattr(self.gateway,'revoke_context'):
            self.state.record('context_revoke_unavailable');return
        if terminal:
            self.context_terminal_job=Job(self.gateway.revoke_context,authority,True);return
        if self.context_revoke_job and not self.context_revoke_job.future.done():
            self.state.record('context_revoke_busy');return
        self.context_revoke_job=Job(self.gateway.revoke_context,authority,terminal)

    def close(self):
        if self.closed:return
        # Revoke in an independent real transport slot. The occupied context
        # request remains accounted until its actual completion.
        self.closed=True
        error=None
        finalizers=[lambda:self.revoke_context(self.state.authority,True)]
        if self.speech_adapter:finalizers.append(self.speech_adapter.close)
        if self.audio_adapter:finalizers.append(self.audio_adapter.close)
        for finalize in finalizers:
            try:finalize()
            except BaseException as exc:
                if error is None:error=exc
                else:error.add_note('Additional scheduler close failure: '+type(exc).__name__)
        if self.services:
            self.state.log_sink=None
            self.services.close()
        if error is not None:raise error

    def speech_activity(self,origin):
        # Trusted classifier hook; echo cannot create a State human utterance.
        if origin not in ('human_activity','echo'):raise ValueError('Speech provenance')
        if self.speech_adapter:return self.speech_adapter.interrupt(origin)

    def confirm_no_user_utterance(self,since,until):
        return bool(self.speech_adapter and self.speech_adapter.confirm_no_utterance(since=since,until=until))

    def handshake_compute(self, boot, generation):
        """Single-owner authenticated health/reconnect callback, never a model result."""
        return self.state.set_compute_boot(boot, generation)

    def advance(self, now=None):
        if self.closed:return
        now = time.monotonic() if now is None else now
        before_operator=self.state.authority;was_private=self.state.privacy
        if self.speech_adapter:
            receipt=self.speech_adapter.operator_view()
            if receipt:self.state.set_speech_operator(receipt)
        else:receipt=None
        if self.audio_adapter:
            self.state.audio_source_bound=self.audio_adapter.status()['source_boot'] is not None
            event=self.audio_adapter.advance(self.state.authority,receipt,
                allow_start=not self.production or self.state.overload=='ACTIVE')
            if event:self.ingest(event,now)
            if self.production and hasattr(self.audio_adapter,'drain_level'):
                level=self.audio_adapter.drain_level(self.state.authority)
                if level:self.ingest(level,now)
        if self.motion_adapter:
            if self.actor_job and self.actor_job.future.done():
                try:self.state.set_actor(self.actor_job.future.result())
                except Exception:
                    self.state.motion_allowed=False;self.state.record('actor_authority_unavailable')
                self.actor_job=None
            if not self.actor_job and now>=self.next_actor:
                self.actor_job=Job(self.motion_adapter.refresh);self.next_actor=now+.1
            if self.motion_job and self.motion_job.future.done():
                try:
                    report=self.motion_job.future.result()
                    if not report.get('skipped'):
                        self.state.record('motion_completed' if report['accepted'] else 'motion_failed',request_id=report['request_id'])
                except Exception:self.state.record('motion_failed')
                self.motion_job=None
        if self.state.privacy and not was_private:self.revoke_context(before_operator)
        # Detect pressure before background admission can refill emptied slots.
        self.pressure(now)
        if self.services:self.services.advance(now)
        self.pressure(now)
        if self.motion_adapter and getattr(self.motion_adapter,'follow_person',False):
            self.state.working['visual_tracking']=self.motion_adapter.status()['tracking_mode']
            enabled=(self.production and self.state.overload=='ACTIVE' and not self.state.stopped
                and not self.state.privacy and not self.state.quiet and not self.state.muted)
            request=self.motion_adapter.follow_request(self.state.sensors.get('camera.person'),now,enabled,
                allow_scan=(self.last_dialogue_at is None or now-self.last_dialogue_at>10)
                    and not (self.speech_adapter and self.speech_adapter.status().get('execution_busy')))
            if request and not self.motion_job:self.motion_job=Job(self.motion_adapter.follow,request)
        if self.config.get('context',{}).get('enabled') and hasattr(self.gateway,'context') and hasattr(self.gateway,'revoke_context'):
            if self.context_job and self.context_job.future.done():
                request_id,authority,started=self.context_binding
                try:
                    result=self.context_job.future.result()
                    if result['request_id']!=request_id or result['compute_boot_id']!=authority.compute_boot_id or authority!=self.state.authority:
                        raise ValueError('Stale context authority')
                    self.state.update_context(result['output'],now,now-started)
                except Exception:self.state.record('context_failed')
                self.context_job=self.context_binding=None
            if (not self.context_job and now>=self.next_context and not self.state.stopped
                    and (not self.production or self.state.overload=='ACTIVE')):
                request_id=uid();self.context_binding=(request_id,self.state.authority,now)
                self.context_job=Job(self.gateway.context,request_id,self.state.current_utterance,self.state.privacy,self.state.authority)
                self.next_context=now+self.config['context'].get('refresh_s',.5)
        # Poll done futures without waiting; worker threads never mutate hub state.
        if self.main_job and self.main_job.future.done():
            task = self.main_task
            try:
                result = self.main_job.future.result()
                self.latencies['main']=max(0,now-getattr(self.main_job,'started',now))
                if result['compute_boot_id'] != task.authority.compute_boot_id or result['request_id'] != task.attempt_id:
                    self.state.complete(task.task_id, task.attempt_id, task.authority, None, now, error=True)
                else:
                    self.state.complete(task.task_id, task.attempt_id, task.authority, result['output'], now,
                        provenance=result.get('completion_provenance'))
            except Exception:
                self.state.complete(task.task_id, task.attempt_id, task.authority, None, now, error=True)
            if getattr(self,'private_trace',None) is not None:
                emit(self,'main_checked',task_id=task.task_id,attempt_id=task.attempt_id,input_ref=task.input_ref,
                    authority=task.authority.wire(),disposition=task.status,final=task.completion_provenance)
            self.main_job = self.main_task = None
            if task.status=='ready' or self.state.candidates:
                self.decision_pending = True
        if self.fast_job and self.fast_job.future.done():
            try:
                result = self.fast_job.future.result()
                if (result['compute_boot_id'] != self.binding.authority.compute_boot_id
                        or result['request_id'] != self.binding.request_id):
                    raise ValueError('Completion does not match request authority')
                self.latencies['fast']=max(0,now-getattr(self.fast_job,'started',now))
                choice = result['output']
                if self.production and self.state.overload=='CONSOLIDATING':
                    validate('FastChoice',choice)
                    if (now>self.binding.deadline or self.binding.authority!=self.state.authority
                            or self.binding.durable_revision!=self.state.durable_revision):raise ValueError('Stale consolidation')
                    self.state.overload='ACTIVE';self.state.record('consolidation_completed')
                # Capacity rejection before reducer consumes the candidate.
                if choice.get('start') and (self.main_job or self.services and self.services.maintenance):
                    self.state.record('main_execution_busy')
                    # A full main lane must not suppress an independent gaze.
                    choice={key:value for key,value in choice.items() if key!='start'}
                    task = self.state.apply(choice, self.binding, now)
                else:
                    task = self.state.apply(choice, self.binding, now)
                if self.state.motion_proposals:
                    proposal=self.state.motion_proposals.popleft()
                    if self.motion_adapter and not self.motion_job:
                        self.motion_job=Job(self.motion_adapter.execute,proposal)
                    else:self.state.record('motion_execution_busy')
                if task:
                    self.main_task = task
                    trace=getattr(self,'private_trace',None)
                    self.main_job = Job(main_call,trace,self.gateway.main,task,getattr(self.gateway,'main_with_transport',None)) if trace is not None else Job(self.gateway.main,task)
            except Exception as exc:
                self.state.record('fast_failed', error_class=type(exc).__name__)
            self.fast_job = self.binding = None
        if self.speech_adapter:
            self.speech_adapter.advance(self.state.authority)
            if self.state.speech_proposals:
                proposal=self.state.speech_proposals.popleft()
                try:self.speech_adapter.execute(proposal)
                except Exception:self.state.record('speech_admission_rejected')
        self.state.collect(now)
        if self.fast_job and now > self.binding.deadline and not self.expiry_logged:
            self.state.record('fast_deadline_expired')
            self.expiry_logged = True
        if self.production and (self.state.stopped or self.state.overload=='DRAINING'):return
        if self.motion_adapter and self.state.actor_binding is None and not self.production:return
        # Coalesce new dialogue/ready transitions, without bypassing the model
        # decision or pretending a revoked main request has physically finished.
        # At most one reactive launch per period; quiet ticks keep their cadence.
        ready = any(task.status=='ready' for task in self.state.tasks.values())
        candidate_available = bool(self.state.candidates) and not self.main_job and not (
            self.services and self.services.maintenance)
        reactive = (self.decision_pending and now>=self.next_reaction and not self.fast_job
                    and (ready or candidate_available))
        if now < self.next_tick and not reactive:
            return
        # No catch-up burst. Skipped busy ticks remain explicit gaps.
        self.next_tick = now + self.config['period_s']
        if self.fast_job:
            self.state.record('tick_busy_gap'); return
        if self.production:
            self.state.visual.advance(self.state,now,allow_start=not self.main_job
                and not (self.services and self.services.maintenance)
                and not (self.speech_adapter and self.speech_adapter.status().get('execution_busy')))
        if (self.production and self.state.overload=='ACTIVE' and not self.state.privacy and not self.state.candidates and not self.main_job
                and now>=self.next_autonomous and not any(task.status=='ready' for task in self.state.tasks.values())):
            # One replaceable self-directed input, never an invented human utterance.
            ref='autonomous:'+uid()
            self.state.candidates[ref]='Self-directed reflection on current observations, goal and unfinished work.'
            self.state.candidate_kinds[ref]='main'
            self.next_autonomous=now+30
        view = self.state.snapshot(now)
        if self.production:
            view['runtime']['latency_s']=dict(self.latencies)
            view['runtime']['queue_depth']=len(self.state.candidates)+sum(t.status=='running' for t in self.state.tasks.values())
            view['runtime']['background_busy']=self.services.busy() if self.services else 0
        if self.main_job and not self.main_job.future.done() and self.main_task.status != 'running':
            # Revoking a result does not conceal still-busy physical execution.
            view['pending'] = view['pending'][:7] + [dict(alias=self.main_task.task_id,
                kind=self.main_task.kind, status='execution_busy_result_revoked',
                age_ms=max(0, int((now-self.main_task.created)*1000)))]
        if self.decision_pending:
            self.next_reaction = now + self.config['period_s']
            self.decision_pending = False
        self.binding = self.state.bind(now, self.config['fast_deadline_s'])
        self.fast_job = Job(self.gateway.fast, self.binding.request_id, view)
        self.expiry_logged = False
        self.state.record('fast_requested', request_id=self.binding.request_id)

    def run(self, duration_s, events=(), output=None):
        start = time.monotonic()
        primary=None
        try:
            pending = iter(events)
            event = next(pending, None)
            while time.monotonic() - start < duration_s:
                now = time.monotonic()
                while event is not None and event['at_s'] <= now-start:
                    self.ingest({k:v for k,v in event.items() if k != 'at_s'}, now)
                    event = next(pending, None)
                self.advance(now)
                time.sleep(min(0.01, self.config['period_s']/10))
        except BaseException as exc:
            primary=exc;raise
        finally:
            # Exceptions/interrupts withdraw admission too. An occupied worker
            # remains occupied; closing never certifies model/physical stop.
            cleanup_error=None;motion_stopped=self.motion_adapter is None
            finalizers=[self.close]
            if self.motion_adapter:finalizers.append(self.motion_adapter.close)
            for index,finalize in enumerate(finalizers):
                try:
                    result=finalize()
                    if index==1:motion_stopped=result
                except BaseException as exc:
                    if primary is not None:primary.add_note('Scheduler run cleanup failure: '+type(exc).__name__)
                    elif cleanup_error is None:cleanup_error=exc
                    else:cleanup_error.add_note('Additional scheduler run cleanup failure: '+type(exc).__name__)
            if cleanup_error is not None:raise cleanup_error
        self.state.ingest(dict(type='operator', muted=True),time.monotonic())
        report = dict(mode='replay' if isinstance(self.gateway, ReplayGateway) else 'real_model_shadow',
                      actuators='bounded_native_antenna17' if self.motion_adapter else 'simulated', counts=dict(self.state.counts),
                      execution_busy=dict(fast=bool(self.fast_job and not self.fast_job.future.done()),
                                          main=bool(self.main_job and not self.main_job.future.done()),
                                          actor=bool(self.actor_job and not self.actor_job.future.done()),
                                          context=bool(self.context_job and not self.context_job.future.done()),
                                          context_revoke=bool(self.context_revoke_job and not self.context_revoke_job.future.done()),
                                          context_terminal_revoke=bool(self.context_terminal_job and not self.context_terminal_job.future.done()),
                                          motion=bool(self.motion_job and not self.motion_job.future.done()) or bool(self.motion_adapter and hasattr(self.motion_adapter,'status') and self.motion_adapter.status()['execution_busy'])),
                      ledger=list(self.state.ledger), authority=self.state.authority.wire())
        if self.motion_adapter:
            report['motion_receipts']=list(self.motion_adapter.receipts)
            report['motion_stop_known']=motion_stopped
        if self.speech_adapter:
            report['speech']=self.speech_adapter.status()
            report['execution_busy']['speech']=report['speech']['execution_busy'] or report['speech']['tts_execution_busy']
        if self.audio_adapter:
            report['audio']=self.audio_adapter.status()
            report['execution_busy']['audio']=report['audio']['execution_busy']
        if output:
            from pathlib import Path
            path = Path(output)
            # Avoid accidental overwriting; caller selects privacy-sensitive output destination.
            with path.open('x') as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
        return report
