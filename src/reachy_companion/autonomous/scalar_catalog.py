"""Bounded scalar ingress for Services, with no worker-owned runtime state.

Descriptors are untrusted descriptive data, never instructions or permissions.
The configured reader is the trust boundary; a peer cannot register another
reader or select its own supported semantics. Clock bounds are local policy.
"""
import copy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

from .contracts import decode, uid, validate

PROTOCOL = 'scalar-catalog-v1'
MAX_BYTES = 16384
MAX_CAPABILITIES = 12
SUPPORTED = {'metric.scalar': {'major': 1, 'max_minor': 0}}


@lru_cache(maxsize=3)
def validator(kind):
    from jsonschema import Draft202012Validator, validators
    schema = decode((Path(__file__).parents[1]/'assets/scalar-catalog.json').read_text())
    # JSON Schema calls 499.0 an integer; State and sequence guards require a
    # Python int. Use the actual consumer type throughout every nested field.
    strict = validators.extend(Draft202012Validator, type_checker=
        Draft202012Validator.TYPE_CHECKER.redefine('integer', lambda _, value: type(value) is int))
    return strict({**schema, '$ref': '#/$defs/'+kind})


def checked(kind, value):
    from jsonschema import ValidationError
    if len(json.dumps(value, allow_nan=False).encode()) > MAX_BYTES:
        raise ValueError('Scalar envelope byte bound')
    try:validator(kind).validate(value)
    except ValidationError as exc:raise ValueError('Invalid scalar '+kind) from exc
    if type(value['protocol']) is not int:raise ValueError('Scalar protocol type')
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def runtime_id(reader, capability):
    return 'scalar:'+digest([reader, capability])


def catalog_checked(value, connection, cap):
    checked('Catalog', value)
    if value['connection_id'] != connection or len(value['capabilities']) > cap:
        raise ValueError('Catalog connection/capacity')
    ids = set()
    for item in value['capabilities']:
        checked('Capability',item)
        version = item['version']
        if (item['id'] in ids or item['source_boot_id'] != value['source_boot_id']
                or item['catalog_generation'] != value['catalog_generation']
                or version['min_minor'] > version['minor']
                or item['range'] is not None and item['range'][0] > item['range'][1]):
            raise ValueError('Ambiguous catalog')
        ids.add(item['id'])
    return value


def agreement(catalog, request):
    catalog_checked(catalog, request['connection_id'], request['max_capabilities'])
    selected = []
    for cap in catalog['capabilities']:
        version = cap['version']
        local = request['supported'].get(cap['semantic'])
        supported = (cap['module'] == 'metrics' and cap['direction'] == 'source'
                     and local and local['major'] == version['major']
                     and local['max_minor'] >= version['min_minor'])
        minor = min(local['max_minor'], version['minor']) if supported else None
        selected.append(dict(id=cap['id'], minor=minor, status='unsupported' if not supported
                             else 'supported' if minor == version['minor'] else 'limited'))
    return dict(connection_id=request['connection_id'], challenge_id=request['challenge_id'],
                source_boot_id=catalog['source_boot_id'], catalog_generation=catalog['catalog_generation'],
                catalog_digest=digest(catalog), selected=selected)


def settings_checked(settings):
    for key, default, low, high in (('max_capabilities', 4, 1, 12), ('policy_ttl_ms', 1500, 1, 60000)):
        value = settings.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError('Scalar policy bound: '+key)
    error = settings.get('clock_error_ms')
    if error is not None and (type(error) is not int or not 0 <= error <= 60000):
        raise ValueError('Scalar clock error bound')
    if type(settings.get('enabled', True)) is not bool:
        raise ValueError('Scalar enable flag')


class ScalarReader:
    """One finite exchange; a result is only a candidate for the owner's commit."""
    def __init__(self, settings):
        from .production import http_reader
        settings_checked(settings)
        self.settings = dict(settings)
        self.transport = http_reader(settings, scalar=True)
        self.enabled = settings.get('enabled', True)

    def __call__(self, request):
        catalog = self.transport(dict(kind='catalog_request', protocol=1,
                                      connection_id=request['connection_id']))
        selected = agreement(catalog, request)
        response = self.transport(dict(kind='observation_request', protocol=1, agreement=selected))
        return catalog, response


