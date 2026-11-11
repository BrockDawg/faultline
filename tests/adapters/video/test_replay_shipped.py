"""The shipped replay set: the record of three clips under demo/record/ rebuilds their ruling lines
to the byte from a fresh clone, with no clip, no ffmpeg and the network off:
python -m unittest discover -s tests"""

import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from faultline.adapters.video import cli, client, perception

ROOT = Path(__file__).resolve().parents[3]
SHIPPED = ROOT / "demo" / "record"
PREDS = SHIPPED / "preds.jsonl"
# the sha256 of preds.jsonl as the judge wrote it; a replay prints the same hash
PREDS_SHA256 = "d991b59e6768a1f6b77bdd0fd0c4c6fb45afbe9d837bdfc9abab0fbfaaff7010"
VERDICTS = {
    "blind_corner_no_vest_07": {"hi_vis_in_truck_zone": "breach"},
    "spotter_ahead_01": {
        "hi_vis_in_truck_zone": "clear",
        "spotter_when_reversing": "clear",
        "pedestrian_separation": "clear",
        "structure_contact": "clear",
    },
    "idle_empty_aisle_40": {"hi_vis_in_truck_zone": "clear", "pedestrian_separation": "clear"},
}


def _no_network(*_a, **_k):
    raise OSError("the network is off for this test")


def _preds() -> bytes:
    return PREDS.read_bytes().replace(b"\r\n", b"\n")


class ShippedReplay(unittest.TestCase):
    def setUp(self):
        # a copy, so anything a replay wrote would show as a changed file set, never touch the tree
        self.td = Path(tempfile.mkdtemp(prefix="fl-shipped-"))
        self.rec = self.td / "record"
        shutil.copytree(SHIPPED, self.rec)

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def _files(self) -> dict[str, bytes]:
        return {
            p.relative_to(self.rec).as_posix(): p.read_bytes()
            for p in self.rec.rglob("*")
            if p.is_file()
        }

    def test_the_shipped_lines_and_their_hash(self):
        self.assertEqual(hashlib.sha256(_preds()).hexdigest(), PREDS_SHA256)
        lines = [json.loads(s) for s in _preds().decode("utf-8").splitlines()]
        self.assertEqual(sorted(x["id"] for x in lines), sorted(VERDICTS))
        for x in lines:
            got = {r["rule"]: r["verdict"] for r in x["rulings"]}
            for rule, verdict in VERDICTS[x["id"]].items():
                self.assertEqual(got[rule], verdict, f"{x['id']} {rule}")

    def test_replay_is_byte_identical_with_the_network_off(self):
        before = self._files()
        out = self.td / "replay.jsonl"
        buf = io.StringIO()
        with (
            mock.patch.object(perception, "RECORD", self.rec),
            mock.patch.object(socket.socket, "connect", _no_network),
            mock.patch.object(socket, "create_connection", _no_network),
            mock.patch.object(client, "POST", _no_network),
            redirect_stdout(buf),
        ):
            rc = cli.main(["replay", str(self.rec / "preds.jsonl"), "--out", str(out)])
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertEqual(out.read_bytes(), _preds())
        self.assertIn(
            f"3 of 3 lines identical to preds.jsonl; sha256 {PREDS_SHA256}", buf.getvalue()
        )
        self.assertEqual(self._files(), before, "a replay wrote into the record")

    def test_the_shipped_set_holds_no_clip_and_no_frame(self):
        video = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".png", ".jpg", ".jpeg"}
        for p in SHIPPED.rglob("*"):
            if not p.is_file():
                continue
            self.assertNotIn(p.suffix.lower(), video, p.name)
            b = p.read_bytes()
            if p.suffix == ".npz":
                # mask arrays only: m (mask bits), b (box), c (confidence) per object and frame
                names = zipfile.ZipFile(io.BytesIO(b)).namelist()
                self.assertTrue(all(n[:2] in ("m_", "b_", "c_") for n in names), p.name)
                continue
            self.assertTrue(b.isascii(), p.name)  # no raw JPEG or PNG bytes
            for embedded in (b"data:image/", b"base64,"):
                self.assertNotIn(embedded, b, p.name)


class ShippedReplayFromTheReadme(unittest.TestCase):
    """The README's command, run as a member would: the real CLI in a fresh process, from the repo
    root, with nothing patched. The record root comes from the preds file's own folder."""

    def test_readme_command_rebuilds_the_shipped_hash(self):
        td = Path(tempfile.mkdtemp(prefix="fl-readme-"))
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        out = td / "replay.jsonl"
        env = {k: v for k, v in os.environ.items() if k != "FAULTLINE_RECORD"}
        # no key, and an endpoint nothing listens on: a replay that tried a call would fail
        env.pop("MODEL_API_KEY", None)
        env.pop("BASETEN_API_KEY", None)
        env["MODEL_API_BASE"] = "http://127.0.0.1:9"
        env["PYTHONIOENCODING"] = "utf-8"
        before = sorted(p.as_posix() for p in SHIPPED.rglob("*"))
        run = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from faultline.adapters.video.cli import main; "
                "sys.exit(main(sys.argv[1:]))",
                "replay",
                "demo/record/preds.jsonl",
                "--out",
                str(out),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(hashlib.sha256(out.read_bytes()).hexdigest(), PREDS_SHA256)
        self.assertIn(f"3 of 3 lines identical to preds.jsonl; sha256 {PREDS_SHA256}", run.stdout)
        self.assertEqual(sorted(p.as_posix() for p in SHIPPED.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
