"""Serial link to the Arduino. One thread owns the port.

The bridge writes one command and waits for the matching reply. It does not
choose moves or track the robot's pose. A missing port leaves the phone game
running.
"""

import logging
import queue
import threading
import time
from dataclasses import dataclass

import serial

log = logging.getLogger(__name__)

BAUD = 115200
MAX_STEPS = 16000
STEP_SECONDS = 0.003
READY_TIMEOUT_SECONDS = 2.0
SHORT_TIMEOUT_SECONDS = 1.0
MOTION_MARGIN_SECONDS = 1.0
READ_SLICE_SECONDS = 0.05


class BridgeError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class MoveResult:
    stopped: bool
    command: str | None = None
    steps: int | None = None
    direction: int | None = None


class _Job:
    def __init__(self, kind: str, **details: object) -> None:
        self.kind = kind
        self.done = threading.Event()
        self.value: object = None
        self.error: BaseException | None = None
        for name, detail in details.items():
            setattr(self, name, detail)

    def result(self) -> object:
        self.done.wait()
        if self.error is not None:
            raise self.error
        return self.value


class _StopWait:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.error: BaseException | None = None


def open_serial_port(name: str) -> serial.Serial:
    return serial.Serial(name, baudrate=BAUD, timeout=READ_SLICE_SECONDS)


def parse_done(line: str) -> tuple[str, int, int] | None:
    parts = line.split(" ")
    if len(parts) != 4 or parts[0] != "DONE" or parts[1] not in ("SPIN", "DRIVE"):
        return None
    if not parts[2].isdigit() or parts[3] not in ("1", "-1"):
        return None
    return parts[1], int(parts[2]), int(parts[3])


def check_move(steps: object, direction: object) -> None:
    if type(steps) is not int or not 1 <= steps <= MAX_STEPS:
        raise BridgeError("The step count must be from 1 through 16000.")
    if type(direction) is not int or direction not in (1, -1):
        raise BridgeError("The direction must be 1 or -1.")


