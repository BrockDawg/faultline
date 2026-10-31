"""The three-minute walk (demo): the page builds byte-identical twice from the smoke and the shift,
carries no script and no outside URL, holds every panel the script names, and the lint finds nothing
on it, the script or the stills' names. The breach, clear and unable shown are the smoke's own
rulings. No clip and no network needed:
python -m unittest discover -s tests"""

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from faultline.adapters.video import cli, demo

ROOT = Path(__file__).resolve().parents[3]
SMOKE = ROOT / "runs" / "smoke"
SHIFT = ROOT / "runs" / "shift-words"
PACK = ROOT / "demo" / "pack"
SCRIPT = ROOT / "demo" / "SCRIPT.md"
STILLS = ROOT / "demo" / "STILLS"
PAGE = ROOT / "demo" / "faultline-demo.html"


def _lint():
    spec = importlib.util.spec_from_file_location(
        "lint_demo", ROOT / "dev" / "demo" / "lint_demo.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@unittest.skipUnless(
    SMOKE.is_dir() and SHIFT.is_dir(), "the smoke and shift builds are not in this tree"
)
class DemoPage(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_builds_byte_identical_twice_through_the_cli(self):
        a, b = self.td / "a.html", self.td / "b.html"
        for out in (a, b):
            rc = cli.main(
                [
                    "demo",
                    "--smoke",
                    str(SMOKE),
                    "--shift",
                    str(SHIFT),
                    "--rules",
                    str(PACK),
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(rc, 0)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertEqual(
            a.read_bytes(), PAGE.read_bytes(), "the committed page is not this code's build"
        )

    def test_the_shift_rows_beyond_the_pack_are_named(self):
        # The pack panel shows the site's four written rules; the shift table's fifth row is named
        # under it
        page = demo.render(demo.gather(SMOKE, SHIFT, PACK))
        self.assertIn("4 rules, one file each", page)
        self.assertIn(
            "The fifth row, site speed limit, is this site's own extra rule",
            __import__("html").unescape(page),
        )

    def test_no_script_no_outside_url(self):
        page = demo.render(demo.gather(SMOKE, SHIFT, PACK)).lower()
        for bad in ("<script", "http://", "https://", 'src="//', "@import", "url("):
            self.assertNotIn(bad, page)

    def test_the_three_clips_are_the_smokes_rulings(self):
        d = demo.gather(SMOKE, SHIFT, PACK)
        smoke = {
            json.loads(x)["id"]: json.loads(x)
            for x in (SMOKE / "preds.jsonl").read_text(encoding="utf-8").splitlines()
        }
        kinds = [p["kind"] for p in d["picks"]]
        self.assertEqual(kinds, ["breach", "clear", "unable"])
        for p in d["picks"]:
            r = next(x for x in smoke[p["clip"]]["rulings"] if x["rule"] == p["rule"])
            self.assertEqual(
                (r["verdict"], r["evidence"], r["missing_fact"]),
                (p["verdict"], p["evidence"], p["missing_fact"]),
            )
            self.assertTrue(p["frames"], f"{p['clip']} shows no frame")
        self.assertIn(
            "70%", d["picks"][0]["decided"]
        )  # the breach's deciding number, with the site line
        self.assertEqual(d["picks"][2]["missing_fact"], "truck.moving")
        self.assertEqual(d["picks"][2]["lacks"]["words"], "whether the truck was moving")

    def test_replay_proof_is_the_files_own_hash(self):
        import hashlib

        d = demo.gather(SMOKE, SHIFT, PACK)
        h = hashlib.sha256((SMOKE / "preds.jsonl").read_bytes()).hexdigest()
        self.assertEqual(d["replay"]["preds_sha"], h)
        self.assertTrue(d["replay"]["same"])
        self.assertIn(h, demo.render(d))

    def test_a_replay_that_differs_is_said_plainly(self):
        sm = self.td / "smoke"
        sm.mkdir()
        shutil.copy(SMOKE / "preds.jsonl", sm / "preds.jsonl")
        (sm / "replay.jsonl").write_bytes((SMOKE / "replay.jsonl").read_bytes() + b"\n")
        page = demo.render(demo.gather(sm, SHIFT, PACK))
        self.assertIn("NOT identical.", page)
        self.assertNotIn("Byte-identical.", page)

    def test_words_shown_once_and_never_as_the_ruling(self):
        page = demo.render(demo.gather(SMOKE, SHIFT, PACK))
        self.assertEqual(page.count("Words beside the ruling, never the ruling"), 1)
        self.assertNotIn("model_read", page)
        panels = demo.page_panels(page)
        roles = [r for r, _, _ in panels["p06"]["items"]]
        self.assertIn("note", roles)
        self.assertFalse(
            any(r.startswith("badge-") for r in roles), "the words panel shows no verdict"
        )

    def test_a_shift_without_notes_refuses_the_words_panel(self):
        sh = self.td / "shift"
        shutil.copytree(SHIFT, sh, ignore=shutil.ignore_patterns("entries"))
        (sh / "preds.words.jsonl").unlink()
        with self.assertRaises(demo.DemoError):
            demo.gather(SMOKE, sh, PACK)

    def test_a_pick_whose_verdict_moved_is_refused(self):
        sm = self.td / "smoke"
        sm.mkdir()
        lines = []
        for x in (SMOKE / "preds.jsonl").read_text(encoding="utf-8").splitlines():
            p = json.loads(x)
            if p["id"] == demo.PICKS[0][1]:
                for r in p["rulings"]:
                    if r["rule"] == demo.PICKS[0][2]:
                        r["verdict"] = "clear"
            lines.append(json.dumps(p))
        (sm / "preds.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        shutil.copy(SMOKE / "replay.jsonl", sm / "replay.jsonl")
        with self.assertRaises(demo.DemoError):
            demo.gather(sm, SHIFT, PACK)


class DemoScript(unittest.TestCase):
    def test_every_script_line_has_a_still_and_a_panel(self):
        lines = demo.script_lines(SCRIPT.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(lines), 10)
        self.assertEqual([n for n, _ in lines], list(range(1, len(lines) + 1)))
        panels = demo.page_panels(PAGE.read_text(encoding="utf-8"))
        want = sorted(demo.still_name(n, pid, panels[pid]["name"]) for n, pid in lines)
        self.assertEqual(sorted(p.name for p in STILLS.glob("*.png")), want)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not on this machine")
class DemoStill(unittest.TestCase):
    def test_a_still_is_a_1920_by_1080_png(self):
        td = Path(tempfile.mkdtemp())
        try:
            panel = {
                "name": "t",
                "items": [
                    ("kicker", "A kicker", {}),
                    ("head", "A heading", {}),
                    ("badge-breach", "Breach", {}),
                    ("text", "word " * 80, {}),
                ],
            }
            demo.render_still(panel, td / "t.png")
            b = (td / "t.png").read_bytes()
            self.assertEqual(b[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(
                (int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")), (1920, 1080)
            )
        finally:
            shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
