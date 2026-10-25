"""Serial bridge commands, without an Arduino attached."""

import threading
import time
import unittest

import serial

from server.app import create_app
from server.bridge import Bridge, BridgeError, MoveResult


class FakePort:
    def __init__(self) -> None:
        self.timeout = 0.02
        self.closed = False
        self.pong_on_ping = False
        self._lock = threading.Lock()
        self.written: list[str] = []
        self._lines: list[str] = []

    def push(self, *lines: str) -> None:
        with self._lock:
            self._lines.extend(lines)

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self.written)

    def write(self, data: bytes) -> None:
        text = data.decode("ascii")
        with self._lock:
            if self.closed:
                raise serial.SerialException("closed")
            self.written.append(text)
            if text == "STOP\n":
                self._lines.append("DONE STOP")
            elif text == "PING\n" and self.pong_on_ping:
                self._lines.append("PONG")

    def readline(self) -> bytes:
        with self._lock:
            if self.closed:
                raise serial.SerialException("closed")
            if self._lines:
                return (self._lines.pop(0) + "\n").encode("ascii")
            timeout = self.timeout
        time.sleep(timeout or 0)
        return b""

    def flush(self) -> None:
        return None

    def close(self) -> None:
        with self._lock:
            self.closed = True


def online_bridge(port: FakePort, **timeouts: float) -> Bridge:
    settings = {
        "ready_timeout": 0.3,
        "short_timeout": 0.4,
        "margin": 0.4,
        "step_seconds": 0.003,
        "read_slice": 0.02,
    }
    settings.update(timeouts)
    bridge = Bridge(lambda _name: port, **settings)
    port.push("READY", "PONG")
    if not bridge.open_port("COM5"):
        bridge.close()
        raise AssertionError("the fake robot did not come online")
    with port._lock:
        port.written.clear()
    return bridge


def wait_until(check, limit: float = 1.0) -> bool:
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.01)
    return False


