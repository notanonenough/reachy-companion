"""Bounded evidence only. Never grants motion authority or clears unknown state."""
import json
from time import monotonic
from urllib.error import HTTPError


def error_fields(exc):
    kind = ('HTTPError' if isinstance(exc, HTTPError) else 'TimeoutError' if isinstance(exc, TimeoutError)
            else 'TransportError' if isinstance(exc, OSError) else 'ResponseError')
    status = exc.code if isinstance(exc, HTTPError) and type(exc.code) is int and 100 <= exc.code <= 599 else None
    return dict(error_class=kind, http_status=status)


def cause_for(exc):
    return 'request_error' if isinstance(exc, (HTTPError, OSError)) else 'invalid_observation'


def project(value):
    """Fresh whitelist views; no exception messages, arbitrary keys or objects."""
    import math
    from uuid import UUID
    def number(value):
        try:return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
        except OverflowError:return None


    def identity(value):
        try:
            return value if type(value) is str and str(UUID(value)) == value else None
        except ValueError:
            return None

    if type(value) is not dict:return None
    def errors(raw):
        return dict(error_class=raw.get('error_class') if raw.get('error_class') in
                    ('HTTPError','TimeoutError','TransportError','ResponseError') else None,
                    http_status=raw.get('http_status') if type(raw.get('http_status')) is int and 100 <= raw['http_status'] <= 599 else None)
    def boolean(x):return x if type(x) is bool else None
    failure=value.get('first_failure');stop=value.get('stop_receipt')
    result=dict(first_failure=None,stop_receipt=None)
    if type(failure) is dict:
        stage=failure.get('stage');cause=failure.get('cause')
        if stage in ('dispatch_post','dispatch_response','stop_preflight','stop_post','stop_observation') and cause in ('request_error','freshness_expired','invalid_observation','absence_timeout'):
            result['first_failure']=dict(schema='stock-failure-1',hub_boot_id=identity(failure.get('hub_boot_id')),
                clock_basis='hub_monotonic',at=number(failure.get('at')),stage=stage,cause=cause,
                owned_uuid=identity(failure.get('owned_uuid')),**errors(failure))
    if type(stop) is dict:
        probes=stop.get('preflight');post=stop.get('post')
        result['stop_receipt']=dict(schema='stock-stop-1',hub_boot_id=identity(stop.get('hub_boot_id')),
            clock_basis='hub_monotonic',owned_uuid=identity(stop.get('owned_uuid')),
            started_at=number(stop.get('started_at')),finished_at=number(stop.get('finished_at')),
            completed=boolean(stop.get('completed')),preflight=[],post=None,
            absence_observed=boolean(stop.get('absence_observed')),stock_unknown_after=boolean(stop.get('stock_unknown_after')))
        out=result['stop_receipt']
        for probe in probes[:2] if type(probes) is list else []:
            if type(probe) is dict:
                out['preflight'].append(dict(elapsed_s=number(probe.get('elapsed_s')),absence=boolean(probe.get('absence')),
                    cause=probe.get('cause') if probe.get('cause') in ('request_error','freshness_expired','invalid_observation') else None,**errors(probe)))
        if type(post) is dict:out['post']=dict(attempted=boolean(post.get('attempted')),accepted=boolean(post.get('accepted')),**errors(post))
    if 'request_id' in value:result['request_id']=identity(value['request_id'])
    return result


class StockDiagnostics:
    def __init__(self, boot):
        self.boot=boot;self.first=None;self.first_token=None
        self.stop=None;self.stop_token=None;self.failed_stop=None

    def begin_stop(self, token, owned):
        self.stop_token=token
        self.stop=dict(schema='stock-stop-1',hub_boot_id=self.boot,clock_basis='hub_monotonic',owned_uuid=owned,
            started_at=monotonic(),finished_at=None,completed=False,preflight=[],
            post=dict(attempted=False,accepted=None,error_class=None,http_status=None),
            absence_observed=None,stock_unknown_after=None)

    def preflight(self, token, elapsed, active, exc=None, stale=False):
        if self.stop is None:return
        self.stop['preflight'].append(dict(elapsed_s=elapsed,absence=not active if active is not None else None,
            cause='freshness_expired' if stale else cause_for(exc) if exc is not None else None,
            **(error_fields(exc) if exc is not None else dict(error_class=None,http_status=None))))
        del self.stop['preflight'][2:]

    def post(self, token, attempted, accepted=None, exc=None):
        if self.stop is not None:self.stop['post']=dict(attempted=attempted,accepted=accepted,
            **(error_fields(exc) if exc is not None else dict(error_class=None,http_status=None)))

    def fail(self, token, stage, cause, owned, exc=None):
        if self.first is not None:return
        self.first=json.dumps(dict(schema='stock-failure-1',hub_boot_id=self.boot,clock_basis='hub_monotonic',
            at=monotonic(),stage=stage,cause=cause or cause_for(exc),owned_uuid=owned,
            **(error_fields(exc) if exc is not None else dict(error_class=None,http_status=None))))
        self.first_token=token
        if stage.startswith('stop_') and self.stop is not None and self.stop_token is token and self.stop['owned_uuid']==owned:
            self.failed_stop=self.stop

    def observe(self, token, absent):
        if self.stop is not None:self.stop['absence_observed']=absent

    def finish_stop(self, token, unknown):
        if self.stop is not None:
            self.stop.update(completed=True,finished_at=monotonic(),stock_unknown_after=unknown)

    def snapshot(self, token=None, scoped=False):
        failure=json.loads(self.first) if self.first is not None and (not scoped or token is self.first_token) else None
        stop=self.failed_stop if failure is not None else self.stop if self.first is None and (not scoped or token is self.stop_token) else None
        return project(dict(first_failure=failure,stop_receipt=stop))
