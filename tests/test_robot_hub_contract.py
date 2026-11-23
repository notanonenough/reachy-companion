"""Finite CONTRACT-01 design vectors, not a registry or transport implementation.

No sockets, devices or model calls. Helpers specify admission rules for future
adapters; only the final scalar projection exercises existing State/Sensor code.
"""
from collections import deque
import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, ValidationError
from reachy_companion.autonomous.contracts import Authority, decode
from reachy_companion.autonomous.state import State

ROOT = Path(__file__).parent / 'fixtures' / 'robot_hub_contract'
SCHEMA = decode((ROOT / 'envelopes.schema.json').read_text())
EXAMPLES = decode((ROOT / 'examples.json').read_text())


def checked(kind, value):
    if len(json.dumps(value, allow_nan=False).encode()) > 16384:
        raise ValueError('Envelope byte bound')
    Draft202012Validator({**SCHEMA, 'oneOf': [{'$ref': '#/$defs/' + kind}]}).validate(value)
    return value


def negotiate(capability, supported):
    """Type support is distinct from the identity or permission of an adapter."""
    checked('Capability', capability)
    version = capability['version']
    if version['min_minor'] > version['minor']:
        raise ValueError('Invalid compatibility interval')
    local = supported.get(capability['semantic'])
    if (not local or local['major'] != version['major']
            or local['max_minor'] < version['min_minor']):
        return dict(status='unsupported', minor=None, blocked=capability['required_for'], reason='incompatible_semantic_version')
    minor = min(local['max_minor'], version['minor'])
    return dict(status='supported' if minor == version['minor'] else 'limited',
                minor=minor, blocked=[], reason=None if minor == version['minor'] else 'minor_downgrade')


def upper_age(message, receiver):
    """A causal challenge RTT uses only receiver-local monotonic times."""
    source_boot = message.get('source_boot_id', message.get('authority', {}).get('hub_boot_id'))
    if (source_boot != receiver['challenge_source_boot_id']
            or message['connection_id'] != receiver['connection_id']
            or message['challenge_id'] != receiver['challenge_id']
            or message['age_at_send_ms'] is None):
        return None
    elapsed = receiver['received_mono_ms'] - receiver['challenge_sent_mono_ms']
    if elapsed < 0 or receiver['clock_error_ms'] is None:
        return None
    return message['age_at_send_ms'] + elapsed + receiver['clock_error_ms']


def observation_event(message, capability, receiver):
    """Design projection into the existing ingestion shape; not wired to Services."""
    checked('Observation', message)
    if (message['capability_id'] != capability['id']
            or message['catalog_generation'] != receiver['catalog_generation']
            or capability['catalog_generation'] != receiver['catalog_generation']
            or message['source_boot_id'] != capability['source_boot_id']
            or message['source_boot_id'] != receiver['source_boot_id']
            or message['connection_id'] != receiver['connection_id']
            or message['sequence'] <= receiver['last_sequence']):
        raise ValueError('Old or unregistered observation')
    age = upper_age(message, receiver)
    availability = message['availability'] if capability['availability'] == 'available' else capability['availability']
    ttl = min(message['ttl_ms'], capability['ttl_ms'])
    if availability == 'available':
        if message['value'] is None:
            raise ValueError('Available scalar requires a value')
        if age is None or message['time_basis'] == 'unknown':
            availability = 'unknown'
        elif age >= ttl:
            raise ValueError('Expired observation')
    summary = json.dumps(dict(value=message['value'], unit=capability['unit'],
                              confidence=message['confidence'], time_basis=message['time_basis']))
    return dict(type='sensor', id=capability['id'], source_id=message['source_boot_id'],
                availability=availability, age_ms=age or 0, ttl_ms=ttl,
                summary=summary if availability == 'available' else '')


def command_admitted(command, capability, supported, receiver, authority, permit, generation):
    checked('Command', command)
    age = upper_age(command, receiver)
    shape = EXAMPLES['argument_schemas'].get(capability['semantic'], {}).get(command['operation'])
    return bool(negotiate(capability, supported)['status'] != 'unsupported'
                and capability['direction'] == 'executor' and capability['availability'] == 'available'
                and capability['source_boot_id'] == authority.robot_boot_id
                and shape is not None and Draft202012Validator(shape).is_valid(command['arguments'])
                and command['capability_id'] == capability['id']
                and command['catalog_generation'] == receiver['catalog_generation']
                and capability['catalog_generation'] == receiver['catalog_generation']
                and command['authority'] == authority.wire()
                and command['generation'] == generation
                and command['operation'] in capability['operations']
                and age is not None and age < min(command['ttl_ms'], capability['ttl_ms'])
                and permit and permit['allowed']
                and permit['capability_id'] == capability['id']
                and permit['id'] == command['permit_id'] and permit['epoch'] == command['permit_epoch']
                and permit['generation'] == generation
                and receiver['received_mono_ms'] < permit['expires_mono_ms'])


