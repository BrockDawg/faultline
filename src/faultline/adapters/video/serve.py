"""The live page's worker: a small FastAPI app on 127.0.0.1; one replay subprocess per job.

    python -m faultline.adapters.video.serve --host 127.0.0.1 --port 8711 \
        --roots <dir holding shipped/ graded/ real/> \
        --bundle <dir holding index.json, racing.json> \
        --racing <racing dir> --replays <dir holding graded26.json>

API (the plan's worker contract):
    GET  /api/health              {"ok": true, "queue": n, "running": n, "commit": sha}
    GET  /api/graded26            replays/graded26.json, or 404
    POST /api/rule                {"id": clip id} -> 202 {"job", "position"}; 404; 429
    POST /api/replay-shipped      the shipped set; one at a time; a result under 10 min is reused
    POST /api/racing/protest      {"id": protest id}
    POST /api/racing/limits       one at a time; takes the whole pool (it runs alone)
    GET  /api/jobs/<job>          text/event-stream: queued, stage, line, result, error

Each job runs in its own process because `perception.RECORD` is a module global. A forklift
replay is handed to a warm spare (imports done, waiting on stdin) when one is up, and a new spare
is started in its place. The browser never sends a path: a clip id maps to its record root through
the bundle's index.json, a protest id through racing.json. No stack trace reaches the client: a
job's stderr goes to this process's log, and the stream carries plain words.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

log = logging.getLogger("faultline.serve")

VIDEO_MODULE = "faultline.adapters.video.replay_one"
RACING_MODULE = "faultline.adapters.pitbot.replay_one"
ROOT_NAMES = ("shipped", "graded", "real")
SAFE_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,80}$")
# keys a replay never needs; the subprocess runs without them
DROP_ENV = ("MODEL_API_KEY", "BASETEN_API_KEY", "FAULTLINE_RECORD")


@dataclass
class Config:
    roots: Path
    bundle: Path
    racing: Path | None = None
    replays: Path | None = None
    slots: int = 2  # a forklift replay peaks at 370 MB: two at once under the 1 GB unit
    queue_max: int = 30
    clip_timeout: float = 90.0
    shipped_timeout: float = 180.0
    protest_timeout: float = 90.0
    limits_timeout: float = 180.0
    heartbeat: float = 15.0
    forget_after: float = 600.0  # jobs forgotten 10 minutes after they finish
    shipped_reuse: float = 600.0  # a shipped-set result under 10 minutes old is returned as is
    warm: bool = True
    python: str = sys.executable
    # the command prefixes; tests swap these for stubs
    video_cmd: list[str] = field(default_factory=lambda: [sys.executable, "-m", VIDEO_MODULE])
    racing_cmd: list[str] = field(default_factory=lambda: [sys.executable, "-m", RACING_MODULE])
    commit: str | None = None


@dataclass
class Job:
    id: str
    kind: str  # rule | shipped | protest | limits
    visitor: str | None
    argv: list[str]
    cwd: Path
    timeout: float
    weight: int = 1
    stdin_job: dict | None = None  # what a warm spare is handed
    status: str = "queued"  # queued | running | done
    events: list[tuple[str, dict]] = field(default_factory=list)
    created: float = field(default_factory=time.monotonic)
    finished: float | None = None
    warm: bool = False


def _commit() -> str | None:
    """The deployed sha: the file COMMIT the deploy writes in the worker's working folder
    (/srv/faultline/current/COMMIT); None when it is absent."""
    try:
        sha = (Path.cwd() / "COMMIT").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return sha[:40] or None


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("could not read %s; its ids are not served", p.name)
        return {}


class Worker:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.commit = cfg.commit or _commit()
        self.jobs: dict[str, Job] = {}
        self.waiting: deque[Job] = deque()
        self.running: set[str] = set()
        self.free = cfg.slots
        self.cond: asyncio.Condition | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.spare: subprocess.Popen | None = None
        self.spares_started = 0
        self.spare_lock = threading.Lock()
        self.dispatcher: asyncio.Task | None = None
        self.procs: dict[str, subprocess.Popen] = {}
        self.clips: dict[str, str] = {}
        self.protests: set[str] = set()
        self.load_bundle()

    # ---------------- the bundle: ids the worker may run, never a path from the browser
    def load_bundle(self) -> None:
        index = _read_json(self.cfg.bundle / "index.json")
        for c in index.get("clips", []):
            cid, root = str(c.get("id", "")), str(c.get("root", ""))
            if SAFE_ID.match(cid) and root in ROOT_NAMES and c.get("live", True):
                self.clips[cid] = root
        racing = _read_json(self.cfg.bundle / "racing.json")
        self.protests = {
            str(p.get("id")) for p in racing.get("protests", []) if SAFE_ID.match(str(p.get("id")))
        }

    # ---------------- lifecycle
    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.cond = asyncio.Condition()
        self.dispatcher = asyncio.create_task(self._dispatch())
        if self.cfg.warm:
            await asyncio.to_thread(self._ensure_spare)

    async def stop(self) -> None:
        if self.dispatcher:
            self.dispatcher.cancel()
        for p in list(self.procs.values()) + ([self.spare] if self.spare else []):
            try:
                p.kill()
            except OSError:
                pass

    def _ensure_spare(self) -> None:
        with self.spare_lock:
            if self.spare is not None and self.spare.poll() is None:
                return
            try:
                self.spare = subprocess.Popen(
                    [*self.cfg.video_cmd, "--wait"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(self.cfg.roots),
                    env=_env(),
                    text=True,
                    encoding="utf-8",
                )
                self.spares_started += 1
            except OSError:
                log.exception("the warm spare did not start")
                self.spare = None

    def _take_spare(self) -> subprocess.Popen | None:
        with self.spare_lock:
            p, self.spare = self.spare, None
        if p is not None and p.poll() is None:
            return p
        return None

    # ---------------- state, under the event loop
    async def _changed(self) -> None:
        assert self.cond is not None
        async with self.cond:
            self.cond.notify_all()

    def _push(self, job: Job, event: str, data: dict) -> None:
        """Called from a job thread: record the event on the loop and wake the streams."""
        assert self.loop is not None

        def put() -> None:
            job.events.append((event, data))
            if event in ("result", "error"):
                # the visitor may run again the moment they hold the result; the slot itself is
                # freed in _finish, once the process has exited
                job.status = "done"
                job.finished = time.monotonic()
            asyncio.ensure_future(self._changed())

        self.loop.call_soon_threadsafe(put)

    def position(self, job: Job) -> int:
        for i, j in enumerate(self.waiting):
            if j.id == job.id:
                return i + 1
        return 0

    def forget_old(self) -> None:
        now = time.monotonic()
        for jid in [
            j.id
            for j in self.jobs.values()
            if j.finished is not None and now - j.finished > self.cfg.forget_after
        ]:
            del self.jobs[jid]

    def busy_visitor(self, visitor: str) -> bool:
        return any(j.visitor == visitor and j.status != "done" for j in self.jobs.values())

    def open_job(self, kind: str) -> Job | None:
        for j in self.jobs.values():
            if j.kind == kind and j.status != "done":
                return j
        return None

    def recent_result(self, kind: str) -> Job | None:
        now = time.monotonic()
        for j in self.jobs.values():
            if (
                j.kind == kind
                and j.status == "done"
                and j.finished is not None
                and now - j.finished < self.cfg.shipped_reuse
                and j.events
                and j.events[-1][0] == "result"
            ):
                return j
        return None

    async def submit(self, job: Job) -> Job:
        self.jobs[job.id] = job
        self.waiting.append(job)
        await self._changed()
        return job

    # ---------------- dispatch: first in, first out; a job starts when its slots are free
    async def _dispatch(self) -> None:
        assert self.cond is not None
        while True:
            async with self.cond:
                await self.cond.wait_for(
                    lambda: bool(self.waiting) and self.free >= self.waiting[0].weight
                )
                job = self.waiting.popleft()
                self.free -= job.weight
                job.status = "running"
                self.running.add(job.id)
                self.cond.notify_all()
            asyncio.get_running_loop().run_in_executor(None, self._run, job)

    def _finish(self, job: Job) -> None:
        def done() -> None:
            job.status = "done"
            job.finished = job.finished or time.monotonic()
            self.running.discard(job.id)
            self.free += job.weight
            asyncio.ensure_future(self._changed())

        assert self.loop is not None
        self.loop.call_soon_threadsafe(done)

    def _run(self, job: Job) -> None:
        """One job in its own process, in a thread: read its JSON lines, enforce its timeout."""
        t0 = time.monotonic()
        terminal = False
        proc: subprocess.Popen | None = None
        timed_out = threading.Event()
        try:
            if job.stdin_job is not None and self.cfg.warm:
                proc = self._take_spare()
            if proc is not None:
                job.warm = True
                assert proc.stdin is not None
                proc.stdin.write(json.dumps(job.stdin_job) + "\n")
                proc.stdin.close()
            else:
                proc = subprocess.Popen(
                    job.argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(job.cwd),
                    env=_env(),
                    text=True,
                    encoding="utf-8",
                )
            if self.cfg.warm and job.stdin_job is not None:
                threading.Thread(target=self._ensure_spare, daemon=True).start()
            self.procs[job.id] = proc
            err = threading.Thread(target=self._drain, args=(job, proc), daemon=True)
            err.start()

            def kill() -> None:
                timed_out.set()
                try:
                    proc.kill()
                except OSError:
                    pass

            timer = threading.Timer(job.timeout, kill)
            timer.start()
            try:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    ev = _parse(raw)
                    if ev is None:
                        continue
                    name, data = ev
                    if name == "ready":
                        continue
                    if name == "result":
                        data = {**data, "seconds": round(time.monotonic() - t0, 2)}
                    if name in ("result", "error"):
                        if terminal:
                            continue
                        terminal = True
                    self._push(job, name, data)
                proc.wait()
            finally:
                timer.cancel()
            if not terminal:
                msg = (
                    "the replay ran past its time limit and was stopped"
                    if timed_out.is_set()
                    else "the replay stopped before it finished"
                )
                self._push(job, "error", {"message": msg})
                terminal = True
        except Exception:  # noqa: BLE001  (logged here; the page gets plain words)
            log.exception("job %s failed", job.id)
            if not terminal:
                self._push(job, "error", {"message": "the replay could not be run on this server"})
        finally:
            self.procs.pop(job.id, None)
            self._finish(job)

    def _drain(self, job: Job, proc: subprocess.Popen) -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            log.info("job %s: %s", job.id, line.rstrip())


def _parse(raw: str) -> tuple[str, dict] | None:
    """A job's stdout line: {"event": name, ...} (or {"type": ...} / {"stage": name})."""
    raw = raw.strip()
    if not raw.startswith("{"):
        return None
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    name = d.pop("event", None) or d.pop("type", None)
    if name is None and "stage" in d:
        return "stage", {"name": d["stage"]}
    if name not in ("stage", "line", "result", "error", "ready"):
        return None
    if name == "error":
        d = {"message": str(d.get("message") or "the replay stopped on an error")}
    return name, d


