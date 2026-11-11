"""Checks with no clip and no network:

- the judge's evidence names no model ("Wonder", "SAM"), on a synthetic sheet, in rules.py's string
  literals and on a built shift's pages (skipped when no shift is built);
- the load-mask crops read the same pixels; the memory retry runs only where no model call can be
  made; ffmpeg-to-a-file returns the pipe's bytes.
"""

import io
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_reads import HI, SEP, SITE, SPOT, sheet  # noqa: E402

from faultline.adapters.video import cli, measure, rules, sam, video  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
BUILT = ROOT / "runs" / "shift"
NAMES = re.compile(r"Wonder|SAM")


class NoModelNameInEvidence(unittest.TestCase):
    def test_the_vest_read_evidence_names_no_model(self):
        ctx, point, draws = sheet("unknown")
        f = rules.fields(ctx, point, draws, SITE)
        for agreed, answers in (("yes", ["yes"] * 3), (None, ["yes", "no", "yes"])):
            reads = {"1": {"agreed": agreed, "answers": answers, "src_frames": [0, 24, 48]}}
            for r in rules.judge(f, SITE, [HI, SPOT, SEP], ctx, vest_reads=reads):
                self.assertIsNone(NAMES.search(r["evidence"]), r["evidence"])

    def test_no_string_in_rules_names_a_model(self):
        """Every string token of rules.py that is not a docstring (the judge's evidence is written
        there).
        """
        src = (ROOT / "src" / "faultline" / "adapters" / "video" / "rules.py").read_text(
            encoding="utf-8"
        )
        prev = None
        hits = []
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.STRING, getattr(tokenize, "FSTRING_MIDDLE", -1)):
                docstring = tok.string.startswith(('"""', "'''")) and prev in (
                    tokenize.INDENT,
                    tokenize.NEWLINE,
                    tokenize.DEDENT,
                    None,
                )
                if not docstring and NAMES.search(tok.string):
                    hits.append((tok.start[0], tok.string))
            if tok.type not in (tokenize.NL, tokenize.COMMENT):
                prev = tok.type
        self.assertEqual(hits, [])

    def test_the_built_pages_name_no_model(self):
        pages = [BUILT / d / "dashboard.html" for d in ("shift", "shift-words")]
        if not all(p.exists() for p in pages):
            self.skipTest("the merge's shifts are not built")
        for p in pages:
            html = p.read_text(encoding="utf-8")
            self.assertEqual(NAMES.findall(html), [], p)
            self.assertNotIn("http://", html)
            self.assertNotIn("https://", html)


class LoadCrops(unittest.TestCase):
    """The load-mask crop tests."""

    def _box(self, y: int) -> np.ndarray:
        m = np.zeros((measure.H, measure.W), dtype=bool)
        m[y : y + 30, 100:130] = True
        return m

    def test_crops_read_the_same_drops_as_full_frames(self):
        full = {
            "1": {f: self._box(100 + 12 * f) for f in range(6)},
            "2": {f: self._box(300) for f in range(6)},
        }
        crops = {o: {f: sam.crop(m) for f, m in d.items()} for o, d in full.items()}
        self.assertEqual(measure.load_drops(full, {}, 20), measure.load_drops(crops, {}, 20))
        self.assertTrue(measure.load_drops(crops, {}, 20))
        truck = {f: self._box(100 + 12 * f) for f in range(6)}
        self.assertEqual(measure.load_drops(full, truck, 20), measure.load_drops(crops, truck, 20))
        partial = {f: self._box(140 + 12 * f) for f in range(6)}  # overlaps the lower part only
        self.assertEqual(
            measure.load_drops(full, partial, 20), measure.load_drops(crops, partial, 20)
        )

    def test_mask_crops_matches_masks(self):
        with tempfile.TemporaryDirectory() as d:
            h = sam.sha("reply")
            arrs = {}
            for f, oid, y in ((0, "1", 10), (3, "1", 50), (3, "2", 400)):
                m = self._box(y)
                arrs[f"m_{f}_{oid}"] = np.packbits(m.ravel())
                arrs[f"b_{f}_{oid}"] = np.asarray([100, y, 130, y + 30], dtype=np.int32)
                arrs[f"c_{f}_{oid}"] = np.asarray(0.9)
            np.savez_compressed(Path(d) / f"{h}.npz", **arrs)
            full = sam.masks("reply", Path(d))
            crops = sam.mask_crops("reply", Path(d))
            n = 0
            for f, objs in full.items():
                for oid, e in objs.items():
                    y0, x0, c = crops[oid][f]
                    back = np.zeros_like(e["mask"])
                    back[y0 : y0 + c.shape[0], x0 : x0 + c.shape[1]] = c
                    np.testing.assert_array_equal(back, e["mask"])
                    n += 1
            self.assertEqual(n, 3)


class MemoryRetry(unittest.TestCase):
    """The memory retry, and the limit on it."""

    def setUp(self):
        self.saved = cli.MEMORY_PAUSE_S
        cli.MEMORY_PAUSE_S = 0.0

    def tearDown(self):
        cli.MEMORY_PAUSE_S = self.saved

    @staticmethod
    def flaky(calls, fails):
        def fn():
            calls.append(1)
            if len(calls) <= fails:
                raise MemoryError
            return "line"

        return fn

    def test_a_refused_allocation_is_retried_then_returns(self):
        calls = []
        self.assertEqual(cli._retry_memory(self.flaky(calls, 2), "x"), "line")
        self.assertEqual(len(calls), 3)

    def test_gives_up_after_the_last_retry(self):
        with self.assertRaises(MemoryError):
            cli._retry_memory(self.flaky([], 99), "x")

    def test_an_offline_judge_is_retried(self):
        calls = []
        self.assertEqual(cli._judge_retrying(self.flaky(calls, 1), True, "x"), "line")
        self.assertEqual(len(calls), 2)

    def test_a_judge_that_may_call_a_model_is_never_retried(self):
        calls = []
        with self.assertRaises(MemoryError):
            cli._judge_retrying(self.flaky(calls, 1), False, "x")
        self.assertEqual(len(calls), 1, "a retry with calls allowed could pay twice")


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
class FfmpegToAFile(unittest.TestCase):
    """_run: a command that writes to stdout writes to a temporary file, and the bytes are the
    pipe's.
    """

    def test_same_bytes_as_the_pipe(self):
        raw = [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x36:rate=4",
            "-frames:v",
            "3",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
        jpg = [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x36:rate=4",
            "-frames:v",
            "1",
            "-q:v",
            "5",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "-",
        ]
        for cmd in (raw, jpg):
            piped = subprocess.run(cmd, capture_output=True, check=True).stdout
            self.assertTrue(piped)
            self.assertEqual(video._run(cmd), piped)


if __name__ == "__main__":
    unittest.main()
