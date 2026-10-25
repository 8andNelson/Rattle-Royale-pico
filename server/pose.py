"""Stored robot pose. The planner can update it after a finished move.

This module does not open a serial port and does not send motor commands.
Home is the center, pointed at seat 0. A stop, a timeout, or a dropped cable
makes the pose unknown until home is confirmed.
"""

import math

STEPS_PER_MM = 34.31
STEPS_PER_DEGREE = 38.03


def _wrap(degrees: float) -> float:
    wrapped = degrees % 360.0
    if wrapped == 0.0:
        return 0.0
    return wrapped


class Pose:
    def __init__(self) -> None:
        self._x = 0.0
        self._y = 0.0
        self._heading = 0.0
        self._known = True

    @property
    def x(self) -> float:
        return self._x

    @property
    def y(self) -> float:
        return self._y

    @property
    def heading(self) -> float:
        return self._heading

    @property
    def known(self) -> bool:
        return self._known

    def confirm_home(self) -> None:
        """The host has placed the robot on the center mark, pointed at seat 0."""
        self._x = 0.0
        self._y = 0.0
        self._heading = 0.0
        self._known = True

    def mark_unknown(self) -> None:
        """A stop, a timeout, or a dropped cable. Keep the last numbers and do not guess."""
        self._known = False

    def apply(self, command: str, steps: float | None = None, direction: int | None = None) -> None:
        """Apply one finished reply.

        ``command`` is ``SPIN``, ``DRIVE``, or ``STOP``. A spin or a drive is
        ignored while the pose is unknown. ``STOP`` marks it unknown.
        """
        if command == "STOP":
            self.mark_unknown()
            return
        if not self._known or steps is None or direction not in (1, -1):
            return
        if command == "SPIN":
            self._heading = _wrap(self._heading + direction * steps / STEPS_PER_DEGREE)
            return
        if command == "DRIVE":
            # Direction -1 travels along the heading. Direction 1 travels against it.
            signed_distance = -direction * steps / STEPS_PER_MM
            radians = math.radians(self._heading)
            self._x += math.cos(radians) * signed_distance
            self._y += math.sin(radians) * signed_distance
