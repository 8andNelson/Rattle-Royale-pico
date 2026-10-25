"""Wireless link to the Pico W robot.

The robot polls over HTTPS. Each poll reports its pose and gets back what to
do: chase a seat's floor mark, hold still, drive home, or go to a test point.
The robot plans its own spins and drives. The laptop never sends steps.

Every order also carries a reset id. When it changes, the robot sets its pose
back to the center, pointed at seat 0. The host asks for that after placing
the robot there by hand.

A host can stop the robot at any time. Every order is then stop, until the
host resumes it or marks it back on the center.

Manual control, from the /robot panel, keeps the robot out of the game: it
holds still unless it is given a jog (one relative drive or spin) or a point
to drive to. After the robot reaches a chase winner it wiggles for a few
seconds before it drives home.

Every report carries a boot id. When a new boot id shows up soon after the
last report, the robot just rebooted, so the next orders carry the pose it
had last. The robot takes that pose if it has not moved yet.
"""

import math
import secrets
import time

from server.lobby import LobbyBook

MARK_RADIUS_MM = 152.4
ONLINE_SECONDS = 3.0
HOME_RADIUS_MM = 30.0
HOME_HEADING_DEGREES = 10.0
RESTORE_SECONDS = 60.0
CELEBRATE_SECONDS = 3.0
MAX_JOG_MM = 1000.0
MAX_JOG_DEGREES = 720.0
HEALTH_KEYS = ("uptime_s", "latency_ms", "rssi", "mem_free")


class PicoLink:
    def __init__(self, token: str | None, mark_radius: float = MARK_RADIUS_MM) -> None:
        self.token = token or None
        self.mark_radius = mark_radius
        self.pose: dict | None = None
        self.seen_at: float | None = None
        self.arrivals: list[dict] = []
        self.test_point: dict | None = None
        self.reset_id: str | None = None
        self.halted = False
        self.manual = False
        self.jog: dict | None = None
        self.celebration: dict | None = None
        self.boot_id: str | None = None
        self.boots = 0
        self.restore: dict | None = None
        self.health: dict | None = None

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
        self.restore = None
        self.halted = False

    def halt(self) -> None:
        self.halted = True
        self.jog = None

    def resume(self) -> None:
        self.halted = False

    def set_manual(self, on: bool) -> None:
        self.manual = on
        self.jog = None
        if not on:
            self.test_point = None

    def add_jog(self, kind: object, amount: object) -> None:
        """One relative move. A jog puts the robot in manual control."""
        if kind not in ("drive", "spin"):
            raise ValueError("A jog is a drive or a spin.")
        limit = MAX_JOG_MM if kind == "drive" else MAX_JOG_DEGREES
        if not is_number(amount) or amount == 0 or abs(amount) > limit:
            unit = "millimeters" if kind == "drive" else "degrees"
            raise ValueError(f"Jog by 1 to {limit:g} {unit}, either way.")
        self.manual = True
        self.test_point = None
        self.jog = {"id": secrets.token_hex(4), "kind": kind, "amount": float(amount)}

    def goto_seat(self, seat: object, count: object) -> None:
        if type(count) is not int or not 1 <= count <= 8:
            raise ValueError("The seat count is 1 through 8.")
        if type(seat) is not int or not 0 <= seat < count:
            raise ValueError("That seat is not on the circle.")
        x, y = mark_position(360 * seat / count, self.mark_radius)
        self.jog = None
        self.test_point = {"x": x, "y": y}

    def go_home(self) -> None:
        self.manual = False
        self.jog = None
        self.test_point = None

    def summary(self) -> dict:
        """What phones see."""
        return {
            "online": self.online(),
            "home": self.at_home(),
            "pose": self.pose,
            "radius": self.mark_radius,
            "halted": self.halted,
            "manual": self.manual,
        }

    def poll(self, book: LobbyBook, report: object, now: float | None = None) -> tuple[dict, dict | None]:
        """Record a robot report. Returns the order and any new arrival.

        An arrival for the open chase ends that round in the book.
        """
        moment = time.time() if now is None else now
        arrival = None
        if isinstance(report, dict):
            self._note_boot(report.get("boot"), moment)
            if report.get("restored") is True:
                self.restore = None
            pose = read_pose(report)
            if pose is not None:
                self.pose = pose
            self.health = read_health(report.get("health"))
            if self.jog is not None and report.get("jog_done") == self.jog["id"]:
                self.jog = None
            arrival = self._record_arrival(report.get("arrived"), moment)
            if arrival is not None:
                arrival["won"] = book.arrive(arrival["round"], arrival["seat"], moment)
                if arrival["won"]:
                    self.celebration = {"id": secrets.token_hex(4), "until": moment + CELEBRATE_SECONDS}
        self.seen_at = moment
        return self.order(book, moment), arrival

    def order(self, book: LobbyBook, now: float | None = None) -> dict:
        order = self._order(book, time.time() if now is None else now)
        order["reset"] = self.reset_id
        if self.restore is not None:
            order["restore"] = self.restore
        return order

    def _order(self, book: LobbyBook, now: float) -> dict:
        if self.halted:
            return {"mode": "stop"}
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
        if self.celebration is not None and now < self.celebration["until"]:
            return {"mode": "celebrate", "id": self.celebration["id"]}
        if self.jog is not None:
            return {"mode": "jog", "id": self.jog["id"], "kind": self.jog["kind"], "amount": self.jog["amount"]}
        if self.test_point is not None:
            return {"mode": "test", "x": self.test_point["x"], "y": self.test_point["y"]}
        if self.manual:
            return {"mode": "hold"}
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
        self.jog = None
        self.test_point = {"x": float(x), "y": float(y)}

    def status(self, book: LobbyBook) -> dict:
        return {
            "online": self.online(),
            "seen_seconds_ago": None if self.seen_at is None else round(time.time() - self.seen_at, 1),
            "pose": self.pose,
            "halted": self.halted,
            "manual": self.manual,
            "home": self.at_home(),
            "radius": self.mark_radius,
            "order": self.order(book),
            "health": self.health,
            "boot": self.boot_id,
            "boots": self.boots,
            "restoring": self.restore is not None,
            "arrivals": self.arrivals[-5:],
        }

    def _note_boot(self, boot: object, moment: float) -> None:
        """A new boot id soon after the last report means a reboot mid-game."""
        if not isinstance(boot, str) or boot == self.boot_id:
            return
        recent = self.seen_at is not None and moment - self.seen_at <= RESTORE_SECONDS
        if self.boot_id is not None and recent and self.pose is not None:
            self.restore = {key: self.pose[key] for key in ("x", "y", "heading")}
        else:
            self.restore = None
        self.boot_id = boot
        self.boots += 1

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


def read_health(health: object) -> dict | None:
    if not isinstance(health, dict):
        return None
    return {key: health.get(key) if is_number(health.get(key)) else None for key in HEALTH_KEYS}


def is_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)