class ScalarRegistry:
    """Owned only by Services. No State mutations occur while validating a batch."""
    def __init__(self, name, reader, source):
        self.name, self.reader, self.source = name, reader, source
        self.connection = uid()
        self.ids = set()
        self.boot = None
        self.generation = -1
        self.catalog_digest = None
        self.sequences = {}
        self.retired_boots = set()
        self.pending = None

    def withdraw(self, scheduler, now):
        for name in self.ids:
            scheduler.ingest(dict(type='sensor_remove', id=name), now)
        self.ids.clear()
        self.connection = uid()
        self.pending = None
        # Keep bounded sequence/retired-boot fences across privacy/reconnect.

    def request(self):
        request = dict(connection_id=self.connection, challenge_id=uid(),
                       supported=copy.deepcopy(SUPPORTED),
                       max_capabilities=self.reader.settings.get('max_capabilities', 4))
        self.pending = copy.deepcopy(request)
        return request

    def accept(self, result, request, started, now, state):
        if request != self.pending or request['connection_id'] != self.connection:
            raise ValueError('Withdrawn scalar request')
        self.pending = None  # challenge is single use even when validation fails
        catalog, response = result
        expected = agreement(catalog, request)
        if (not isinstance(response, dict) or set(response) != {'kind','protocol','ack','observations'}
                or response['kind'] != 'scalar_snapshot' or type(response['protocol']) is not int
                or response['protocol'] != 1 or response['ack'] != expected
                or not isinstance(response['observations'], list)
                or len(response['observations']) > request['max_capabilities']):
            raise ValueError('Unconfirmed scalar catalog')
        if len(json.dumps(response, allow_nan=False).encode()) > MAX_BYTES:
            raise ValueError('Scalar snapshot byte bound')
        boot, generation = catalog['source_boot_id'], catalog['catalog_generation']
        # connection_id is not part of the immutable source catalog identity.
        fingerprint = digest({k:v for k,v in catalog.items() if k != 'connection_id'})
        if (boot in self.retired_boots or self.boot == boot and generation < self.generation
                or self.boot == boot and generation == self.generation
                and self.catalog_digest is not None and fingerprint != self.catalog_digest):
            raise ValueError('Replayed or changed catalog generation')
        if self.boot is not None and self.boot != boot and len(self.retired_boots) >= 8:
            raise ValueError('Source boot history exhausted; reconfigure reader')
        caps = {c['id']: c for c in catalog['capabilities']}
        ids = {runtime_id(self.name, cap) for cap in caps}
        if len((set(state.sensors)-self.ids) | ids) > state.config['sensor_cap']:
            raise ValueError('Global sensor capacity')
        sequences = dict(self.sequences) if boot == self.boot else {}
        observations = {}
        elapsed = (now-started)*1000
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError('Local elapsed time')
        for item in response['observations']:
            checked('Observation', item)
            name = item['capability_id']
            if (name in observations or name not in caps or item['source_boot_id'] != boot
                    or item['connection_id'] != self.connection or item['catalog_generation'] != generation
                    or item['challenge_id'] != request['challenge_id']
                    or item['sequence'] <= sequences.get(name, -1)):
                raise ValueError('Replayed or unregistered scalar observation')
            if type(item['value']) is bool:
                raise ValueError('metric.scalar requires a number')
            bounds = caps[name]['range']
            if item['value'] is not None and bounds is not None and not bounds[0] <= item['value'] <= bounds[1]:
                raise ValueError('Scalar value outside descriptor range')
            observations[name] = item
            sequences[name] = item['sequence']
        if len(sequences) > 64:
            raise ValueError('Sequence history exhausted; new source boot required')
        events = []
        for selection in expected['selected']:
            name = selection['id']; cap = caps[name]; item = observations.get(name)
            availability = cap['availability']
            ttl = min(cap['ttl_ms'], self.reader.settings.get('policy_ttl_ms', 1500),
                      item['ttl_ms'] if item else 60000)
            age = None
            if selection['status'] == 'unsupported':
                if item is not None:raise ValueError('Unsupported source sent a value')
                availability = 'unsupported'
            elif item is None:
                availability = 'unknown' if availability == 'available' else availability
            else:
                if availability == 'available':availability = item['availability']
                error = self.reader.settings.get('clock_error_ms')
                if error is not None and item['age_at_send_ms'] is not None and item['time_basis'] != 'unknown':
                    age = math.ceil(item['age_at_send_ms']+elapsed+error)
                if availability == 'available' and age is None:availability = 'unknown'
            metadata = dict(reader=self.name, capability_id=name, description=cap['description'], unit=cap['unit'],
                            source_boot_id=boot, connection_id=self.connection, catalog_generation=generation,
                            sequence=item['sequence'] if item else None, support=selection['status'],
                            major=cap['version']['major'], minor=selection['minor'], semantic=cap['semantic'],
                            time_basis=item['time_basis'] if item else 'unknown',
                            value=item['value'] if item and availability == 'available' else None)
            summary = json.dumps(dict(value=metadata['value'], unit=cap['unit']), ensure_ascii=False)
            validate('ScalarMetadata',metadata)
            if len(summary)>256:raise ValueError('Scalar summary bound')
            events.append(dict(type='sensor', id=runtime_id(self.name, name), source_id=self.source,
                               availability=availability, age_ms=age or 0, ttl_ms=ttl,
                               summary=summary if availability == 'available' else '', scalar=metadata))
        return events, ids, boot, generation, fingerprint, sequences

    def commit(self, candidate, scheduler, now):
        events, ids, boot, generation, fingerprint, sequences = candidate
        removed = self.ids-ids
        # Reserve cleanup ownership before the first ingest. If any consumer
        # unexpectedly fails, Services.withdraw removes the entire union,
        # including new IDs that have not reached the successful commit yet.
        self.ids |= ids
        for name in removed:scheduler.ingest(dict(type='sensor_remove', id=name), now)
        for event in events:scheduler.ingest(event, now)
        if self.boot is not None and self.boot != boot:self.retired_boots.add(self.boot)
        self.ids, self.boot, self.generation = ids, boot, generation
        self.catalog_digest, self.sequences = fingerprint, sequences


