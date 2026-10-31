"""The reads, with no clip and no network:

- the Wonder vest read reaches the hi-vis rule only and never makes a breach;
- the words are off by default and go to a side file;
- the span checker (number words, policy, explicit site values) and the judge reading a compiled
  predicate.
"""

import json
import unittest
from pathlib import Path

from faultline.adapters.video import cli, rules
from faultline.adapters.video import compile as fcompile

ROOT = Path(__file__).resolve().parents[3]
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
    "wide_m": 1.0,
}
HI = {"id": "hi_vis_in_truck_zone", "title": "Hi-vis", "route": "window", "kind": "hi_vis"}
SPOT = {"id": "spotter_when_reversing", "title": "Spotter", "route": "window", "kind": "spotter"}
SEP = {
    "id": "pedestrian_separation",
    "title": "Separation",
    "route": "window",
    "kind": "separation",
}


def sheet(vest: str, dist: float = 5.0) -> tuple[dict, dict, list[dict]]:
    """A one-person fact sheet: a moving truck, never reversing, a person on foot `dist` metres
    away.
    """
    person = {
        "id": "1",
        "operator": False,
        "operator_share": 0.0,
        "vest": vest,
        "frames_read": 30,
        "frames": list(range(30)),
        "vest_share": {"vested": 0.0, "unvested": 0.0, "unknown": 1.0}
        if vest == "unknown"
        else {"vested": 1.0, "unvested": 0.0, "unknown": 0.0},
    }
    point = {
        "truck": True,
        "moving_frames": 30,
        "stopped_frames": 0,
        "peak_speed": 1.0,
        "fork_known": True,
        "forward_frames": 30,
        "reversing_frames": 0,
        "direction_unknown_moving": 0,
        "rev_runs": [],
        "structure": None,
        "strip_runs": [],
        "people": [
            {
                "id": "1",
                "frames": 30,
                "min_dist_moving": dist,
                "min_dist_all": dist,
                "frame_min": 4,
                "close_exempt_frames": 0,
                "close_unknown_frames": 0,
                "span_m": 2.0,
                "cone_share": None,
            }
        ],
    }
    ctx = {
        "n_frames": 60,
        "shot_cuts": [],
        "camera": {"static": True},
        "truck_frames": list(range(30)),
        "structures": [],
        "zone_source": "none",
        "onsets": [],
        "dock_faces": [],
        "people": [person],
    }
    return ctx, point, [dict(point) for _ in range(40)]


class VestRead(unittest.TestCase):
    def test_three_yes_clears_hi_vis_only(self):
        ctx, point, draws = sheet("unknown")
        f = rules.fields(ctx, point, draws, SITE)
        base = {r["rule"]: r for r in rules.judge(f, SITE, [HI, SPOT, SEP], ctx)}
        self.assertEqual(base["hi_vis_in_truck_zone"]["missing_fact"], "person.vested")
        reads = {"1": {"agreed": "yes", "answers": ["yes"] * 3, "src_frames": [0, 24, 48]}}
        got = {r["rule"]: r for r in rules.judge(f, SITE, [HI, SPOT, SEP], ctx, vest_reads=reads)}
        self.assertEqual(got["hi_vis_in_truck_zone"]["verdict"], "clear")
        self.assertIn("three of three", got["hi_vis_in_truck_zone"]["evidence"])
        for rid in (
            "spotter_when_reversing",
            "pedestrian_separation",
        ):  # no other rule sees the read
            self.assertEqual(got[rid], base[rid])
        self.assertEqual(ctx["people"][0]["vest"], "unknown")  # nothing shared was written

    def test_a_no_or_a_split_never_makes_a_breach(self):
        ctx, point, draws = sheet("unknown")
        f = rules.fields(ctx, point, draws, SITE)
        for agreed, answers in (("no", ["no"] * 3), (None, ["yes", "no", "yes"])):
            r = rules.judge(
                f,
                SITE,
                [HI],
                ctx,
                vest_reads={"1": {"agreed": agreed, "answers": answers, "src_frames": [0]}},
            )[0]
            self.assertEqual((r["verdict"], r["missing_fact"]), ("unable_to_rule", "person.vested"))

    def test_the_read_never_overrides_the_colour_read(self):
        ctx, point, draws = sheet("unknown")
        ctx["people"][0].update(
            vest="unvested", vest_share={"vested": 0.0, "unvested": 1.0, "unknown": 0.0}
        )
        f = rules.fields(ctx, point, draws, SITE)
        r = rules.judge(
            f,
            SITE,
            [HI],
            ctx,
            vest_reads={"1": {"agreed": "yes", "answers": ["yes"] * 3, "src_frames": [0]}},
        )[0]
        self.assertEqual(r["verdict"], "breach")


class Words(unittest.TestCase):
    def test_words_go_to_a_side_file(self):
        self.assertEqual(cli.words_path(Path("x/preds.jsonl")), Path("x/preds.words.jsonl"))

    def test_words_are_off_by_default(self):
        import argparse

        seen = {}
        orig = cli.cmd_judge
        try:
            cli.cmd_judge = lambda a: seen.setdefault("words", a.words) or 0
            cli.main(["judge", "items.jsonl", "--rules", "r", "--out", "o.jsonl"])
            self.assertFalse(seen["words"])
            seen.clear()
            cli.main(["judge", "items.jsonl", "--rules", "r", "--out", "o.jsonl", "--words"])
            self.assertTrue(seen["words"])
        finally:
            cli.cmd_judge = orig
        _ = argparse


