"""Plumbing checks that need no clip and no network: python -m unittest discover -s tests"""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from faultline.adapters.video import (
    compile as fcompile,
)
from faultline.adapters.video import (
    floor,
    measure,
    racing,
    rules,
    sam,
    steward_cli,
)

ROOT = Path(__file__).resolve().parents[3]


class Compile(unittest.TestCase):
    def test_site_pack_compiles_inside_vocabulary(self):
        packs = fcompile.load_rules_dir(ROOT / "packs" / "forklift-site-rules")
        doc = fcompile.compile_pack(packs[0])
        self.assertEqual(
            [r["id"] for r in doc["rules"]], [g for g in rules.GRADED if g != "site_speed_limit"]
        )  # the public pack holds four rules
        for r in doc["rules"]:
            self.assertEqual(r["route"], "window")
            for p in r["predicates"]:
                for c in p["all"]:
                    self.assertIn(c["field"], rules.VOCAB)

    def test_every_pack_compiles_with_no_invented_field(self):
        n = 0
        for d in sorted((ROOT / "packs").iterdir()):
            if not d.is_dir():
                continue
            for p in fcompile.load_rules_dir(d):
                doc = fcompile.compile_pack(p)
                for r in doc["rules"]:
                    n += 1
                    self.assertIn(r["route"], ("scan", "window", "out"))
                    for pr in r["predicates"]:
                        for c in pr["all"]:
                            self.assertIn(c["field"], rules.VOCAB)
        self.assertGreater(n, 60)

    def test_model_proposal_outside_vocabulary_is_refused(self):
        self.assertIsNone(
            fcompile._valid(
                {
                    "route": "window",
                    "predicates": [{"all": [{"field": "truck.colour", "is": True}]}],
                }
            )
        )
        self.assertIsNotNone(
            fcompile._valid(
                {
                    "route": "window",
                    "predicates": [
                        {"all": [{"field": "truck.reversing", "is": True, "span": "reverses"}]}
                    ],
                }
            )
        )
        # A condition with no span of its own is refused
        self.assertIsNone(
            fcompile._valid(
                {
                    "route": "window",
                    "predicates": [{"all": [{"field": "truck.reversing", "is": True}]}],
                }
            )
        )

    def test_provenance_by_content(self):
        rule = {
            "id": "pedestrian_separation",
            "title": "Keep the distance",
            "text": "A moving truck keeps at least [3] metres from any person on foot. No vested "
            "person behind it.",
        }
        site = {
            "pedestrian_separation_m": 3.0,
            "rear_cone_half_angle_deg": 35.0,
            "still_spotter_exempt": True,
        }

        def row(cond):
            return {"route": "window", "predicates": [{"all": [cond]}]}

        ok = {
            "field": "person.distance_m",
            "band": "under",
            "line": {"site": "pedestrian_separation_m", "span": "keeps at least [3] metres"},
        }
        self.assertEqual(fcompile.problems(row(ok), rule, site), [])
        weak = {
            "field": "person.distance_m",
            "band": "under",
            "line": {"site": "pedestrian_separation_m", "span": "keeps at least"},
        }
        self.assertTrue(any("does not name" in x for x in fcompile.problems(row(weak), rule, site)))
        case = {"field": "person.distance_m", "band": "under", "span": "a moving truck"}
        self.assertTrue(
            any("not in the rule text" in x for x in fcompile.problems(row(case), rule, site))
        )
        child = {
            "field": "person.in_rear_cone",
            "count_vested": 0,
            "span": "No vested person behind it",
        }
        self.assertTrue(any("bare number" in x for x in fcompile.problems(row(child), rule, site)))
        own = {
            "field": "person.in_rear_cone",
            "count_vested": {"value": 0, "span": "No vested person"},
            "span": "No vested person behind it",
        }
        self.assertEqual(fcompile.problems(row(own), rule, site), [])
        sw_bad = {"field": "person.still", "is": True, "site": "still_spotter_exempt"}
        self.assertTrue(
            fcompile.problems(
                {"route": "window", "predicates": [{"all": [own]}], "unless": [sw_bad]}, rule, site
            )
        )
        sw = {
            "field": "person.still",
            "is": True,
            "switch": {"site": "still_spotter_exempt", "from": "site.json"},
        }
        self.assertEqual(
            fcompile.problems(
                {"route": "window", "predicates": [{"all": [own]}], "unless": [sw]}, rule, site
            ),
            [],
        )

    def test_key_span_alternatives_pick_the_copy_compiled(self):
        for packdir in (
            ROOT / "packs" / "forklift-site-rules",
            ROOT / "packs" / "forklift-site-rules",
        ):
            if not packdir.exists():
                continue
            doc = fcompile.compile_pack(fcompile.load_rules_dir(packdir)[0])
            for r in doc["rules"]:
                self.assertEqual(r["route"], "window", (packdir, r["id"], r.get("why")))


class Floor(unittest.TestCase):
    def test_homography_round_trip(self):
        img = [(100, 600), (900, 600), (800, 300), (200, 300)]
        flr = [(0, 0), (4, 0), (4, 6), (0, 6)]
        Hm = floor.solve(img, flr)
        out = floor.project(Hm, img)
        self.assertTrue(np.allclose(out, flr, atol=1e-6))

    def test_mask_geometry(self):
        m = np.zeros((720, 1280), bool)
        m[300:400, 500:600] = True
        self.assertEqual(sam.foot(m), (549.5, 399.0))
        self.assertEqual(sam.box_of(m), (500, 300, 599, 399))
        self.assertEqual(int(sam.dilate(m, 3).sum()), 106 * 106)
        d = sam.chessboard_to(m, 5)
        self.assertEqual(int(d[350, 550]), 0)
        self.assertEqual(int(d[350, 603]), 4)
        self.assertEqual(int(d[0, 0]), 6)

    def test_raster_matches_box(self):
        z = measure.raster([[(10, 10), (20, 10), (20, 20), (10, 20)]])
        self.assertEqual(int(z.sum()), 100)


class Racing(unittest.TestCase):
    def test_bands_and_valid_lines(self):
        self.assertEqual(racing.verdict_for(10), "no_action")
        self.assertEqual(racing.verdict_for(90), "racing_incident")
        self.assertEqual(racing.verdict_for(500), "penalty")
        item = {"id": "x:0:30", "clip": "nowhere/x.mp4", "start_s": 0, "end_s": 30}
        line = racing.steward_line(item, Path(tempfile.gettempdir()), read_frames=True)
        self.assertTrue(steward_cli.valid(line))
        self.assertEqual(line["verdict"], "no_action")
        self.assertIn("not a ruling", line["reasoning"])
        json.dumps(line)


if __name__ == "__main__":
    unittest.main()
