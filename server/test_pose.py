"""Pose updates from finished moves, without an Arduino attached."""

import unittest

from server.pose import STEPS_PER_DEGREE, STEPS_PER_MM, Pose


class PoseTests(unittest.TestCase):
    def test_home_is_the_origin_pointed_at_seat_zero(self) -> None:
        pose = Pose()
        self.assertEqual(pose.x, 0)
        self.assertEqual(pose.y, 0)
        self.assertEqual(pose.heading, 0)
        self.assertTrue(pose.known)

    def test_drive_toward_seat_zero_increases_x(self) -> None:
        pose = Pose()
        pose.apply("DRIVE", STEPS_PER_MM, -1)
        self.assertAlmostEqual(pose.x, 1)
        self.assertAlmostEqual(pose.y, 0)
        self.assertEqual(pose.heading, 0)

    def test_drive_away_from_seat_zero_decreases_x(self) -> None:
        pose = Pose()
        pose.apply("DRIVE", STEPS_PER_MM, 1)
        self.assertAlmostEqual(pose.x, -1)
        self.assertAlmostEqual(pose.y, 0)
        self.assertEqual(pose.heading, 0)

    def test_the_same_drive_at_heading_90_changes_y(self) -> None:
        pose = Pose()
        pose.apply("SPIN", 90 * STEPS_PER_DEGREE, 1)
        pose.apply("DRIVE", STEPS_PER_MM, -1)
        self.assertAlmostEqual(pose.x, 0, places=6)
        self.assertAlmostEqual(pose.y, 1, places=6)
        self.assertAlmostEqual(pose.heading, 90)

    def test_one_degree_of_spin_in_each_direction(self) -> None:
        pose = Pose()
        pose.apply("SPIN", STEPS_PER_DEGREE, 1)
        self.assertAlmostEqual(pose.heading, 1)
        self.assertEqual(pose.x, 0)
        self.assertEqual(pose.y, 0)
        pose.apply("SPIN", STEPS_PER_DEGREE, -1)
        self.assertAlmostEqual(pose.heading, 0)

        pose.apply("SPIN", STEPS_PER_DEGREE, -1)
        self.assertAlmostEqual(pose.heading, 359)

    def test_heading_wraps_past_360_and_through_zero(self) -> None:
        pose = Pose()
        pose.apply("SPIN", 359 * STEPS_PER_DEGREE, 1)
        pose.apply("SPIN", 2 * STEPS_PER_DEGREE, 1)
        self.assertAlmostEqual(pose.heading, 1)

        pose.apply("SPIN", 2 * STEPS_PER_DEGREE, -1)
        self.assertAlmostEqual(pose.heading, 359)

    def test_a_drive_after_a_spin_uses_the_new_heading(self) -> None:
        pose = Pose()
        pose.apply("SPIN", 90 * STEPS_PER_DEGREE, 1)
        pose.apply("DRIVE", 2 * STEPS_PER_MM, -1)
        self.assertAlmostEqual(pose.x, 0, places=6)
        self.assertAlmostEqual(pose.y, 2, places=6)

    def test_stop_makes_a_later_done_a_no_op_until_home_is_confirmed(self) -> None:
        pose = Pose()
        pose.apply("DRIVE", STEPS_PER_MM, -1)
        pose.apply("STOP")
        self.assertFalse(pose.known)
        self.assertAlmostEqual(pose.x, 1)

        pose.apply("DRIVE", 10 * STEPS_PER_MM, -1)
        pose.apply("SPIN", STEPS_PER_DEGREE, 1)
        self.assertFalse(pose.known)
        self.assertAlmostEqual(pose.x, 1)
        self.assertAlmostEqual(pose.y, 0)
        self.assertEqual(pose.heading, 0)

        pose.confirm_home()
        self.assertTrue(pose.known)
        self.assertEqual(pose.x, 0)
        self.assertEqual(pose.y, 0)
        self.assertEqual(pose.heading, 0)

    def test_a_timeout_or_dropped_cable_ignores_a_later_done(self) -> None:
        pose = Pose()
        pose.apply("DRIVE", STEPS_PER_MM, -1)
        pose.mark_unknown()
        pose.apply("DRIVE", STEPS_PER_MM, -1)
        self.assertFalse(pose.known)
        self.assertAlmostEqual(pose.x, 1)

        pose.confirm_home()
        pose.apply("DRIVE", STEPS_PER_MM, -1)
        self.assertTrue(pose.known)
        self.assertAlmostEqual(pose.x, 1)


if __name__ == "__main__":
    unittest.main()
