"""Gate 5b, camera.height: a camera marked low over the floor rules no floor rule.

From near the floor, the truck's lowest outline row is not where it meets the floor and its body
covers the floor beyond it, so a floor position read through the marked plane is wrong (the first
real footage, 1 Nov 2026: two false structure-contact breaches from a camera at the aisle's end).
The camera's height comes from its four floor marks alone, before any model call. Under
gates.LOW_CAMERA_M every rule that reads the truck's floor position is unable, naming
`camera.height`; the hi-vis rule reads the torso and is still ruled. No shipped mark set is low, so
the synthetic site is unchanged.
No clip and no network: python -m unittest discover -s tests"""

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from faultline.adapters.video import cli, floor, gates, perception
from faultline.adapters.video.video import H, W

F_PX = 1000.0
FLOOR = [(-1.5, 3.0), (1.5, 3.0), (1.5, 6.0), (-1.5, 6.0)]
# the first real footage's marks: two image rows across the aisle's two painted lines (the rows lie
# along the image rows, so one floor axis's vanishing point is at infinity)
REAL_AISLE = [
    {"img": [312, 590], "floor": [0, 0]},
    {"img": [960, 590], "floor": [3.0, 0]},
    {"img": [840, 510], "floor": [3.0, 3.3]},
    {"img": [462, 510], "floor": [0, 3.3]},
]
PACK = [
    {"id": "hi_vis_in_truck_zone", "title": "Hi-vis", "route": "window", "kind": "hi_vis"},
    {"id": "spotter_when_reversing", "title": "Spotter", "route": "window", "kind": "spotter"},
    {"id": "pedestrian_separation", "title": "Separation", "route": "window", "kind": "separation"},
    {"id": "structure_contact", "title": "Structure", "route": "window", "kind": "structure"},
    {"id": "site_speed_limit", "title": "Speed", "route": "window", "kind": "speed"},
]


def marks_from(height_m: float, tilt_deg: float, yaw_deg: float = 0.0) -> dict:
    """Four floor points as a pinhole camera height_m above the floor sees them."""
    th, ps = math.radians(tilt_deg), math.radians(yaw_deg)
    fwd = np.array([math.sin(ps) * math.cos(th), math.cos(ps) * math.cos(th), -math.sin(th)])
    right = np.array([math.cos(ps), -math.sin(ps), 0.0])
    down = np.cross(fwd, right)
    R = np.vstack([right, down, fwd])
    t = -R @ np.array([0.0, 0.0, height_m])
    K = np.array([[F_PX, 0.0, W / 2.0], [0.0, F_PX, H / 2.0], [0.0, 0.0, 1.0]])
    P = K @ np.c_[R, t]
    pts = []
    for x, y in FLOOR:
        v = P @ np.array([x, y, 0.0, 1.0])
        assert v[2] > 0
        pts.append({"img": [float(v[0] / v[2]), float(v[1] / v[2])], "floor": [x, y]})
    return {"floor_points": pts}


def height_of(marks: dict) -> float | None:
    pts = marks["floor_points"]
    Hm = floor.solve([p["img"] for p in pts], [p["floor"] for p in pts])
    return floor.camera_height(Hm, W, H)


class CameraHeight(unittest.TestCase):
    def test_a_raised_camera_is_read_and_passes(self):
        m = marks_from(4.0, 30.0, yaw_deg=20.0)
        self.assertAlmostEqual(height_of(m), 4.0, places=3)
        self.assertIsNone(gates.low_camera(m))

    def test_a_raised_camera_with_rows_along_the_image_rows_passes(self):
        m = marks_from(3.0, 25.0)
        self.assertAlmostEqual(height_of(m), 3.0, places=3)
        self.assertIsNone(gates.low_camera(m))

    def test_a_camera_under_the_line_is_low(self):
        for m in (marks_from(1.0, 10.0, yaw_deg=15.0), marks_from(0.9, 2.0)):
            h = gates.low_camera(m)
            self.assertIsNotNone(h)
            self.assertLess(h, gates.LOW_CAMERA_M)
        self.assertAlmostEqual(gates.low_camera(marks_from(0.9, 2.0)), 0.9, places=3)

    def test_the_first_real_footage_marks_are_low(self):
        h = gates.low_camera({"floor_points": REAL_AISLE})
        self.assertIsNotNone(h)
        self.assertAlmostEqual(h, 0.888, places=2)

    def test_no_marks_or_no_consistent_camera_reads_no_height(self):
        self.assertIsNone(gates.low_camera(None))
        self.assertIsNone(gates.low_camera({"floor_points": REAL_AISLE[:3]}))
        # an affine quadrilateral (both floor axes parallel in the image) holds no camera
        flat = [
            {"img": [500, 600], "floor": [0, 0]},
            {"img": [700, 600], "floor": [1, 0]},
            {"img": [700, 300], "floor": [1, 3]},
            {"img": [500, 300], "floor": [0, 3]},
        ]
        self.assertIsNone(gates.low_camera({"floor_points": flat}))

    def test_no_shipped_camera_is_low(self):
        hm = json.loads(
            (perception.ASSETS / "marks" / "hand_marks.json").read_text(encoding="utf-8")
        )["clips"]
        self.assertGreaterEqual(len(hm), 26)
        low = sorted(m.get("stem", k) for k, m in hm.items() if gates.low_camera(m) is not None)
        self.assertEqual(low, [])

    def test_the_line_is_declared_beside_the_gates_and_kept_out_of_the_gate_keys(self):
        self.assertEqual(gates.LOW_CAMERA_M, 1.5)
        self.assertNotIn("LOW_CAMERA_M", gates.KEYS)  # recorded gate facts keep their keys
        self.assertNotIn("hi_vis", gates.FLOOR_KINDS)


