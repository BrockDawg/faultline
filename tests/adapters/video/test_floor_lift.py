"""The truck's underside is not on the floor; given its height, the chain reads the floor under it.

The camera is the Blender twin's (K, R, t from its truth files). A truck edge 0.12 m above the floor
moves at exactly 1.0 m/s away from the camera. Through the floor plane alone it reads about 3.9%
fast (the base, and the twin's +4.0%); with the site's `truck_m.underside_m` the chain reads it
within 0.5%. A site without that value is unchanged.
"""

import math
import unittest

import numpy as np

from faultline.adapters.video import floor, measure

K = np.array([[1108.5125732421875, 0.0, 640.0], [0.0, 1108.5125732421875, 360.0], [0.0, 0.0, 1.0]])
R = np.array(
    [
        [0.9975179433822632, 0.07041304558515549, 4.068476666674314e-09],
        [0.024754662066698074, -0.35069093108177185, -0.9361640214920044],
        [-0.06591816246509552, 0.9338403940200806, -0.35156354308128357],
    ]
)
T = np.array([-0.49289125204086304, 2.4548356533050537, 2.565314769744873])
P = K @ np.c_[R, T]
FLOOR = [(-0.575, 5.0), (0.575, 5.0), (0.575, 8.0), (-0.575, 8.0)]
SITE = {
    "moving_mps": 0.1,
    "stopped_window_s": 2.0,
    "pedestrian_separation_m": 3.0,
    "dock_guide_max_mps": 0.5,
    "rear_cone_half_angle_deg": 35.0,
    "rear_cone_depth_truck_lengths": 2.0,
    "truck_m": {"length": 3.0, "width": 1.15},
    "structure_strip_m": 0.3,
    "structure_run_frames": 3,
    "consequence_window_s": 0.5,
}


def px(x, y, z):
    v = P @ np.array([x, y, z, 1.0])
    return (float(v[0] / v[2]), float(v[1] / v[2]))


def ctx(h=0.12, speed=1.0):
    frames = list(range(61))
    feet, env, centre = {}, {}, {}
    for f in frames:
        y = 5.0 + speed * f / measure.FPS
        feet[f] = px(0.0, y, h)
        env[f] = np.array([px(x, y, h) for x in (-0.5, -0.25, 0.0, 0.25, 0.5)])
        centre[f] = feet[f]
    return {
        "n_frames": 61,
        "truck_frames": frames,
        "feet": feet,
        "env": env,
        "centre": centre,
        "fork_marks": {},
        "docks": [],
        "people": [],
        "structures": [],
        "floor_points": [{"img": list(px(x, y, 0.0)), "floor": [x, y]} for x, y in FLOOR],
    }


def mid_speed(out):
    sp = out["speed"]
    return float(np.median([sp[f] for f in sorted(sp)[10:-10]]))


class CameraFromPlane(unittest.TestCase):
    def test_recovers_the_twin_camera(self):
        Hm = floor.solve([px(x, y, 0.0) for x, y in FLOOR], FLOOR)
        cam = floor.camera(Hm, 1280, 720)
        self.assertIsNotNone(cam)
        self.assertAlmostEqual(cam["height_m"], 3.2, places=2)
        self.assertAlmostEqual(cam["ground"][0], 0.6, places=2)
        self.assertAlmostEqual(cam["ground"][1], -1.5, places=2)
        self.assertAlmostEqual(cam["focal_px"], 1108.51, delta=1.0)

    def test_lift_moves_a_point_toward_the_camera(self):
        cam = {"ground": np.array([0.0, 0.0]), "height_m": 4.0}
        out = floor.lift(np.array([[0.0, 10.0]]), cam, 0.4)
        self.assertAlmostEqual(float(out[0][1]), 9.0)
        self.assertTrue(
            np.array_equal(floor.lift(np.array([[1.0, 2.0]]), None, 0.4), np.array([[1.0, 2.0]]))
        )

    def test_no_camera_from_inconsistent_marks(self):
        """m1's blind clicks on the twin (guessed far corners) and an affine hand rectangle hold no
        pinhole camera.
        """
        m1 = [[530, 455], [708, 457], [712.5, 306], [583, 305]]
        self.assertIsNone(floor.camera(floor.solve(m1, FLOOR), 1280, 720))
        rect = [[500, 600], [700, 600], [700, 200], [500, 200]]
        self.assertIsNone(floor.camera(floor.solve(rect, FLOOR), 1280, 720))


class UndersideLift(unittest.TestCase):
    def test_no_lift_without_a_camera(self):
        """A site that states the underside height on a plane with no consistent camera reads as the
        base did.
        """
        site = {**SITE, "truck_m": {**SITE["truck_m"], "underside_m": 0.12}}
        c = ctx()
        c["floor_points"] = [
            {"img": [530, 455], "floor": list(FLOOR[0])},
            {"img": [708, 457], "floor": list(FLOOR[1])},
            {"img": [712.5, 306], "floor": list(FLOOR[2])},
            {"img": [583, 305], "floor": list(FLOOR[3])},
        ]
        self.assertEqual(measure.draw(c, site, None)["speed"], measure.draw(c, SITE, None)["speed"])

    def test_speed_reads_the_floor_under_the_underside(self):
        site = {**SITE, "truck_m": {**SITE["truck_m"], "underside_m": 0.12}}
        v = mid_speed(measure.draw(ctx(), site, None))
        self.assertLess(abs(v - 1.0), 0.005, f"read {v:.4f} m/s against 1.0")

    def test_without_the_site_value_nothing_changes(self):
        v = mid_speed(measure.draw(ctx(), SITE, None))
        # the base's bias, unchanged when the site states no underside height: 3.2 / (3.2 - 0.12) =
        # 1.039
        self.assertGreater(v, 1.03)
        self.assertLess(v, 1.05)
        self.assertTrue(math.isfinite(v))


class OperatorReadConstant(unittest.TestCase):
    def test_no_source_reads_the_operator_variable(self):
        """FAULTLINE_OPERATOR_READ was once a verdict switch read from the environment; it is a
        constant now.
        """
        from pathlib import Path

        root = Path(measure.__file__).resolve().parent
        text = "".join(p.read_text(encoding="utf-8") for p in root.glob("*.py"))
        self.assertNotIn("FAULTLINE_OPERATOR_READ", text)
        self.assertEqual(measure.OPERATOR_READ, "both")


if __name__ == "__main__":
    unittest.main()
