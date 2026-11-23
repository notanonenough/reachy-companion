"""Finite CONTRACT-01 design vectors, not a registry or transport implementation.

No sockets, devices or model calls. Helpers specify admission rules for future
adapters; only the final scalar projection exercises existing State/Sensor code.
"""
from collections import deque
import copy
import hashlib
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


def catalog_checked(value):
    checked('Catalog', value)
    ids = set()
    for cap in value['capabilities']:
        if (cap['id'] in ids or cap['catalog_generation'] != value['catalog_generation']
                or cap['source_boot_id'] != value['source_boot_id']):
            raise ValueError('Mixed or ambiguous catalog snapshot')
        ids.add(cap['id'])
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


def descriptor_digest(capability):
    return hashlib.sha256(json.dumps(capability, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def confirmed_agreement(capability, supported, receiver):
    """Trusted handshake fixture, not a peer-supplied permission or self-ack."""
    result = negotiate(capability, supported)
    return dict(connection_id=receiver['connection_id'], source_boot_id=capability['source_boot_id'],
                catalog_generation=capability['catalog_generation'], capability_id=capability['id'],
                semantic=capability['semantic'], major=capability['version']['major'],
                minor=result['minor'], status=result['status'], descriptor_digest=descriptor_digest(capability))


def capability_confirmed(capability, receiver):
    checked('Capability', capability)
    agreement = receiver['agreements'].get(capability['id'])
    expected = confirmed_agreement(capability, receiver['supported'], receiver)
    return (agreement == expected and expected['status'] in ('supported', 'limited')
            and capability['catalog_generation'] == receiver['catalog_generation'])


def effective_ttl(message, receiver, capability=None):
    policy = receiver['policy_ttl_ms']
    if type(policy) is not int or not 1 <= policy <= 60000:
        raise ValueError('Bounded local policy required')
    return min(message['ttl_ms'], policy, capability['ttl_ms'] if capability else policy)


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
    if not capability_confirmed(capability, receiver):
        raise ValueError('Capability not confirmed for this connection')
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
    ttl = effective_ttl(message, receiver, capability)
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
    return bool(capability_confirmed(capability, receiver)
                and negotiate(capability, supported)['status'] != 'unsupported'
                and capability['direction'] == 'executor' and capability['availability'] == 'available'
                and capability['source_boot_id'] == authority.robot_boot_id
                and shape is not None and Draft202012Validator(shape).is_valid(command['arguments'])
                and command['capability_id'] == capability['id']
                and command['catalog_generation'] == receiver['catalog_generation']
                and capability['catalog_generation'] == receiver['catalog_generation']
                and command['authority'] == authority.wire()
                and command['generation'] == generation
                and command['operation'] in capability['operations']
                and age is not None and age < effective_ttl(command, receiver, capability)
                and permit and permit['allowed']
                and permit['capability_id'] == capability['id']
                and permit['id'] == command['permit_id'] and permit['epoch'] == command['permit_epoch']
                and permit['generation'] == generation
                and receiver['received_mono_ms'] < permit['expires_mono_ms'])


def owned_control_admitted(command, receiver, authority, owned):
    """Cancels an authenticated owner's known scope, even after actuation revoke.

    An existing local ownership record is required. No new physical target is
    admitted and no live movement permit is required for this finite example.
    """
    checked('Command', command)
    age = upper_age(command, receiver)
    return bool(command['operation'] == 'cancel' and owned
                and command['arguments'] == {'target_command_id': owned['command_id']}
                and command['capability_id'] == owned['capability_id']
                and command['generation'] == owned['generation']
                and command['authority'] == authority.wire()
                and owned['authority']['hub_boot_id'] == authority.hub_boot_id
                and owned['authority']['robot_boot_id'] == authority.robot_boot_id
                and age is not None and age < effective_ttl(command, receiver))


def receipt_replay(original, receipt, repeated):
    if repeated != original:
        raise ValueError('Same command id with different content')
    return copy.deepcopy(receipt)  # Receipt only: no second execution.


class RobotHubContractTests(unittest.TestCase):
    def setUp(self):
        self.values = copy.deepcopy(EXAMPLES)
        self.caps = {c['module']: c for c in self.values['capabilities']}
        for key in ('receiver', 'command_receiver'):
            receiver = self.values[key]
            receiver['supported'] = self.values['hub_supported']
            receiver['agreements'] = {cap['id']: confirmed_agreement(cap, receiver['supported'], receiver)
                                      for cap in self.caps.values()}

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

    def test_catalog_is_one_bounded_snapshot_without_duplicate_or_mixed_boot_entries(self):
        catalog = dict(kind='catalog', protocol=1, connection_id='link-2', catalog_generation=3,
                       source_boot_id='robot-boot-1', capabilities=self.values['capabilities'])
        catalog_checked(catalog)
        for capabilities in (catalog['capabilities'] + [catalog['capabilities'][0]],
                             [{**catalog['capabilities'][0], 'source_boot_id': 'old-boot'}]):
            with self.assertRaises(ValueError): catalog_checked({**catalog, 'capabilities': capabilities})
        with self.assertRaises(ValueError):
            catalog_checked({**catalog, 'capabilities': [catalog['capabilities'][0]] * 65})

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
        projected = next(s for s in state.snapshot(1.050)['sensors'] if s['id'] == cap['id'])
        self.assertEqual(json.loads(projected['summary'])['value'], 22.5)
        self.assertEqual(sensor.view(3.040, False)['state'], 'stale')

    def test_observations_require_current_confirmed_catalog_not_an_announced_descriptor(self):
        message, receiver, cap = self.values['observation'], self.values['receiver'], self.caps['metrics']
        with self.assertRaises(ValueError):
            observation_event(message, cap, {**receiver, 'agreements': {}})
        unknown = {**cap, 'semantic': 'unimplemented.scalar'}
        unsupported = {**receiver, 'agreements': {cap['id']: confirmed_agreement(unknown, receiver['supported'], receiver)}}
        for current in (receiver, unsupported):
            with self.assertRaises(ValueError): observation_event(message, unknown, current)
        for patch in ({'connection_id': 'old-link'}, {'source_boot_id': 'old-boot'},
                      {'catalog_generation': 2}, {'minor': 99}, {'status': 'unsupported'}):
            ack = {**receiver['agreements'][cap['id']], **patch}
            with self.assertRaises(ValueError):
                observation_event(message, cap, {**receiver, 'agreements': {cap['id']: ack}})

    def test_local_ttl_caps_both_observations_and_new_actions_including_exact_expiry(self):
        message, receiver, cap = self.values['observation'], self.values['receiver'], self.caps['metrics']
        for ttl in (50, 62):
            with self.assertRaises(ValueError):
                observation_event(message, cap, {**receiver, 'policy_ttl_ms': ttl})
        event = observation_event(message, cap, {**receiver, 'policy_ttl_ms': 63})
        self.assertEqual(event['ttl_ms'], 63)
        command = self.values['command']; authority = Authority(**command['authority'])
        for ttl in (50, 52):
            self.assertFalse(command_admitted(command, self.caps['motion'], self.values['hub_supported'],
                {**self.values['command_receiver'], 'policy_ttl_ms': ttl}, authority, self.values['permit'], 4))

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
        current['agreements'] = {cap['id']: confirmed_agreement(cap, current['supported'], current)}
        self.assertEqual(observation_event(new, cap, current)['availability'], 'available')

    def test_unknown_age_value_and_source_receipt_are_not_fabricated_sample_time(self):
        message, receiver = self.values['observation'], self.values['receiver']
        for patch in ({'age_at_send_ms': None}, {'challenge_id': 'unknown'}, {'time_basis': 'unknown'}):
            event = observation_event({**message, **patch}, self.caps['metrics'], receiver)
            state = State(); state.ingest(event, 1.040)
            self.assertEqual(state.sensors['room.temperature'].view(1.040, False)['state'], 'unknown')
            self.assertEqual(state.sensors['room.temperature'].summary, '')
        offline_cap = {**self.caps['metrics'], 'availability': 'offline', 'catalog_generation': 4}
        offline_receiver = {**receiver, 'catalog_generation': 4}
        offline_receiver['agreements'] = {offline_cap['id']: confirmed_agreement(offline_cap, receiver['supported'], offline_receiver)}
        offline = observation_event({**message, 'catalog_generation': 4}, offline_cap, offline_receiver)
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

    def test_owner_cancel_survives_revoke_but_never_crosses_owner_or_action_scope(self):
        owned = self.values['command']; authority = Authority(**owned['authority'])
        cancel = {**owned, 'command_id': 'cancel-1', 'operation': 'cancel',
                  'arguments': {'target_command_id': owned['command_id']},
                  'permit_id': None, 'permit_epoch': None}
        receiver = self.values['command_receiver']
        # Expired/revoked permit blocks a new target, but it is not a cancel prerequisite.
        revoked = {**self.values['permit'], 'allowed': False, 'expires_mono_ms': 0}
        self.assertFalse(command_admitted(owned, self.caps['motion'], self.values['hub_supported'],
                                         receiver, authority, revoked, 4))
        self.assertTrue(owned_control_admitted(cancel, receiver, authority, owned))
        self.assertFalse(owned_control_admitted(cancel, receiver, authority, None))
        for patch in ({'capability_id': 'other.motion'}, {'generation': 5},
                      {'arguments': {'target_command_id': 'other-command'}}, {'operation': 'target'},
                      {'authority': {**owned['authority'], 'hub_boot_id': 'other-owner'}}):
            self.assertFalse(owned_control_admitted({**cancel, **patch}, receiver, authority, owned))
        foreign = {**owned, 'authority': {**owned['authority'], 'hub_boot_id': 'other-owner'}}
        self.assertFalse(owned_control_admitted(cancel, receiver, authority, foreign))
        self.assertFalse(owned_control_admitted(cancel, {**receiver, 'policy_ttl_ms': 10}, authority, owned))

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
