"""(From): Brock's rulings 2, 3, 4 and 6 of 30 Oct 2026 written into the judge, the three clip 40
gate items relabelled under ruling 1, and ruling 8 left out (it was withdrawn). Ruling 1's own read
is, tested in test_w5_wild02.py. No clip and no network: python -m unittest discover -s tests"""

import hashlib
import json
import unittest
from pathlib import Path

import numpy as np

from faultline.adapters.video import measure

ROOT = Path(__file__).resolve().parents[3]


class Ruling1GateLabels(unittest.TestCase):
    def test_the_three_clip_40_gate_items_are_relabelled_clear(self):
        p = ROOT / "dev" / "gates" / "labels.jsonl"
        if not p.exists():
            self.skipTest("the gate labels are build files, not in this tree")
        labs = [json.loads(s) for s in p.read_text(encoding="utf-8").splitlines() if s.strip()]
        forty = [
            lab
            for lab in labs
            if lab["id"] in ("g1_nosub_00_40", "g1_nosub_01_40", "g2_nosub_00_40")
        ]
        self.assertEqual(len(forty), 3)
        for lab in forty:
            self.assertEqual(lab["clear"], ["hi_vis_in_truck_zone", "pedestrian_separation"])


class Ruling8Withdrawn(unittest.TestCase):
    """Ruling 8 was withdrawn: no lap offset anywhere, and the recorded read scores are the base's
    bytes.
    """

    def test_no_offset_and_the_read_scores_are_the_base(self):
        try:
            from faultline.adapters.video import report_read
        except ImportError:
            self.skipTest("racing report mode is not in this tree")
        self.assertFalse(hasattr(report_read, "completed_laps"))
        self.assertFalse(hasattr(report_read, "COUNTER_LAP_OFFSET"))
        p = ROOT / "record" / "report" / "read.json"
        if not p.exists():
            self.skipTest("the recorded read scores are run output, not in this tree")
        self.assertTrue(hashlib.sha256(p.read_bytes()).hexdigest().startswith("81522bfc"))


PUBLIC = ROOT / "packs" / "forklift-site-rules"


