"""Local object localization; never called by the scheduler or HTTP handler.

YOLOX-s model/preprocessing contract: OpenCV Zoo object_detection_yolox
https://github.com/opencv/opencv_zoo/tree/main/models/object_detection_yolox
Weights are Apache-2.0; pinned hash is the upstream Git LFS object ID.
"""
import base64
import hashlib
import io
import platform
import logging
from pathlib import Path
from .scene_changes import COCO_LABELS


MODEL_SHA256='c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063'


class ObjectDetector:
    def __init__(self, model_path, *, backend='auto'):
        import numpy as np
        import onnxruntime as ort
        if backend not in ('auto','cpu','coreml'):raise ValueError('Detector backend')
        self.requested_backend=backend;self.backend_error=None
        path=Path(model_path)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=MODEL_SHA256:
            raise ValueError('Object detector weights do not match audited model')
        options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
        options.add_session_config_entry('session.intra_op.allow_spinning','0')
        options.add_session_config_entry('session.inter_op.allow_spinning','0')
        self.model_path=path;self.session_options=options
        coreml=platform.system()=='Darwin' and 'CoreMLExecutionProvider' in ort.get_available_providers()
        if backend=='coreml' and not coreml:raise ValueError('CoreML detector unavailable')
        self.backend='cpu'
        if backend!='cpu' and coreml:
            try:
                cache=path.parent/'coreml-cache'/MODEL_SHA256;cache.mkdir(parents=True,exist_ok=True)
                self.session=ort.InferenceSession(str(path),sess_options=options,providers=[
                    ('CoreMLExecutionProvider',dict(ModelFormat='MLProgram',MLComputeUnits='CPUAndNeuralEngine',
                        RequireStaticInputShapes='1',ModelCacheDirectory=str(cache))), 'CPUExecutionProvider'])
                self.session.disable_fallback()
                if 'CoreMLExecutionProvider' not in self.session.get_providers():raise RuntimeError('CoreML initialization failed')
                # Compile/warm up using synthetic pixels, before accepting camera frames.
                self.session.run(None,{self.session.get_inputs()[0].name:np.full((1,3,640,640),114,dtype=np.float32)})
                self.backend='coreml_cpu_ane'
            except Exception as exc:
                if backend=='coreml':raise
                self.backend_error=type(exc).__name__
                logging.getLogger(__name__).warning('CoreML detector unavailable; using CPU (%s)',self.backend_error)
        if self.backend=='cpu':self.session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
        self.input=self.session.get_inputs()[0].name
        self.grids=[];self.strides=[]
        for stride in (8,16,32):
            x,y=np.meshgrid(np.arange(640//stride),np.arange(640//stride))
            grid=np.stack((x,y),axis=-1).reshape(-1,2)
            self.grids.append(grid);self.strides.append(np.full((len(grid),1),stride))
        self.grids=np.concatenate(self.grids);self.strides=np.concatenate(self.strides)

    def __call__(self,frame):
        from PIL import Image
        raw=base64.b64decode(frame['jpeg'],validate=True)
        with Image.open(io.BytesIO(raw)) as source:
            width,height=source.size
            if source.format!='JPEG' or not 1<=width<=1280 or not 1<=height<=720:
                raise ValueError('Bounded camera JPEG required')
            rgb=source.convert('RGB')
        try:
            result=self.infer_image(rgb)
            if not result['people']:
                # Small/occluded people can disappear in a whole-room resize.
                # At most two overlapping enlarged side views, same CPU slot.
                crop_width=round(width*.6)
                for left in (0,width-crop_width):
                    with rgb.crop((left,0,left+crop_width,height)) as crop:zoom=self.infer_image(crop)
                    if zoom['people']:
                        result['people']=self.map_people(zoom['people'],left,crop_width,width)
                        people=[dict(label='person',side='left' if p[0]<.4 else 'right' if p[0]>.6 else 'center')
                            for p in result['people'] if p[4]>=.65]
                        result['objects']=(people+result['objects'])[:6]
                        break
            return result
        finally:rgb.close()

    @staticmethod
    def map_people(people,left,crop_width,width):
        return [[round((left+p[0]*crop_width)/width,3),p[1],round(p[2]*crop_width/width,3),p[3],p[4]] for p in people]

    def infer_image(self,rgb):
        import numpy as np
        from PIL import Image
        width,height=rgb.size;ratio=min(640/width,640/height)
        rw,rh=int(width*ratio),int(height*ratio)
        resized=np.asarray(rgb.resize((rw,rh),Image.Resampling.BILINEAR),dtype=np.float32)
        tensor=np.full((640,640,3),114,dtype=np.float32);tensor[:rh,:rw]=resized
        inputs={self.input:tensor.transpose(2,0,1)[None]}
        try:output=self.session.run(None,inputs)[0]
        except Exception as exc:
            if self.backend!='coreml_cpu_ane' or self.requested_backend!='auto':raise
            # run() is synchronous: its error is terminal for this invocation.
            # Recover once on CPU in this same worker, with no extra inference slot.
            import onnxruntime as ort
            self.backend_error=type(exc).__name__;self.backend='cpu'
            logging.getLogger(__name__).warning('CoreML detector failed; using CPU (%s)',self.backend_error)
            self.session=ort.InferenceSession(str(self.model_path),sess_options=self.session_options,providers=['CPUExecutionProvider'])
            output=self.session.run(None,inputs)[0]
        return self.decode(output,rw,rh,with_people=True)

    def decode(self,output,width,height,with_people=False):
        import numpy as np
        if output.shape!=(1,8400,85) or not np.isfinite(output).all():raise ValueError('Detector output contract')
        rows=output[0];labels=rows[:,5:].argmax(axis=1)
        scores=rows[:,4]*rows[np.arange(len(rows)),5+labels]
        indices=np.flatnonzero(scores>=np.where(labels==0,.45,.65))
        indices=indices[np.argsort(scores[indices])[::-1]][:300]
        centers=(rows[indices,:2]+self.grids[indices])*self.strides[indices]
        sizes=np.exp(np.clip(rows[indices,2:4],-15,15))*self.strides[indices]
        boxes=np.concatenate((centers-sizes/2,centers+sizes/2),axis=1)
        boxes[:,[0,2]]=boxes[:,[0,2]].clip(0,width);boxes[:,[1,3]]=boxes[:,[1,3]].clip(0,height)
        kept=[]
        for i,index in enumerate(indices):
            box=boxes[i];area=max(0,box[2]-box[0])*max(0,box[3]-box[1])
            if area<25:continue
            duplicate=False
            for other in kept:
                if labels[index]!=labels[indices[other]]:continue
                b=boxes[other]
                intersection=max(0,min(box[2],b[2])-max(box[0],b[0]))*max(0,min(box[3],b[3])-max(box[1],b[1]))
                union=area+(b[2]-b[0])*(b[3]-b[1])-intersection
                if union>0 and intersection/union>.5:duplicate=True;break
            if not duplicate:kept.append(i)
        # Stable left-to-right order within a class, and people before objects
        # when the bounded six-object cache is full.
        kept.sort(key=lambda i:(labels[indices[i]]!=0,-scores[indices[i]]))
        people=[]
        for i in kept:
            if labels[indices[i]]==0:
                box=boxes[i]
                people.append([round(float((box[0]+box[2])/2/width),3),
                    round(float((box[1]+box[3])/2/height),3),
                    round(float((box[2]-box[0])/width),3),round(float((box[3]-box[1])/height),3),
                    round(float(scores[indices[i]]),3)])
        result=[]
        for i in [i for i in kept if scores[indices[i]]>=.65][:6]:
            x=float((boxes[i,0]+boxes[i,2])/2/width)
            result.append((COCO_LABELS[labels[indices[i]]],x))
        result.sort()
        objects=[dict(label=label,side='left' if x<.4 else 'right' if x>.6 else 'center') for label,x in result]
        return dict(objects=objects,people=people[:3]) if with_people else objects
