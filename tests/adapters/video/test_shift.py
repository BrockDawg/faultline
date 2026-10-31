"""The demo's lifecycle and shift plumbing; no clip and no network needed: python -m unittest
discover -s tests
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from faultline.adapters.video import dashboard, lifecycle, shift

PREDS = [
    {
        "id": "w01-a",
        "entry": "fl-000000000001",
        "record": "0" * 64,
        "rulings": [
            {
                "rule": "hi_vis_in_truck_zone",
                "verdict": "breach",
                "missing_fact": None,
                "frames": [12, 24, 36, 48],
                "evidence": "x" * 40,
            },
            {
                "rule": "structure_contact",
                "verdict": "unable_to_rule",
                "missing_fact": "truck.front_in_strip",
                "frames": [],
                "evidence": "y" * 40,
            },
        ],
    },
    {
        "id": "w02-b",
        "entry": "fl-000000000002",
        "record": "1" * 64,
        "rulings": [
            {
                "rule": "hi_vis_in_truck_zone",
                "verdict": "clear",
                "missing_fact": None,
                "frames": [],
                "evidence": "z" * 40,
            },
            {
                "rule": "structure_contact",
                "verdict": "clear",
                "missing_fact": None,
                "frames": [],
                "evidence": "z" * 40,
            },
        ],
    },
]
KEY = "w01-a/hi_vis_in_truck_zone"


class Lifecycle(unittest.TestCase):
    def doc(self):
        return lifecycle.initial(PREDS)

    def test_only_breaches_enter_identified(self):
        d = self.doc()
        self.assertEqual(list(d["rulings"]), [KEY])
        self.assertEqual(d["rulings"][KEY]["state"], "identified")

    def test_the_whole_road(self):
        d = self.doc()
        lifecycle.apply(d, KEY, "confirmed", "insurer")
        lifecycle.apply(d, KEY, "disputed", "site", "the person is a visitor with an escort")
        lifecycle.apply(d, KEY, "final", "insurer")
        self.assertEqual(
            [h["to"] for h in d["rulings"][KEY]["history"]], ["confirmed", "disputed", "final"]
        )

    def test_refusals(self):
        bad = [
            ([], "disputed", "site"),  # disputed without a confirm
            ([("denied", "insurer")], "disputed", "site"),  # a denied ruling cannot be disputed
            ([], "confirmed", "site"),  # the site does not confirm
            ([("confirmed", "insurer")], "disputed", "insurer"),  # the insurer does not dispute
            (
                [("confirmed", "insurer"), ("final", "insurer")],
                "identified",
                "insurer",
            ),  # final back to identified
            (
                [("confirmed", "insurer"), ("final", "insurer")],
                "disputed",
                "site",
            ),  # final never moves
            ([], "final", "insurer"),  # identified straight to final
            ([], "identified", "insurer"),
        ]
        for pre, to, by in bad:
            d = self.doc()
            for t, b in pre:
                lifecycle.apply(d, KEY, t, b)
            before = json.dumps(d, sort_keys=True)
            with self.assertRaises(lifecycle.IllegalTransition, msg=f"{pre} -> {to} by {by}"):
                lifecycle.apply(d, KEY, to, by)
            self.assertEqual(
                json.dumps(d, sort_keys=True),
                before,
                "a refused move leaves the lifecycle as it was",
            )

    def test_cli_refuses_and_keeps_file(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "lifecycle.json"
            lifecycle.save(self.doc(), p)
            before = p.read_bytes()

            class A:
                file, ruling, to, by, note, show = str(p), KEY, "disputed", "site", "", False

            self.assertEqual(lifecycle.cmd(A), 1)
            self.assertEqual(p.read_bytes(), before)
            A.to, A.by = "confirmed", "insurer"
            self.assertEqual(lifecycle.cmd(A), 0)
            self.assertEqual(lifecycle.load(p)["rulings"][KEY]["state"], "confirmed")


class Shift(unittest.TestCase):
    def test_idle_names_every_gap(self):
        w = [{"window": "w01-a"}, {"window": "w02-b"}, {"window": "w03-c"}]
        rules = ["hi_vis_in_truck_zone", "structure_contact"]
        self.assertEqual(shift.idle(w[:2], PREDS, rules), [])
        self.assertEqual(shift.idle(w, PREDS, rules), ["w03-c: no ruling line"])
        p2 = json.loads(json.dumps(PREDS))
        p2[0]["rulings"][1]["missing_fact"] = None
        self.assertEqual(
            shift.idle(w[:2], p2, rules),
            ["w01-a: structure_contact is unable to rule but names no fact"],
        )

    def test_windows_follow_the_manifest_clock(self):
        m = {
            "clips": [
                {"clip": "/x/a.mp4", "gap_before_s": 0.0, "start_s": 0.0, "end_s": 5.0},
                {"clip": "/x/b.mp4", "gap_before_s": 2.5, "start_s": 1.0, "end_s": 4.0},
                {"clip": "/x/a.mp4", "gap_before_s": 1.0, "start_s": 0.0, "end_s": 5.0},
            ]
        }
        w = shift.make_windows(m)
        self.assertEqual([x["window"] for x in w], ["w01-a", "w02-b", "w03-a-2"])
        self.assertEqual(
            [(x["shift_start_s"], x["shift_end_s"]) for x in w],
            [(0.0, 5.0), (7.5, 10.5), (11.5, 16.5)],
        )

    def test_ruling_frames_are_capped(self):
        self.assertEqual(shift.ruling_frames(PREDS[0]["rulings"][0]), [12, 36, 48])


JS_CASES = """
var cases = %s;
var bad = cases.filter(function(c){ return (check(c[0], c[1], c[2]) === null) !== c[3]; });
function cp(o){ return JSON.parse(JSON.stringify(o)); }
var K = %s;
var good = cp(D.initial); good.rulings[K].history = \
[{from:'identified',to:'confirmed',by:'insurer'},{from:'confirmed',to:'final',by:'insurer'}]; \
good.rulings[K].state = 'final';
var forged = cp(good); forged.rulings[K].history.push({from:'final',to:'identified',by:'insurer'});\
 forged.rulings[K].state = 'identified';