class Bridge:
    def __init__(
        self,
        opener: object = None,
        *,
        ready_timeout: float = READY_TIMEOUT_SECONDS,
        short_timeout: float = SHORT_TIMEOUT_SECONDS,
        margin: float = MOTION_MARGIN_SECONDS,
        step_seconds: float = STEP_SECONDS,
        read_slice: float = READ_SLICE_SECONDS,
    ) -> None:
        self._opener = opener or open_serial_port
        self._ready_timeout = ready_timeout
        self._short_timeout = short_timeout
        self._margin = margin
        self._step_seconds = step_seconds
        self._read_slice = read_slice
        self._jobs: queue.Queue[_Job | None] = queue.Queue()
        self._lock = threading.Lock()
        self._port: object = None
        self._pending = b""
        self._online = False
        self._closed = False
        self._motion_in_flight = False
        self._stop_requested = threading.Event()
        self._stop_waiter: _StopWait | None = None
        self._thread = threading.Thread(target=self._run, name="robot-serial", daemon=True)
        self._thread.start()

    @property
    def online(self) -> bool:
        with self._lock:
            return self._online

    def open_port(self, name: str) -> bool:
        """Open the port, then ping. False means the robot stays offline."""
        if self._is_closed() or not isinstance(name, str) or not name.strip():
            return False
        job = _Job("open", name=name.strip())
        self._submit(job)
        return bool(job.result())

    def ping(self) -> None:
        self._require_idle()
        job = _Job("ping")
        self._submit(job)
        job.result()

    def spin(self, steps: object, direction: object) -> MoveResult:
        return self._move("SPIN", steps, direction)

    def drive(self, steps: object, direction: object) -> MoveResult:
        return self._move("DRIVE", steps, direction)

    def stop(self) -> None:
        """Abort the move in flight, or release the coils when the robot is idle."""
        with self._lock:
            if self._closed or not self._online:
                raise BridgeError("The robot is offline.")
            if self._motion_in_flight:
                self._stop_requested.set()
                waiter = self._stop_waiter
            else:
                waiter = None
        if waiter is not None:
            waiter.event.wait()
            if waiter.error is not None:
                raise waiter.error
            return
        job = _Job("stop")
        self._submit(job)
        job.result()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._jobs.put(None)
        self._thread.join(timeout=5)

    def _move(self, command: str, steps: object, direction: object) -> MoveResult:
        check_move(steps, direction)
        job = _Job("motion", command=command, steps=steps, direction=direction)
        with self._lock:
            if self._closed or not self._online:
                raise BridgeError("The robot is offline.")
            if self._motion_in_flight:
                raise BridgeError("A move is already running.")
            self._stop_requested.clear()
            self._motion_in_flight = True
            self._stop_waiter = _StopWait()
        self._submit(job)
        return job.result()  # type: ignore[return-value]

    def _require_idle(self) -> None:
        with self._lock:
            if self._closed or not self._online:
                raise BridgeError("The robot is offline.")
            if self._motion_in_flight:
                raise BridgeError("A move is already running.")

    def _is_closed(self) -> bool:
        with self._lock:
            return self._closed

    def _submit(self, job: _Job) -> None:
        with self._lock:
            if self._closed:
                raise BridgeError("The robot is offline.")
        self._jobs.put(job)

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                self._drop_port()
                return
            try:
                job.value = self._execute(job)
            except Exception as exc:
                job.error = exc
                log.info("Robot command failed: %s", exc)
            finally:
                if job.kind == "motion":
                    self._finish_motion(job.error)
                job.done.set()

    def _finish_motion(self, error: BaseException | None) -> None:
        with self._lock:
            self._motion_in_flight = False
            waiter = self._stop_waiter
            self._stop_waiter = None
        if waiter is not None:
            waiter.error = error
            waiter.event.set()

    def _execute(self, job: _Job) -> object:
        if job.kind == "open":
            return self._do_open(job.name)  # type: ignore[attr-defined]
        if job.kind == "ping":
            self._write("PING")
            self._read_pong(time.monotonic() + self._short_timeout)
            return None
        if job.kind == "stop":
            self._write("STOP")
            self._read_exact("DONE STOP", time.monotonic() + self._short_timeout)
            return None
        return self._run_motion(job.command, job.steps, job.direction)  # type: ignore[attr-defined]

    def _do_open(self, name: str) -> bool:
        self._drop_port()
        try:
            port = self._opener(name)  # type: ignore[operator]
        except (serial.SerialException, OSError) as exc:
            log.info("Robot port %s did not open: %s", name, exc)
            return False
        self._port = port
        self._pending = b""
        try:
            port.timeout = self._read_slice
        except Exception:
            log.info("Robot port %s has no read timeout", name)
        try:
            if not self._wait_ready():
                log.info("Robot on %s did not send READY", name)
            self._write("PING")
            self._read_pong(time.monotonic() + self._short_timeout)
        except BridgeError as exc:
            log.info("Robot on %s is not answering: %s", name, exc.message)
            self._drop_port()
            return False
        with self._lock:
            self._online = True
        log.info("Robot online on %s", name)
        return True

    def _wait_ready(self) -> bool:
        deadline = time.monotonic() + self._ready_timeout
        while time.monotonic() < deadline:
            line = self._readline()
            if line == "READY":
                return True
        return False

    def _run_motion(self, command: str, steps: int, direction: int) -> MoveResult:
        self._write(f"{command} {steps} {direction}")
        deadline = time.monotonic() + steps * self._step_seconds + self._margin
        stop_written = False
        while True:
            if time.monotonic() >= deadline:
                self._drop_port()
                raise BridgeError("The robot did not answer in time.")
            line = self._readline()
            if not line:
                if self._stop_requested.is_set() and not stop_written:
                    self._write("STOP")
                    stop_written = True
                    deadline = time.monotonic() + self._short_timeout
                continue
            if line in ("READY", "PONG"):
                log.info("Ignored %s while a move was running", line)
                continue
            if line in ("ERR BAD", "ERR BUSY"):
                raise BridgeError(f"The robot answered {line}.")
            if line == "DONE STOP" and stop_written:
                return MoveResult(stopped=True)
            parsed = parse_done(line)
            if parsed == (command, steps, direction):
                if stop_written:
                    self._drain_done_stop()
                return MoveResult(False, command, steps, direction)
            self._drop_port()
            raise BridgeError("The robot's reply did not match the move.")

    def _drain_done_stop(self) -> None:
        """A STOP that lost the race can still answer after DONE. Drop that line."""
        deadline = time.monotonic() + min(0.2, self._short_timeout)
        while time.monotonic() < deadline:
            line = self._readline()
            if not line or line in ("READY", "PONG"):
                continue
            if line != "DONE STOP":
                log.info("Ignored %s after a finished move", line)
            return

    def _read_pong(self, deadline: float) -> None:
        while time.monotonic() < deadline:
            line = self._readline()
            if line == "PONG":
                return
            if line == "READY" or not line:
                continue
            log.info("Ignored %s while waiting for PONG", line)
        self._drop_port()
        raise BridgeError("The robot did not answer in time.")

    def _read_exact(self, expected: str, deadline: float) -> None:
        while time.monotonic() < deadline:
            line = self._readline()
            if line == expected:
                return
            if not line:
                continue
            self._drop_port()
            raise BridgeError("The robot's reply did not match the move.")
        self._drop_port()
        raise BridgeError("The robot did not answer in time.")

    def _write(self, text: str) -> None:
        port = self._port
        if port is None:
            raise BridgeError("The robot is offline.")
        try:
            port.write((text + "\n").encode("ascii"))  # type: ignore[attr-defined]
            flush = getattr(port, "flush", None)
            if flush is not None:
                flush()
        except (serial.SerialException, OSError) as exc:
            self._drop_port()
            raise BridgeError("The robot disconnected.") from exc

    def _readline(self) -> str | None:
        if b"\n" not in self._pending:
            port = self._port
            if port is None:
                raise BridgeError("The robot is offline.")
            try:
                raw = port.readline()  # type: ignore[attr-defined]
            except (serial.SerialException, OSError) as exc:
                self._drop_port()
                raise BridgeError("The robot disconnected.") from exc
            if raw:
                self._pending += raw
        if b"\n" not in self._pending:
            return None
        line, _, self._pending = self._pending.partition(b"\n")
        return line.decode("ascii", errors="replace").strip("\r").strip()

    def _drop_port(self) -> None:
        port = self._port
        self._port = None
        self._pending = b""
        with self._lock:
            self._online = False
        if port is None:
            return
        try:
            port.close()  # type: ignore[attr-defined]
        except Exception:
            log.warning("Closing the robot port failed", exc_info=True)
