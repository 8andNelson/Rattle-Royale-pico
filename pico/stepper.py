"""Two 28BYJ-48 steppers on ULN2003 drivers, stepped from the Pico's second core.

Core 0 runs Wi-Fi and planning, and an HTTPS request there can block for a
while. Core 1 does nothing but step the wheels, so that wait never stalls the
motors. The two cores share a few counters behind one lock.

A move is a signed step count per wheel in forward terms. Both wheels finish
together, so a spin or a drive stays straight. stop() ends a move between
steps, and take_steps() reports what each wheel really did, so the pose stays
right even when a move is cut short.
"""

import _thread
import time

from machine import Pin

# Half-step order for IN1, IN2, IN3, IN4.
SEQUENCE = (
    (1, 0, 0, 0),
    (1, 1, 0, 0),
    (0, 1, 0, 0),
    (0, 1, 1, 0),
    (0, 0, 1, 0),
    (0, 0, 1, 1),
    (0, 0, 0, 1),
    (1, 0, 0, 1),
)


class Wheels:
    def __init__(self, left_pins, right_pins, left_forward, right_forward, step_us):
        self._pins = (
            [Pin(n, Pin.OUT, value=0) for n in left_pins],
            [Pin(n, Pin.OUT, value=0) for n in right_pins],
        )
        self._forward = (left_forward, right_forward)
        self._phase = [0, 0]
        self._step_us = step_us
        self._lock = _thread.allocate_lock()
        self._goal = [0, 0]
        self._sent = [0, 0]
        self._ticks = 0
        self._length = 0
        self._done = [0, 0]
        self._running = True
        self._exited = False
        _thread.start_new_thread(self._run, ())

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
        """Forward steps each wheel took since the last call."""
        with self._lock:
            done = (self._done[0], self._done[1])
            self._done = [0, 0]
        return done

    def shutdown(self):
        """Stop core 1 and release the coils. Call before a soft reset."""
        self._running = False
        for _ in range(100):
            if self._exited:
                break
            time.sleep_ms(10)

    def _run(self):
        released = True
        due = time.ticks_us()
        while self._running:
            stepped = False
            with self._lock:
                if self._ticks < self._length:
                    self._ticks += 1
                    for wheel in (0, 1):
                        goal = self._goal[wheel]
                        # Spread each wheel's steps evenly over the move.
                        wanted = abs(goal) * self._ticks // self._length
                        if wanted > abs(self._sent[wheel]):
                            sign = 1 if goal > 0 else -1
                            self._sent[wheel] += sign
                            self._done[wheel] += sign
                            self._step(wheel, sign)
                    stepped = True
            if stepped:
                released = False
                due = time.ticks_add(due, self._step_us)
                wait = time.ticks_diff(due, time.ticks_us())
                if wait > 0:
                    time.sleep_us(wait)
                else:
                    due = time.ticks_us()
            else:
                if not released:
                    self._release()
                    released = True
                time.sleep_ms(1)
                due = time.ticks_us()
        self._release()
        self._exited = True

    def _step(self, wheel, sign):
        self._phase[wheel] = (self._phase[wheel] + sign * self._forward[wheel]) % 8
        for pin, value in zip(self._pins[wheel], SEQUENCE[self._phase[wheel]]):
            pin.value(value)

    def _release(self):
        for pins in self._pins:
            for pin in pins:
                pin.value(0)
