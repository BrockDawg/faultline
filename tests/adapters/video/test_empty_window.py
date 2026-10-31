"""(From, with person_run): ruling 1 (the empty-window read clears a person rule only when three
admitted reads see nobody on every frame, each reply's frame count covers the window, and the person
track's run record, where it covers the window, is cited in the evidence and is never a
precondition), and the words of rulings 2 and 7. Ruling 4 is, tested in test_w5_rulings.py.
No clip and no network: python -m unittest discover -s tests"""

import unittest

from faultline.adapters.video import cli, gates, rules, sam

PACK = [
    {"id": "hi_vis_in_truck_zone", "route": "window"},
    {"id": "spotter_when_reversing", "route": "window"},
    {"id": "pedestrian_separation", "route": "window"},
    {"id": "structure_contact", "route": "window"},
]


class FakePerc:
    def __init__(self, replies: dict):
        self.replies = replies

    def empty_track(self, name, prompt):
        return self.replies.get(prompt, (None, None))


ADM = {"person": ["person", "pedestrian", "worker"], "truck": ["forklift", "vehicle"]}
# one frame of a recorded person reply (frame 23, one object)
BOX = (
    "<23f>0<|box;x1=629;y1=0;x2=644;y2=18;w=1280;h=720;c=0.7264957427978516|><|mask;x=0;y=0;c=0."
    "7264957427978516;data=19,16,~!!!#?!0c]CSDwZ:]L`_WsU_{g#^0F86[jjo={b:obbIRaM%BT?B_PS#ov3TuBg"
    "nZn-AV7s=m-_)@HzQo)9S/Gn4B]%00Z(R^r?Dy)E:S/FVvH&fS9kknZ[4pCeZXe4-q.k:fRaf&K3!u!!!|>\n"
)


class EmptyRead(unittest.TestCase):
    def test_an_empty_reply_holds_no_object(self):
        self.assertEqual(sam.frames_with_objects(""), {})
        self.assertEqual(sam.frames_with_objects(BOX), {23: 1})

    def test_three_empty_reads_over_every_frame_clear_the_person_rules_only(self):
        perc = FakePerc({p: ("", {"video_frames_processed": 60}) for p in ADM["person"]})
        er = cli.empty_read(perc, ADM, 60)
        self.assertTrue(er["person"]["empty"])
        self.assertFalse(er["truck"]["empty"])  # two admitted truck prompts: never read empty
        refused = cli._refuse(PACK, "truck.moving", "No truck track exists in this window.")
        out = {
            r["rule"]: (r["verdict"], r["missing_fact"])
            for r in cli.apply_empty(refused, PACK, er, 60)
        }
        self.assertEqual(out["hi_vis_in_truck_zone"], ("clear", None))
        self.assertEqual(out["pedestrian_separation"], ("clear", None))
        self.assertEqual(out["spotter_when_reversing"], ("unable_to_rule", "truck.moving"))
        self.assertEqual(out["structure_contact"], ("unable_to_rule", "truck.moving"))

    def test_one_person_seen_or_a_short_read_keeps_the_refusal(self):
        seen = FakePerc(
            {
                "person": ("", {"video_frames_processed": 60}),
                "pedestrian": (BOX, {"video_frames_processed": 60}),
                "worker": ("", {"video_frames_processed": 60}),
            }
        )
        self.assertFalse(cli.empty_read(seen, ADM, 60)["person"]["empty"])
        short = FakePerc({p: ("", {"video_frames_processed": 30}) for p in ADM["person"]})
        self.assertFalse(cli.empty_read(short, ADM, 60)["person"]["empty"])
        unread = FakePerc({"person": ("", {"video_frames_processed": 60})})
        self.assertFalse(cli.empty_read(unread, ADM, 60)["person"]["empty"])


class Words(unittest.TestCase):
    def test_the_camera_gate_says_it_reads_fixed_cameras(self):
        self.assertIn(
            "the camera moved; this judge reads fixed site cameras",
            gates.text("camera.static", shift=9.0, held=1.0).lower(),
        )

    def test_the_no_consequence_structure_text(self):
        src = open(rules.__file__, encoding="utf-8").read()
        self.assertIn("touch not provable from this camera; no consequence seen", src.lower())


