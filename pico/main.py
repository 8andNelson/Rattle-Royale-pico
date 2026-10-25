"""Rattle Royale robot. Runs on its own when the Pico W powers up.

Place the robot on the center mark, pointed at seat 0, before power-on. That
is where the pose starts. brain.py has the rules it follows.
"""

import config
from brain import Brain
from link import Link, start_wifi
from stepper import Wheels


def main():
    wheels = Wheels(
        config.LEFT_PINS,
        config.RIGHT_PINS,
        config.LEFT_FORWARD,
        config.RIGHT_FORWARD,
        config.STEP_US,
    )
    try:
        wlan = start_wifi(config.WIFI_SSID, config.WIFI_PASSWORD)
        Brain(config, wheels, Link(config.SERVER_URL, config.ROBOT_TOKEN), wlan).run()
    finally:
        wheels.shutdown()


main()
