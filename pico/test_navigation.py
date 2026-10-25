"""Pose and move planning. Runs on the laptop: python -m unittest discover -s pico"""

import math
import unittest

from navigation import Geometry, Pose, facing, toward, wrap

# 100 steps per millimeter keeps the numbers easy to read.
GEOMETRY = Geometry(wheel_diameter_mm=4096 / (100 * math.pi), steps_per_rev=4096, wheel_base_mm=100)
ALIGN = math.radians(15)
MAX_SPIN = math.radians(30)
MAX_DRIVE = 40


class PoseTests(unittest.TestCase):
    def test_equal_steps_drive_straight_along_the_heading(self) -> None:
        pose = Pose(heading=math.pi / 2)
        pose.advance(1000, 1000, GEOMETRY)
        self.assertAlmostEqual(pose.x, 0)
        self.assertAlmostEqual(pose.y, 10)
        self.assertAlmostEqual(pose.heading, math.pi / 2)

    def test_opposite_steps_spin_in_place(self) -> None:
        pose = Pose()
        pose.advance(*GEOMETRY.spin_steps(math.pi / 2), GEOMETRY)
        self.assertAlmostEqual(pose.x, 0)
        self.assertAlmostEqual(pose.y, 0)
        self.assertAlmostEqual(pose.heading, math.pi / 2, places=3)

    def test_heading_wraps_past_a_half_turn(self) -> None:
        self.assertAlmostEqual(wrap(math.radians(190)), math.radians(-170))


class PlanTests(unittest.TestCase):
    def test_a_target_ahead_is_a_capped_forward_drive(self) -> None:
        self.assertEqual(toward(Pose(), 250, 0, GEOMETRY, ALIGN, MAX_SPIN, MAX_DRIVE), (4000, 4000))

    def test_a_target_to_the_side_is_a_capped_spin_toward_it(self) -> None:
        left, right = toward(Pose(), 0, 250, GEOMETRY, ALIGN, MAX_SPIN, MAX_DRIVE)
        self.assertLess(left, 0)
        self.assertGreater(right, 0)
        self.assertEqual((left, right), GEOMETRY.spin_steps(MAX_SPIN))

    def test_a_target_behind_is_reached_in_reverse(self) -> None:
        self.assertEqual(toward(Pose(), -250, 0, GEOMETRY, ALIGN, MAX_SPIN, MAX_DRIVE), (-4000, -4000))

    def test_chunks_reach_a_mark_from_the_center(self) -> None:
        pose = Pose()
        target = (250 * math.cos(math.radians(135)), 250 * math.sin(math.radians(135)))
        for _ in range(100):
            if pose.distance_to(*target) <= 75:
                break
            pose.advance(*toward(pose, *target, GEOMETRY, ALIGN, MAX_SPIN, MAX_DRIVE), GEOMETRY)
        self.assertLessEqual(pose.distance_to(*target), 75)

    def test_facing_stops_inside_the_tolerance(self) -> None:
        self.assertIsNone(facing(Pose(heading=math.radians(3)), 0, GEOMETRY, math.radians(5), MAX_SPIN))
        left, right = facing(Pose(heading=math.radians(20)), 0, GEOMETRY, math.radians(5), MAX_SPIN)
        self.assertGreater(left, 0)
        self.assertLess(right, 0)


if __name__ == "__main__":
    unittest.main()
