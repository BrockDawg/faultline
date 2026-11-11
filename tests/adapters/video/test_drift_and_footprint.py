"""Camera drift, footprint distance, the far-mark guard. No clip and no network."""

import unittest

import numpy as np

from faultline.adapters.video import floor, measure
from faultline.adapters.video.video import FPS


class CameraDrift(unittest.TestCase):
    def _clip(self, drift_from: int | None, px: int):
        rng = np.random.default_rng(1)
        big = (rng.random((1000, 1320)) * 255).astype(np.uint8)
        frames = []
        for i in range(5 * FPS):
            dy = px if drift_from is not None and i >= drift_from else 0
            frames.append(big[150 - dy : 870 - dy, 20:1300])
        return np.stack(frames)

    def test_still_camera_is_static(self):
        self.assertIs(measure.camera_static(self._clip(None, 0))["static"], True)

    def test_small_drift_is_compensated_with_its_sign(self):
        cam = measure.camera_static(self._clip(36, 16))
        self.assertEqual(cam["static"], "compensated")
        self.assertEqual(cam["held_frames"], 36)
        # content moved down 16 px from frame 36: a point there is moved back up by 16
        self.assertAlmostEqual(cam["offsets"][40][1], 16.0, delta=1.0)
        self.assertAlmostEqual(cam["offsets"][10][1], 0.0, delta=0.5)

    def test_large_late_move_keeps_the_held_span(self):
        cam = measure.camera_static(self._clip(36, 120))
        self.assertIn(cam["static"], ("held", "compensated"))
        self.assertEqual(cam["held_frames"], 36)


class Footprint(unittest.TestCase):
    def test_seg_dist_many_matches_the_single_form(self):
        pts = np.array([[0.0, 1.0], [2.0, 0.5], [-1.0, -1.0]])
        a, b = np.array([0.0, 0.0]), np.array([1.0, 0.0])
        self.assertAlmostEqual(
            floor.seg_dist_many(pts, a, b), min(floor.seg_dist(p, a, b) for p in pts)
        )
        self.assertEqual(floor.seg_dist_many(np.zeros((0, 2)), a, b), float("inf"))


if __name__ == "__main__":
    unittest.main()
