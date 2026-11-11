"""The span checker (scripts/check_spans.py): provenance by value, the explicit site table and the
racing report.

The compiler is unchanged, so the by-value checker reports its weak spans honestly: these tests pin
that count rather than hide it.
"""

import importlib.util
import json
import unittest
from pathlib import Path

from faultline.adapters.video import compile as fcompile

ROOT = Path(__file__).resolve().parents[3]
SITE = json.loads(
    (ROOT / "src/faultline/adapters/video/data/site.json").read_text(encoding="utf-8")
)
PACKS = ROOT / "packs"


def checker():
    spec = importlib.util.spec_from_file_location(
        "check_spans", ROOT / "scripts" / "check_spans.py"
    )
    cs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cs)
    return cs


SEP = {
    "id": "pedestrian_separation",
    "title": "Keep the site distance",
    "text": "A moving truck keeps at least [3] metres from any person on foot. The site's own "
    "value "
    "replaces the placeholder.",
}
SPEED = {
    "id": "travel_speed",
    "title": "Travel at a safe speed",
    "text": "Drive at a speed that lets the truck stop safely. Keep to the site's authorised speed "
    "limits and traffic rules.",
}


def row(line, field="person.distance_m", band="under"):
    return {
        "route": "window",
        "predicates": [{"all": [{"field": field, "band": band, "line": line}]}],
    }


def text(rule):
    return [checker().norm(rule["title"] + " \n " + rule["text"])]


class ByValue(unittest.TestCase):
    def test_span_holding_the_site_number_passes(self):
        cs = checker()
        bad = cs.check_row(
            "pedestrian_separation",
            row({"site": "pedestrian_separation_m", "span": "keeps at least [3] metres"}),
            text(SEP),
            SITE,
            {},
            set(),
        )
        self.assertFalse(any(bad.values()), bad)

    def test_quantity_word_no_longer_names_a_value(self):
        """The checker passed 'metres' as naming pedestrian_separation_m; by value it does not hold
        3.
        """
        cs = checker()
        bad = cs.check_row(
            "pedestrian_separation",
            row({"site": "pedestrian_separation_m", "span": "metres from any person on foot"}),
            text(SEP),
            SITE,
            {},
            set(),
        )
        self.assertTrue(bad["weak"])

    def test_a_different_site_value_fails_the_same_span(self):
        cs = checker()
        bad = cs.check_row(
            "pedestrian_separation",
            row({"site": "pedestrian_separation_m", "span": "keeps at least [3] metres"}),
            text(SEP),
            {**SITE, "pedestrian_separation_m": 2.5},
            {},
            set(),
        )
        self.assertTrue(bad["weak"])

    def test_number_inside_a_longer_number_does_not_count(self):
        cs = checker()
        self.assertFalse(cs.names_number("at 3.5 metres", 3.0))
        self.assertFalse(cs.names_number("at 13 metres", 3.0))
        self.assertTrue(cs.names_number("at [3] metres", 3.0))
        self.assertTrue(cs.names_number("within half a second", 0.5))
        self.assertTrue(cs.names_number("for a second or more", 1.0))

    def test_table_sentence_passes_only_for_its_rule_and_key(self):
        cs = checker()
        table = cs.load_table()
        r = row(
            {"site": "speed_limit_mps", "span": "Keep to the site's authorised speed limits"},
            "truck.speed_mps",
            "high",
        )
        used = set()
        ok = cs.check_row("travel_speed", r, text(SPEED), SITE, table, used)
        self.assertFalse(ok["weak"] or ok["site"])
        self.assertEqual(used, {("travel_speed", "speed_limit_mps")})
        self.assertTrue(cs.check_row("wet_floor_speed", r, text(SPEED), SITE, table, set())["weak"])

    def test_explicit_form_is_weak(self):
        cs = checker()
        bad = cs.check_row(
            "pedestrian_separation",
            row({"site": "pedestrian_separation_m", "explicit": "x"}),
            text(SEP),
            SITE,
            {},
            set(),
        )
        self.assertTrue(any("explicit form" in x for x in bad["weak"]))

    def test_by_value_span_does_not_use_a_table_entry(self):
        cs = checker()
        table = {
            (
                "pedestrian_separation",
                "pedestrian_separation_m",
            ): "The site's own value replaces the placeholder."
        }
        got = cs.check_row(
            "pedestrian_separation",
            row({"site": "pedestrian_separation_m", "span": "keeps at least [3] metres"}),
            text(SEP),
            SITE,
            table,
            set(),
        )
        self.assertEqual(got["explicit"], [])


class Tables(unittest.TestCase):
    def test_every_table_sentence_is_in_its_rule_and_says_site(self):
        cs = checker()
        texts = cs.load_texts(PACKS) if PACKS.exists() else {}
        if not texts:
            self.skipTest("faultline packs not on this host")
        for (rid, k), sent in cs.load_table().items():
            self.assertIn("site", sent.lower())
            self.assertTrue(any(cs.norm(sent) in t for _, t in texts[rid]), (rid, k))

    def test_the_held_compiler_reports_its_honest_weak_spans(self):
        """The compiler under the by-value checker: 110 parsed, 0 invented, 0 bare, 0 site faults
        and exactly these five weak spans (a sixth, travel_speed's, passes as the explicit site
        table's one entry). A fix that clears one moves this test on purpose; a fix that hides one
        in an unchecked table must not."""
        if not (ROOT / "record" / "compile").exists():
            self.skipTest("the recorded compile replies are run output, not in this tree")
        cs = checker()
        docs = [
            fcompile.compile_pack(p, record_dir=ROOT / "record" / "compile")
            for p in fcompile.load_rules_dir(PACKS)
        ]
        rows = [r for d in docs for r in d["rules"]]
        self.assertEqual(len(rows), 110)
        self.assertFalse(any("measuring" in d for d in docs), "the measuring move is held")
        texts, table, used = cs.load_texts(PACKS), cs.load_table(), set()
        weak = []
        for r in rows:
            bad = cs.check_row(r["id"], r, [t for _, t in texts[r["id"]]], SITE, table, used)
            self.assertFalse(bad["invented"] or bad["bare"] or bad["site"], (r["id"], bad))
            weak += [(r["id"], x.split(" ")[1]) for x in bad["weak"]]
        self.assertEqual(
            sorted(weak),
            [
                ("hi_vis_in_truck_zone", "hivis_rule_share"),
                ("pedestrian_separation", "moving_mps"),
                ("pedestrian_separation", "pedestrian_separation_m"),
                ("spotter_when_reversing", "rear_cone_half_angle_deg"),
                ("structure_contact", "structure_strip_m"),
            ],
        )
        self.assertEqual(used, set(table))


class Racing(unittest.TestCase):
    def test_racing_report_flags_a_contact_rule_routed_out(self):
        cs = checker()
        rows = [
            {"id": "r1", "pack": "pitbot-library-oval", "route": "out"},
            {"id": "r2", "pack": "pitbot-library-oval", "route": "out"},
        ]
        texts = {
            "r1": [("oval", "bump drafting in the turns is not allowed")],
            "r2": [("oval", "qualifying is two laps")],
        }
        self.assertEqual(cs.racing_report(rows, texts), ["oval/r1"])


if __name__ == "__main__":
    unittest.main()
