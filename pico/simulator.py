"""Pretend to be the Pico W robot, on the laptop.

Runs the robot's real brain.py and navigation.py against the game server,
with wheels that only count steps. Phones see it exactly like the real robot,
so a whole chase can be played before the hardware exists.

From the project folder, with the server running and RATTLE_ROBOT_TOKEN set:

  python pico/simulator.py
  python pico/simulator.py --speed 5
  python pico/simulator.py --url https://petroleum-guy-whenever.ngrok-free.dev

--speed runs the wheels that many times faster than the real motors.
"""

import argparse
import http.client
import json
import os
import sys
import threading
import time
import types
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config_example  # noqa: E402
from brain import Brain  # noqa: E402


class SimWheels:
    """Same calls as stepper.Wheels. Steps happen on a timer, not on pins."""

    def __init__(self, step_us, speed):
        self._tick_seconds = step_us / 1_000_000 / speed
        self._lock = threading.Lock()
        self._goal = [0, 0]
        self._sent = [0, 0]
        self._ticks = 0
        self._length = 0
        self._done = [0, 0]
        self._running = True
        self._thread = threading.Thread(target=self._run, name="sim-wheels", daemon=True)
        self._thread.start()

    def move(self, left_steps, right_steps):
        with self._lock:
            self._goal = [left_steps, right_steps]
            self._sent = [0, 0]
            self._ticks = 0
            self._length = max(abs(left_steps), abs(right_steps))

    def stop(self):
        with self._lock:
            self._length = 0

    def busy(self):
        with self._lock:
            return self._ticks < self._length

    def take_steps(self):
        with self._lock:
            done = (self._done[0], self._done[1])
            self._done = [0, 0]
        return done

    def shutdown(self):
        self._running = False
        self._thread.join(timeout=1)

    def _run(self):
        last = time.monotonic()
        owed = 0.0
        while self._running:
            time.sleep(0.005)
            now = time.monotonic()
            owed += (now - last) / self._tick_seconds
            last = now
            with self._lock:
                while owed >= 1 and self._ticks < self._length:
                    owed -= 1
                    self._ticks += 1
                    for wheel in (0, 1):
                        goal = self._goal[wheel]
                        wanted = abs(goal) * self._ticks // self._length
                        if wanted > abs(self._sent[wheel]):
                            sign = 1 if goal > 0 else -1
                            self._sent[wheel] += sign
                            self._done[wheel] += sign
                if self._ticks >= self._length:
                    owed = 0.0


class SimWlan:
    def isconnected(self):
        return True

    def ifconfig(self):
        return ("simulator",)

    def connect(self, ssid, password):
        pass

    def disconnect(self):
        pass


class HttpLink:
    """Same calls as wifi_link.Link, on Python's http.client. Keeps one connection."""

    def __init__(self, url, token, timeout_s=3):
        parts = urlsplit(url)
        self._secure = parts.scheme == "https"
        self._host = parts.hostname
        self._port = parts.port
        self._prefix = parts.path.rstrip("/")
        self._token = token
        self._timeout = timeout_s
        self._connection = None

    def post(self, path, body):
        if self._connection is None:
            kind = http.client.HTTPSConnection if self._secure else http.client.HTTPConnection
            self._connection = kind(self._host, self._port, timeout=self._timeout)
        headers = {
            "Authorization": "Bearer " + self._token,
            "Content-Type": "application/json",
            "User-Agent": "rattle-robot-sim",
            "ngrok-skip-browser-warning": "1",
        }
        try:
            self._connection.request("POST", self._prefix + path, json.dumps(body), headers)
            response = self._connection.getresponse()
            reply = response.read()
        except (OSError, http.client.HTTPException):
            self.close()
            raise
        if response.status != 200:
            raise ValueError("Server answered " + str(response.status) + ": " + reply[:80].decode())
        return json.loads(reply)

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def settings(token, url):
    values = {name: getattr(config_example, name) for name in dir(config_example) if name.isupper()}
    values.update(ROBOT_TOKEN=token, SERVER_URL=url)
    return types.SimpleNamespace(**values)


def main():
    parser = argparse.ArgumentParser(description="Pretend to be the Pico W robot.")
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--token", default=os.environ.get("RATTLE_ROBOT_TOKEN", ""))
    parser.add_argument("--speed", type=float, default=1.0)
    args = parser.parse_args()
    if not args.token:
        parser.error("Pass --token or set RATTLE_ROBOT_TOKEN, matching the server.")

    config = settings(args.token, args.url)
    wheels = SimWheels(config.STEP_US, args.speed)
    brain = Brain(config, wheels, HttpLink(config.SERVER_URL, config.ROBOT_TOKEN), SimWlan())
    print("Simulated robot talking to", args.url, "at", args.speed, "x speed. Ctrl+C stops it.")
    shown_at = 0.0
    try:
        while True:
            brain.tick()
            now = time.monotonic()
            if now - shown_at >= 1:
                shown_at = now
                report = brain.report()
                print(
                    "  {mode:<5} x={x:7.1f} y={y:7.1f} heading={heading:6.1f}{moving}".format(
                        mode=brain.order.get("mode", "?"),
                        moving="  moving" if report["moving"] else "",
                        **{key: report[key] for key in ("x", "y", "heading")},
                    )
                )
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        wheels.shutdown()


if __name__ == "__main__":
    main()