class FakePerc:
    """Gate facts for a still, marked window; a model call fails the test unless allowed."""

    calls: list[str] = []
    allow_track = False

    def __init__(self, *a, **k):
        self.notes: list[str] = []

    def gate_facts(self, key, make):
        view = ["1" * 80] * 44 + ["0" + "1" * 79]  # not whole, so no empty-window read is made
        cam = {"static": True, "shift_px": 0.0, "held_frames": 60}
        return {"window_s": 5.0, "frames": 60, "cuts": [], "camera": cam, "view": view}

    def inputs(self):
        return {}

    def truck_masks(self):
        FakePerc.calls.append("truck_masks")
        if not FakePerc.allow_track:
            raise AssertionError("a model call was made past a low camera")
        return {}

    def truck_box(self):
        FakePerc.calls.append("truck_box")
        return None


class JudgeLowCamera(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="fl-camh-"))
        self.clip = self.td / "clip.mp4"
        self.clip.write_bytes(b"not a real clip")
        FakePerc.calls = []
        FakePerc.allow_track = False

    def judge(self, pack, marks):
        with (
            mock.patch.object(perception, "RECORD", self.td / "record"),
            mock.patch.object(perception, "Perception", FakePerc),
            mock.patch.object(cli, "_marks_for", return_value=marks),
        ):
            line, manifest = cli.judge_item(
                {"id": "w", "clip": str(self.clip), "start_s": 0.0, "end_s": 5.0},
                pack,
                {"files": {}},
                {},
                "site",
                allow_calls=False,
            )
        return {r["rule"]: r for r in line["rulings"]}, manifest

    def test_floor_rules_only_are_refused_before_any_model_call(self):
        rl, man = self.judge(PACK[1:], {"floor_points": REAL_AISLE})
        self.assertEqual(FakePerc.calls, [])
        self.assertEqual(man["gates"]["fired"], "camera.height")
        self.assertIn("camera_height", man["inputs"])
        for r in rl.values():
            self.assertEqual((r["verdict"], r["missing_fact"]), ("unable_to_rule", "camera.height"))
            self.assertIn("0.89 m above the floor", r["evidence"])
            self.assertIn("1.50 m line", r["evidence"])

    def test_the_hi_vis_rule_goes_on_and_every_floor_rule_stays_refused(self):
        FakePerc.allow_track = True
        rl, man = self.judge(PACK, {"floor_points": REAL_AISLE})
        self.assertEqual(FakePerc.calls[0], "truck_masks")
        # with no truck track the hi-vis rule keeps gate 4's own refusal; it is never camera.height
        self.assertEqual(rl["hi_vis_in_truck_zone"]["missing_fact"], "truck.moving")
        for rid in [r["id"] for r in PACK[1:]]:
            self.assertEqual(rl[rid]["missing_fact"], "camera.height", rid)
        self.assertNotEqual(man["gates"].get("fired"), "camera.height")

    def test_a_raised_camera_is_not_refused_by_the_gate(self):
        FakePerc.allow_track = True
        rl, man = self.judge(PACK, marks_from(4.0, 30.0, yaw_deg=20.0))
        self.assertNotIn("camera_height", man["inputs"])
        self.assertNotIn("camera_height", man["gates"])
        self.assertEqual({r["missing_fact"] for r in rl.values()}, {"truck.moving"})


if __name__ == "__main__":
    unittest.main()
