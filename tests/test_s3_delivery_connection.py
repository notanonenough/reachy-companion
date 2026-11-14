"""S3 transport receipts, reconnection and bounded failure; no cloud writes."""
import http.client
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from reachy_companion.autonomous.durable import Delivery


def response(status=200):
    value=MagicMock(status=status,will_close=False,headers={})
    value.read.return_value=b''
    return value


class S3ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict('os.environ',{'AWS_ACCESS_KEY_ID':'fixture-access',
            'AWS_SECRET_ACCESS_KEY':'fixture-secret'},clear=True)
        self.env.start();self.addCleanup(self.env.stop)
        self.sink=Delivery('s3',dict(bucket='fixture-logs',region='eu-central-1'))

    def test_successive_batches_reuse_one_tls_connection(self):
        connection=MagicMock();connection.getresponse.return_value=response()
        with patch('reachy_companion.autonomous.durable.http.client.HTTPSConnection',return_value=connection) as factory:
            for identity in ('first','second'):
                self.assertEqual(self.sink(identity,{'id':identity}),identity)
        self.assertEqual(factory.call_count,1)
        self.assertEqual(connection.request.call_count,2)
        connection.close.assert_not_called()

    def test_unknown_put_receipt_retries_same_object_and_payload(self):
        first=MagicMock();first.getresponse.side_effect=TimeoutError('receipt lost')
        second=MagicMock();second.getresponse.return_value=response()
        body={'id':'same-event','metadata':{'kind':'decision'}}
        with patch('reachy_companion.autonomous.durable.http.client.HTTPSConnection',side_effect=[first,second]):
            self.assertEqual(self.sink('same-event',body),'same-event')
        first.close.assert_called_once()
        a,b=first.request.call_args,second.request.call_args
        self.assertEqual(a.args,b.args)
        self.assertEqual(a.kwargs['body'],b.kwargs['body'])
        self.assertEqual(json.loads(b.kwargs['body']),body)

    def test_repeated_disconnect_never_acknowledges_or_loops(self):
        connections=[MagicMock(),MagicMock()]
        for connection in connections:
            connection.getresponse.side_effect=http.client.RemoteDisconnected('closed')
        with patch('reachy_companion.autonomous.durable.http.client.HTTPSConnection',side_effect=connections) as factory:
            with self.assertRaises(http.client.RemoteDisconnected):self.sink('event',{'id':'event'})
        self.assertEqual(factory.call_count,2)
        for connection in connections:connection.close.assert_called_once()
        self.assertIsNone(self.sink.s3_connection)

    def test_rejection_does_not_retry_or_acknowledge(self):
        connection=MagicMock();connection.getresponse.return_value=response(403)
        with patch('reachy_companion.autonomous.durable.http.client.HTTPSConnection',return_value=connection) as factory:
            with self.assertRaises(HTTPError):self.sink('event',{'id':'event'})
        self.assertEqual(factory.call_count,1)
        connection.close.assert_called_once()

    def test_relay_waits_for_reconnect_but_requires_exact_receipt(self):
        sink=Delivery('s3',dict(relay=True,url='http://127.0.0.1:8097/logs/{id}',token_env='RELAY_TOKEN'))
        sink.opener=MagicMock()
        sink.opener.open.return_value.__enter__.return_value.status=200
        sink.opener.open.return_value.__enter__.return_value.read.return_value=b'{"accepted":true,"id":"other-event"}'
        with patch.dict('os.environ',{'RELAY_TOKEN':'fixture'}):
            with self.assertRaises(ValueError):sink('event',{'id':'event'})
        self.assertEqual(sink.opener.open.call_args.kwargs['timeout'],12)


if __name__=='__main__':unittest.main()