def source_response(request, capabilities, observations, boot, generation):
    """Stateless source-side acknowledgement used by camera and loopback adapters.

    observations are the current bounded measurement set; this helper owns no
    capture resource, connection history or task queue.
    """
    if not isinstance(request, dict) or type(request.get('protocol')) is not int or request['protocol'] != 1:
        raise ValueError('Scalar request protocol')
    if request.get('kind') == 'catalog_request' and set(request) == {'kind','protocol','connection_id'}:
        connection = request['connection_id']
        catalog = dict(kind='catalog', protocol=1, connection_id=connection, source_boot_id=boot,
                       catalog_generation=generation, capabilities=capabilities)
        return catalog_checked(catalog, connection, MAX_CAPABILITIES)
    if request.get('kind') != 'observation_request' or set(request) != {'kind','protocol','agreement'}:
        raise ValueError('Scalar request shape')
    ack = request['agreement']
    catalog = dict(kind='catalog', protocol=1, connection_id=ack['connection_id'], source_boot_id=boot,
                   catalog_generation=generation, capabilities=capabilities)
    expected = agreement(catalog, dict(connection_id=ack['connection_id'], challenge_id=ack['challenge_id'],
                                      max_capabilities=MAX_CAPABILITIES, supported=SUPPORTED))
    if ack != expected:raise ValueError('Source catalog changed or unsupported agreement')
    supported = {c['id'] for c in expected['selected'] if c['status'] != 'unsupported'}
    values = [dict(item, connection_id=ack['connection_id'], challenge_id=ack['challenge_id'])
              for item in observations if item['capability_id'] in supported]
    return dict(kind='scalar_snapshot', protocol=1, ack=expected, observations=values)