class Rulings2And6PackText(unittest.TestCase):
    """Rulings 2 and 6: the judge's copy of the pack is the public text, the three bracketed values
    leave every rule text for a declared site file the checker lists, and a structure ruling that
    lacks the consequence says the touch is not provable."""

    def test_the_judges_copy_is_the_public_text_byte_for_byte(self):
        if not PUBLIC.is_dir():
            self.skipTest("public pack not on this machine")
        for f in sorted(PUBLIC.iterdir()):
            self.assertEqual(
                (ROOT / "packs" / "forklift-site-rules" / f.name).read_bytes(),
                f.read_bytes(),
                f.name,
            )

    def test_no_rule_text_holds_the_three_values(self):
        import sys

        sys.path.insert(0, str(ROOT / "scripts"))
        import check_spans

        site = json.loads(
            (ROOT / "src/faultline/adapters/video/data/site.json").read_text(encoding="utf-8")
        )
        for md in sorted((ROOT / "packs" / "forklift-site-rules").glob("*.md")):
            t = md.read_text(encoding="utf-8")
            for k in ("moving_mps", "structure_strip_m", "hivis_rule_share"):
                self.assertFalse(check_spans.value_in_text(site[k], [t]), (md.name, k))
        # the copy's texts held them, so the check is not vacuous
        self.assertTrue(check_spans.value_in_text(0.7, ["no band on at least [70]% of the frames"]))
        self.assertTrue(
            check_spans.value_in_text(0.3, ["within [0.30] metres of a marked structure base"])
        )
        self.assertTrue(check_spans.value_in_text(0.1, ["at over [0.1] m/s for a second"]))

    def test_the_three_values_are_declared_and_compiled_with_no_span(self):
        from faultline.adapters.video import compile as fcompile

        declared = fcompile.declared_site_values()
        self.assertEqual(
            sorted(declared),
            [
                ("hi_vis_in_truck_zone", "hivis_rule_share"),
                ("pedestrian_separation", "moving_mps"),
                ("structure_contact", "structure_strip_m"),
            ],
        )
        key = fcompile.route_key()
        for rid, k in declared:
            lines = [
                c["line"]
                for p in key[rid]["predicates"]
                for c in p["all"]
                if isinstance(c.get("line"), dict) and c["line"].get("site") == k
            ]
            self.assertEqual(len(lines), 1, (rid, k))
            self.assertIn("explicit", lines[0])
            self.assertNotIn("span", lines[0])

    def test_the_checker_lists_declared_values_and_counts_the_rest_weak(self):
        import sys

        sys.path.insert(0, str(ROOT / "scripts"))
        import check_spans

        site = json.loads(
            (ROOT / "src/faultline/adapters/video/data/site.json").read_text(encoding="utf-8")
        )
        row = {
            "predicates": [
                {
                    "all": [
                        {
                            "field": "truck.front_in_strip",
                            "is": True,
                            "line": {"site": "structure_strip_m", "explicit": "x"},
                        }
                    ]
                }
            ]
        }
        declared = check_spans.load_declared()
        ok = check_spans.check_row(
            "structure_contact",
            row,
            ["The truck or its load meets racking."],
            site,
            {},
            set(),
            declared,
            set(),
        )
        self.assertEqual(ok["weak"], [])
        self.assertEqual(len(ok["explicit"]), 1)
        still = check_spans.check_row(
            "structure_contact",
            row,
            ["comes within [0.30] metres of a marked structure base"],
            site,
            {},
            set(),
            declared,
            set(),
        )
        self.assertEqual(len(still["site"]), 1)  # the value has not left this text
        undeclared = check_spans.check_row(
            "spotter_when_reversing",
            {
                "predicates": [
                    {
                        "all": [
                            {
                                "field": "person.in_rear_cone",
                                "line": {"site": "rear_cone_half_angle_deg", "explicit": "x"},
                            }
                        ]
                    }
                ]
            },
            ["behind it"],
            site,
            {},
            set(),
            declared,
            set(),
        )
        self.assertEqual(len(undeclared["weak"]), 1)

    def test_a_structure_ruling_without_a_consequence_says_the_touch_is_not_provable(self):
        from faultline.adapters.video import rules

        self.assertEqual(
            rules.NO_CONSEQUENCE, "Touch not provable from this camera; no consequence seen."
        )
        site = json.loads(
            (ROOT / "src/faultline/adapters/video/data/site.json").read_text(encoding="utf-8")
        )
        f = {
            "window.covers_second": True,
            "window.one_shot": True,
            "camera.static": True,
            "truck.present": True,
            "people": [],
            "truck.front_in_strip": {
                "marked": 1,
                "longest_run": 47,
                "run_share": 1.0,
                "first_run_frame": 0,
                "min_front_dist": 0.0,
                "structure": "upright",
            },
            "contact.consequence": {"onsets": [[27, "zone"]], "pairs": [], "pair_share": 0.0},
        }
        rl = rules.judge(
            f, site, [{"id": "structure_contact", "route": "window", "title": "t"}], {}
        )
        self.assertEqual(rl[0]["missing_fact"], "contact.consequence")
        self.assertTrue(
            rl[0]["evidence"].startswith(
                "Touch not provable from this camera; no consequence seen."
            )
        )
        from faultline.adapters.video import dashboard

        self.assertEqual(
            dashboard.FACT_WORDS["contact.consequence"],
            "touch not provable from this camera; no consequence seen",
        )


class Ruling4EdgeCutReverse(unittest.TestCase):
    """Ruling 4: a reverse read only across footpoints the frame's bottom edge cuts is never ruled.
    Synthetic floor as test_merge_edge (1 px = 1 cm): a truck reverses (travels towards its rear,
    -x) for the whole track."""

    def setUp(self):
        import sys

        sys.path.insert(0, str(ROOT / "tests"))
        from test_edge_state import SITE, ctx_for

        self.SITE = SITE
        xs = [450.0 - 5.0 * f for f in range(36)]
        marks = {
            str(t): {"fork": [xs[12 * t] + 150.0, 300.0], "rear": [xs[12 * t] - 150.0, 300.0]}
            for t in range(3)
        }
        self.ctx = ctx_for(xs, marks=marks)
        self.saved = measure.CUT_REVERSE_CHECK, measure.CUT_STOP_CHECK

    def tearDown(self):
        measure.CUT_REVERSE_CHECK, measure.CUT_STOP_CHECK = self.saved

    def test_an_uncut_reverse_stands(self):
        d = measure.draw(self.ctx, self.SITE, None)
        self.assertGreaterEqual(d["reversing_frames"], 12)
        self.assertEqual(d["rev_cut_frames"], [])
        self.assertEqual(d["rev_clean_frames"], d["reversing_frames"])

    def test_a_reverse_read_across_cut_footpoints_is_flagged(self):
        self.ctx["foot_cut"] = {f: True for f in self.ctx["truck_frames"]}
        self.ctx["top"] = {}
        measure.CUT_STOP_CHECK = True
        d = measure.draw(self.ctx, self.SITE, None)
        self.assertGreaterEqual(
            d["reversing_frames"], 12
        )  # the pinned footpoint is not what moves this synthetic truck
        self.assertEqual(len(d["rev_cut_frames"]), d["reversing_frames"])
        self.assertEqual(d["rev_clean_frames"], 0)

    def _spotter(self, clean_share):
        from faultline.adapters.video import rules

        site = json.loads(
            (ROOT / "src/faultline/adapters/video/data/site.json").read_text(encoding="utf-8")
        )
        f = {
            "window.covers_second": True,
            "window.one_shot": True,
            "camera.static": True,
            "truck.present": True,
            "people": [],
            "truck.direction": {
                "known": True,
                "forward_frames": 0,
                "reversing_frames": 13,
                "unknown_moving_frames": 0,
            },
            "truck.moving": {
                "moving_frames": 13,
                "stopped_frames": 0,
                "unknown_frames": 0,
                "truck_frames": 30,
            },
            "truck.reversing": {
                "point": True,
                "share": 1.0,
                "runs": [[13, 25]],
                "band": "yes",
                "cut_frames": list(range(13, 26)),
                "clean_share": clean_share,
            },
            "rear_cone_visible": 1.0,
        }
        return rules.judge(
            f, site, [{"id": "spotter_when_reversing", "route": "window", "title": "t"}], {}
        )[0]

    def test_the_spotter_rule_is_unable_on_a_cut_reverse_and_breaches_on_a_clean_one(self):
        r = self._spotter(0.0)
        self.assertEqual((r["verdict"], r["missing_fact"]), ("unable_to_rule", "truck.reversing"))
        self.assertIn("bottom edge cuts the truck's mask", r["evidence"])
        self.assertEqual(self._spotter(1.0)["verdict"], "breach")
        measure.CUT_REVERSE_CHECK = False
        self.assertEqual(self._spotter(0.0)["verdict"], "breach")


