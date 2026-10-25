"""Rattle Royale robot. Runs on its own when the Pico W powers up.

Place the robot on the center mark, pointed at seat 0, before power-on. That
is where the pose starts. The server says what to do on every poll:

  chase  drive to that seat's mark and stop inside the arrival radius
  hold   stop where it is (a round is open, nobody has pull)
  home   drive back to the center and face seat 0 (no round is open)
  test   drive to a test point (no round is open)

The server never sends steps. A new order cuts the current move short, and
the pose counts only the steps the wheels really took. A lost link holds.
"""

import math
import time

import config
from link import Link, start_wifi
from navigation import Geometry, Pose, facing, toward
from stepper import Wheels

RECONNECT_MS = 10000


def goal_of(order):
    """What the robot is after. A change cuts the current move short."""
    mode = order.get("mode")
    if mode == "chase":
        return ("chase", order.get("round"), order.get("seat"))
    if mode == "test":
        return ("test", order.get("x"), order.get("y"))
    return (mode,)


def next_move(order, pose, geometry):
    """Returns (steps or None, arrival or None)."""
    align = math.radians(config.ALIGN_DEGREES)
    max_spin = math.radians(config.MAX_SPIN_DEGREES)
    mode = order.get("mode")
    if mode in ("chase", "test"):
        x, y = order["x"], order["y"]
        if pose.distance_to(x, y) <= config.ARRIVAL_RADIUS_MM:
            if mode == "chase":
                return None, {"round": order.get("round"), "seat": order.get("seat")}
            return None, None
        return toward(pose, x, y, geometry, align, max_spin, config.MAX_DRIVE_MM), None
    if mode == "home":
        if pose.distance_to(0, 0) > config.HOME_RADIUS_MM:
            return toward(pose, 0, 0, geometry, align, max_spin, config.MAX_DRIVE_MM), None
        tolerance = math.radians(config.HOME_HEADING_DEGREES)
        return facing(pose, 0.0, geometry, tolerance, max_spin), None
    return None, None


def report(pose, moving, arrival):
    return {
        "x": round(pose.x, 1),
        "y": round(pose.y, 1),
        "heading": round(math.degrees(pose.heading), 1),
        "moving": moving,
        "arrived": arrival,
    }


def run(wheels):
    geometry = Geometry(config.WHEEL_DIAMETER_MM, config.STEPS_PER_REV, config.WHEEL_BASE_MM)
    pose = Pose()
    wlan = start_wifi(config.WIFI_SSID, config.WIFI_PASSWORD)
    joined_at = time.ticks_ms()
    link = Link(config.SERVER_URL, config.ROBOT_TOKEN)
    order = {"mode": "hold"}
    goal = goal_of(order)
    arrival = None
    heard_at = time.ticks_ms()
    poll_at = time.ticks_ms()
    online = False

    while True:
        pose.advance(*wheels.take_steps(), geometry)
        now = time.ticks_ms()

        if not wlan.isconnected():
            if online:
                print("Wi-Fi dropped")
                online = False
                link.close()
            if time.ticks_diff(now, joined_at) > RECONNECT_MS:
                wlan.disconnect()
                wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
                joined_at = now
        elif time.ticks_diff(now, poll_at) >= 0:
            poll_at = time.ticks_add(now, config.POLL_MS)
            try:
                order = link.post("/api/robot", report(pose, wheels.busy(), arrival))
                heard_at = time.ticks_ms()
                if not online:
                    print("Server reached from", wlan.ifconfig()[0])
                    online = True
            except Exception as error:
                print("Poll failed:", error)

        if time.ticks_diff(time.ticks_ms(), heard_at) > config.LINK_LOST_MS:
            if order.get("mode") != "hold":
                print("Link lost, holding still")
            order = {"mode": "hold"}
            online = False

        current = goal_of(order)
        if current != goal:
            wheels.stop()
            goal = current
            arrival = None
            print("New order:", order)

        if not wheels.busy():
            pose.advance(*wheels.take_steps(), geometry)
            steps, reached = next_move(order, pose, geometry)
            if reached is not None and arrival is None:
                print("Reached seat", reached["seat"])
            arrival = reached or arrival
            if steps is not None and steps != (0, 0):
                wheels.move(*steps)

        time.sleep_ms(10)


def main():
    wheels = Wheels(
        config.LEFT_PINS,
        config.RIGHT_PINS,
        config.LEFT_FORWARD,
        config.RIGHT_FORWARD,
        config.STEP_US,
    )
    try:
        run(wheels)
    finally:
        wheels.shutdown()


main()
