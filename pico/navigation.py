"""Pose tracking and move planning for a two-wheel robot.

Pure math, so it runs under MicroPython on the Pico W and under desktop
Python for tests. Millimeters and radians. Heading 0 points along +x, toward
seat 0, and positive heading turns counterclockwise seen from above.

Wheel steps are signed in "forward" terms: +1 rolls that wheel forward. The
stepper module turns that into coil directions.
"""

import math


def wrap(angle):
    """Keep an angle in [-pi, pi)."""
    return (angle + math.pi) % (2 * math.pi) - math.pi


class Geometry:
    def __init__(self, wheel_diameter_mm, steps_per_rev, wheel_base_mm):
        self.mm_per_step = math.pi * wheel_diameter_mm / steps_per_rev
        self.wheel_base = wheel_base_mm

    def drive_steps(self, distance_mm):
        steps = round(distance_mm / self.mm_per_step)
        return steps, steps

    def spin_steps(self, angle):
        """Counterclockwise spin in place by angle radians."""
        steps = round(angle * self.wheel_base / 2 / self.mm_per_step)
        return -steps, steps


class Pose:
    def __init__(self, x=0.0, y=0.0, heading=0.0):
        self.x = x
        self.y = y
        self.heading = heading

    def advance(self, left_steps, right_steps, geometry):
        """Dead-reckon from the steps each wheel actually took."""
        if not left_steps and not right_steps:
            return
        left = left_steps * geometry.mm_per_step
        right = right_steps * geometry.mm_per_step
        distance = (left + right) / 2
        turn = (right - left) / geometry.wheel_base
        middle = self.heading + turn / 2
        self.x += distance * math.cos(middle)
        self.y += distance * math.sin(middle)
        self.heading = wrap(self.heading + turn)

    def distance_to(self, x, y):
        return math.hypot(x - self.x, y - self.y)


def toward(pose, x, y, geometry, align, max_spin, max_drive):
    """Next chunk toward (x, y): a spin until aligned, then a short drive.

    A point behind the robot is reached in reverse, so the robot never turns
    more than a quarter turn to line up. Returns (left_steps, right_steps).
    """
    distance = pose.distance_to(x, y)
    error = wrap(math.atan2(y - pose.y, x - pose.x) - pose.heading)
    if abs(error) > math.pi / 2:
        error = wrap(error - math.pi)
        distance = -distance
    if abs(error) > align:
        return geometry.spin_steps(clamp(error, max_spin))
    return geometry.drive_steps(clamp(distance, max_drive))


def facing(pose, heading, geometry, tolerance, max_spin):
    """Next spin toward a heading, or None once within tolerance."""
    error = wrap(heading - pose.heading)
    if abs(error) <= tolerance:
        return None
    return geometry.spin_steps(clamp(error, max_spin))


def clamp(value, limit):
    return max(-limit, min(limit, value))
