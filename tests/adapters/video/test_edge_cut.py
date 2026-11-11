"""A truck footpoint on the frame's bottom edge is the frame cutting the truck, not a floor contact,
so a "stopped" read there needs the mask's top point to agree (CUT_STOP_CHECK). Synthetic floor, as
test_edge_state:
1 px = 1 cm. No clip and no network.
"""

import unittest

import numpy as np
from test_edge_state import SITE, ctx_for

from faultline.adapters.video import measure, record, rules, sam
from faultline.adapters.video.video import H, W

N = 36


def cut_ctx(tops_y: list[float], cut: bool = True) -> dict:
    """A truck parked on the floor plane by its (pinned) footpoint, every frame marked cut, its top
    point at tops_y.
    """
    ctx = ctx_for([300.0] * len(tops_y))
    ctx["foot_cut"] = {f: cut for f in ctx["truck_frames"]}
    ctx["top"] = {f: (300.0, float(y)) for f, y in enumerate(tops_y)}
    return ctx


class TopPoint(unittest.TestCase):
    def test_top_point_is_the_mean_column_of_the_top_rows(self):
        m = np.zeros((H, W), bool)
        m[100:400, 200:260] = True
        self.assertEqual(sam.top_point(m), (229.5, 100.0))

    def test_a_mask_cut_by_the_top_edge_has_no_top_point(self):
        m = np.zeros((H, W), bool)
        m[0:400, 200:260] = True
        self.assertIsNone(sam.top_point(m))

    def test_a_foot_on_the_bottom_rows_is_cut(self):
        m = np.zeros((H, W), bool)
        m[500:H, 200:260] = True
        self.assertTrue(measure.foot_on_edge(sam.foot(m)))
        m[:] = False
        m[500:700, 200:260] = True
        self.assertFalse(measure.foot_on_edge(sam.foot(m)))
        self.assertFalse(measure.foot_on_edge(None))


class CutStop(unittest.TestCase):
    def setUp(self):
        self.saved = measure.CUT_STOP_CHECK

    def tearDown(self):
        measure.CUT_STOP_CHECK = self.saved

    def test_a_pinned_footpoint_with_a_moving_top_is_not_stopped(self):
        # the footpoint never moves (the frame edge), the top point travels 1 m/s up the image: the
        # truck drives in
        ctx = cut_ctx([450.0 - 100.0 * f / 12 for f in range(N)])
        measure.CUT_STOP_CHECK = True
        st = measure.draw(ctx, SITE, None)["state"]
        self.assertNotIn("stopped", st.values())
        self.assertNotIn("moving", st.values())  # the check never makes a frame moving
        measure.CUT_STOP_CHECK = False
        self.assertEqual(
            set(measure.draw(ctx, SITE, None)["state"].values()), {"stopped"}
        )  # the base's artefact

    def test_a_still_top_confirms_stopped(self):
        ctx = cut_ctx([200.0] * N)
        measure.CUT_STOP_CHECK = True
        self.assertEqual(set(measure.draw(ctx, SITE, None)["state"].values()), {"stopped"})

    def test_no_top_point_leaves_a_cut_frame_unread(self):
        ctx = cut_ctx([200.0] * N)
        ctx["top"] = {f: None for f in ctx["truck_frames"]}
        measure.CUT_STOP_CHECK = True
        d = measure.draw(ctx, SITE, None)
        self.assertEqual(set(d["state"].values()), {"unknown"})
        self.assertEqual((d["cut_frames"], d["cut_unread"]), (N, N))

    def test_uncut_frames_are_read_as_before(self):
        ctx = cut_ctx([450.0 - 100.0 * f / 12 for f in range(N)], cut=False)
        measure.CUT_STOP_CHECK = True
        self.assertEqual(set(measure.draw(ctx, SITE, None)["state"].values()), {"stopped"})

    def test_stopped_frames_matches_the_base_window_without_cuts(self):
        fr = list(range(40))
        sp = {f: (0.05 if 10 <= f < 35 else 0.5) for f in fr}
        base = {
            f
            for f in fr
            if any(
                all(sp.get(j) is not None and sp[j] < 0.1 for j in range(s, s + 25))
                for s in range(f - 24, f + 1)
            )
        }
        self.assertEqual(measure.stopped_frames(fr, sp, 0.1, 25), base)
        self.assertEqual(measure.stopped_frames(fr, sp, 0.1, 25, {f: True for f in fr}, {}), set())

    def test_the_check_rides_in_the_rule_constants(self):
        rc = record.rule_constants()
        self.assertIs(rc["CUT_STOP_CHECK"], True)
        self.assertEqual(rc["CUT_EDGE_PX"], 2)


class Evidence(unittest.TestCase):
    def test_separation_names_the_cut(self):
        f = {
            "window.covers_second": True,
            "window.one_shot": True,
            "camera.static": True,
            "truck.present": True,
            "people": [
                {
                    "id": "0",
                    "on_foot": True,
                    "frames": 5,
                    "vested": "vested",
                    "distance_m": {
                        "band": "over",
                        "line": 3.0,
                        "close_unknown_frames": 7,
                        "close_unknown_cut": 7,
                        "close_exempt_frames": 0,
                        "min_moving": float("inf"),
                    },
                }
            ],
        }
        r = rules.judge(
            f,
            SITE,
            [{"id": "pedestrian_separation", "title": "sep", "route": "window"}],
            {"people": []},
        )[0]
        self.assertEqual((r["verdict"], r["missing_fact"]), ("unable_to_rule", "truck.moving"))
        self.assertIn("cut by the frame's bottom edge", r["evidence"])


if __name__ == "__main__":
    unittest.main()
