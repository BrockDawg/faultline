"""The deterministic edge state and its per-frame still-spotter exemption, on a synthetic floor: 1
px = 1 cm, the four floor points a 4 m square. No clip and no network.
"""

import unittest

import numpy as np

from faultline.adapters.video import measure

SITE = {
    "pedestrian_separation_m": 3.0,
    "speed_limit_mps": 2.2,
    "truck_m": {"length": 3.0, "width": 1.15},
    "moving_mps": 0.1,
    "moving_window_s": 1.0,
    "stopped_window_s": 2.0,
    "dock_guide_max_mps": 0.5,
    "rear_cone_half_angle_deg": 35.0,
    "rear_cone_depth_truck_lengths": 2.0,
    "structure_strip_m": 0.3,
    "structure_run_frames": 3,
    "consequence_window_s": 0.5,
    "hivis_rule_share": 0.7,
    "still_spotter_exempt": True,
}
FLOOR = [
    {"img": [100, 100], "floor": [1.0, 1.0]},
    {"img": [500, 100], "floor": [5.0, 1.0]},
    {"img": [500, 500], "floor": [5.0, 5.0]},
    {"img": [100, 500], "floor": [1.0, 5.0]},
]
N = 36


def ctx_for(xs: list[float], y: float = 300.0, people=None, marks=None) -> dict:
    fr = list(range(len(xs)))
    return {
        "n_frames": len(xs),
        "truck_frames": fr,
        "floor_points": FLOOR,
        "docks": [],
        "structures": [],
        "feet": {f: (xs[f], y) for f in fr},
        "centre": {f: (xs[f], y) for f in fr},
        "env": {f: np.array([[xs[f] - 150.0, y], [xs[f], y], [xs[f] + 150.0, y]]) for f in fr},
        "fork_marks": marks or {},
        "people": people or [],
    }


class EdgeState(unittest.TestCase):
    def setUp(self):
        self.saved = measure.EDGE_SPEED, measure.UNKNOWN_BOTH_WAYS

    def tearDown(self):
        measure.EDGE_SPEED, measure.UNKNOWN_BOTH_WAYS = self.saved

    def test_a_parked_truck_reads_stopped_to_the_track_ends(self):
        ctx = ctx_for([300.0] * N)
        measure.EDGE_SPEED = True
        on = measure.draw(ctx, SITE, None)["state"]
        self.assertEqual(set(on.values()), {"stopped"})
        measure.EDGE_SPEED = False
        off = measure.draw(ctx, SITE, None)["state"]
        self.assertEqual(
            off[0], "unknown"
        )  # the centred second has no frames before the track's start
        self.assertEqual(off[N - 1], "unknown")

    def test_an_edge_read_never_makes_a_frame_moving(self):
        ctx = ctx_for([450.0 - 5.0 * f for f in range(N)])  # 0.6 m/s the whole track
        measure.EDGE_SPEED = True
        st = measure.draw(ctx, SITE, None)["state"]
        # moving needs a whole centred second of centred reads either side: frames 12 to 23 of 36
        self.assertEqual(sorted(f for f, v in st.items() if v == "moving"), list(range(12, N - 12)))

    def test_a_still_vested_spotter_on_unread_frames_next_to_a_reverse_is_exempt(self):
        # the truck reverses (travels towards its rear, -x) and its track ends; a still person
        # stands behind it
        xs = [450.0 - 5.0 * f for f in range(N)]
        marks = {
            str(t): {"fork": [xs[12 * t] + 150.0, 300.0], "rear": [xs[12 * t] - 150.0, 300.0]}
            for t in range(3)
        }
        person = {
            "id": "1",
            "feet": {f: (60.0, 300.0) for f in range(N)},
            "on_edge": {f: False for f in range(N)},
            "vest": "vested",
        }
        ctx = ctx_for(xs, people=[person], marks=marks)
        measure.EDGE_SPEED = True
        measure.UNKNOWN_BOTH_WAYS = True
        d = measure.draw(ctx, SITE, None)
        self.assertGreaterEqual(d["reversing_frames"], 12)
        self.assertEqual(d["people"][0]["close_unknown_frames"], 0)
        measure.UNKNOWN_BOTH_WAYS = False
        self.assertGreater(measure.draw(ctx, SITE, None)["people"][0]["close_unknown_frames"], 0)
        # the exemption reads the script's colour read only: a person not read vested is never
        # exempt this way
        measure.UNKNOWN_BOTH_WAYS = True
        person["vest"] = "unknown"
        self.assertGreater(measure.draw(ctx, SITE, None)["people"][0]["close_unknown_frames"], 0)


if __name__ == "__main__":
    unittest.main()
