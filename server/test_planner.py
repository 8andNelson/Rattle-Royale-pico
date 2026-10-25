"""Chunk choice from a pose and a mark, without an Arduino attached."""

import unittest

from server.planner import (
    ALIGN_DEGREES,
    ARRIVAL_RADIUS_MM,
    MARK_RADIUS_MM,
    MAX_DRIVE_MM,
    MAX_SPIN_DEGREES,
    Chunk,
    arrived_mark,
    choose_chunk,
    mark_at,
    next_chunk,
    plan,
)
from server.pose import STEPS_PER_DEGREE, STEPS_PER_MM, Pose


def steps_for(amount: float, scale: float) -> int:
    return int(round(amount * scale))


class ChooseChunkTests(unittest.TestCase):
    def test_a_large_heading_error_spins_one_short_chunk(self) -> None:
        chunk = choose_chunk(90, MARK_RADIUS_MM)
        self.assertEqual(
            chunk,
            Chunk("SPIN", steps_for(MAX_SPIN_DEGREES, STEPS_PER_DEGREE), 1),
        )

    def test_heading_errors_above_the_cap_share_one_spin_chunk(self) -> None:
        capped = choose_chunk(90, 100)
        still_capped = choose_chunk(ALIGN_DEGREES + 1, 100)
        self.assertEqual(capped, still_capped)
        self.assertEqual(capped.steps, steps_for(MAX_SPIN_DEGREES, STEPS_PER_DEGREE))

    def test_a_negative_heading_error_spins_toward_lower_seats(self) -> None:
        chunk = choose_chunk(-90, MARK_RADIUS_MM)
        self.assertEqual(chunk.command, "SPIN")
        self.assertEqual(chunk.direction, -1)
        self.assertEqual(chunk.steps, steps_for(MAX_SPIN_DEGREES, STEPS_PER_DEGREE))

    def test_an_exact_half_turn_spins_toward_higher_seats(self) -> None:
        chunk = choose_chunk(180, MARK_RADIUS_MM)
        self.assertEqual(chunk.direction, 1)

    def test_alignment_at_the_threshold_drives_forward(self) -> None:
        chunk = choose_chunk(ALIGN_DEGREES, MARK_RADIUS_MM)
        self.assertEqual(
            chunk,
            Chunk("DRIVE", steps_for(MAX_DRIVE_MM, STEPS_PER_MM), -1),
        )

    def test_a_short_remaining_distance_is_not_padded_to_the_cap(self) -> None:
        remaining = MAX_DRIVE_MM - 2
        chunk = choose_chunk(0, remaining)
        self.assertEqual(chunk, Chunk("DRIVE", steps_for(remaining, STEPS_PER_MM), -1))

    def test_no_distance_and_no_turn_sends_nothing(self) -> None:
        self.assertIsNone(choose_chunk(0, 0))


