"""Real HTTP timing metadata is distinct from ping or Internet reachability."""
import json
import unittest

from reachy_companion.autonomous.network_observation import NetworkObservation
from reachy_companion.autonomous.state import State


class NetworkObservationTests(unittest.TestCase):
    def test_targets_age_independently_and_failure_replaces_success(self):
        network=NetworkObservation()
        self.assertEqual(network.status(0)['compute']['state'],'unknown')
        network.observe('compute',1,1.02,True)
        network.observe('robot',3,3.01,True)
        view=network.status(3.02)
        self.assertEqual(view['compute']['state'],'stale')
        self.assertEqual(view['robot']['state'],'reachable')
        self.assertEqual(view['robot']['elapsed_ms'],10)
        self.assertEqual(view['internet'],'unknown')
        network.observe('compute',3,4,False)
        self.assertEqual(network.status(4)['compute']['state'],'failed')
        self.assertEqual(network.status(6)['robot']['state'],'stale')

    def test_snapshot_has_ttl_and_privacy_discards_network_sensor(self):
        network=NetworkObservation();network.observe('compute',1,1.1,True)
        state=State();event=network.event(1.1)
        self.assertLessEqual(len(event['summary']),256)
        state.ingest(event,1.1)
        sensor=state.sensors['network']
        self.assertEqual(sensor.view(1.2,False)['state'],'ready')
        summary=json.loads(sensor.summary)
        self.assertEqual(summary['http']['compute']['state'],'reachable')
        self.assertEqual(summary['http']['robot']['state'],'unknown')
        self.assertEqual(sensor.view(2.7,False)['state'],'stale')
        self.assertEqual(sensor.view(2.7,False)['summary'],'')
        state.privacy=True;state.ingest(event,3)
        self.assertEqual(state.sensors['network'].availability,'disabled')


if __name__=='__main__':unittest.main()