def _sse(name: str, data: dict) -> str:
    body = json.dumps({"event": name, **data}, ensure_ascii=False)
    return f"event: {name}\ndata: {body}\n\n"


def create_app(cfg: Config) -> FastAPI:
    from contextlib import asynccontextmanager

    worker = Worker(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await worker.start()
        try:
            yield
        finally:
            await worker.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.worker = worker

    @app.exception_handler(Exception)
    async def plain(request: Request, exc: Exception):  # never a stack trace to the client
        log.exception("request failed")
        return JSONResponse({"error": "the worker hit an error"}, status_code=500)

    def visitor(request: Request) -> str:
        return request.headers.get("x-real-ip") or (
            request.client.host if request.client else "unknown"
        )

    async def body_id(request: Request) -> str | None:
        try:
            d = await request.json()
        except ValueError:
            return None
        v = d.get("id") if isinstance(d, dict) else None
        return str(v) if isinstance(v, (str, int)) and SAFE_ID.match(str(v)) else None

    def accepted(job: Job) -> JSONResponse:
        return JSONResponse({"job": job.id, "position": worker.position(job)}, status_code=202)

    def refuse(request: Request) -> JSONResponse | None:
        worker.forget_old()
        if worker.busy_visitor(visitor(request)):
            return JSONResponse(
                {"error": "you already have a replay running; it finishes first"}, status_code=429
            )
        if len(worker.waiting) >= cfg.queue_max:
            return JSONResponse(
                {"error": "the queue is full; the stored ruling stands"}, status_code=429
            )
        return None

    def not_found() -> JSONResponse:
        return JSONResponse({"error": "no such clip"}, status_code=404)

    @app.get("/api/health")
    async def health():
        return {
            "ok": True,
            "queue": len(worker.waiting),
            "running": len(worker.running),
            "commit": worker.commit,
        }

    @app.get("/api/graded26")
    async def graded26():
        p = cfg.replays / "graded26.json" if cfg.replays else None
        if p is None or not p.is_file():
            return JSONResponse({"error": "no set replay yet"}, status_code=404)
        return Response(p.read_bytes(), media_type="application/json")

    @app.post("/api/rule")
    async def rule(request: Request):
        cid = await body_id(request)
        if cid is None or cid not in worker.clips:
            return not_found()
        if (r := refuse(request)) is not None:
            return r
        root = cfg.roots / worker.clips[cid]
        job = Job(
            id=str(uuid.uuid4()),
            kind="rule",
            visitor=visitor(request),
            argv=[*cfg.video_cmd, "--record", str(root), "--entry", cid],
            cwd=cfg.roots,
            timeout=cfg.clip_timeout,
            stdin_job={"record": str(root), "entry": cid},
        )
        return accepted(await worker.submit(job))

    @app.post("/api/replay-shipped")
    async def replay_shipped(request: Request):
        worker.forget_old()
        if (j := worker.open_job("shipped") or worker.recent_result("shipped")) is not None:
            return accepted(j)
        if (r := refuse(request)) is not None:
            return r
        root = cfg.roots / "shipped"
        preds = root / "preds.jsonl"
        job = Job(
            id=str(uuid.uuid4()),
            kind="shipped",
            visitor=visitor(request),
            argv=[*cfg.video_cmd, "--record", str(root), "--all", str(preds)],
            cwd=cfg.roots,
            timeout=cfg.shipped_timeout,
            stdin_job={"record": str(root), "all": str(preds)},
        )
        return accepted(await worker.submit(job))

    @app.post("/api/racing/protest")
    async def protest(request: Request):
        pid = await body_id(request)
        if cfg.racing is None or pid is None or pid not in worker.protests:
            return JSONResponse({"error": "no such protest"}, status_code=404)
        if (r := refuse(request)) is not None:
            return r
        job = Job(
            id=str(uuid.uuid4()),
            kind="protest",
            visitor=visitor(request),
            argv=[*cfg.racing_cmd, "--racing", str(cfg.racing), "--protest", pid],
            cwd=cfg.racing,
            timeout=cfg.protest_timeout,
        )
        return accepted(await worker.submit(job))

    @app.post("/api/racing/limits")
    async def limits(request: Request):
        if cfg.racing is None:
            return JSONResponse({"error": "no racing record on this server"}, status_code=404)
        worker.forget_old()
        if (j := worker.open_job("limits")) is not None:
            return accepted(j)
        if (r := refuse(request)) is not None:
            return r
        job = Job(
            id=str(uuid.uuid4()),
            kind="limits",
            visitor=visitor(request),
            argv=[*cfg.racing_cmd, "--racing", str(cfg.racing), "--limits"],
            cwd=cfg.racing,
            timeout=cfg.limits_timeout,
            weight=cfg.slots,  # 497 MB peak: it runs alone
        )
        return accepted(await worker.submit(job))

    @app.get("/api/jobs/{jid}")
    async def stream(jid: str):
        worker.forget_old()
        job = worker.jobs.get(jid)
        if job is None:
            return JSONResponse({"error": "no such job"}, status_code=404)

        async def gen():
            assert worker.cond is not None
            sent, last_pos = 0, None
            while True:
                while sent < len(job.events):
                    name, data = job.events[sent]
                    sent += 1
                    yield _sse(name, data)
                    if name in ("result", "error"):
                        return
                if job.status == "queued":
                    pos = worker.position(job)
                    if pos != last_pos:
                        last_pos = pos
                        yield _sse("queued", {"position": pos})
                if job.status == "done" and sent >= len(job.events):
                    yield _sse("error", {"message": "the replay ended without a result"})
                    return
                beat = False
                async with worker.cond:  # checked under the lock, so no wake-up is missed
                    quiet = (
                        sent == len(job.events)
                        and job.status != "done"
                        and not (job.status == "queued" and worker.position(job) != last_pos)
                    )
                    if quiet:
                        try:
                            await asyncio.wait_for(worker.cond.wait(), timeout=cfg.heartbeat)
                        except TimeoutError:
                            beat = True
                if beat:
                    yield ": heartbeat\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m faultline.adapters.video.serve")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8711)
    ap.add_argument("--roots", required=True, help="the folder holding shipped/ graded/ real/")
    ap.add_argument("--bundle", required=True, help="the folder holding index.json, racing.json")
    ap.add_argument("--racing", help="the racing record folder (server only)")
    ap.add_argument("--replays", help="the folder holding graded26.json")
    ap.add_argument("--slots", type=int, default=2)
    ap.add_argument("--no-warm", action="store_true", help="no warm spare process")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cfg = Config(
        roots=Path(a.roots).resolve(),
        bundle=Path(a.bundle).resolve(),
        racing=Path(a.racing).resolve() if a.racing else None,
        replays=Path(a.replays).resolve() if a.replays else None,
        slots=a.slots,
        warm=not a.no_warm,
    )
    import uvicorn

    uvicorn.run(create_app(cfg), host=a.host, port=a.port, log_level="info", access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
