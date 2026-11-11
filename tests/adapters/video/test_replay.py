"""The record and the roster, with no clip and no network: python -m unittest discover -s tests"""

import importlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fl-rec-"))
        os.environ["FAULTLINE_RECORD"] = str(self.tmp / "record")
        from faultline.adapters.video import perception, record

        importlib.reload(perception)
        importlib.reload(record)
        self.perception, self.record = perception, record

    def tearDown(self):
        os.environ.pop("FAULTLINE_RECORD", None)
        from faultline.adapters.video import perception, record

        importlib.reload(perception)
        importlib.reload(record)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_line_endings_never_move_a_text_hash(self):
        a, b = self.tmp / "a.md", self.tmp / "b.md"
        a.write_bytes(b"---\nid: x\n---\nbody\n")
        b.write_bytes(b"---\r\nid: x\r\n---\r\nbody\r\n")
        self.assertEqual(self.record.sha_norm(a), self.record.sha_norm(b))
        self.assertEqual(self.record.put_blob(a.read_bytes()), self.record.put_blob(b.read_bytes()))

    def test_binary_files_hash_raw(self):
        a, b = self.tmp / "a.npz", self.tmp / "b.npz"
        a.write_bytes(b"\x00\r\n\x01")
        b.write_bytes(b"\x00\n\x01")
        self.assertNotEqual(self.record.sha_norm(a), self.record.sha_norm(b))

    def test_canon_is_order_free(self):
        self.assertEqual(
            self.record.canon({"b": 1.5, "a": [1, 2]}), self.record.canon({"a": [1, 2], "b": 1.5})
        )
        self.assertEqual(self.record.canon({"x": 0.1 + 0.2}), '{"x":0.30000000000000004}')

    def test_pack_round_trips_through_blobs_with_posix_names(self):
        pack = ROOT / "packs" / "forklift-site-rules"
        rec = self.record.store_pack(pack)
        self.assertTrue(all("\\" not in k for k in rec["files"]))
        dest = self.tmp / "pack"
        self.record.materialise_pack(rec, dest)
        self.assertEqual(self.record.store_pack(dest), rec)

    def test_roster_fails_on_a_hash_with_no_file(self):
        from faultline.adapters.video import cli

        importlib.reload(cli)
        site = self.record.put_blob(b'{"a": 1}\n')
        inputs = {
            "site.json": site,
            "constants": self.record.put_json_blob({"k": 1}),
            "clip": "0" * 64,
        }
        self.record.write_entry(
            "fl-test",
            {"inputs": inputs, "item": {"id": "t", "clip": "/nowhere/c.mp4"}, "host_paths": {}},
        )
        preds = self.tmp / "p.jsonl"
        preds.write_text(
            json.dumps(
                {
                    "id": "t",
                    "entry": "fl-test",
                    "record": self.record.inputs_hash(inputs),
                    "rulings": [],
                }
            )
            + "\n"
        )
        args = SimpleNamespace(preds=str(preds), clips_root=None, external_ok=True)
        self.assertEqual(
            cli.cmd_roster(args), 0
        )  # the clip is external here, every other hash has its file
        args.external_ok = False
        self.assertEqual(cli.cmd_roster(args), 1)  # strict: the clip has no file
        args.external_ok = True
        (self.record.blob_dir() / site).unlink()
        self.assertEqual(cli.cmd_roster(args), 1)  # a blob gone: fails

    def test_replay_never_decodes(self):
        from faultline.adapters.video import client

        p = self.perception.Perception(
            None, 0.0, 5.0, csha="0" * 64, allow_calls=False, allow_decode=False
        )
        with self.assertRaises(client.ApiError):
            p.rgb()


if __name__ == "__main__":
    unittest.main()
