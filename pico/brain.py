"""The robot's decisions, apart from any hardware.

main.py runs this on the Pico W with real wheels, Wi-Fi, and HTTPS.
simulator.py runs the same code on the laptop with pretend wheels, so the whole
game can be played before the robot exists.

The server says what to do on every poll:

  chase  drive to that seat's mark and stop inside the arrival radius
  hold   stop where it is (a chase is open, nobody has pull)
  home   drive back to the center and face seat 0 (no chase is open)
  test   drive to a test point (no chase is open)

Every order also carries a reset id. A new id means the host just placed the
robot on the center mark, so the pose goes back to the center facing seat 0.

The server never sends steps. A new order cuts the current move short, and
the pose counts only the steps the wheels really took. A lost link holds.
"""

import math

from navigation import Geometry, Pose, facing, toward

try:
    from time import sleep_ms, ticks_add, ticks_diff, ticks_ms
except ImportError:
    import time

    def ticks_ms():
        return int(time.monotonic() * 1000)

    def ticks_add(ticks, delta):
        return ticks + delta

    def ticks_diff(end, start):
        return end - start

    def sleep_ms(ms):
        time.sleep(ms / 1000)


RECONNECT_MS = 10000
_UNSEEN = object()


def goal_of(order):
    """What the robot is after. A change cuts the current move short."""
    mode = order.get("mode")
    if mode == "chase":
        return ("chase", order.get("round"), order.get("seat"))
    if mode == "test":
        return ("test", order.get("x"), order.get("y"))
    return (mode,)


class Brain:
    def __init__(self, config, wheels, link, wlan, log=print):
        self.config = config
        self.wheels = wheels
        self.link = link
        self.wlan = wlan
        self.log = log
        self.geometry = Geometry(config.WHEEL_DIAMETER_MM, config.STEPS_PER_REV, config.WHEEL_BASE_MM)
        self.pose = Pose()
        self.order = {"mode": "hold"}
        self.goal = goal_of(self.order)
        self.arrival = None
        self.online = False
        self.reset_seen = _UNSEEN
        now = ticks_ms()
        self.joined_at = now
        self.heard_at = now
        self.poll_at = now

    def run(self):
        while True:
            self.tick()
            sleep_ms(10)

    def tick(self):
        self.pose.advance(*self.wheels.take_steps(), self.geometry)
        self._talk()
        self._watch_link()
        current = goal_of(self.order)
        if current != self.goal:
            self.wheels.stop()
            self.goal = current
            self.arrival = None
            self.log("New order:", self.order)
        if not self.wheels.busy():
            self.pose.advance(*self.wheels.take_steps(), self.geometry)
            steps, reached = self.next_move()
            if reached is not None and self.arrival is None:
                self.log("Reached seat", reached["seat"])
            self.arrival = reached or self.arrival
            if steps is not None and steps != (0, 0):
                self.wheels.move(*steps)

    def next_move(self):
        """Returns (steps or None, arrival or None)."""
        config = self.config
        pose = self.pose
        align = math.radians(config.ALIGN_DEGREES)
        max_spin = math.radians(config.MAX_SPIN_DEGREES)
        mode = self.order.get("mode")
        if mode in ("chase", "test"):
            x, y = self.order["x"], self.order["y"]
            if pose.distance_to(x, y) <= config.ARRIVAL_RADIUS_MM:
                if mode == "chase":
                    return None, {"round": self.order.get("round"), "seat": self.order.get("seat")}
                return None, None
            return toward(pose, x, y, self.geometry, align, max_spin, config.MAX_DRIVE_MM), None
        if mode == "home":
            if pose.distance_to(0, 0) > config.HOME_RADIUS_MM:
                return toward(pose, 0, 0, self.geometry, align, max_spin, config.MAX_DRIVE_MM), None
            tolerance = math.radians(config.HOME_HEADING_DEGREES)
            return facing(pose, 0.0, self.geometry, tolerance, max_spin), None
        return None, None

    def report(self):
        return {
            "x": round(self.pose.x, 1),
            "y": round(self.pose.y, 1),
            "heading": round(math.degrees(self.pose.heading), 1),
            "moving": self.wheels.busy(),
            "arrived": self.arrival,
        }

    def _talk(self):
        now = ticks_ms()
        if not self.wlan.isconnected():
            if self.online:
                self.log("Wi-Fi dropped")
                self.online = False
                self.link.close()
            if ticks_diff(now, self.joined_at) > RECONNECT_MS:
                self.wlan.disconnect()
                self.wlan.connect(self.config.WIFI_SSID, self.config.WIFI_PASSWORD)
                self.joined_at = now
            return
        if ticks_diff(now, self.poll_at) < 0:
            return
        self.poll_at = ticks_add(now, self.config.POLL_MS)
        try:
            order = self.link.post("/api/robot", self.report())
        except Exception as error:
            self.log("Poll failed:", error)
            return
        self.heard_at = ticks_ms()
        if not self.online:
            self.log("Server reached from", self.wlan.ifconfig()[0])
            self.online = True
        self._apply_reset(order.get("reset"))
        self.order = order

    def _apply_reset(self, reset):
        """The first id seen is only remembered. A later new id resets the pose."""
        if self.reset_seen is not _UNSEEN and reset is not None and reset != self.reset_seen:
            self.wheels.stop()
            self.wheels.take_steps()
            self.pose = Pose()
            self.log("Pose reset to the center")
        self.reset_seen = reset

    def _watch_link(self):
        if ticks_diff(ticks_ms(), self.heard_at) <= self.config.LINK_LOST_MS:
            return
        if self.order.get("mode") != "hold":
            self.log("Link lost, holding still")
        self.order = {"mode": "hold"}
        self.online = False
