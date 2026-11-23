import unittest
import numpy as np
from reachy_companion.autonomous.camera_sensor import Measurements
from reachy_companion.autonomous.contracts import Sensor


class MeasurementTests(unittest.TestCase):
    def test_frame_changes_expiry_duplicate_and_no_capture_claim(self):
        cache=Measurements();pixels=np.zeros((720,1280,3),dtype=np.uint8)
        self.assertTrue(cache.publish(pixels,1,('owner',),10))
        self.assertFalse(cache.publish(pixels,1,('owner',),11))
        self.assertTrue(cache.publish(pixels+255,2,('owner',),11))
        view=cache.snapshot(11.2)
        self.assertIn('image_change=1.000',view['summary'])
        self.assertIn('exposure age unknown',view['summary'])
        self.assertLessEqual(len(view['summary']),256)
        self.assertEqual(view['availability'],'available')
        self.assertEqual(cache.snapshot(11.2,('new-camera-generation',))['availability'],'disabled')
        self.assertEqual(cache.snapshot(13)['availability'],'offline')
        self.assertTrue(cache.publish(pixels,0,('new owner',),14))
        self.assertIn('image_change=unknown',cache.snapshot(14)['summary'])
        cache.clear();self.assertEqual(cache.snapshot(14)['availability'],'unknown')

    def test_unknown_pts_and_invalid_geometry_are_not_observations(self):
        cache=Measurements()
        self.assertFalse(cache.publish(np.zeros((720,1280,3),dtype=np.uint8),None,'owner',10))
        self.assertEqual(cache.snapshot(10)['availability'],'unknown')
        with self.assertRaises(ValueError):cache.publish(np.zeros((4,4,3),dtype=np.uint8),1,'owner',10)

class S3EndpointTests(unittest.TestCase):
    def test_yandex_file_credentials_and_https_validation(self):
        import tempfile
        from pathlib import Path
        from reachy_companion.autonomous.durable import Delivery
        with tempfile.TemporaryDirectory() as directory:
            access=Path(directory)/'pub';secret=Path(directory)/'priv'
            access.write_text('fixture-access');secret.write_text('fixture-secret')
            settings=dict(bucket='reachy-test',region='ru-central1',endpoint='https://storage.yandexcloud.net',
                          prefix='robot/events',access_key_file=str(access),secret_key_file=str(secret))
            delivery=Delivery('s3',settings)
            request=delivery.s3_request('event',{'id':'event'})
            self.assertEqual(request.full_url,'https://storage.yandexcloud.net/reachy-test/robot/events/event.json')
            self.assertIn('/ru-central1/s3/aws4_request',request.get_header('Authorization'))
            before=request.get_header('Authorization')
            secret.write_text('rotated-secret')
            self.assertNotEqual(delivery.s3_request('event',{'id':'event'}).get_header('Authorization'),before)
            for endpoint in ('http://storage.yandexcloud.net','https://user:pass@example.org','https://example.org/path','https://example.org?secret=x'):
                with self.subTest(endpoint=endpoint),self.assertRaises(ValueError):Delivery('s3',{**settings,'endpoint':endpoint})

class S3RelayTests(unittest.TestCase):
    def test_authenticated_metadata_only_relay_requires_actual_delivery(self):
        import json
        import os
        from pathlib import Path
        import threading
        from unittest.mock import patch
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        from reachy_companion.autonomous.config import load
        from reachy_companion.autonomous.gateway import create_server
        from reachy_companion.autonomous.durable import Delivery
        cfg=load(Path(__file__).parents[1]/'config.autonomous.normal.example.json')
        cfg['context']['enabled']=False;cfg['gateway']['port']=0
        cfg['gateway']['log_s3']=dict(bucket='fixture',region='ru-central1',endpoint='https://storage.yandexcloud.net')
        token='test-only-token-'*3
        with patch.dict(os.environ,{cfg['gateway']['token_env']:token}),patch.object(Delivery,'__call__',side_effect=lambda i,b:i) as send:
            server=create_server(cfg);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            event_id='00000000-0000-0000-0000-000000000001'
            url='http://127.0.0.1:'+str(server.server_port)+'/logs/'+event_id
            def put(body,credential=token):
                request=Request(url,data=json.dumps(body).encode(),method='PUT',headers={'Authorization':'Bearer '+credential})
                with urlopen(request,timeout=2) as response:return json.load(response)
            try:
                body=dict(id=event_id,metadata=dict(kind='decision_accepted',activity='wait'))
                with self.assertRaises(HTTPError) as error:put(body,'wrong')
                self.assertEqual(error.exception.code,401);send.assert_not_called()
                with self.assertRaises(HTTPError):put(dict(id=event_id,metadata=dict(transcript='must not export')))
                send.assert_not_called()
                self.assertEqual(put(body),dict(accepted=True,id=event_id));send.assert_called_once_with(event_id,body)
                batch=dict(id=event_id,events=[body])
                self.assertEqual(put(batch),dict(accepted=True,id=event_id))
                with self.assertRaises(HTTPError):put(dict(id=event_id,events=[body]*33))
                send.side_effect=OSError('offline')
                with self.assertRaises(HTTPError) as error:put(body)
                self.assertEqual(error.exception.code,503)
            finally:server.shutdown();server.server_close();thread.join(2)

class ComputeAwakeTests(unittest.TestCase):
    def test_idle_sleep_assertion_is_scoped_to_gateway_child(self):
        import io
        import tempfile
        from pathlib import Path
        from unittest.mock import Mock,patch
        from reachy_companion.production_logs import run_logged
        child=Mock(pid=4242,stdout=io.BytesIO(b''));child.wait.return_value=0;child.poll.return_value=0
        awake=Mock();awake.poll.return_value=None
        with tempfile.TemporaryDirectory() as directory,patch('reachy_companion.production_logs.sys.platform','darwin'),patch(
                'reachy_companion.production_logs.subprocess.Popen',side_effect=[child,awake]) as popen:
            self.assertEqual(run_logged(Path(directory)/'gateway.log',['fixture'],keep_awake=True),0)
            self.assertEqual(popen.call_args_list[1].args[0],['/usr/bin/caffeinate','-i','-w','4242'])
            awake.terminate.assert_called_once();awake.wait.assert_called_once_with(timeout=2)
