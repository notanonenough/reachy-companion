"""Pure bounded head/body planner. Inputs are image boxes and measured poses.

Coordinates are normalized in the unmirrored image, not world positions or
identities. No file/network IO and no independent hardware owner.
"""
import math


def checked_sample(value):
    if (not isinstance(value,dict) or set(value)!={'source','seq','people'}
            or not isinstance(value['source'],str) or not 1<=len(value['source'])<=64
            or type(value['seq']) is not int or value['seq']<0
            or not isinstance(value['people'],list) or len(value['people'])>3):raise ValueError('Person sample')
    for box in value['people']:
        if (not isinstance(box,list) or len(box)!=5
                or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in box)
                or box[2]<=0 or box[3]<=0 or box[4]<.45):raise ValueError('Person box')
    return value


def clamp(x,limit):return max(-limit,min(limit,x))


def smooth_error(error,deadband,ramp):
    """Continuous correction at the quiet-zone edge, full gain farther away."""
    weight=max(0,min(1,(abs(error)-deadband)/ramp))
    return error*weight*weight*(3-2*weight)


def measured_pose(state):
    head=state['head_pose'];values=[head['yaw'],head['pitch'],state['body_yaw']]
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in values):raise ValueError('Measured pose unavailable')
    yaw,pitch,body=map(math.degrees,values)
    # FK pitch can exceed the commanded 10-degree cap by calibration error.
    # Admit only the same 8-degree correction envelope as the dispatch guard.
    if abs(yaw)>65 or abs(body)>55 or abs(yaw-body)>25 or abs(pitch)>18:
        raise ValueError('Measured pose outside follow envelope')
    return yaw,pitch,body


class PersonFollow:
    def __init__(self):
        self.source=None;self.sequence=-1;self.target=None;self.hits=0
        self.last_person=None;self.next_scan=None;self.scan_index=None;self.dwell_until=None
        self.mode='waiting_for_camera';self.scans=0
        self.commanded=None

    def committed(self,step):
        self.commanded=(math.degrees(step['head_pose']['yaw']),math.degrees(step['head_pose']['pitch']),math.degrees(step['body_yaw']))

    def plan(self,sample,pose,now,allow_scan=True):
        checked_sample(sample)
        if self.source!=sample['source']:
            self.__init__();self.source=sample['source'];self.next_scan=now+5
        if sample['seq']<=self.sequence:return None
        self.sequence=sample['seq']
        yaw,pitch,body=measured_pose(pose)
        yaw_base,pitch_base,body_base=self.commanded or (yaw,pitch,body)
        people=sample['people'];box=None
        if people:
            if self.target:
                box=min(people,key=lambda p:(p[0]-self.target[0])**2+(p[1]-self.target[1])**2)
                distance=math.hypot(box[0]-self.target[0],box[1]-self.target[1])
                self.hits=self.hits+1 if distance<.3 else 1
            else:box=max(people,key=lambda p:p[2]*p[3]);self.hits=1
            self.target=box;self.last_person=now;self.scan_index=None;self.dwell_until=None
            self.next_scan=now+45
            if self.hits<2:self.mode='confirming_person';return None
            self.mode='following'
            # Aim at upper torso/head vicinity rather than the feet/full-box center.
            x=box[0];y=max(0,box[1]-.25*box[3])
            dx=-smooth_error(x-.5,.04,.04)*60
            dy=smooth_error(y-.5,.05,.05)*40
            # Close most of the image error at once, then reduce the correction
            # near the target. Duration below limits physical angular speed.
            desired=clamp(yaw_base+clamp(dx*.85,10),60)
            next_pitch=clamp(pitch_base+clamp(dy*.65,3),10)
            body_delta=clamp(dx*.65,8)
            if dx==0 and abs(yaw-body)>10:body_delta=clamp(yaw-body,2)
        else:
            self.target=None;self.hits=0;self.mode='holding'
            if (not allow_scan or self.last_person is not None and now-self.last_person<5):return None
            if self.scan_index is None:
                if now<self.next_scan:return None
                self.scan_index=0;self.scans+=1
            self.mode='surveying'
            goal=(45,-45,0)[self.scan_index]
            if abs(yaw-goal)<8 and abs(body-clamp(goal,50))<3:
                if self.dwell_until is None:self.dwell_until=now+6
                if now<self.dwell_until:return None
                self.scan_index+=1;self.dwell_until=None
                if self.scan_index>=3:
                    self.scan_index=None;self.next_scan=now+45;self.mode='holding';return None
                goal=(45,-45,0)[self.scan_index]
            desired=yaw_base+clamp(goal-yaw_base,5);next_pitch=clamp(pitch_base+clamp(-pitch_base,3),10)
            body_delta=clamp(goal-body,4)
        # Body follows the gaze gradually; keep at most 15 degrees of neck twist.
        # Anti-windup: an unresponsive/offset neck cannot accumulate ever larger
        # targets while the body is still catching up.
        desired=yaw+clamp(desired-yaw,10)
        next_pitch=pitch+clamp(next_pitch-pitch,7.8)
        next_body=clamp(body+body_delta,50)
        next_yaw=clamp(max(next_body-15,min(next_body+15,desired)),60)
        if max(abs(next_yaw-yaw_base),abs(next_pitch-pitch_base),abs(next_body-body_base))<.8:return None
        duration=.8
        if self.mode=='following':
            # Quintic minjerk has peak acceleration 10/sqrt(3) * angle/T².
            # Faster far turns, without making short corrections snap abruptly.
            angles=(abs(next_yaw-yaw),abs(next_body-body),abs(next_pitch-pitch))
            duration=max(.35,*(angle/rate for angle,rate in zip(angles,(26,20,12))),
                         *(math.sqrt((10/math.sqrt(3))*angle/acceleration)
                           for angle,acceleration in zip(angles,(320,250,160))))
        return dict(head_pose=dict(x=0,y=0,z=0,roll=0,pitch=math.radians(next_pitch),yaw=math.radians(next_yaw)),
            body_yaw=math.radians(next_body),antennas=None,duration=math.ceil(duration*1000)/1000,interpolation='minjerk')
