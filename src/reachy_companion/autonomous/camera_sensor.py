"""Robot camera stream measurements, without audio, actuators or stored frames.

TTL describes receipt of a stream frame, not the unverified exposure timestamp.
Numeric measurements and one bounded in-memory JPEG are available to local consumers.
"""
import argparse
import base64
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import signal
import threading
import time
from uuid import uuid4
from urllib.request import Request, build_opener, ProxyHandler


class Measurements:
    def __init__(self):
        self.lock=threading.Lock()
        self.latest=None
        self.previous=None
        self.binding=None
        self.sequence=None
        self.jpeg=None;self.generation=str(uuid4())

    def clear(self):
        with self.lock:
            self.latest=self.previous=self.binding=self.sequence=None
            self.jpeg=None;self.generation=str(uuid4())

    def publish(self, pixels, sequence, binding, now, jpeg=None):
        import numpy as np
        if pixels.shape!=(720,1280,3) or pixels.dtype!=np.uint8:
            raise ValueError('Camera geometry must be 1280x720 BGR uint8')
        grid=pixels[::40,::40].astype(np.float32)
        with self.lock:
            if binding!=self.binding:
                self.previous=None;self.sequence=None
                self.generation=str(uuid4())
            if sequence is None or self.sequence is not None and sequence<=self.sequence:return False
            change=None if self.previous is None else float(np.abs(grid-self.previous).mean()/255)
            brightness=float(grid.mean()/255)
            self.latest=(now,brightness,change)
            self.previous=grid;self.binding=binding;self.sequence=sequence
            self.jpeg=jpeg
            return True

    def frame(self,now,binding=None):
        with self.lock:
            if binding is not None and self.binding!=binding:return dict(availability='disabled')
            if self.latest is None or self.jpeg is None or now-self.latest[0]>1.5:
                return dict(availability='unknown')
            return dict(availability='available',source_id=self.generation,sequence=self.sequence,
                        age_ms=max(0,int((now-self.latest[0])*1000)),ttl_ms=1500,
                        exposure_age_known=False,jpeg=base64.b64encode(self.jpeg).decode())

    def snapshot(self, now, binding=None):
        with self.lock:
            if binding is not None and self.binding!=binding:return dict(availability='disabled',ttl_ms=1500)
            if self.latest is None:return dict(availability='unknown',ttl_ms=1500)
            received,brightness,change=self.latest
            age=max(0,int((now-received)*1000))
            if age>1500:return dict(availability='offline',ttl_ms=1500)
            delta='unknown' if change is None else f'{change:.3f}'
            summary=(f'Camera stream frame received: brightness={brightness:.3f}, image_change={delta} (0..1). '
                     'TTL is receipt age; exposure age unknown. No objects identified; change may be robot motion.')
            return dict(availability='available',summary=summary,age_ms=age,ttl_ms=1500)