var skip = cp(D.initial); skip.rulings[K].history = [{from:'identified',to:'disputed',by:'site'}]; \
skip.rulings[K].state = 'disputed';
console.log(JSON.stringify({bad: bad, good: validate(good), forged: validate(forged), skip: \
validate(skip)}));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class DashboardJs(unittest.TestCase):
    """The page's own check() and validate(), run by node against every move lifecycle.py allows or
    refuses.
    """

    def test_page_refuses_what_the_module_refuses(self):
        m = {"name": "t", "note": ""}
        windows = [
            {
                "window": p["id"],
                "clip": f"/x/{p['id']}.mp4",
                "shift_start_s": 0.0,
                "shift_end_s": 5.0,
                "gap_before_s": 0.0,
            }
            for p in PREDS
        ]
        rules = [
            {"id": "hi_vis_in_truck_zone", "title": "t"},
            {"id": "structure_contact", "title": "t"},
        ]
        html = dashboard.render(
            m, windows, PREDS, rules, {}, {"w01-a": {}, "w02-b": {}}, lifecycle.initial(PREDS), None
        )
        self.assertNotIn("https://", html)
        self.assertNotIn("http://", html)
        data = re.search(
            r'<script type="application/json" id="data">(.*?)</script>', html, re.S
        ).group(1)
        js = html[html.index("function check(") : html.index("function persist(")]
        js = js[: js.index("function move(")] + js[js.index("/* a loaded file") :]
        cases = []
        for s in lifecycle.STATES:
            for t in lifecycle.STATES:
                for by in lifecycle.PARTIES:
                    try:
                        lifecycle.check(s, t, by)
                        ok = True
                    except lifecycle.IllegalTransition:
                        ok = False
                    cases.append([s, t, by, ok])
        prog = (
            "var D = "
            + data
            + "; var T = D.transitions;\n"
            + js
            + JS_CASES % (json.dumps(cases), json.dumps(KEY))
        )
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "t.js"
            f.write_text(prog, encoding="utf-8")
            out = json.loads(
                subprocess.run(["node", str(f)], capture_output=True, text=True, check=True).stdout
            )
        self.assertEqual(out["bad"], [])
        self.assertIsNone(out["good"])
        self.assertIn("not an allowed move", out["forged"])
        self.assertIn("not an allowed move", out["skip"])


if __name__ == "__main__":
    unittest.main()
