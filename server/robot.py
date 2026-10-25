"""Wireless link to the Pico W robot.

The robot polls over HTTPS. Each poll reports its pose and gets back what to
do: chase a seat's floor mark, hold still, drive home, or go to a test point.
The robot plans its own spins and drives. The laptop never sends steps.

Every order also carries a reset id. When it changes, the robot sets its pose
back to the center, pointed at seat 0. The host asks for that after placing
the robot there by hand.
"""

import math
import secrets
import time

from server.lobby import LobbyBook

MARK_RADIUS_MM = 250.0
ONLINE_SECONDS = 3.0
HOME_RADIUS_MM = 30.0
HOME_HEADING_DEGREES = 10.0


class RobotLink:
    def __init__(self, token: str | None, mark_radius: float = MARK_RADIUS_MM) -> None:
        self.token = token or None
        self.mark_radius = mark_radius
        self.pose: dict | None = None
        self.seen_at: float | None = None
        self.arrivals: list[dict] = []
        self.test_point: dict | None = None
        self.reset_id: str | None = None

    @property
    def enabled(self) -> bool:
        return self.token is not None

    def authorized(self, header: str | None) -> bool:
        if self.token is None or not header or not header.startswith("Bearer "):
            return False
        return secrets.compare_digest(header[len("Bearer "):].encode(), self.token.encode())

    def online(self, now: float | None = None) -> bool:
        moment = time.time() if now is None else now
        return self.seen_at is not None and moment - self.seen_at <= ONLINE_SECONDS

    def at_home(self) -> bool:
        """Online, still, and on the center mark facing seat 0."""
        pose = self.pose
        if not self.online() or pose is None or pose["moving"]:
            return False
        if math.hypot(pose["x"], pose["y"]) > HOME_RADIUS_MM:
            return False
        return abs((pose["heading"] + 180) % 360 - 180) <= HOME_HEADING_DEGREES

    def request_reset(self) -> None:
        self.reset_id = secrets.token_hex(4)
        self.pose = None

    def summary(self) -> dict:
        """What phones see."""
        return {
            "online": self.online(),
            "home": self.at_home(),
            "pose": self.pose,
            "radius": self.mark_radius,
        }

    def poll(self, book: LobbyBook, report: object, now: float | None = None) -> tuple[dict, dict | None]:
        """Record a robot report. Returns the order and any new arrival.

        An arrival for the open chase ends that round in the book.
        """
        moment = time.time() if now is None else now
        self.seen_at = moment
        arrival = None
        if isinstance(report, dict):
            pose = read_pose(report)
            if pose is not None:
                self.pose = pose
            arrival = self._record_arrival(report.get("arrived"), moment)
            if arrival is not None:
                arrival["won"] = book.arrive(arrival["round"], arrival["seat"], moment)
        return self.order(book), arrival

    def order(self, book: LobbyBook) -> dict:
        order = self._order(book)
        order["reset"] = self.reset_id
        return order

    def _order(self, book: LobbyBook) -> dict:
        current = book.robot_round()
        if current is not None:
            target = current["target"]
            if target is None:
                return {"mode": "hold", "round": current["code"]}
            x, y = mark_position(target["angle"], self.mark_radius)
            return {
                "mode": "chase",
                "round": current["code"],
                "seat": target["seat"],
                "name": target["name"],
                "x": x,
                "y": y,
            }
        if self.test_point is not None:
            return {"mode": "test", "x": self.test_point["x"], "y": self.test_point["y"]}
        return {"mode": "home"}

    def set_test_point(self, payload: object) -> None:
        if isinstance(payload, dict) and payload.get("clear") is True:
            self.test_point = None
            return
        if not isinstance(payload, dict):
            raise ValueError("Send x and y in millimeters, or clear.")
        x, y = payload.get("x"), payload.get("y")
        if not is_number(x) or not is_number(y):
            raise ValueError("Send x and y in millimeters, or clear.")
        self.test_point = {"x": float(x), "y": float(y)}

    def status(self, book: LobbyBook) -> dict:
        return {
            "online": self.online(),
            "seen_seconds_ago": None if self.seen_at is None else round(time.time() - self.seen_at, 1),
            "pose": self.pose,
            "order": self.order(book),
            "arrivals": self.arrivals[-5:],
        }

    def _record_arrival(self, arrived: object, moment: float) -> dict | None:
        if not isinstance(arrived, dict):
            return None
        code, seat = arrived.get("round"), arrived.get("seat")
        if not isinstance(code, str) or type(seat) is not int:
            return None
        if any(entry["round"] == code and entry["seat"] == seat for entry in self.arrivals):
            return None
        entry = {"round": code, "seat": seat, "at": moment}
        self.arrivals.append(entry)
        return entry


def mark_position(angle_degrees: float, radius: float) -> tuple[float, float]:
    """Seat 0 is along +x. Higher seats go counterclockwise, seen from above."""
    theta = math.radians(angle_degrees)
    return round(radius * math.cos(theta), 1), round(radius * math.sin(theta), 1)


def read_pose(report: dict) -> dict | None:
    x, y, heading = report.get("x"), report.get("y"), report.get("heading")
    if not (is_number(x) and is_number(y) and is_number(heading)):
        return None
    return {"x": float(x), "y": float(y), "heading": float(heading), "moving": report.get("moving") is True}


def is_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)
