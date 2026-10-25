"""Measure the two geometry numbers in config.py. Wheels on the floor.

1. Drive: the robot rolls DRIVE_MM forward. Measure how far it really went,
   then set WHEEL_DIAMETER_MM = WHEEL_DIAMETER_MM * measured / DRIVE_MM.
2. Spin: the robot turns one full circle in place. If it turns too far, raise
   WHEEL_BASE_MM. If it stops short, lower it. It scales the same way:
   WHEEL_BASE_MM = WHEEL_BASE_MM * 360 / degrees_turned.
"""

import math
import time

import config
from navigation import Geometry
from stepper import Wheels

DRIVE_MM = 200

geometry = Geometry(config.WHEEL_DIAMETER_MM, config.STEPS_PER_REV, config.WHEEL_BASE_MM)
wheels = Wheels(config.LEFT_PINS, config.RIGHT_PINS, config.LEFT_FORWARD, config.RIGHT_FORWARD, config.STEP_US)


def run(label, steps):
    print(label, steps)
    wheels.move(*steps)
    while wheels.busy():
        time.sleep_ms(20)
    wheels.take_steps()


try:
    run("Driving", geometry.drive_steps(DRIVE_MM))
    print("Measure the distance now. Spinning in 5 seconds.")
    time.sleep(5)
    run("Spinning", geometry.spin_steps(2 * math.pi))
    print("Done.")
finally:
    wheels.shutdown()
