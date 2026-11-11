"""The operator read is a constant, the grey frames are unchanged by the frame-by-frame form, and
the dropped structure-sway read stays out of the judge."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SRC = str(ROOT / "src")


class OperatorReadConstant(unittest.TestCase):
    def test_stray_variable_changes_nothing(self):
        code = (
            "import json; from faultline.adapters.video import measure, record; "
            "print(json.dumps([measure.OPERATOR_READ, record.constants()], sort_keys=True))"
        )

        def run(extra):
            env = {k: v for k, v in os.environ.items() if not k.startswith("FAULTLINE_")}
            env.update(extra)
            env["PYTHONPATH"] = SRC
            return subprocess.run(
                [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
            ).stdout

        clean, stray = run({}), run({"FAULTLINE_OPERATOR_READ": "seat"})
        self.assertEqual(clean, stray)
        self.assertEqual(json.loads(clean)[0], "both")

    def test_no_source_reads_it(self):
        text = "".join(
            p.read_text(encoding="utf-8") for p in (Path(SRC) / "faultline").glob("*.py")
        )
        self.assertNotIn("FAULTLINE_OPERATOR_READ", text)


class GreyFrameByFrame(unittest.TestCase):
    def test_same_bytes_as_the_whole_array_form(self):
        from faultline.adapters.video import perception

        rng = np.random.default_rng(4)
        src = rng.integers(0, 256, (5, 18, 32, 3), dtype=np.uint8)
        p = perception.Perception(
            None, 0.0, 1.0, csha="0" * 64, allow_calls=False, allow_decode=False
        )
        p._rgb = src
        rgb = src.astype(np.uint16)
        want = ((rgb[..., 0] * 299 + rgb[..., 1] * 587 + rgb[..., 2] * 114) // 1000).astype(
            np.uint8
        )
        self.assertTrue(np.array_equal(p.grey(), want))


class SwayDroppedFromJudge(unittest.TestCase):
    def test_no_sway_constant_in_the_judge_or_its_record(self):
        from faultline.adapters.video import measure, record

        self.assertFalse([k for k in vars(measure) if k.startswith("SWAY")])
        self.assertNotIn("sway", json.dumps(record.rule_constants()).lower())


if __name__ == "__main__":
    unittest.main()
