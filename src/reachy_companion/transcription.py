"""One remote STT execution slot, with a fence for requests delayed in transit.

Only a currently reserved ticket can start inference. Settling an unused ticket
revokes it; settling a running ticket observes completion without cancelling or
pretending that an HTTP timeout stopped the recognizer. No audio/results stored.
"""
import threading
import time
import uuid


def checked_execution(value):
    if type(value) is not dict or set(value)!={'boot_id','slot_id'}:
        raise ValueError('Transcription execution ticket')
    for field in value.values():
        if type(field) is not str or str(uuid.UUID(field))!=field:
            raise ValueError('Transcription execution identity')
    return value


class TranscriptionBusy(RuntimeError):
    pass


class TranscriptionSlot:
    def __init__(self, *, clock=time.monotonic):
        self.clock=clock;self.boot_id=str(uuid.uuid4());self.lock=threading.Lock()
        self.active=None;self.started=self.finished=0

    def expire(self):
        if self.active and self.active['state']=='reserved' and self.clock()>=self.active['deadline']:
            self.active=None

    def reserve(self):
        with self.lock:
            self.expire()
            if self.active:raise TranscriptionBusy('Transcription execution busy')
            ticket=dict(boot_id=self.boot_id,slot_id=str(uuid.uuid4()))
            self.active=dict(ticket=ticket,state='reserved',deadline=self.clock()+2,started=None)
            return dict(ticket)

    def run(self,ticket,work):
        checked_execution(ticket)
        with self.lock:
            self.expire()
            if not self.active or self.active['ticket']!=ticket or self.active['state']!='reserved':
                raise ValueError('Transcription reservation expired or revoked')
            self.active.update(state='running',started=self.clock());self.started+=1
        try:return work()
        finally:
            with self.lock:
                self.active=None;self.finished+=1

    def settle(self,ticket):
        checked_execution(ticket)
        with self.lock:
            self.expire()
            if ticket['boot_id']!=self.boot_id:
                # A new endpoint boot is not proof that the old process exited.
                state='foreign_boot';terminal=False
            elif self.active and self.active['ticket']==ticket:
                if self.active['state']=='reserved':
                    self.active=None;state='revoked';terminal=True
                else:state='running';terminal=False
            else:
                # Old tickets can never be admitted again, including after a
                # newer reservation. No unbounded tombstone/result map needed.
                state='terminal';terminal=True
            return dict(execution=dict(ticket),state=state,terminal=terminal)

    def status(self):
        with self.lock:
            self.expire();active=self.active
            return dict(state=active['state'] if active else 'idle',
                execution_busy=bool(active and active['state']=='running'),
                active_age_s=self.clock()-active['started'] if active and active['started'] is not None else None,
                started=self.started,finished=self.finished)
