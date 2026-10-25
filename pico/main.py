"""Rattle Royale robot. Runs on its own when the Pico W powers up.

Place the robot on the center mark, pointed at seat 0, before power-on. That
is where the pose starts. brain.py has the rules it follows.

The onboard LED shows the link: a fast blink while joining Wi-Fi, a slow
blink while looking for the server, solid when online, and a double blink
while a host has the robot stopped.
"""

import config
from brain import Brain, blink_lit, wifi_networks
from machine import Pin
from stepper import wheels_from
from wifi_link import Link, start_wifi


class Led:
    def __init__(self):
        self._pin = Pin("LED", Pin.OUT, value=0)

    def show(self, state, now_ms):
        self._pin.value(1 if blink_lit(state, now_ms) else 0)

    def off(self):
        self._pin.value(0)


def main():
    wheels = wheels_from(config)
    led = Led()
    try:
        ssid, password = wifi_networks(config)[0]
        wlan = start_wifi(ssid, password)
        Brain(config, wheels, Link(config.SERVER_URL, config.ROBOT_TOKEN), wlan, indicator=led).run()
    finally:
        wheels.shutdown()
        led.off()


main()
