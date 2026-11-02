"""The live page's worker (serve.py) and its one-job replay process (replay_one.py).

The worker tests drive the real FastAPI app through its own lifespan, with a stub command in place
of the replay, so they run in seconds on any OS. The replay tests run the real replay_one in a
fresh process on demo/record/, and the contract-drift test holds it to `faultline-video replay`.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from faultline.adapters.video import serve

ROOT = Path(__file__).resolve().parents[3]
SHIPPED = ROOT / "demo" / "record"
PREDS_SHA256 = "d991b59e6768a1f6b77bdd0fd0c4c6fb45afbe9d837bdfc9abab0fbfaaff7010"
DEAD = "http://127.0.0.1:9"

# A stand-in for both replay modules: it speaks the same JSON lines; the clip id picks what it does.
STUB = textwrap.dedent(
    """
    import json, os, sys, time
    def emit(ev, **f):
        print(json.dumps({"event": ev, **f}), flush=True)
    a = sys.argv[1:]
    if "--wait" in a:
        emit("ready")
        job = json.loads(sys.stdin.readline())
        key = job.get("entry") or "shipped"
    elif "--entry" in a:
        key = a[a.index("--entry") + 1]
    elif "--protest" in a:
        key = "protest-" + a[a.index("--protest") + 1]
    elif "--limits" in a:
        key = "limits"
    else:
        key = "shipped"
    emit("stage", name="start")
    if key.startswith("slow"):
        time.sleep(1.2)
    if key.startswith("hang"):
        time.sleep(60)
    if key.startswith("crash"):
        raise RuntimeError("C:/secret/host/path went wrong")
    emit("stage", name="record")
    emit("stage", name="rebuild")
    if key == "limits":
        emit("line", id="Race 1", match=True, record="r1")
    emit("stage", name="seal")
    emit("result", id=key, record_shipped="abc", record_rebuilt="abc", match=True,
         rulings=[], seconds=0.0, set_sha256="abc", pid=os.getpid(), cwd=os.getcwd(),
         warm="--wait" in a)
    """
)


def parse_sse(text: str) -> tuple[list[tuple[str, dict]], int]:
    events, beats = [], 0
    for block in text.replace("\r\n", "\n").split("\n\n"):
        if block.startswith(": heartbeat"):
            beats += 1
            continue
        name = data = None
        for ln in block.splitlines():
            if ln.startswith("event: "):
                name = ln[len("event: ") :]
            elif ln.startswith("data: "):
                data = json.loads(ln[len("data: ") :])
        if name:
            events.append((name, data))
    return events, beats


def _rmtree(p: Path) -> None:
    def onerror(fn, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        fn(path)

    shutil.rmtree(p, onerror=onerror)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="fl-serve-"))
        self.addCleanup(_rmtree, self.td)
        self.stub = self.td / "stub.py"
        self.stub.write_text(STUB, encoding="utf-8")
        for r in serve.ROOT_NAMES:
            (self.td / "roots" / r).mkdir(parents=True)
        (self.td / "racing").mkdir()
        (self.td / "replays").mkdir()
        self.bundle = self.td / "bundle"
        self.bundle.mkdir()
        clips = [
            {"id": c, "root": "shipped", "live": True}
            for c in ("ok_clip", "slow_clip", "slow_two", "hang_clip", "crash_clip")
        ]
        clips.append({"id": "dead_clip", "root": "shipped", "live": False})
        clips.append({"id": "escape", "root": "../../etc", "live": True})
        (self.bundle / "index.json").write_text(json.dumps({"clips": clips}), encoding="utf-8")
        (self.bundle / "racing.json").write_text(
            json.dumps({"protests": [{"id": "1"}, {"id": "slow1"}], "limits_mode": "checked"}),
            encoding="utf-8",
        )

    def app(self, **kw) -> tuple[TestClient, serve.Worker]:
        cmd = [sys.executable, str(self.stub)]
        cfg = serve.Config(
            roots=self.td / "roots",
            bundle=self.bundle,
            racing=self.td / "racing",
            replays=self.td / "replays",
            video_cmd=cmd,
            racing_cmd=cmd,
            commit="feedbeef",
            **kw,
        )
        app = serve.create_app(cfg)
        return TestClient(app), app.state.worker

    @staticmethod
    def until(pred, limit=20.0):
        t = time.monotonic()
        while time.monotonic() - t < limit:
            if pred():
                return
            time.sleep(0.05)
        raise AssertionError("condition not reached")

    def post(self, c, path, body=None, ip="1.1.1.1"):
        return c.post(path, json=body, headers={"X-Real-IP": ip})

    def stream(self, c, job):
        r = c.get(f"/api/jobs/{job}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["cache-control"], "no-cache")
        self.assertEqual(r.headers["x-accel-buffering"], "no")
        self.assertTrue(r.headers["content-type"].startswith("text/event-stream"))
        return parse_sse(r.text)

    def test_a_clip_runs_its_stages_in_order_and_ends_in_a_result(self):
        c, _ = self.app(warm=False)
        with c:
            r = self.post(c, "/api/rule", {"id": "ok_clip"})
            self.assertEqual(r.status_code, 202)
            self.assertEqual(set(r.json()), {"job", "position"})
            ev, _ = self.stream(c, r.json()["job"])
        names = [n for n, _ in ev if n != "queued"]
        stages = [d["name"] for n, d in ev if n == "stage"]
        self.assertEqual(stages, ["start", "record", "rebuild", "seal"])
        self.assertEqual(names[-1], "result")
        res = ev[-1][1]
        self.assertTrue(res["match"])
        self.assertIsInstance(res["seconds"], float)  # the worker's own wall clock

    def test_unknown_dead_and_path_escaping_ids_are_404(self):
        c, _ = self.app(warm=False)
        with c:
            for body in ({"id": "nope"}, {"id": "dead_clip"}, {"id": "escape"}, {"id": "../x"}):
                self.assertEqual(self.post(c, "/api/rule", body).status_code, 404, body)
            self.assertEqual(c.post("/api/rule", content=b"not json").status_code, 404)
            self.assertEqual(c.get("/api/jobs/no-such-job").status_code, 404)
            self.assertEqual(self.post(c, "/api/racing/protest", {"id": "9"}).status_code, 404)

    def test_one_job_per_visitor(self):
        c, _ = self.app(warm=False)
        with c:
            first = self.post(c, "/api/rule", {"id": "slow_clip"}, ip="9.9.9.9")
            self.assertEqual(first.status_code, 202)
            self.assertEqual(
                self.post(c, "/api/rule", {"id": "ok_clip"}, ip="9.9.9.9").status_code, 429
            )
            self.assertEqual(
                self.post(c, "/api/rule", {"id": "ok_clip"}, ip="8.8.8.8").status_code, 202
            )
            self.stream(c, first.json()["job"])
            # once it is done the same visitor may run again
            self.assertEqual(
                self.post(c, "/api/rule", {"id": "ok_clip"}, ip="9.9.9.9").status_code, 202
            )

    def test_a_full_queue_is_429_and_queued_jobs_see_their_position(self):
        c, w = self.app(warm=False, slots=1, queue_max=1)
        with c:
            a = self.post(c, "/api/rule", {"id": "slow_clip"}, ip="1.0.0.1").json()["job"]
            self.until(lambda: w.jobs[a].status == "running")
            b = self.post(c, "/api/rule", {"id": "slow_two"}, ip="1.0.0.2")
            self.assertEqual(b.json()["position"], 1)
            full = self.post(c, "/api/rule", {"id": "ok_clip"}, ip="1.0.0.3")
            self.assertEqual(full.status_code, 429)
            self.assertNotIn("Traceback", full.text)
            ev, _ = self.stream(c, b.json()["job"])
            self.assertEqual(ev[0], ("queued", {"event": "queued", "position": 1}))
            self.assertEqual(ev[-1][0], "result")
            self.until(lambda: c.get("/api/health").json()["running"] == 0)
            h = c.get("/api/health").json()
            self.assertEqual(h, {"ok": True, "queue": 0, "running": 0, "commit": "feedbeef"})

    def test_a_killed_subprocess_is_an_error_event(self):
        c, w = self.app(warm=False)
        with c:
            j = self.post(c, "/api/rule", {"id": "hang_clip"}).json()["job"]
            self.until(lambda: j in w.procs)
            w.procs[j].kill()
            ev, _ = self.stream(c, j)
        self.assertEqual(ev[-1][0], "error")
        self.assertNotIn("result", [n for n, _ in ev])

    def test_a_job_past_its_time_limit_is_stopped(self):
        c, _ = self.app(warm=False, clip_timeout=1.0)
        with c:
            j = self.post(c, "/api/rule", {"id": "hang_clip"}).json()["job"]
            ev, _ = self.stream(c, j)
        self.assertEqual(ev[-1][0], "error")
        self.assertIn("time limit", ev[-1][1]["message"])

    def test_a_crash_reaches_the_page_as_plain_words_only(self):
        c, _ = self.app(warm=False)
        with c:
            j = self.post(c, "/api/rule", {"id": "crash_clip"}).json()["job"]
            r = c.get(f"/api/jobs/{j}")
        ev, _ = parse_sse(r.text)
        self.assertEqual(ev[-1][0], "error")
        for leak in ("Traceback", "RuntimeError", "secret", "C:/"):
            self.assertNotIn(leak, r.text)

    def test_heartbeat_on_a_slow_job(self):
        c, _ = self.app(warm=False, heartbeat=0.2)
        with c:
            j = self.post(c, "/api/rule", {"id": "slow_clip"}).json()["job"]
            ev, beats = self.stream(c, j)
        self.assertGreaterEqual(beats, 2)
        self.assertEqual(ev[-1][0], "result")

    def test_the_warm_spare_is_used_and_replaced(self):
        c, w = self.app(warm=True)
        with c:
            self.until(lambda: w.spare is not None)
            first = w.spare
            j = self.post(c, "/api/rule", {"id": "ok_clip"}).json()["job"]
            ev, _ = self.stream(c, j)
            self.assertTrue(ev[-1][1]["warm"])  # it ran in a --wait process: the spare
            self.assertTrue(w.jobs[j].warm)
            self.until(lambda: w.spares_started == 2 and w.spare is not None)
            self.assertIsNot(w.spare, first)
            self.until(lambda: first.poll() is not None)  # the used spare is gone, one job each
            self.assertIsNone(w.spare.poll())
            second = w.spare
            j2 = self.post(c, "/api/rule", {"id": "ok_clip"}, ip="2.2.2.2").json()["job"]
            self.assertTrue(self.stream(c, j2)[0][-1][1]["warm"])
            self.until(lambda: second.poll() is not None)

    def test_a_finished_job_fetched_twice_is_the_same_result_not_a_rerun(self):
        c, _ = self.app(warm=False)
        with c:
            j = self.post(c, "/api/rule", {"id": "ok_clip"}).json()["job"]
            one, _ = self.stream(c, j)
            two, _ = self.stream(c, j)
        self.assertEqual(one, two)

    def test_the_shipped_set_runs_once_and_a_recent_result_is_reused(self):
        c, _ = self.app(warm=False)
        with c:
            a = self.post(c, "/api/replay-shipped", ip="3.0.0.1").json()["job"]
            b = self.post(c, "/api/replay-shipped", ip="3.0.0.2").json()["job"]
            self.assertEqual(a, b)  # one at a time globally: the second joins the first
            ev, _ = self.stream(c, a)
            self.assertEqual(ev[-1][0], "result")
            again = self.post(c, "/api/replay-shipped", ip="3.0.0.3").json()["job"]
            self.assertEqual(again, a)  # under 10 minutes old: returned, not rerun

    def test_racing_protest_and_limits_run_in_the_racing_dir(self):
        c, w = self.app(warm=False)
        with c:
            p = self.post(c, "/api/racing/protest", {"id": "1"}).json()["job"]
            ev, _ = self.stream(c, p)
            self.assertEqual(ev[-1][1]["id"], "protest-1")
            self.assertEqual(Path(ev[-1][1]["cwd"]).resolve(), (self.td / "racing").resolve())
            lim = self.post(c, "/api/racing/limits", ip="4.0.0.1").json()["job"]
            ev, _ = self.stream(c, lim)
            self.assertIn(
                ("line", {"event": "line", "id": "Race 1", "match": True, "record": "r1"}), ev
            )
            self.assertEqual(ev[-1][1]["id"], "limits")

    def test_limits_takes_the_whole_pool(self):
        c, w = self.app(warm=False)
        with c:
            a = self.post(c, "/api/rule", {"id": "slow_clip"}, ip="5.0.0.1").json()["job"]
            self.until(lambda: w.jobs[a].status == "running")
            lim = self.post(c, "/api/racing/limits", ip="5.0.0.2").json()["job"]
            b = self.post(c, "/api/rule", {"id": "ok_clip"}, ip="5.0.0.3").json()["job"]
            time.sleep(0.4)
            # a slot is free, but the limits job is first in line and needs both
            self.assertEqual(w.jobs[lim].status, "queued")
            self.assertEqual(w.jobs[b].status, "queued")
            self.until(lambda: w.jobs[lim].status != "queued")
            self.assertEqual(w.jobs[a].status, "done")
            self.assertEqual(w.jobs[b].status, "queued")  # nothing runs beside it
            self.stream(c, b)

    def test_graded26_and_health(self):
        c, _ = self.app(warm=False)
        with c:
            self.assertEqual(c.get("/api/graded26").status_code, 404)
            (self.td / "replays" / "graded26.json").write_text('{"lines": 26}', encoding="utf-8")
            self.assertEqual(c.get("/api/graded26").json(), {"lines": 26})
            self.assertTrue(c.get("/api/health").json()["ok"])

    def test_health_commit_comes_from_the_working_folder_or_is_null(self):
        here = Path.cwd()
        self.addCleanup(os.chdir, here)
        work = self.td / "current"
        work.mkdir()
        os.chdir(work)
        c, _ = self.app(warm=False)
        c.app.state.worker.commit = serve._commit()
        with c:
            self.assertIsNone(c.get("/api/health").json()["commit"])
        (work / "COMMIT").write_text("0123456789abcdef0123456789abcdef01234567\n", "utf-8")
        self.assertEqual(serve._commit(), "0123456789abcdef0123456789abcdef01234567")


def run_replay_one(args: list[str], cwd: Path, **env_extra) -> tuple[int, list[dict], str]:
    env = {k: v for k, v in os.environ.items() if k not in serve.DROP_ENV}
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(env_extra)
    r = subprocess.run(
        [sys.executable, "-m", "faultline.adapters.video.replay_one", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
    )
    return r.returncode, [json.loads(s) for s in r.stdout.splitlines() if s.strip()], r.stderr


def faultline_video() -> list[str]:
    """The installed `faultline-video` console script, beside this Python (Scripts/ or bin/)."""
    for name in ("faultline-video.exe", "faultline-video"):
        exe = Path(sys.executable).parent / name
        if exe.is_file():
            return [str(exe)]
    return [  # the same entry point, when the script is not installed
        sys.executable,
        "-c",
        "import sys; from faultline.adapters.video.cli import main; sys.exit(main(sys.argv[1:]))",
    ]


class ReplayOneTests(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="fl-replay-one-"))
        self.addCleanup(_rmtree, self.td)

    def test_contract_drift_against_faultline_video_replay(self):
        """The worker's shipped-set hash and per-entry match equal the CLI's on the same input."""
        out = self.td / "cli.jsonl"
        env = {k: v for k, v in os.environ.items() if k not in serve.DROP_ENV}
        env["PYTHONIOENCODING"] = "utf-8"
        cli_run = subprocess.Popen(
            [
                *faultline_video(),
                "replay",
                str(SHIPPED / "preds.jsonl"),
                "--out",
                str(out),
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        rc, ev, err = run_replay_one(
            ["--record", str(SHIPPED), "--all", str(SHIPPED / "preds.jsonl")], self.td
        )
        cli_out, cli_err = cli_run.communicate(timeout=600)
        self.assertEqual(cli_run.returncode, 0, cli_out + cli_err)
        self.assertEqual(rc, 0, err)
        cli_sha = cli_out.strip().rsplit("sha256 ", 1)[1]
        cli_same = int(cli_out.split(" of ")[0].rsplit(" ", 1)[1])
        res = ev[-1]
        self.assertEqual(res["event"], "result")
        self.assertEqual(res["set_sha256"], cli_sha)
        # install.sh reads the LAST JSON line with a set_sha256 key: it is the cmd_replay hash
        last = [e for e in ev if "set_sha256" in e][-1]
        self.assertEqual(last["set_sha256"], cli_sha)
        self.assertEqual(cli_sha, PREDS_SHA256)
        cli_lines = [json.loads(s) for s in out.read_text(encoding="utf-8").splitlines()]
        shipped = [json.loads(s) for s in (SHIPPED / "preds.jsonl").read_text("utf-8").splitlines()]
        cli_match = {a["id"]: a == b for a, b in zip(cli_lines, shipped, strict=True)}
        worker_match = {e["id"]: e["match"] for e in ev if e["event"] == "line"}
        self.assertEqual(worker_match, cli_match)
        self.assertEqual(sum(worker_match.values()), cli_same)
        self.assertEqual(
            [e["name"] for e in ev if e["event"] == "stage"], ["start", "record", "rebuild", "seal"]
        )

    def test_one_line_from_a_foreign_folder_with_the_network_dead(self):
        """--record wins over the default root (the reviewer's FileNotFoundError), and the
        replay needs no network: every proxy points at a dead address."""
        dead = {
            k: DEAD
            for k in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            )
        }
        rc, ev, err = run_replay_one(
            ["--record", str(SHIPPED), "--entry", "blind_corner_no_vest_07"],
            self.td,
            MODEL_API_BASE=DEAD,
            **dead,
        )
        self.assertEqual(rc, 0, err)
        res = ev[-1]
        self.assertEqual(res["event"], "result")
        self.assertTrue(res["match"])
        self.assertEqual(res["record_rebuilt"], res["record_shipped"])
        self.assertTrue(res["record_rebuilt"].startswith("c82ca137"))

    def test_a_set_replay_is_named_by_its_record_root(self):
        """graded26.json must say "graded", never "shipped": the id is the root folder's name."""
        rec = self.td / "graded"
        shutil.copytree(SHIPPED, rec)
        one = [
            s
            for s in (rec / "preds.jsonl").read_text("utf-8").splitlines()
            if '"idle_empty_aisle_40"' in s
        ]
        (rec / "preds.jsonl").write_bytes((one[0] + "\n").encode("utf-8"))
        rc, ev, err = run_replay_one(
            ["--record", str(rec), "--all", str(rec / "preds.jsonl")], self.td
        )
        self.assertEqual(rc, 0, err)
        self.assertEqual(ev[-1]["event"], "result")
        self.assertEqual(ev[-1]["id"], "graded")
        self.assertTrue(ev[-1]["match"])

    def _readonly_copy(self) -> Path:
        rec = self.td / "record"
        shutil.copytree(SHIPPED, rec)
        for p in rec.rglob("*"):
            if p.is_file():
                os.chmod(p, stat.S_IREAD)
        return rec

    def test_a_read_only_root_replays_and_matches(self):
        rec = self._readonly_copy()
        before = sorted(p.as_posix() for p in rec.rglob("*"))
        rc, ev, err = run_replay_one(
            ["--record", str(rec), "--entry", "idle_empty_aisle_40"], self.td
        )
        self.assertEqual(rc, 0, err)
        self.assertTrue(ev[-1]["match"])
        self.assertEqual(sorted(p.as_posix() for p in rec.rglob("*")), before)

    def test_a_missing_blob_is_an_error_naming_the_clip_never_a_mismatch(self):
        rec = self._readonly_copy()
        line = next(
            json.loads(s)
            for s in (rec / "preds.jsonl").read_text("utf-8").splitlines()
            if '"idle_empty_aisle_40"' in s
        )
        entry = json.loads((rec / "entries" / f"{line['entry']}.json").read_text("utf-8"))
        blob = rec / "blobs" / entry["site_blob"]
        os.chmod(blob, stat.S_IWRITE)
        blob.unlink()
        rc, ev, err = run_replay_one(
            ["--record", str(rec), "--entry", "idle_empty_aisle_40"], self.td
        )
        self.assertEqual(rc, 2)
        self.assertEqual(ev[-1]["event"], "error")
        self.assertIn("idle_empty_aisle_40", ev[-1]["message"])
        self.assertNotIn("result", [e["event"] for e in ev])
        self.assertNotIn("Traceback", json.dumps(ev))
        self.assertNotIn(str(rec), json.dumps(ev))


if __name__ == "__main__":
    unittest.main()
