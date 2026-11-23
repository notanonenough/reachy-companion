"""Bounded semantic novelty, independent of pixel brightness and image movement.

Tracks object categories/counts, not identities. Two independent observations
confirm an appearance; three misses and a cooldown rearm it. No frame storage.
"""
from collections import Counter
from uuid import uuid4


COCO_LABELS = ('person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train',
    'truck', 'boat', 'traffic light', 'fire hydrant', 'stop sign', 'parking meter',
    'bench', 'bird', 'cat', 'dog', 'horse', 'sheep', 'cow', 'elephant', 'bear',
    'zebra', 'giraffe', 'backpack', 'umbrella', 'handbag', 'tie', 'suitcase',
    'frisbee', 'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat',
    'baseball glove', 'skateboard', 'surfboard', 'tennis racket', 'bottle',
    'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple',
    'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza', 'donut',
    'cake', 'chair', 'couch', 'potted plant', 'bed', 'dining table', 'toilet',
    'tv', 'laptop', 'mouse', 'remote', 'keyboard', 'cell phone', 'microwave',
    'oven', 'toaster', 'sink', 'refrigerator', 'book', 'clock', 'vase',
    'scissors', 'teddy bear', 'hair drier', 'toothbrush')
LABELS = COCO_LABELS + ('phone',
          'chair', 'table', 'cabinet', 'window', 'curtain', 'mirror', 'door',
          'plant', 'lamp', 'bag', 'box', 'toy', 'ball', 'screen', 'keyboard',
          'food', 'plate', 'clock', 'picture', 'sofa', 'bed', 'clothing')
SIDES = ('left', 'center', 'right')


def checked_objects(value):
    if not isinstance(value,dict) or set(value)!={'objects'}:raise ValueError('Scene object contract')
    rows=value['objects']
    if not isinstance(rows,list) or len(rows)>6:raise ValueError('Scene object bound')
    for row in rows:
        if (not isinstance(row,dict) or set(row)!={'label','side'}
                or row['label'] not in LABELS or row['side'] not in SIDES):
            raise ValueError('Scene label/side contract')
    return rows


class SceneChanges:
    def __init__(self):
        self.samples=0;self.known=set();self.hits=Counter();self.misses=Counter()
        self.last={};self.event=None;self.events=0;self.event_expires=0

    def observe(self, rows, captured, now):
        counts=Counter();present={}
        for row in rows:
            label=row['label'];counts[label]+=1
            present[(label,counts[label])]=row['side']
        self.samples+=1
        # Establish the room before calling furniture "new" on startup.
        if self.samples<=2:
            self.known.update(present)
            return
        for key in self.known|set(self.hits)|set(present):
            if key in present:
                self.hits[key]+=1;self.misses[key]=0
            else:
                self.hits[key]=0;self.misses[key]+=1
                if self.misses[key]>=3:self.known.discard(key)
        new=[key for key in present if key not in self.known and self.hits[key]>=2]
        new.sort(key=lambda key:(key[0]!='person',key))
        eligible=[key for key in new if now-self.last.get(key,-1e9)>=60]
        self.known.update(new)
        if eligible:
            key=eligible[0];self.last[key]=now
            self.event=(captured,dict(id=str(uuid4()),label=key[0],side=present[key]),key)
            self.event_expires=now+30
            self.events+=1
        elif self.event:
            captured_at,event,key=self.event
            # A gone target must not cause a delayed glance. Side changes alone
            # never count as appearances (including our own head movements).
            if key not in present or now>=self.event_expires:self.event=None
            else:self.event=(captured,{**event,'side':present[key]},key)

    def snapshot(self, now):
        if not self.event or now-self.event[0]>20 or now>=self.event_expires:return None
        return self.event[:2]
