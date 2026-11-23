"""Bounded command validation. No trajectories or inference on the router."""
import math


def number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('Motion values must be finite numbers')
    return value


def validate_steps(steps, settings):
    if not isinstance(steps, list) or not 1 <= len(steps) <= settings['max_steps']:
        raise ValueError('Invalid expression step count')
    total = 0
    for step in steps:
        if not isinstance(step, dict) or set(step) != {'head_pose', 'antennas', 'duration', 'interpolation'}:
            raise ValueError('Expression can only control head orientation and antennas')
        duration = number(step['duration'])
        if not .5 <= duration <= 1.5 or step['interpolation'] != 'minjerk':
            raise ValueError('Expression must use a slow smooth movement')
        total += duration
        head = step['head_pose']
        if not isinstance(head, dict) or set(head) != {'x', 'y', 'z', 'roll', 'pitch', 'yaw'}:
            raise ValueError('Invalid expression head pose')
        if any(number(head[axis]) != 0 for axis in ('x', 'y', 'z')):
            raise ValueError('Expression translations are disabled')
        if any(abs(number(head[axis])) > math.radians(settings['max_head_degrees']) for axis in ('roll', 'pitch', 'yaw')):
            raise ValueError('Expression head angle exceeds limits')
        antennas = step['antennas']
        if not isinstance(antennas, list) or len(antennas) != 2 or any(abs(number(a)) > math.radians(settings['max_antenna_degrees']) for a in antennas):
            raise ValueError('Expression antenna angle exceeds limits')
    if total > settings['max_total_seconds']:
        raise ValueError('Expression is too long')
    return steps


def validate_follow_step(step, current=None):
    """Separate internal stock capability; ordinary expression grants stay narrow."""
    if (type(step) is not dict or set(step)!={'head_pose','body_yaw','antennas','duration','interpolation'}
            or step['antennas'] is not None or step['interpolation']!='minjerk'
            or not .35<=number(step['duration'])<=1.5):raise ValueError('Follow step contract')
    head=step['head_pose']
    if type(head) is not dict or set(head)!={'x','y','z','roll','pitch','yaw'}:raise ValueError('Follow head pose')
    if any(number(head[k])!=0 for k in ('x','y','z','roll')):raise ValueError('Follow translations/roll disabled')
    yaw=number(head['yaw']);pitch=number(head['pitch']);body=number(step['body_yaw'])
    if (abs(yaw)>math.radians(60) or abs(body)>math.radians(50)
            or abs(pitch)>math.radians(10) or abs(yaw-body)>math.radians(15.01)):
        raise ValueError('Follow absolute limit')
    if current is not None:
        actual=current['head_pose']
        # Measured FK has calibration error; command slew is separately bounded
        # by the planner. Allow its small correction plus measured offset.
        if (abs(yaw-number(actual['yaw']))>math.radians(12)
                or abs(pitch-number(actual['pitch']))>math.radians(8)
                or abs(body-number(current['body_yaw']))>math.radians(9)):
            raise ValueError('Follow step delta limit')
        # Average angular speed; minjerk peak is 1.875 times this value.
        # Small margin over planner rates allows fresh measured-pose jitter.
        if (abs(yaw-actual['yaw'])/step['duration']>math.radians(30)
                or abs(pitch-actual['pitch'])/step['duration']>math.radians(14)
                or abs(body-current['body_yaw'])/step['duration']>math.radians(23)):
            raise ValueError('Follow angular speed limit')
        for delta,limit in ((yaw-actual['yaw'],360),(pitch-actual['pitch'],190),
                            (body-current['body_yaw'],290)):
            if (10/math.sqrt(3))*abs(delta)/step['duration']**2>math.radians(limit):
                raise ValueError('Follow angular acceleration limit')
    return step