class NextChunkTests(unittest.TestCase):
    def test_home_aimed_at_seat_zero_drives_toward_it(self) -> None:
        chunk = next_chunk(Pose(), mark_at(0))
        self.assertEqual(
            chunk,
            Chunk("DRIVE", steps_for(MAX_DRIVE_MM, STEPS_PER_MM), -1),
        )

    def test_seat_zero_is_on_the_positive_x_axis(self) -> None:
        x, y = mark_at(0)
        self.assertAlmostEqual(x, MARK_RADIUS_MM)
        self.assertAlmostEqual(y, 0)
        x, y = mark_at(90)
        self.assertAlmostEqual(x, 0, places=6)
        self.assertAlmostEqual(y, MARK_RADIUS_MM)

    def test_a_mark_to_the_left_spins_toward_higher_seats(self) -> None:
        chunk = next_chunk(Pose(), mark_at(90))
        self.assertEqual(
            chunk,
            Chunk("SPIN", steps_for(MAX_SPIN_DEGREES, STEPS_PER_DEGREE), 1),
        )

    def test_a_mark_to_the_right_spins_the_short_way(self) -> None:
        chunk = next_chunk(Pose(), mark_at(270))
        self.assertEqual(chunk.command, "SPIN")
        self.assertEqual(chunk.direction, -1)

    def test_the_short_way_wraps_across_zero(self) -> None:
        pose = Pose()
        pose.apply("SPIN", 10 * STEPS_PER_DEGREE, 1)
        chunk = next_chunk(pose, mark_at(350))
        self.assertEqual(chunk.command, "SPIN")
        self.assertEqual(chunk.direction, -1)
        self.assertEqual(chunk.steps, steps_for(MAX_SPIN_DEGREES, STEPS_PER_DEGREE))

    def test_a_drive_uses_the_heading_after_the_spin(self) -> None:
        pose = Pose()
        pose.apply("SPIN", 90 * STEPS_PER_DEGREE, 1)
        chunk = next_chunk(pose, mark_at(90))
        self.assertEqual(chunk.command, "DRIVE")
        self.assertEqual(chunk.direction, -1)

    def test_a_new_leader_is_a_spin_on_the_next_chunk(self) -> None:
        pose = Pose()
        pose.apply("SPIN", 90 * STEPS_PER_DEGREE, 1)
        chunk = next_chunk(pose, mark_at(0))
        self.assertEqual(
            chunk,
            Chunk("SPIN", steps_for(MAX_SPIN_DEGREES, STEPS_PER_DEGREE), -1),
        )

    def test_no_target_sends_nothing(self) -> None:
        self.assertIsNone(next_chunk(Pose(), None))

    def test_an_unknown_pose_sends_nothing(self) -> None:
        pose = Pose()
        pose.mark_unknown()
        self.assertIsNone(next_chunk(pose, mark_at(0)))

    def test_inside_the_arrival_radius_sends_nothing(self) -> None:
        pose = Pose()
        pose.apply("DRIVE", (MARK_RADIUS_MM - ARRIVAL_RADIUS_MM / 2) * STEPS_PER_MM, -1)
        self.assertIsNone(next_chunk(pose, mark_at(0)))


class ArrivalTests(unittest.TestCase):
    def test_home_has_not_reached_a_mark(self) -> None:
        self.assertIsNone(arrived_mark(Pose(), [mark_at(0), mark_at(180)]))

    def test_the_closest_mark_inside_the_radius_wins(self) -> None:
        pose = Pose()
        pose.apply("DRIVE", 100 * STEPS_PER_MM, -1)
        marks = [(120, 0), (100, 10), mark_at(90)]
        self.assertEqual(arrived_mark(pose, marks), 1)

    def test_a_tie_keeps_the_earlier_mark(self) -> None:
        pose = Pose()
        pose.apply("DRIVE", 100 * STEPS_PER_MM, -1)
        marks = [(100 + ARRIVAL_RADIUS_MM, 0), (100 - ARRIVAL_RADIUS_MM, 0)]
        self.assertEqual(arrived_mark(pose, marks), 0)

    def test_arrival_at_another_mark_sends_no_chunk(self) -> None:
        pose = Pose()
        pose.apply("SPIN", 90 * STEPS_PER_DEGREE, 1)
        pose.apply("DRIVE", (MARK_RADIUS_MM - 10) * STEPS_PER_MM, -1)
        marks = [mark_at(0), mark_at(90)]
        decision = plan(pose, mark_at(0), marks)
        self.assertEqual(decision.arrived, 1)
        self.assertIsNone(decision.chunk)

    def test_an_unknown_pose_does_not_count_as_arrived(self) -> None:
        pose = Pose()
        pose.apply("DRIVE", MARK_RADIUS_MM * STEPS_PER_MM, -1)
        pose.mark_unknown()
        self.assertIsNone(arrived_mark(pose, [mark_at(0)]))


if __name__ == "__main__":
    unittest.main()
