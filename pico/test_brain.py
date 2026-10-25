"""The robot's brain and the step ramp, without hardware.

Runs on the laptop: python -m unittest discover -s pico
"""

import sys
import types
import unittest

import config_example
from brain import Brain, blink_lit, wifi_networks

# stepper.py imports MicroPython modules. Stand-ins let its math load here.
sys.modules.setdefault("machine", types.SimpleNamespace(Pin=None))
sys.modules.setdefault("_thread", types.SimpleNamespace())
from stepper import ramped_us  # noqa: E402


class FakeWheels:
    def __init__(self) -> None:
        self.moves: list[tuple[int, int]] = []
        self.stops = 0

    def move(self, left: int, right: int) -> None:
        self.moves.append((left, right))

    def stop(self) -> None:
        self.stops += 1

    def busy(self) -> bool:
        return False

    def take_steps(self) -> tuple[int, int]:
        return 0, 0


class FakeLink:
    def __init__(self, order: dict) -> None:
        self.order = order

    def post(self, path: str, body: dict) -> dict:
        return dict(self.order)

    def close(self) -> None:
        pass


class FakeWlan:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected
        self.joins: list[str] = []

    def isconnected(self) -> bool:
        return self.connected

    def ifconfig(self) -> tuple:
        return ("test",)

    def connect(self, ssid: str, password: str) -> None:
        self.joins.append(ssid)

    def disconnect(self) -> None:
        pass


class Lights:
    def __init__(self) -> None:
        self.states: list[str] = []

    def show(self, state: str, now_ms: int) -> None:
        self.states.append(state)


def config(**changes) -> types.SimpleNamespace:
    values = {name: getattr(config_example, name) for name in dir(config_example) if name.isupper()}
    values.update(changes)
    return types.SimpleNamespace(**values)


def brain(order: dict, wlan: FakeWlan | None = None, **changes) -> tuple[Brain, FakeWheels, Lights]:
    wheels, lights = FakeWheels(), Lights()
    made = Brain(config(**changes), wheels, FakeLink(order), wlan or FakeWlan(), log=lambda *_: None, indicator=lights)
    return made, wheels, lights


class BlinkTests(unittest.TestCase):
    def test_online_is_solid_and_joining_blinks_fast(self) -> None:
        self.assertTrue(all(blink_lit("online", t) for t in range(0, 2000, 50)))
        self.assertTrue(blink_lit("joining", 50))
        self.assertFalse(blink_lit("joining", 150))

    def test_stopped_is_a_double_blink(self) -> None:
        lit = [blink_lit("stopped", t) for t in (50, 200, 300, 600)]
        self.assertEqual(lit, [True, False, True, False])


class WifiTests(unittest.TestCase):
    def test_networks_come_from_the_list(self) -> None:
        self.assertEqual(wifi_networks(config(WIFI_NETWORKS=[("a", "1"), ("b", "2")])), [("a", "1"), ("b", "2")])

    def test_an_older_single_network_config_still_works(self) -> None:
        old = types.SimpleNamespace(WIFI_SSID="home", WIFI_PASSWORD="pw")
        self.assertEqual(wifi_networks(old), [("home", "pw")])

    def test_no_network_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            wifi_networks(config(WIFI_NETWORKS=[]))

    def test_a_network_that_will_not_connect_hands_over_to_the_next(self) -> None:
        wlan = FakeWlan(connected=False)
        robot, _, lights = brain({"mode": "home"}, wlan, WIFI_NETWORKS=[("venue", "1"), ("hotspot", "2")])
        robot.joined_at -= 20000
        robot.tick()
        robot.joined_at -= 20000
        robot.tick()
        self.assertEqual(wlan.joins, ["hotspot", "venue"])
        self.assertEqual(lights.states[-1], "joining")


class OrderTests(unittest.TestCase):
    def test_a_stop_order_cuts_the_move_and_never_drives(self) -> None:
        robot, wheels, lights = brain({"mode": "stop", "reset": None})
        robot.tick()
        self.assertEqual(robot.order["mode"], "stop")
        self.assertGreaterEqual(wheels.stops, 1)
        self.assertEqual(wheels.moves, [])
        self.assertEqual(lights.states[-1], "stopped")

    def test_a_test_point_ahead_drives_and_shows_online(self) -> None:
        robot, wheels, lights = brain({"mode": "test", "x": 100, "y": 0, "reset": None})
        robot.tick()
        self.assertEqual(len(wheels.moves), 1)
        left, right = wheels.moves[0]
        self.assertGreater(left, 0)
        self.assertEqual(left, right)
        self.assertEqual(lights.states[-1], "online")

    def test_no_reply_yet_shows_searching(self) -> None:
        robot, _, lights = brain({"mode": "home"})
        robot.poll_at += 60000
        robot.tick()
        self.assertEqual(lights.states[-1], "searching")


class RampTests(unittest.TestCase):
    def test_a_long_move_starts_slow_cruises_then_slows(self) -> None:
        times = [ramped_us(tick, 1000, 2000, 3000, 200) for tick in range(1000)]
        self.assertEqual(times[0], 3000)
        self.assertEqual(times[100], 2500)
        self.assertEqual(times[500], 2000)
        self.assertEqual(times[999], 2995)
        self.assertEqual(times, sorted(times[:500], reverse=True) + sorted(times[500:]))

    def test_a_short_move_never_reaches_cruise(self) -> None:
        times = [ramped_us(tick, 100, 2000, 3000, 200) for tick in range(100)]
        self.assertGreater(min(times), 2000)

    def test_no_ramp_is_a_flat_step_time(self) -> None:
        self.assertEqual({ramped_us(tick, 50, 3000, 3000, 0) for tick in range(50)}, {3000})


if __name__ == "__main__":
    unittest.main()
