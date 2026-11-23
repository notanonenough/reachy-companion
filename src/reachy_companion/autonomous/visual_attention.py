"""Single-owner visual initiative; no model calls or actuator IO here."""
from collections import deque
from uuid import UUID
from .contracts import decode
from .scene_changes import LABELS, SIDES


PREFIX='autonomous:vision:'


class VisualAttention:
    def __init__(self):
        self.event=None;self.authority=None
        self.seen=deque(maxlen=128);self.moved=deque(maxlen=128);self.considered=deque(maxlen=128)
        self.next_comment=0

    def refresh(self,state,now):
        value=None;sensor=state.sensors.get('camera.change')
        if (state.production and not state.stopped and not state.privacy and not state.quiet
                and sensor and sensor.view(now,False)['state']=='ready'):
            try:
                candidate=decode(sensor.summary)
                if (set(candidate)=={'id','label','side'} and str(UUID(candidate['id']))==candidate['id']
                        and candidate['label'] in LABELS and candidate['side'] in SIDES):value=candidate
            except (ValueError,TypeError,KeyError,AttributeError):pass
        self.event=value
        if self.authority!=state.authority:
            self.authority=state.authority
            # Do not replay a cached appearance across microphone/operator epochs.
            if value:self.moved.append(value['id']);self.considered.append(value['id'])
        active=PREFIX+value['id'] if value else None
        for ref in list(state.candidates):
            if ref.startswith(PREFIX) and ref!=active:
                state.candidates.pop(ref);state.candidate_kinds.pop(ref,None)
        for task in state.tasks.values():
            if task.input_ref.startswith(PREFIX) and task.input_ref!=active and task.status in ('running','ready'):
                task.status='discarded';task.result=None;state.record('visual_result_withdrawn')
        state.working.pop('visual_attention',None)
        if value:
            if value['id'] not in self.seen:
                self.seen.append(value['id']);state.record('visual_change_observed')
            if value['id'] not in self.moved:
                state.working['visual_attention']='New '+value['label']+' '+value['side']+'; attentive motion looks toward it.'

    def target(self,state,now):
        self.refresh(state,now)
        if self.event and self.event['id'] not in self.moved and state.actor_binding and state.actor_binding.get('transport')=='stock':
            return (self.event['id'],self.event['side'])

    def advance(self,state,now,allow_start):
        self.refresh(state,now)
        value=self.event
        if (not value or not allow_start or state.overload!='ACTIVE' or state.muted
                or value['id'] in self.considered or now<self.next_comment
                or state.dialogue_at is not None and now-state.dialogue_at<10
                or any(not ref.startswith('autonomous:') for ref in state.candidates)
                or any(task.status in ('running','ready') for task in state.tasks.values())):return
        # Replace the idle reflection, never a human request. At most one item.
        for ref in list(state.candidates):
            if ref.startswith('autonomous:'):
                state.candidates.pop(ref);state.candidate_kinds.pop(ref,None)
        ref=PREFIX+value['id']
        state.candidates[ref]=('Visual appearance confirmed in successive observations: '+value['label']+' '+value['side']+
            '. Nobody spoke. Decide whether a brief spontaneous Russian comment is useful; otherwise remain silent. Do not invent identity or intent.')
        state.candidate_kinds[ref]='main';self.considered.append(value['id']);self.next_comment=now+45
        state.record('visual_reflection_requested')
