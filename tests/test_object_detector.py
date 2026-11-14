import unittest
import json
import tempfile
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock,patch
from pathlib import Path
import numpy as np
from reachy_companion.autonomous.object_detector import ObjectDetector
from reachy_companion.autonomous.scene_changes import COCO_LABELS


class DetectorGeometryTests(unittest.TestCase):
    def test_local_detector_configuration_loads_and_rejects_invalid_paths(self):
        from reachy_companion.autonomous.config import load
        root=Path(__file__).parents[1]
        cfg=json.loads((root/'config.autonomous.normal.example.json').read_text())
        cfg['gateway']['vision']=dict(enabled=True,camera_url='http://127.0.0.1:18794/frame',
            model_url='http://127.0.0.1:18099',camera_token_file='token',detector_model='models/yolox.onnx')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json';path.write_text(json.dumps(cfg))
            self.assertEqual(load(path)['gateway']['vision']['detector_model'],str(Path(directory).resolve()/'models/yolox.onnx'))
            for value in (True,[],None,''):
                cfg['gateway']['vision']['detector_model']=value;path.write_text(json.dumps(cfg))
                with self.assertRaises(ValueError):load(path)

    def test_backend_rejects_unknown_configuration(self):
        from reachy_companion.autonomous.config import load
        root=Path(__file__).parents[1]
        cfg=json.loads((root/'config.autonomous.normal.example.json').read_text())
        cfg['gateway']['vision']=dict(enabled=True,camera_url='http://127.0.0.1/frame',
            model_url='http://127.0.0.1:18099',camera_token_file='token',detector_backend='remote')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json';path.write_text(json.dumps(cfg))
            with self.assertRaisesRegex(ValueError,'Detector backend'):load(path)

    def setUp(self):
        self.detector=ObjectDetector.__new__(ObjectDetector)
        self.detector.grids=np.zeros((8400,2));self.detector.strides=np.ones((8400,1))*8
        self.output=np.zeros((1,8400,85),dtype=np.float32)

    def box(self,i,x,y,label='person',score=.9):
        row=self.output[0,i]
        row[:2]=[x/8,y/8];row[2:4]=np.log([80/8,100/8])
        row[4]=1;row[5+COCO_LABELS.index(label)]=score

    def test_image_sectors_class_aware_nms_and_padding(self):
        self.box(0,100,150);self.box(1,102,150,score=.8) # overlapping same person
        self.box(2,540,150);self.box(3,320,150,'cup')
        self.box(4,320,550) # wholly within letterbox padding
        self.box(5,320,150,'bottle',.2) # weak classification
        self.box(6,102,150,'cup') # different object at same location retained
        rows=self.detector.decode(self.output,640,360)
        self.assertEqual(rows,[dict(label='cup',side='left'),dict(label='cup',side='center'),
            dict(label='person',side='left'),dict(label='person',side='right')])

    def test_invalid_output_rejected_without_producing_objects(self):
        for output in (np.zeros((1,10,85)),np.full((1,8400,85),float('nan'))):
            with self.assertRaises(ValueError):self.detector.decode(output,640,360)

    def test_tracking_preserves_boxes_and_lower_score_needs_downstream_confirmation(self):
        self.box(0,100,150,score=.5)
        result=self.detector.decode(self.output,640,360,with_people=True)
        self.assertEqual(result['objects'],[]) # not a high-confidence appearance event
        self.assertEqual(result['people'],[[.156,.417,.125,.278,.5]])

    def test_crop_coordinates_return_to_full_image_frame(self):
        people=[[.5,.4,.2,.3,.8]]
        self.assertEqual(ObjectDetector.map_people(people,0,384,640),[[.3,.4,.12,.3,.8]])
        self.assertEqual(ObjectDetector.map_people(people,256,384,640),[[.7,.4,.12,.3,.8]])


class DetectorBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'model.onnx';self.path.write_bytes(b'fixture')
        for target,value in (
            ('reachy_companion.autonomous.object_detector.MODEL_SHA256',hashlib.sha256(b'fixture').hexdigest()),
            ('reachy_companion.autonomous.object_detector.platform.system',lambda:'Darwin'),
            ('onnxruntime.get_available_providers',lambda:['CoreMLExecutionProvider','CPUExecutionProvider'])):
            p=patch(target,value);p.start();self.addCleanup(p.stop)

    def session(self,providers):
        session=Mock();session.get_inputs.return_value=[SimpleNamespace(name='images')]
        session.get_providers.return_value=providers
        session.run.return_value=[np.zeros((1,8400,85),dtype=np.float32)]
        return session

    def test_accelerator_failure_falls_back_once_without_new_parallel_lane(self):
        from PIL import Image
        coreml=self.session(['CoreMLExecutionProvider']);cpu=self.session(['CPUExecutionProvider'])
        with patch('onnxruntime.InferenceSession',side_effect=[coreml,cpu]) as factory:
            detector=ObjectDetector(self.path)
            self.assertEqual(detector.backend,'coreml_cpu_ane')
            coreml.run.side_effect=RuntimeError('hardware failure')
            with Image.new('RGB',(640,360)) as image:
                self.assertEqual(detector.infer_image(image),dict(objects=[],people=[]))
                detector.infer_image(image)
            self.assertEqual(detector.backend,'cpu');self.assertEqual(detector.backend_error,'RuntimeError')
            self.assertEqual(factory.call_count,2);self.assertEqual(cpu.run.call_count,2)
            self.assertEqual(coreml.run.call_count,2) # warmup and one failed inference

    def test_auto_init_failure_uses_cpu_but_explicit_coreml_reports_failure(self):
        cpu=self.session(['CPUExecutionProvider'])
        with patch('onnxruntime.InferenceSession',side_effect=[RuntimeError('compile'),cpu]) as factory:
            detector=ObjectDetector(self.path)
            self.assertEqual(detector.backend,'cpu');self.assertEqual(detector.backend_error,'RuntimeError')
            self.assertEqual(factory.call_count,2)
        with patch('onnxruntime.InferenceSession',side_effect=RuntimeError('compile')) as factory:
            with self.assertRaises(RuntimeError):ObjectDetector(self.path,backend='coreml')
            self.assertEqual(factory.call_count,1)


if __name__=='__main__':unittest.main()
