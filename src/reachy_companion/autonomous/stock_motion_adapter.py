"""Finite stock-daemon expressions through Hub's permission and UUID fences.

Completion means the owned factory UUID disappeared; it does not certify pose
or a hardware stop deadline. No SDK, UART or additional motor owner is opened.
"""
import math
import threading
import time


class StockMotionAdapter:
    def __init__(self, hub, *, cooldown_s=6, follow_person=False):
        if not hub.stock_selected() or not 3 <= cooldown_s <= 60:
            raise ValueError('Explicit stock transport and bounded cooldown required')
        self.hub = hub
        self.cooldown_s = cooldown_s
        self.session = hub.boot_id
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.hub.stock_cancel = self.cancel
        self.busy = self.closed = self.failed = False
        self.next_motion = 0
        self.cached = None
        self.receipts = []
        self.stock_diagnostic_receipt=None
        self.completed = 0
        self.done = threading.Event()
        self.done.set()
        from .person_follow import PersonFollow
        self.follow_person=follow_person;self.follower=PersonFollow()
        self.follow_due=0;self.follow_sample=None;self.follow_finished=0;self.follow_error=None
        self.follow_admitted=False

    def diagnostic_token(self):
        try:return self.hub.stock_diagnostic_token()
        except BaseException:return None

    def capture_diagnostic(self, before, report):
        try:
            after=self.hub.stock_diagnostic_token()
            if after is None or after is before:return
            value=self.hub.stock_diagnostic_snapshot(after,scoped=True)
            if not value or not (value['first_failure'] or value['stop_receipt']):return
            value=dict(value,request_id=report['request_id'])
            from .stock_diagnostics import project
            report['stock_diagnostics']=project(value)
            if self.stock_diagnostic_receipt is None or self.stock_diagnostic_receipt['first_failure'] is None:
                self.stock_diagnostic_receipt=value
        except BaseException:
            pass

    def binding(self, operator):
        return dict(agent_boot_id=operator['agent_boot_id'],
                    actor_boot_id=operator['agent_boot_id'], session_id=self.session,
                    operator_epoch=operator['microphone_epoch'],
                    motor_epoch=operator['motion_policy']['epoch'], transport='stock')

    def refresh(self):
        operator, _ = self.hub.operator_proxy()
        policy = operator['motion_policy']
        with self.lock:
            allowed = (not (self.busy or self.closed or self.failed or self.hub.stock_unknown)
                       and time.monotonic() >= self.next_motion
                       and operator['microphone_enabled'] and policy['motor_enabled']
                       and not policy['quiet'] and not policy['privacy_all'])
        value = dict(binding=self.binding(operator), policy=policy,
                     microphone_enabled=operator['microphone_enabled'], motion_allowed=allowed and not self.follow_person,
                     tracking_ready=allowed and self.follow_person,
                     received=time.monotonic())
        self.cached = value
        return value

    def follow_request(self, sensor, now, enabled, allow_scan=True):
        """Only bounded memory work on the scheduler thread; all IO is in follow()."""
        if not self.follow_person:return None
        self.follow_admitted=enabled
        if not enabled:
            self.cancel.set()
            return None
        with self.lock:
            if self.busy or self.closed or self.failed or now<self.follow_due:return None
        if not sensor or sensor.view(now,False)['state']!='ready':return None
        from .contracts import decode,uid
        from .person_follow import checked_sample
        try:sample=checked_sample(decode(sensor.summary))
        except (ValueError,TypeError):return None
        identity=(sample['source'],sample['seq'])
        if identity==self.follow_sample or sensor.captured<=self.follow_finished+.05:return None
        self.follow_sample=identity;self.follow_due=now+.15
        if not self.cached:return None
        return dict(sample=sample,allow_scan=allow_scan,request_id=uid(),
            captured=sensor.captured,
            deadline=min(sensor.captured+sensor.ttl,now+1),actual_binding=dict(self.cached['binding']))

    def follow(self, proposal):
        report=dict(accepted=False,request_id=proposal['request_id'],transport='stock',
            pose_verified=False,hard_stop_certified=False,tracking=True)
        with self.lock:
            if self.busy or self.closed or self.failed or not self.follow_admitted:return report
            self.busy=True;self.cancel.clear();self.done.clear()
        before=self.diagnostic_token()
        began=time.monotonic();moved=False;phase='operator'
        try:
            operator,_=self.hub.operator_proxy();policy=operator['motion_policy']
            if (time.monotonic()>=proposal['deadline'] or self.binding(operator)!=proposal['actual_binding']
                    or not operator['microphone_enabled'] or not policy['motor_enabled']
                    or policy['quiet'] or policy['privacy_all'] or self.cancel.is_set()):raise RuntimeError('Follow withdrawn')
            phase='pose';pose=self.hub.robot('/api/state/full')
            phase='plan'
            step=self.follower.plan(proposal['sample'],pose,time.monotonic(),proposal['allow_scan'])
            report['tracking_mode']=self.follower.mode
            if step is None:
                self.follow_error=None;report.update(accepted=True,skipped=True);return report
            if time.monotonic()>=proposal['deadline'] or self.cancel.is_set() or not self.follow_admitted:raise RuntimeError('Follow frame expired')
            binding=dict(agent_boot_id=operator['agent_boot_id'],microphone_epoch=operator['microphone_epoch'],
                microphone_enabled=operator['microphone_enabled'],policy_epoch=policy['epoch'],expression_version=operator['expression_version'])
            phase='dispatch';dispatch_at=time.monotonic()
            report.update(dispatch_started_at=dispatch_at,
                          frame_age_s=round(dispatch_at-proposal.get('captured',began),3),
                          duration_s=step['duration'],planning_s=round(dispatch_at-began,3))
            result=self.hub.expression(dict(steps=[step],operator_binding=binding),follow=True)
            finished_at=time.monotonic()
            report['dispatch_finished_at']=finished_at
            report['dispatch_s']=round(finished_at-dispatch_at,3)
            report.update(result);report['accepted']=result.get('ok') is True and result.get('steps_observed')==1
            moved=report['accepted']
            if moved:
                self.follower.committed(step)
                report.update(head_yaw_degrees=round(math.degrees(step['head_pose']['yaw']),2),
                              head_pitch_degrees=round(math.degrees(step['head_pose']['pitch']),2),
                              body_yaw_degrees=round(math.degrees(step['body_yaw']),2))
            self.follow_error=None
        except Exception as exc:
            report['error']=type(exc).__name__;report['error_phase']=phase;self.follow_error=phase+':'+type(exc).__name__
            if isinstance(exc,ValueError) and str(exc) in ('Follow absolute limit','Follow step delta limit','Follow angular speed limit','Follow angular acceleration limit','Measured pose outside follow envelope'):
                report['reason']=str(exc);self.follow_error+=':'+str(exc)
                if str(exc)=='Measured pose outside follow envelope':
                    self.failed=True;self.follower.mode='pose_fault'
            if self.hub.stock_unknown:self.failed=True
        finally:
            self.capture_diagnostic(before,report)
            with self.lock:
                self.busy=False
                if moved:self.follow_finished=time.monotonic()
                self.follow_due=time.monotonic()+(.05 if report['accepted'] else 1)
            if not report.get('skipped'):
                self.receipts.append(report);del self.receipts[:-32]
            self.done.set()
        return report

    def execute(self, proposal):
        with self.lock:
            if self.busy or self.closed or self.failed or time.monotonic() < self.next_motion:
                raise RuntimeError('Stock expression unavailable')
            self.busy = True
            self.cancel.clear()
            self.done.clear()
        report = dict(accepted=False, request_id=proposal['request_id'], transport='stock',
                      pose_verified=False, hard_stop_certified=False)
        before=self.diagnostic_token()
        try:
            operator, _ = self.hub.operator_proxy()
            policy = operator['motion_policy']
            if (time.monotonic() >= proposal['deadline'] or proposal['motion'] != 'attentive'
                    or self.binding(operator) != proposal['actual_binding']
                    or not operator['microphone_enabled'] or not policy['motor_enabled']
                    or policy['quiet'] or policy['privacy_all'] or self.cancel.is_set()):
                raise RuntimeError('Stock proposal stale or permission withdrawn')
            angle = math.radians(4 if self.completed % 2 == 0 else -4)
            side=proposal.get('gaze_side')
            if side is not None:
                if side not in ('left','center','right'):raise ValueError('Unknown gaze sector')
                # Camera x points right; robot +yaw points left. Finite glance,
                # then neutral, within the existing 12-degree expression guard.
                angle=math.radians({'left':8,'center':0,'right':-8}[side])
                report['gaze_side']=side
            def step(yaw, antenna):
                return dict(head_pose=dict(x=0,y=0,z=0,roll=0,pitch=0,yaw=yaw),
                            antennas=[antenna,-antenna], duration=.6, interpolation='minjerk')
            binding = dict(agent_boot_id=operator['agent_boot_id'],
                           microphone_epoch=operator['microphone_epoch'],
                           microphone_enabled=operator['microphone_enabled'],
                           policy_epoch=policy['epoch'], expression_version=operator['expression_version'])
            result = self.hub.expression(dict(steps=[step(angle,angle),step(0,0)],
                                              operator_binding=binding))
            report.update(result)
            report['accepted'] = result.get('ok') is True and result.get('steps_observed') == 2
            if report['accepted']: self.completed += 1
        except Exception as exc:
            report['error'] = type(exc).__name__
            # Unknown output must be reconciled explicitly, never retried.
            if self.hub.stock_unknown: self.failed = True
        finally:
            self.capture_diagnostic(before,report)
            with self.lock:
                self.busy = False
                self.next_motion = time.monotonic() + self.cooldown_s
            self.receipts.append(report)
            del self.receipts[:-32]
            self.done.set()
        return report

    def stop(self):
        self.cancel.set()
        self.done.wait(.3)
        return not self.busy and not self.hub.stock_unknown

    def close(self):
        with self.lock: self.closed = True
        return self.stop()

    def status(self):
        from .stock_diagnostics import project
        with self.lock:
            return dict(execution_busy=self.busy, closed=self.closed,
                        stop_known=not self.busy and not self.hub.stock_unknown,
                        hard_stop_certified=False,tracking_enabled=self.follow_person,
                        tracking_mode=self.follower.mode,tracking_error=self.follow_error,
                        surveys=self.follower.scans,stock_diagnostics=project(self.stock_diagnostic_receipt))