class Checker(unittest.TestCase):
    RULE = {
        "id": "structure_contact",
        "title": "Never touch racking",
        "text": "A truck or its load never touches racking. A consequence within half a second. "
        "Keep a metre clear for a single second.",
    }

    def row(self, cond):
        return {
            "route": "window",
            "predicates": [
                {
                    "all": [
                        {
                            "field": "truck.front_in_strip",
                            "is": True,
                            "span": "never touches racking",
                            **cond,
                        }
                    ]
                }
            ],
        }

    def test_a_is_not_a_number_word(self):
        v = {"line": {"site": "pedestrian_separation_m", "span": "A truck"}}
        self.assertFalse(fcompile._names_number("A truck", 1))
        self.assertTrue(fcompile._names_number("a metre clear", 1))
        self.assertTrue(fcompile._names_number("a single second", 1))
        self.assertTrue(fcompile.problems(self.row(v), self.RULE, SITE))

    def test_policy_on_a_numeric_site_key_fails(self):
        bad = fcompile.problems(
            self.row({"line": {"policy": "structure_strip_m"}}), self.RULE, SITE
        )
        self.assertTrue(any("numeric site key" in x for x in bad))

    def test_explicit_site_values_only_for_the_three(self):
        ok = fcompile.problems(
            self.row(
                {"line": {"site": "structure_strip_m", "explicit": "no rule's words hold 0.3 m"}}
            ),
            self.RULE,
            SITE,
        )
        self.assertEqual(ok, [])
        bad = fcompile.problems(
            self.row({"line": {"site": "pedestrian_separation_m", "explicit": "x"}}),
            self.RULE,
            SITE,
        )
        self.assertTrue(bad)
        weak = fcompile.problems(
            self.row({"line": {"site": "structure_strip_m", "span": "never touches racking"}}),
            self.RULE,
            SITE,
        )
        self.assertTrue(
            any("does not name" in x for x in weak)
        )  # a word span no longer stands in for the strip

    def test_dev_checker_by_value(self):
        """scripts/check_spans.py is the by-value checker (the compiler above is unchanged):
        the explicit form is weak there, a span holding the value passes, a policy on a numeric site
        key fails."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "check_spans", ROOT / "scripts" / "check_spans.py"
        )
        cs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cs)
        texts = [cs.norm(self.RULE["title"] + " \n " + self.RULE["text"])]
        bad = cs.check_row(
            "structure_contact",
            self.row({"line": {"site": "structure_strip_m", "explicit": "why"}}),
            texts,
            SITE,
            {},
            set(),
        )
        self.assertTrue(bad["weak"])
        ok = cs.check_row(
            "structure_contact",
            self.row(
                {
                    "within": {
                        "site": "consequence_window_s",
                        "span": "A consequence within half a second",
                    }
                }
            ),
            texts,
            SITE,
            {},
            set(),
        )
        self.assertFalse(any(ok.values()))
        bad = cs.check_row(
            "structure_contact",
            self.row({"line": {"policy": "structure_strip_m"}}),
            [cs.norm(self.RULE["text"])],
            SITE,
            {},
            set(),
        )
        self.assertTrue(bad["site"])


class JudgeReadsCompiledPredicates(unittest.TestCase):
    def test_compiled_line_moves_the_separation_verdict(self):
        """The judge reads the separation line from the compiled predicate, so a compiler change
        moves a verdict.
        """
        ctx, point, draws = sheet("vested", dist=2.0)
        packdir = ROOT / "packs" / "forklift-site-rules"
        compiled = cli.load_pack_rules(packdir)
        sep = [r for r in compiled if r["id"] == "pedestrian_separation"]
        self.assertEqual(rules.compiled_lines(sep)["person.distance_m"], "pedestrian_separation_m")
        f = rules.fields(ctx, point, draws, SITE, rules.compiled_lines(sep))
        self.assertEqual(
            rules.judge(f, SITE, sep, ctx)[0]["verdict"], "breach"
        )  # 2.0 m under the 3.0 m line
        moved = json.loads(json.dumps(sep))
        for p in moved[0]["predicates"]:
            for c in p["all"]:
                if c.get("field") == "person.distance_m":
                    c["line"] = {"site": "wide_m", "span": "metres"}
        f2 = rules.fields(ctx, point, draws, SITE, rules.compiled_lines(moved))
        self.assertEqual(
            rules.judge(f2, SITE, moved, ctx)[0]["verdict"], "clear"
        )  # 2.0 m over a 1.0 m line


class BlobRace(unittest.TestCase):
    def test_parallel_writers_of_one_blob_all_succeed(self):
        """The --words threads store the same blob at once; on Windows a shared temp name raised
        WinError 32.
        """
        import concurrent.futures as cf
        import tempfile

        from faultline.adapters.video import perception, record

        saved = perception.RECORD
        with tempfile.TemporaryDirectory() as d:
            perception.RECORD = Path(d)
            try:
                with cf.ThreadPoolExecutor(8) as ex:
                    shas = set(ex.map(lambda _: record.put_blob(b"same words"), range(64)))
                self.assertEqual(len(shas), 1)
                self.assertEqual(
                    sorted(x.name for x in (Path(d) / "blobs").iterdir()), [shas.pop()]
                )
            finally:
                perception.RECORD = saved


class Roster(unittest.TestCase):
    def test_roster_finds_the_shipped_blobs(self):
        from faultline.adapters.video import perception, record

        fp = perception.ASSETS / "marks" / "fingerprints.npz"
        self.assertEqual(
            cli._resolve("fingerprints", record.sha_file(fp), {}, None)["status"], "ok"
        )
        self.assertEqual(cli._resolve("fingerprints", "0" * 64, {}, None)["status"], "mismatch")
        ship = perception.ASSETS / "wonder" / "ship.json"
        h = record.put_blob(ship.read_bytes())
        self.assertEqual(cli._resolve("wonder/ship", h, {}, None)["status"], "ok")


if __name__ == "__main__":
    unittest.main()
