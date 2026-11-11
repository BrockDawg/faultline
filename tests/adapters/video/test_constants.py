"""Two plumbing faults a review found, and the switches that must not come from the environment."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

SRC = str(Path(__file__).resolve().parents[3] / "src")


class NoEnvironmentSwitch(unittest.TestCase):
    def test_stray_variables_change_nothing(self):
        """EDGE_SPEED, UNKNOWN_BOTH_WAYS and the vest read are constants read from
        record.rule_constants, never the env.
        """
        code = (
            "import json; from faultline.adapters.video import measure, vest_read, record; "
            "print(json.dumps([measure.EDGE_SPEED, measure.UNKNOWN_BOTH_WAYS, "
            "vest_read.READ_ON, record.rule_constants()], sort_keys=True))"
        )

        def run(extra):
            env = {k: v for k, v in os.environ.items() if not k.startswith("FAULTLINE_")}
            env.update(extra)
            env["PYTHONPATH"] = SRC
            return subprocess.run(
                [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
            ).stdout

        clean = run({})
        stray = run(
            {
                "FAULTLINE_EDGE_SPEED": "0",
                "FAULTLINE_UNKNOWN_BOTH_WAYS": "0",
                "FAULTLINE_VEST_READ": "0",
            }
        )
        self.assertEqual(clean, stray)
        self.assertEqual(json.loads(clean)[:3], [True, True, True])

    def test_no_source_reads_those_variables(self):
        root = Path(SRC) / "faultline"
        text = "".join(p.read_text(encoding="utf-8") for p in root.glob("*.py"))
        for name in ("FAULTLINE_EDGE_SPEED", "FAULTLINE_UNKNOWN_BOTH_WAYS", "FAULTLINE_VEST_READ"):
            self.assertNotIn(name, text)


class VestKey(unittest.TestCase):
    def _perc(self, d, start, end):
        boxes = {f: {"box": [100 + f, 100, 140 + f, 200]} for f in (0, 12, 24, 36)}
        return SimpleNamespace(
            start_s=start,
            end_s=end,
            csha="ab" * 32,
            dir=Path(d),
            used=set(),
            allow_decode=False,
            person_masks=lambda: {"0": boxes},
        )

    def test_a_recorded_read_serves_any_window_over_the_same_frames(self):
        from faultline.adapters.video import vest_read

        with tempfile.TemporaryDirectory() as d:
            p0 = self._perc(d, 0.0, 5.0)
            pick = vest_read.pick_frames({f: b["box"] for f, b in p0.person_masks()["0"].items()})
            crops = [vest_read.crop_of(p0.person_masks()["0"][f]["box"]) for f in pick]
            key_obj, key = vest_read.key_of(p0.csha, "0", pick, crops)
            self.assertNotIn("window", key_obj)
            (Path(d) / "vest").mkdir()
            (Path(d) / "vest" / f"{key}.json").write_text(
                json.dumps({"agreed": "yes", "answers": ["yes"] * 3, "src_frames": []})
            )
            for start, end in ((0.0, 5.0), (0.0, 5.042), (0.0, 6.0)):
                rd = vest_read.read(
                    self._perc(d, start, end), "0", [0, 12, 24, 36], allow_calls=False
                )
                self.assertIsNotNone(rd, (start, end))
                self.assertEqual(rd["agreed"], "yes")

    def test_no_recorded_read_and_no_calls_is_none(self):
        from faultline.adapters.video import vest_read

        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(
                vest_read.read(self._perc(d, 0.0, 5.0), "0", [0, 12, 24, 36], allow_calls=False)
            )

    def test_the_recorded_vest_reads_are_all_on_the_new_key(self):
        from faultline.adapters.video import perception, vest_read

        files = sorted((perception.RECORD / "clips").glob("*/vest/*.json"))
        if not files:
            self.skipTest("the recorded vest reads are run output, not in this tree")
        for p in files:
            rec = json.loads(p.read_text(encoding="utf-8"))
            k = rec["key"]
            self.assertNotIn("window", k)
            self.assertEqual(
                vest_read.key_of(p.parent.parent.name, k["person"], k["frames"], k["crops"])[1],
                p.stem,
            )


if __name__ == "__main__":
    unittest.main()