class Ruling3DockZone(unittest.TestCase):
    """Ruling 3: clip 08's dock zone is the trailer mouth plus two metres each side; a guide in it
    is recorded, and the dock-guide exemption never excuses a frame whose truck speed is read from a
    cut footpoint."""

    def test_the_zone_is_drawn_from_the_mouth_not_the_guide(self):
        from faultline.adapters.video import floor

        d = json.loads(
            (ROOT / "src/faultline/adapters/video/data/marks" / "hand_marks.json").read_text(
                encoding="utf-8"
            )
        )
        m = next(v for v in d["clips"].values() if v.get("stem") == "loading_dock_spotter_08")
        self.assertNotEqual(m["dock_zones"], [[[485, 225], [830, 225], [845, 390], [480, 390]]])
        Hm = floor.solve(
            [tuple(p["img"]) for p in m["floor_points"]],
            [tuple(p["floor"]) for p in m["floor_points"]],
        )
        z = floor.project(Hm, m["dock_zones"][0])
        s = next(x for x in m["structures"] if x["what"] == "trailer_rear")
        a, b = floor.project(Hm, [s["a"], s["b"]])
        width = float(np.linalg.norm(b - a))
        sides = sorted(float(np.linalg.norm(z[i] - z[(i + 1) % 4])) for i in range(4))
        self.assertAlmostEqual(sides[-1], width + 4.0, delta=0.05)  # the mouth plus 2 m each end
        self.assertAlmostEqual(sides[0], 4.0, delta=0.05)  # 2 m either side of the mouth line
        mid = ((s["a"][0] + s["b"][0]) / 2, (s["a"][1] + s["b"][1]) / 2)
        self.assertTrue(
            floor.in_poly(mid, m["dock_zones"][0])
        )  # the trailer face stays a dock face

    def test_the_exemption_never_excuses_a_cut_frame(self):
        import sys

        sys.path.insert(0, str(ROOT / "tests"))
        from test_edge_state import SITE, ctx_for

        xs = [
            100.0 + 0.2 * f for f in range(36)
        ]  # the cut footpoint creeps into the zone, under the dock line
        person = {
            "id": "1",
            "feet": {f: (300.0, 400.0) for f in range(36)},
            "on_edge": {f: False for f in range(36)},
            "vest": "vested",
        }
        ctx = ctx_for(xs, people=[person])
        ctx["docks"] = [[[0, 0], [600, 0], [600, 600], [0, 600]]]
        ctx["foot_cut"] = {f: True for f in range(36)}
        ctx["top"] = {
            f: (300.0, 200.0 - 5.0 * f) for f in range(36)
        }  # the top point travels: the truck drives in
        saved = measure.DOCK_CUT_GUARD, measure.CUT_STOP_CHECK
        try:
            measure.CUT_STOP_CHECK = True
            measure.DOCK_CUT_GUARD = True
            p = measure.draw(ctx, SITE, None)["people"][0]
            self.assertEqual(p["dock_frames"], 36)
            self.assertGreater(p["close_unknown_dock"], 0)
            measure.DOCK_CUT_GUARD = False
            self.assertEqual(measure.draw(ctx, SITE, None)["people"][0]["close_unknown_dock"], 0)
        finally:
            measure.DOCK_CUT_GUARD, measure.CUT_STOP_CHECK = saved


if __name__ == "__main__":
    unittest.main()
