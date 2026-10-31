"""The shift dashboard, shown: unable rulings name their fact in the pack's words, breaches show the
number that decided them, Wonder's words appear only with the side file, and the rebuild is
byte-identical with and without them.
No clip and no network needed: python -m unittest discover -s tests"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from faultline.adapters.video import cli, dashboard, lifecycle, perception, shift

ROOT = Path(__file__).resolve().parents[3]
PACK = perception.PACKS / "forklift-site-rules"
DEMO = (
    ROOT / "runs" / "shift"
)  # a shift built by `faultline-video shift`: run output, so these tests skip when it is absent

# the evidence forms rules.py writes for a breach, one per rule, as they stand in the full shift's
# rulings
BREACHES = {
    "site_speed_limit": (
        "Peak floor speed 3.66 m/s (interval 3.31 to 4.60), smoothed over one second, "
        "against the site limit "
        "of 2.2 m/s; the whole interval is over the line.",
        "Peak floor speed 3.66 m/s (interval 3.31 to 4.60) · site limit of 2.2 m/s",
    ),
    "pedestrian_separation": (
        "person 0 on foot came within 0.35 m (interval 0.23 to 0.46) of the truck's floor "
        "outline while the "
        "truck was moving; the site line is 3.0 m and the whole interval is under it.",
        "came within 0.35 m (interval 0.23 to 0.46) · site line is 3.0 m",
    ),
    "hi_vis_in_truck_zone": (
        "person 0 on foot reads no hi-vis band on the torso on 87% of 60 read frames "
        "(vested 0%, unreadable "
        "13%); the site line is 70%.",
        "no hi-vis band on the torso on 87% of 60 read frames · site line is 70%",
    ),
    "spotter_when_reversing": (
        "The truck travelled against its fork end for 2.4 s (1 reverse run(s)) with no "
        "vested person in the "
        "rear cone (person 0 in the cone on 0%, unknown); this site requires a spotter for "
        "every reverse.",
        "travelled against its fork end for 2.4 s · with no vested person in the rear cone",
    ),
    "structure_contact": (
        "The truck's floor footprint (the mask's near edge, forks included, carried to the "
        "site's 3.0 by 1.15 m "
        "truck on the hidden side) held within 0.30 m of the rack_face base from frame 20 "
        "to 52 while not "
        "stopped, and a consequence followed at frame 54 (zone-surround change) within 0.5 "
        "s; 100% of the "
        "ensemble reads the run and the consequence together.",
        "held within 0.30 m of the rack_face base from frame 20 to 52 · consequence "
        "followed at frame 54 "
        "(zone-surround change) within 0.5 s · 100% of the ensemble",
    ),
}

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
                "frames": [12, 24],
                "evidence": BREACHES["hi_vis_in_truck_zone"][0],
            },
            {
                "rule": "structure_contact",
                "verdict": "unable_to_rule",
                "missing_fact": "contact.consequence",
                "frames": [4],
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
                "verdict": "unable_to_rule",
                "missing_fact": "camera.static",
                "frames": [],
                "evidence": "z" * 40,
            },
            {
                "rule": "structure_contact",
                "verdict": "unable_to_rule",
                "missing_fact": "camera.static",
                "frames": [],
                "evidence": "z" * 40,
            },
        ],
    },
]
WORDS = [
    {
        "id": "w01-a",
        "entry": "fl-000000000001",
        "words": True,
        "record": "2" * 64,
        "rulings": [
            {
                "rule": "hi_vis_in_truck_zone",
                "verdict": "breach",
                "note": "The frames show a person without a band. Hi-vis note.",
                "model_read": "breach",
            },
            {
                "rule": "structure_contact",
                "verdict": "clear",
                "note": "A note written for a ruling that has since moved.",
            },
        ],
    },
    {
        "id": "w02-b",
        "entry": "fl-000000000002",
        "words": True,
        "record": "3" * 64,
        "rulings": [
            {"rule": "hi_vis_in_truck_zone", "verdict": "unable_to_rule", "note": None},
            {"rule": "structure_contact", "verdict": "unable_to_rule", "note": None},
        ],
    },
]


def _pack():
    return cli.load_pack_rules(PACK)


def _page(words=None):
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
    rframes = {
        "w01-a": {12: "frames/a-12.jpg", 24: "frames/a-24.jpg", 4: "frames/a-4.jpg"},
        "w02-b": {},
    }
    return dashboard.render(
        m, windows, PREDS, _pack(), {}, rframes, lifecycle.initial(PREDS), None, words=words
    )


def _data(html, el="data"):
    return json.loads(
        re.search(rf'<script type="application/json" id="{el}">(.*?)</script>', html, re.S).group(1)
    )


class UnableNamesItsFact(unittest.TestCase):
    def test_pack_words_are_the_packs_own(self):
        rules = _pack()
        texts = (
            " ".join(" ".join(r["text"].split()) for r in rules).replace("[", "").replace("]", "")
        )
        # (Rulings 2 and 6): the judge's pack is the public text again, which names seven of these
        # facts (the merge
        # added anchors for the moving truck and the site distance); the fork end is not in its
        # words, so the
        # page says it in plain words only
        facts = [
            "contact.consequence",
            "truck.front_in_strip",
            "truck.reversing",
            "person.in_rear_cone",
            "person.vested",
            "truck.moving",
            "person.distance_m",
        ]
        if any(
            r["id"] == "site_speed_limit" for r in rules
        ):  # the speed sentence is the site's fifth rule's, when present
            facts.append("truck.speed_mps")
        for fact in facts:
            words = dashboard.pack_words(fact, "structure_contact", rules)
            self.assertTrue(words, fact)
            self.assertIn(words, texts, f"{fact}: the quote must be the pack's own sentence")
        self.assertIsNone(dashboard.pack_words("truck.direction", "structure_contact", rules))
        self.assertEqual(
            dashboard.pack_words("truck.moving", "pedestrian_separation", rules),
            "A moving truck keeps at least 3 metres from any person on foot",
        )
        self.assertEqual(
            dashboard.pack_words("contact.consequence", "structure_contact", rules),
            "A consequence within half a second (the structure shifts, something falls, the "
            "truck stops abruptly) "
            "is the evidence that the touch was real",
        )
        self.assertIsNone(dashboard.pack_words("camera.static", "structure_contact", rules))

    def test_every_unable_ruling_on_the_page_names_its_fact(self):
        d = _data(_page())
        for w in d["windows"]:
            for r in w["rulings"]:
                if r["verdict"] == "unable_to_rule":
                    self.assertEqual(r["lacks"]["field"], r["missing_fact"])
                    self.assertTrue(r["lacks"]["words"])
                    self.assertNotEqual(
                        r["lacks"]["words"], r["missing_fact"], "plain words, not the field name"
                    )
                else:
                    self.assertIsNone(r["lacks"])
        r = d["windows"][0]["rulings"][1]
        self.assertIn("A consequence within half a second", r["lacks"]["pack"])
        self.assertEqual(
            [f["i"] for f in r["frames"]], [4], "the unable ruling keeps its frames beside the fact"
        )

    def test_the_shift_unables_all_name_a_fact_in_words(self):
        p = DEMO / "shift" / "dashboard.html"
        if not p.exists():
            self.skipTest("the demo shift is not built")
        d = _data(p.read_text(encoding="utf-8"))
        n = 0
        for w in d["windows"]:
            for r in w["rulings"]:
                if r["verdict"] == "unable_to_rule":
                    n += 1
                    self.assertEqual(r["lacks"]["field"], r["missing_fact"])
                    self.assertIn(
                        r["missing_fact"],
                        dashboard.FACT_WORDS,
                        f"{w['window']}: no plain words for {r['missing_fact']}",
                    )
        self.assertGreater(n, 0)


class BreachShowsItsNumber(unittest.TestCase):
    def test_every_breach_form_yields_its_measured_numbers(self):
        for rule, (ev, want) in BREACHES.items():
            self.assertEqual(dashboard.decided_by(rule, ev), want, rule)

    def test_the_shift_breaches_all_match_a_form(self):
        p = DEMO / "shift" / "preds.jsonl"
        if not p.exists():
            self.skipTest("the demo shift is not built")
        n = 0
        for s in p.read_text(encoding="utf-8").splitlines():
            for r in json.loads(s)["rulings"]:
                if r["verdict"] == "breach":
                    n += 1
                    got = dashboard.decided_by(r["rule"], r["evidence"])
                    self.assertIn(
                        " · ", got, f"{r['rule']}: no fixed form matched, fell back to {got!r}"
                    )
        self.assertGreater(n, 0)


class WordsOnlyWithTheSideFile(unittest.TestCase):
    def test_no_words_no_words_code(self):
        html = _page()
        for tok in dashboard.WORDS_TOKENS:
            self.assertNotIn(tok, html)
        self.assertNotIn('id="words"', html)
        self.assertNotIn("wordsBox", html)
        self.assertNotIn(".words{", html)

    def test_words_page_is_the_plain_page_plus_the_panel_only(self):
        plain, worded = _page(), _page(WORDS)
        self.assertIn('id="words"', worded)
        wd = _data(worded, "words")
        stripped = worded
        for piece in (
            dashboard.WORDS_CSS,
            dashboard.WORDS_FN,
            dashboard.WORDS_RULING,
            dashboard.WORDS_INIT,
            dashboard.WORDS_DATA.replace("__WD__", dashboard._json_script(wd)),
        ):
            self.assertEqual(stripped.count(piece), 1)
            stripped = stripped.replace(piece, "")
        self.assertEqual(
            stripped,
            plain,
            "with the words pieces taken out, the page is byte-identical to the plain one",
        )
        self.assertEqual(_data(worded), _data(plain), "the rulings' data never changes with words")

    def test_a_note_is_shown_only_beside_the_ruling_it_was_written_for(self):
        wd = dashboard.words_payload(WORDS, PREDS)
        self.assertEqual(set(wd["windows"]), {"w01-a"})
        self.assertEqual(
            set(wd["windows"]["w01-a"]),
            {"hi_vis_in_truck_zone"},
            "the stale structure note is dropped",
        )
        self.assertEqual(wd["windows"]["w01-a"]["hi_vis_in_truck_zone"]["model_read"], "breach")

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_both_pages_script_parses(self):
        for html in (_page(), _page(WORDS)):
            js = re.findall(r"<script>(.*?)</script>", html, re.S)
            self.assertEqual(len(js), 1)
            with tempfile.TemporaryDirectory() as t:
                f = Path(t) / "p.js"
                f.write_text(js[0], encoding="utf-8")
                subprocess.run(["node", "--check", str(f)], check=True, capture_output=True)

    def test_no_outside_url_and_no_model_verdict_as_ruling(self):
        for html in (_page(), _page(WORDS)):
            self.assertNotIn("http://", html)
            self.assertNotIn("https://", html)
            self.assertNotIn("<link", html)
            self.assertNotIn("/x/", html, "no host path of a clip rides in the page")
        worded = _page(WORDS)
        self.assertIn("Words beside the ruling, not the ruling", worded)
        self.assertIn("The ruling is the script's", worded)


class LifecycleAndRebuild(unittest.TestCase):
    def test_lifecycle_moves_never_reach_the_built_files(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            for n in shift.BUILT:
                (d / n).write_text("x\n", encoding="utf-8")
            init = lifecycle.initial(PREDS)
            lifecycle.save(init, d / "lifecycle.json")
            before = shift._files(d)
            doc = lifecycle.load(d / "lifecycle.json")
            lifecycle.apply(doc, "w01-a/hi_vis_in_truck_zone", "confirmed", "insurer")
            lifecycle.save(doc, d / "lifecycle.json")
            self.assertEqual(
                shift._files(d), before, "lifecycle.json is the live file and is never compared"
            )
            self.assertNotIn("lifecycle.json", before)
            self.assertIn("lifecycle.initial.json", before)
            self.assertIn(
                shift.WORDS_FILE, before, "a words file, when present, is compared by the rebuild"
            )

    def test_built_demo_shifts_rebuilt_byte_identical(self):
        """The logged rebuilds (dev/demo): every built file of each replay hashes as its
        source's.
        """
        pairs = [("shift", "shift-replay"), ("shift-words", "shift-words-replay")]
        if not all((DEMO / a).is_dir() and (DEMO / b).is_dir() for a, b in pairs):
            self.skipTest("the demo shifts are not built")
        for a, b in pairs:
            self.assertEqual(
                shift._files(DEMO / a), shift._files(DEMO / b), f"{b} differs from {a}"
            )
        self.assertNotIn(shift.WORDS_FILE, shift._files(DEMO / "shift"))
        self.assertIn(shift.WORDS_FILE, shift._files(DEMO / "shift-words"))
        plain = (DEMO / "shift" / "dashboard.html").read_text(encoding="utf-8")
        worded = (DEMO / "shift-words" / "dashboard.html").read_text(encoding="utf-8")
        self.assertNotIn('id="words"', plain)
        self.assertIn('id="words"', worded)


if __name__ == "__main__":
    unittest.main()