class CameraSensor:
    def __init__(self, config):
        self.config=config;self.cache=Measurements();self.done=threading.Event()
        self.opener=build_opener(ProxyHandler({}))
        self.failed=None

    def operator(self):
        from ..camera_permission import read_permission
        camera=read_permission(self.config.path(self.config['paths']['data_dir'])/'camera-state.json')
        if not camera['enabled'] or camera['error']:return None
        start=time.monotonic()
        request=Request(self.config['network']['agent_url'].rstrip('/')+'/operator',
                        headers={'Authorization':'Bearer '+self.config.token})
        with self.opener.open(request,timeout=.3) as response:value=json.loads(response.read(16001))
        policy=value['motion_policy']
        owner=value.get('microphone_owner_id')
        if (time.monotonic()-start>.3 or policy['privacy_all'] or policy['quiet']
                or not owner or not value['microphone_enabled']):return None
        return (value['agent_boot_id'],owner,policy['epoch'],value['microphone_epoch'],camera['generation'])

    def run(self):
        camera=None
        try:
            from importlib.metadata import version
            import numpy as np
            import cv2
            from reachy_mini.media.camera_gstreamer import GStreamerCamera, Gst
            sdk_version=version('reachy-mini')
            if sdk_version not in ('1.2.11','1.11.0'):raise RuntimeError('Unaudited camera SDK')
            if sdk_version=='1.2.11':
                from reachy_mini.media.camera_constants import ReachyMiniWirelessCamSpecs
                class StreamCamera(GStreamerCamera):
                    def get_video_device(self):
                        # Never fall back to a second hardware camera owner.
                        if not Path('/tmp/reachymini_camera_socket').is_socket():
                            raise RuntimeError('Factory camera stream unavailable')
                        return '/tmp/reachymini_camera_socket',ReachyMiniWirelessCamSpecs
                create_camera=StreamCamera
            else:
                from reachy_mini.media.camera_constants import get_camera_specs_by_name
                create_camera=lambda:GStreamerCamera(camera_specs=get_camera_specs_by_name('wireless'))
            while not self.done.is_set():
                try:
                    binding=self.operator()
                    if binding is None:
                        self.cache.clear()
                        if camera is not None:
                            self.close_camera(camera,Gst);camera=None
                        self.done.wait(.25);continue
                    if camera is None:
                        if not Path('/tmp/reachymini_camera_socket').is_socket():
                            raise RuntimeError('Factory camera stream unavailable')
                        camera=create_camera();camera.open()
                    sample=camera._appsink_video.emit('try-pull-sample',100_000_000)
                    received=time.monotonic()
                    if sample is None:self.cache.clear();self.done.wait(.1);continue
                    buffer=sample.get_buffer()
                    caps=sample.get_caps().get_structure(0)
                    if (caps.get_value('width'),caps.get_value('height'),caps.get_value('format'))!=(1280,720,'BGR'):
                        raise ValueError('Unexpected camera format')
                    if buffer.get_size()!=1280*720*3:raise ValueError('Frame size bound')
                    # The installed daemon emits PTS=0 for every frame. Its
                    # buffer offset is the advancing stream sequence, not time.
                    sequence=None if buffer.offset==Gst.BUFFER_OFFSET_NONE else int(buffer.offset)
                    raw=buffer.extract_dup(0,buffer.get_size())
                    pixels=np.frombuffer(raw,dtype=np.uint8).reshape((720,1280,3))
                    if binding==self.operator() and not self.done.is_set():
                        ok,encoded=cv2.imencode('.jpg',pixels[::2,::2].copy(),[cv2.IMWRITE_JPEG_QUALITY,75])
                        if not ok:raise ValueError('JPEG encoding failed')
                        jpeg=encoded.tobytes()
                        if len(jpeg)>262144:raise ValueError('JPEG size bound')
                        # Encoding also belongs to the source age budget.
                        if binding==self.operator() and not self.done.is_set():
                            self.cache.publish(pixels,sequence,binding,received,jpeg)
                        else:self.cache.clear()
                    else:self.cache.clear()
                except (OSError,ValueError,KeyError):
                    self.cache.clear()
                    if camera is not None:
                        self.close_camera(camera,Gst);camera=None
                finally:
                    sample=buffer=raw=pixels=encoded=jpeg=None
                self.done.wait(.25)
        except Exception as exc:
            self.failed=type(exc).__name__;self.done.set()
        finally:
            self.cache.clear()
            if camera is not None:
                try:self.close_camera(camera,Gst)
                except Exception as exc:self.failed=type(exc).__name__

    @staticmethod
    def close_camera(camera, gst):
        camera.close()
        if camera.pipeline.get_state(1_000_000_000).state!=gst.State.NULL:
            raise RuntimeError('Camera close unconfirmed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--port',type=int,default=8794)
    args=parser.parse_args()
    from ..config import Config
    config=Config(args.config);sensor=CameraSensor(config)
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup();self.connection.settimeout(1)
        def log_message(self,*args):pass
        def do_GET(self):
            if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+config.token):
                self.send_error(403);return
            if self.path not in ('/sensor','/frame'):self.send_error(404);return
            try:binding=sensor.operator()
            except Exception:binding=None
            allowed=binding is not None
            if not allowed:sensor.cache.clear()
            value=(sensor.cache.frame(time.monotonic(),binding) if self.path=='/frame'
                   else sensor.cache.snapshot(time.monotonic(),binding)) if allowed else dict(availability='disabled',ttl_ms=1500)
            body=json.dumps(value).encode()
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    for number in (signal.SIGTERM,signal.SIGINT):signal.signal(number,lambda *_:sensor.done.set())
    worker=threading.Thread(target=sensor.run,daemon=True,name='camera-stream-measurements')
    with HTTPServer(('127.0.0.1',args.port),Handler) as server:
        server.timeout=.2;worker.start()
        try:
            while not sensor.done.is_set():server.handle_request()
        finally:sensor.done.set();worker.join(5)
    if worker.is_alive() or sensor.failed:raise SystemExit('Camera stopped: '+(sensor.failed or 'worker busy'))


if __name__=='__main__':main()