class BridgeTests(unittest.TestCase):
    def test_a_missing_port_stays_offline(self) -> None:
        def opener(_name: str) -> FakePort:
            raise serial.SerialException("no such port")

        bridge = Bridge(opener, ready_timeout=0.05, short_timeout=0.05)
        self.addCleanup(bridge.close)
        self.assertFalse(bridge.open_port("COM9"))
        self.assertFalse(bridge.online)
        with self.assertRaises(BridgeError) as caught:
            bridge.drive(10, 1)
        self.assertEqual(caught.exception.message, "The robot is offline.")

    def test_boot_noise_then_ready_and_pong_marks_the_link_up(self) -> None:
        port = FakePort()
        bridge = Bridge(lambda _name: port, ready_timeout=0.3, short_timeout=0.3, read_slice=0.02)
        self.addCleanup(bridge.close)
        port.push("garbage", "READY", "PONG")
        self.assertTrue(bridge.open_port("COM5"))
        self.assertTrue(bridge.online)
        self.assertEqual(port.snapshot(), ["PING\n"])

    def test_pong_without_ready_still_comes_online(self) -> None:
        port = FakePort()
        port.pong_on_ping = True
        bridge = Bridge(lambda _name: port, ready_timeout=0.08, short_timeout=0.3, read_slice=0.02)
        self.addCleanup(bridge.close)
        self.assertTrue(bridge.open_port("COM5"))
        self.assertEqual(port.snapshot(), ["PING\n"])

    def test_a_silent_ping_leaves_the_robot_offline(self) -> None:
        port = FakePort()
        bridge = Bridge(lambda _name: port, ready_timeout=0.05, short_timeout=0.08, read_slice=0.02)
        self.addCleanup(bridge.close)
        port.push("READY")
        self.assertFalse(bridge.open_port("COM5"))
        self.assertFalse(bridge.online)
        self.assertTrue(port.closed)

    def test_ping_answers_pong(self) -> None:
        port = FakePort()
        bridge = online_bridge(port)
        self.addCleanup(bridge.close)
        port.push("PONG")
        bridge.ping()
        self.assertEqual(port.snapshot(), ["PING\n"])

    def test_drive_and_spin_echo_the_same_count_and_direction(self) -> None:
        port = FakePort()
        bridge = online_bridge(port)
        self.addCleanup(bridge.close)
        port.push("DONE DRIVE 100 1")
        drive = bridge.drive(100, 1)
        self.assertEqual(drive, MoveResult(False, "DRIVE", 100, 1))
        port.push("READY", "PONG", "DONE SPIN 40 -1")
        spin = bridge.spin(40, -1)
        self.assertEqual(spin, MoveResult(False, "SPIN", 40, -1))
        self.assertEqual(port.snapshot(), ["DRIVE 100 1\n", "SPIN 40 -1\n"])

    def test_a_bad_count_or_direction_is_not_written(self) -> None:
        port = FakePort()
        bridge = online_bridge(port)
        self.addCleanup(bridge.close)
        for steps, direction in ((0, 1), (16001, 1), (10, 2), (10, 0), (True, 1), (10, True)):
            with self.assertRaises(BridgeError):
                bridge.drive(steps, direction)
        self.assertEqual(port.snapshot(), [])
        self.assertTrue(bridge.online)

    def test_err_bad_fails_the_call_and_is_not_retried(self) -> None:
        port = FakePort()
        bridge = online_bridge(port)
        self.addCleanup(bridge.close)
        port.push("ERR BAD")
        with self.assertRaises(BridgeError) as caught:
            bridge.drive(10, 1)
        self.assertEqual(caught.exception.message, "The robot answered ERR BAD.")
        self.assertEqual(port.snapshot(), ["DRIVE 10 1\n"])
        self.assertTrue(bridge.online)
        self.assertFalse(port.closed)

    def test_a_mismatched_done_drops_the_port(self) -> None:
        port = FakePort()
        bridge = online_bridge(port)
        self.addCleanup(bridge.close)
        port.push("DONE DRIVE 9 1")
        with self.assertRaises(BridgeError) as caught:
            bridge.drive(10, 1)
        self.assertEqual(caught.exception.message, "The robot's reply did not match the move.")
        self.assertFalse(bridge.online)
        self.assertTrue(port.closed)

    def test_a_timeout_drops_the_port(self) -> None:
        port = FakePort()
        bridge = online_bridge(port, margin=0.08, step_seconds=0, read_slice=0.02)
        self.addCleanup(bridge.close)
        with self.assertRaises(BridgeError) as caught:
            bridge.drive(10, 1)
        self.assertEqual(caught.exception.message, "The robot did not answer in time.")
        self.assertFalse(bridge.online)
        self.assertTrue(port.closed)

    def test_a_disconnect_drops_the_port(self) -> None:
        port = FakePort()
        bridge = online_bridge(port)
        self.addCleanup(bridge.close)

        def explode() -> bytes:
            raise serial.SerialException("unplugged")

        port.readline = explode  # type: ignore[method-assign]
        with self.assertRaises(BridgeError) as caught:
            bridge.drive(10, 1)
        self.assertEqual(caught.exception.message, "The robot disconnected.")
        self.assertFalse(bridge.online)

    def test_a_second_drive_is_refused_and_not_written(self) -> None:
        port = FakePort()
        bridge = online_bridge(port, margin=1.0)
        self.addCleanup(bridge.close)
        finished = threading.Event()
        holder: dict[str, MoveResult] = {}

        def run() -> None:
            holder["result"] = bridge.drive(10, 1)
            finished.set()

        caller = threading.Thread(target=run)
        caller.start()
        self.assertTrue(wait_until(lambda: "DRIVE 10 1\n" in port.snapshot()))
        with self.assertRaises(BridgeError) as caught:
            bridge.drive(12, -1)
        self.assertEqual(caught.exception.message, "A move is already running.")
        self.assertNotIn("DRIVE 12 -1\n", port.snapshot())
        port.push("DONE DRIVE 10 1")
        self.assertTrue(finished.wait(2))
        caller.join(timeout=1)
        self.assertEqual(holder["result"], MoveResult(False, "DRIVE", 10, 1))

    def test_stop_during_a_drive_writes_stop_once(self) -> None:
        port = FakePort()
        bridge = online_bridge(port, margin=1.0, short_timeout=0.5)
        self.addCleanup(bridge.close)
        finished = threading.Event()
        holder: dict[str, MoveResult] = {}

        def run() -> None:
            holder["result"] = bridge.drive(100, 1)
            finished.set()

        caller = threading.Thread(target=run)
        caller.start()
        self.assertTrue(wait_until(lambda: "DRIVE 100 1\n" in port.snapshot()))
        bridge.stop()
        self.assertTrue(finished.wait(2))
        caller.join(timeout=1)
        self.assertEqual(holder["result"], MoveResult(stopped=True))
        self.assertEqual(port.snapshot().count("STOP\n"), 1)
        self.assertTrue(bridge.online)

    def test_an_idle_stop_releases_the_coils(self) -> None:
        port = FakePort()
        bridge = online_bridge(port)
        self.addCleanup(bridge.close)
        bridge.stop()
        self.assertEqual(port.snapshot(), ["STOP\n"])
        self.assertTrue(bridge.online)

    def test_the_app_holds_a_bridge_and_does_not_open_a_port(self) -> None:
        app = create_app()
        self.addCleanup(app["bridge"].close)
        self.assertFalse(app["bridge"].online)


if __name__ == "__main__":
    unittest.main()
