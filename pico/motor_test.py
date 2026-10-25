"""Bench test for both wheels. Lift the wheels off the desk, then run in Thonny.

Each wheel should roll forward, then back, one at a time. Then both together:
forward (the car would roll), and a spin (left back, right forward, which is
counterclockwise seen from above). A wheel that turns backward on its
"forward" line needs its LEFT_FORWARD or RIGHT_FORWARD flipped in config.py.
"""

import time

import config
from stepper import wheels_from

STEPS = 512

wheels = wheels_from(config)


def run(label, left, right):
    print(label)
    wheels.move(left, right)
    while wheels.busy():
        time.sleep_ms(20)
    print("  took", wheels.take_steps())
    time.sleep_ms(500)


try:
    run("Left wheel forward", STEPS, 0)
    run("Left wheel back", -STEPS, 0)
    run("Right wheel forward", 0, STEPS)
    run("Right wheel back", 0, -STEPS)
    run("Both forward", STEPS, STEPS)
    run("Spin counterclockwise", -STEPS, STEPS)
    print("Done. Both wheels should be still with the coils off.")
finally:
    wheels.shutdown()