def receipt_replay(original, receipt, repeated):
    if repeated != original:
        raise ValueError('Same command id with different content')
    return copy.deepcopy(receipt)  # Receipt only: no second execution.


class RobotHubContractTests(unittest.TestCase):
    def setUp(self):
        self.values = copy.deepcopy(EXAMPLES)
        self.caps = {c['module']: c for c in self.values['capabilities']}

    def test_six_descriptors_and_envelopes_are_bounded_and_valid(self):
        Draft202012Validator.check_schema(SCHEMA)
        self.assertEqual(set(self.caps), {'permissions','motion','playback','audio_capture','video','metrics'})
        for cap in self.caps.values():
            checked('Capability', cap)
            self.assertEqual(negotiate(cap, self.values['hub_supported'])['status'], 'supported')
        for kind in ('Observation','Command','Result'):
            checked(kind, self.values[kind.lower()])
        bad = {**self.values['observation'], 'value': float('inf')}
        with self.assertRaises(ValueError): decode(json.dumps(bad))
        for patch in ({'protocol': 2}, {'confidence': 2}, {'sequence': -1}, {'surprise': True}):
            with self.assertRaises(ValidationError): checked('Observation', {**self.values['observation'], **patch})

    def test_new_scalar_sensor_reaches_existing_state_without_a_new_sensor_branch(self):
        cap = self.caps['metrics']
        self.assertEqual(cap['id'], 'room.temperature')
        self.assertEqual(negotiate(cap, self.values['hub_supported'])['status'], 'supported')
        event = observation_event(self.values['observation'], cap, self.values['receiver'])
        self.assertEqual(event['age_ms'], 62)  # 20 source + 40 causal RTT + 2 drift budget.
        state = State(); state.ingest(event, 1.040)
        sensor = state.sensors['room.temperature']
        view = sensor.view(1.050, False)
        self.assertEqual(view['state'], 'ready')
        self.assertEqual(json.loads(view['summary'])['value'], 22.5)
        self.assertEqual(json.loads(view['summary'])['unit'], 'Cel')
        self.assertEqual(sensor.view(3.040, False)['state'], 'stale')

    def test_older_hub_reports_unknown_actuator_and_limits_only_its_dependent_mode(self):
        cap = {**self.caps['motion'], 'id': 'fixture.gripper', 'semantic': 'motion.gripper',
               'required_for': ['grasp']}
        result = negotiate(cap, self.values['hub_supported'])
        self.assertEqual(result, dict(status='unsupported', minor=None, blocked=['grasp'], reason='incompatible_semantic_version'))
        self.assertNotIn('dialogue', result['blocked'])
        cap['required_for'] = []
        self.assertEqual(negotiate(cap, self.values['hub_supported'])['blocked'], [])
        self.assertEqual(negotiate(self.caps['metrics'], self.values['hub_supported'])['status'], 'supported')

    def test_version_negotiation_never_silently_ignores_required_semantics(self):
        cap = self.caps['metrics']
        cap['version'] = dict(major=1, minor=2, min_minor=0)
        self.assertEqual(negotiate(cap, self.values['hub_supported'])['status'], 'limited')
        cap['version']['min_minor'] = 1
        self.assertEqual(negotiate(cap, self.values['hub_supported'])['status'], 'unsupported')
        cap['version'] = dict(major=2, minor=0, min_minor=0)
        self.assertEqual(negotiate(cap, self.values['hub_supported'])['status'], 'unsupported')

    def test_stale_repeated_reconnected_and_old_boot_data_do_not_refresh_cache(self):
        message, receiver = self.values['observation'], self.values['receiver']
        for patch in ({'sequence': 7}, {'connection_id': 'old-link'},
                      {'source_boot_id': 'old-boot'}, {'catalog_generation': 2}, {'age_at_send_ms': 1999}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                observation_event({**message, **patch}, self.caps['metrics'], receiver)
        cap = {**self.caps['metrics'], 'source_boot_id': 'robot-boot-2', 'catalog_generation': 4}
        new = {**message, 'source_boot_id': 'robot-boot-2', 'catalog_generation': 4, 'sequence': 0,
               'challenge_id': 'fresh-boot-challenge'}
        current = {**receiver, 'source_boot_id': 'robot-boot-2', 'catalog_generation': 4, 'last_sequence': -1,
                   'challenge_source_boot_id': 'robot-boot-2', 'challenge_id': 'fresh-boot-challenge'}
        self.assertEqual(observation_event(new, cap, current)['availability'], 'available')

    def test_unknown_age_value_and_source_receipt_are_not_fabricated_sample_time(self):
        message, receiver = self.values['observation'], self.values['receiver']
        for patch in ({'age_at_send_ms': None}, {'challenge_id': 'unknown'}, {'time_basis': 'unknown'}):
            event = observation_event({**message, **patch}, self.caps['metrics'], receiver)
            state = State(); state.ingest(event, 1.040)
            self.assertEqual(state.sensors['room.temperature'].view(1.040, False)['state'], 'unknown')
            self.assertEqual(state.sensors['room.temperature'].summary, '')
        offline = observation_event(message, {**self.caps['metrics'], 'availability': 'offline'}, receiver)
        self.assertEqual((offline['availability'], offline['summary']), ('offline', ''))
        unavailable = observation_event({**message, 'availability': 'unknown', 'value': None, 'reason': 'no sample'},
                                        self.caps['metrics'], receiver)
        self.assertEqual(unavailable['availability'], 'unknown')
        event = observation_event({**message, 'value': 0}, self.caps['metrics'], receiver)
        self.assertEqual(json.loads(event['summary'])['value'], 0)
        with self.assertRaises(ValidationError):
            observation_event({**message, 'value': None}, self.caps['metrics'], receiver)
        event = observation_event({**message, 'time_basis': 'source_receipt', 'sample_mono_ms': None},
                                  self.caps['metrics'], receiver)
        self.assertEqual(json.loads(event['summary'])['time_basis'], 'source_receipt')

    def test_registration_never_grants_motion_and_revoke_or_replace_rejects_late_command(self):
        command, receiver, permit = (self.values[n] for n in ('command','command_receiver','permit'))
        authority = Authority(**command['authority'])
        allowed = lambda c=command, p=permit, g=4: command_admitted(c, self.caps['motion'],
                         self.values['hub_supported'], receiver, authority, p, g)
        self.assertTrue(allowed())
        self.assertFalse(allowed(p=None))
        self.assertFalse(allowed(p={**permit, 'allowed': False}))
        self.assertFalse(allowed(p={**permit, 'epoch': 6}))
        self.assertFalse(allowed(p={**permit, 'expires_mono_ms': 1040}))
        self.assertFalse(allowed(g=5))
        self.assertFalse(allowed(c={**command, 'age_at_send_ms': 500}))
        self.assertFalse(allowed(c={**command, 'authority': {**command['authority'], 'robot_boot_id': 'old'}}))
        self.assertFalse(allowed(c={**command, 'connection_id': 'old-link'}))
        self.assertFalse(allowed(c={**command, 'arguments': {'yaw_rad': 0.4}}))
        self.assertFalse(allowed(c={**command, 'arguments': {'yaw_rad': 0.1, 'execute': True}}))

    def test_duplicate_unknown_result_is_a_receipt_not_reexecution_or_physical_proof(self):
        command = self.values['command']
        receipt = {**self.values['result'], 'status': 'unknown', 'reason': 'lost completion'}
        checked('Result', receipt)
        self.assertEqual(receipt_replay(command, receipt, command), receipt)
        self.assertFalse(receipt['physical_verified'])
        with self.assertRaises(ValueError):
            receipt_replay(command, receipt, {**command, 'arguments': {'yaw_rad': .2}})
        self.assertFalse(self.values['result']['physical_verified'])
        self.assertEqual(self.values['result']['status'], 'accepted')
        with self.assertRaises(ValidationError):
            checked('Result', {**self.values['result'], 'physical_verified': True})

    def test_slow_metric_consumer_keeps_last_value_and_counts_replacement_separately_from_control(self):
        # An executable policy trace; it does not certify a production queue.
        latest = deque(maxlen=1); replaced = 0; control = deque(maxlen=1)
        for sequence in (8, 9, 10):
            replaced += len(latest)
            latest.append({**self.values['observation'], 'sequence': sequence})
        control.append('revoke')
        self.assertEqual(control.popleft(), 'revoke')
        self.assertEqual((len(latest), latest[0]['sequence'], replaced), (1, 10, 2))


if __name__ == '__main__': unittest.main()
