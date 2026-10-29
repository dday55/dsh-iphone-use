"""Gesture geometry: the swipe must never start in a system gesture area."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "iphone-use" / "server"))

from actions import contains_rect, default_region, safe_limits, swipe_points

IPHONE_SE = {"width": 375.0, "height": 667.0}
IPHONE_15 = {"width": 393.0, "height": 852.0}


class DefaultRegionTest(unittest.TestCase):
    def test_region_is_centered_and_inside_the_viewport(self):
        region = default_region(IPHONE_SE)
        self.assertAlmostEqual(region["x"] + region["width"] / 2, IPHONE_SE["width"] / 2)
        self.assertGreaterEqual(region["x"], 0)
        self.assertLessEqual(region["x"] + region["width"], IPHONE_SE["width"])


class SwipePointsTest(unittest.TestCase):
    def points(self, viewport, direction, region=None):
        return swipe_points(region or default_region(viewport), viewport, direction)

    def test_up_swipe_moves_the_finger_up(self):
        _, from_y, _, to_y = self.points(IPHONE_SE, "up")
        self.assertLess(to_y, from_y)

    def test_down_swipe_moves_the_finger_down(self):
        _, from_y, _, to_y = self.points(IPHONE_SE, "down")
        self.assertGreater(to_y, from_y)

    def test_left_and_right_move_horizontally(self):
        from_x, _, to_x, _ = self.points(IPHONE_SE, "left")
        self.assertLess(to_x, from_x)
        from_x, _, to_x, _ = self.points(IPHONE_SE, "right")
        self.assertGreater(to_x, from_x)

    def test_no_point_reaches_the_top_or_bottom_edges(self):
        for viewport in (IPHONE_SE, IPHONE_15):
            limits = safe_limits(viewport)
            for direction in ("up", "down", "left", "right"):
                from_x, from_y, to_x, to_y = self.points(viewport, direction)
                for y in (from_y, to_y):
                    self.assertGreaterEqual(y, limits["top"])
                    self.assertLessEqual(y, viewport["height"] - limits["bottom"])
                for x in (from_x, to_x):
                    self.assertGreaterEqual(x, limits["side"])
                    self.assertLessEqual(x, viewport["width"] - limits["side"])

    def test_region_at_the_very_top_is_clamped_into_the_safe_area(self):
        region = {"x": 10.0, "y": 0.0, "width": 300.0, "height": 40.0}
        from_x, from_y, to_x, to_y = self.points(IPHONE_SE, "up", region)
        self.assertGreaterEqual(from_y, 60.0)
        self.assertGreaterEqual(to_y, 60.0)


class ContainsRectTest(unittest.TestCase):
    def test_inside_and_outside(self):
        outer = {"x": 0, "y": 0, "width": 100, "height": 100}
        self.assertTrue(contains_rect({"x": 10, "y": 10, "width": 10, "height": 10}, outer))
        self.assertFalse(contains_rect({"x": 95, "y": 10, "width": 10, "height": 10}, outer))


if __name__ == "__main__":
    unittest.main()