class PersonRun(unittest.TestCase):
    """run record of the "person" track, cited beside frame counts where it covers the window."""

    RUN = {
        "window": ["0.000", "5.000"],
        "frames_processed": 60,
        "reply_sha256": "x",
        "how": "first ask",
    }

    def test_a_run_covering_the_window_counts(self):
        self.assertTrue(cli.person_ran(self.RUN, 60, 0.0, 5.0))

    def test_no_run_a_short_run_or_a_narrower_window_does_not(self):
        self.assertFalse(cli.person_ran(None, 60, 0.0, 5.0))
        self.assertFalse(cli.person_ran({**self.RUN, "frames_processed": 30}, 60, 0.0, 5.0))
        self.assertFalse(cli.person_ran({**self.RUN, "window": ["1.000", "5.000"]}, 48, 0.0, 5.0))
        self.assertFalse(cli.person_ran({**self.RUN, "frames_processed": 0}, 60, 0.0, 5.0))

    def test_the_clear_names_the_run_record(self):
        perc = FakePerc({p: ("", {"video_frames_processed": 60}) for p in ADM["person"]})
        er = cli.empty_read(perc, ADM, 60)
        er["person"]["person_run"] = self.RUN
        refused = cli._refuse(PACK, "truck.moving", "No truck track exists in this window.")
        out = {r["rule"]: r for r in cli.apply_empty(refused, PACK, er, 60)}
        self.assertIn(
            "run record shows 60 frames processed", out["hi_vis_in_truck_zone"]["evidence"]
        )
        self.assertTrue(40 <= len(out["pedestrian_separation"]["evidence"]) <= 600)


class FreshWindow(unittest.TestCase):
    """Fix: the run record is evidence, never a precondition. The scorer's window of the empty-aisle
    clip (0 to 5.042 s) has three empty person reads over 61 frames and a run record made over 0 to
    5.000 s; both person rules clear."""

    RUN = {
        "window": ["0.000", "5.000"],
        "frames_processed": 60,
        "reply_sha256": "x",
        "how": "first ask",
    }

    def _clear(self, run):
        perc = FakePerc({p: ("", {"video_frames_processed": 61}) for p in ADM["person"]})
        er = cli.empty_read(perc, ADM, 61)
        notes: list[str] = []
        cli.attach_person_run(er, run, 61, 0.0, 5.042, notes)
        self.assertTrue(er["person"]["empty"])
        refused = cli._refuse(PACK, "truck.moving", "No truck track exists in this window.")
        return {r["rule"]: r for r in cli.apply_empty(refused, PACK, er, 61)}, er, notes

    def test_a_run_record_over_a_narrower_window_does_not_block_the_clear(self):
        out, er, notes = self._clear(self.RUN)
        for rule in ("hi_vis_in_truck_zone", "pedestrian_separation"):
            self.assertEqual((out[rule]["verdict"], out[rule]["missing_fact"]), ("clear", None))
            self.assertNotIn(
                "run record", out[rule]["evidence"]
            )  # a record that does not cover the window is not cited
            self.assertTrue(40 <= len(out[rule]["evidence"]) <= 600)
        self.assertEqual(er["person"]["person_run_outside"], self.RUN)
        self.assertEqual(len(notes), 1)
        self.assertEqual(out["spotter_when_reversing"]["verdict"], "unable_to_rule")

    def test_no_run_record_at_all_does_not_block_the_clear(self):
        out, _, _ = self._clear(None)
        self.assertEqual(out["hi_vis_in_truck_zone"]["verdict"], "clear")
        self.assertEqual(out["pedestrian_separation"]["verdict"], "clear")

    def test_a_covering_run_record_is_cited(self):
        out, er, notes = self._clear(
            {**self.RUN, "window": ["0.000", "5.042"], "frames_processed": 61}
        )
        self.assertIn(
            "run record shows 61 frames processed", out["hi_vis_in_truck_zone"]["evidence"]
        )
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
