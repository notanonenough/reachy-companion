"""Reachability observed by existing HTTP jobs; no extra probes or ICMP claim."""
import json


class NetworkObservation:
    ttl_s = 1.5

    def __init__(self):
        self.samples = {}

    def observe(self, target, started, finished, ok):
        if target not in ('compute', 'robot'):
            raise ValueError('Unknown network target')
        self.samples[target] = (finished, max(0, finished-started), bool(ok))

    def status(self, now):
        result = {'internet': 'unknown', 'measurement': 'http_observed_round_trip'}
        for target in ('compute', 'robot'):
            sample = self.samples.get(target)
            if sample is None:
                result[target] = {'state': 'unknown'}
                continue
            finished, elapsed, ok = sample
            age = max(0, int((now-finished)*1000))
            result[target] = dict(state='stale' if now-finished > self.ttl_s else 'reachable' if ok else 'failed',
                                  age_ms=age, elapsed_ms=round(elapsed*1000, 1))
        return result

    def event(self, now):
        status = self.status(now)
        # Compact, explicit provenance: HTTP includes service/scheduler time,
        # and is neither an ICMP ping nor evidence of Internet connectivity.
        summary = {'http': {target: {key: value for key, value in status[target].items()
                                    if key != 'age_ms'} for target in ('compute', 'robot')},
                   'internet': 'unknown'}
        return dict(type='sensor', id='network', availability='available',
                    source_id='hub-http-observed-round-trip', summary=json.dumps(summary, separators=(',', ':')),
                    age_ms=0, ttl_ms=int(self.ttl_s*1000))
