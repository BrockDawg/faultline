"""Wonder's words and the model's read, beside a forklift ruling the script has already made
(design).

Two things are added to each ruling, and neither touches `verdict`, `missing_fact` or `frames`:

  note        muse-wonder-1.0's two sentences from the ruled frames: what the frames show, the rule
  it bears on (named by
              the rule's title), and the fact that decided the script's verdict. One call per clip
              window covers every ruling in it; the prompt carries the script's ruling and its
              evidence, the rule text and the frames.
  model_read  three independent Spark Open reads of the same 8 window frames, each asked for a
  verdict on every rule
              from the rule text and the frames alone (never the script's verdict, measurements or
              the clip's name).
              The three runs are always kept in the record; the read is written on the ruling only
              where the three agree AND the rule passed the ship test in `data/wonder/ship.json`
              (agreed reads beat the constant answer on the 26 clips against the reviewed key, rule
              fixed in the private build notes before the scored run).

Every reply is a file under record/clips/<clip sha>/wonder/<window>/ and is an input of the ruling's
record hash, so `faultline-video replay` rebuilds the same bytes with no clip, no ffmpeg and no
network.
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import re
from pathlib import Path

from faultline.adapters.video import client, perception, record, video

NOTE_MODEL = "muse-wonder-1.0"
READ_MODEL = "meta-models/muse-spark-open-1026"
READ_RUNS = 3
READ_FRAMES = [
    0,
    15,
    30,
    45,
    60,
    75,
    90,
    105,
]  # 24 fps indexes of a 5 s window; clamped to the window
EMPTY_FRAMES = [12, 60, 108]  # a ruling with no ruled frame is described from these
NOTE_ATTEMPTS = 3  # attempt 3 gets 12,000 tokens: one clip ran out of 6,000 twice, reasoning
W, H = 640, 360
READ_TEMPERATURE = 0.7
VERDICTS = ("breach", "clear", "unable")
BANNED = (
    "compliant",
    "collision",
    "scrape",
    "speeding",
)  # words the leak lint cuts; the note prompt forbids them
SHIP_PATH = perception.ASSETS / "wonder" / "ship.json"

NOTE_SYSTEM = (
    "You write short factual notes beside forklift safety rulings that a measuring script "
    "has already made. "
    "You describe; you never give, change or question a verdict."
)


def _win(item: dict) -> str:
    return f"{float(item.get('start_s', 0.0)):.3f}_{float(item.get('end_s', 0.0)):.3f}"


def _dir(csha: str, item: dict) -> Path:
    return perception.clip_dir(csha) / "wonder" / _win(item)


def _rel(p: Path) -> str:
    return p.resolve().relative_to(perception.RECORD.resolve()).as_posix()


def _write(p: Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _json_of(text: str) -> dict | None:
    """The first JSON object in a reply (a fenced block or bare); None when there is none."""
    t = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", text.strip())
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        v = json.loads(t[a : b + 1])
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def leak(text: str) -> list[str]:
    from faultline.adapters.video.cli import lint

    return lint(text)


def note_ok(note, title: str) -> bool:
    return (
        isinstance(note, str)
        and 40 <= len(note) <= 600
        and title.lower() in note.lower()
        and not leak(note)
    )


def _ruling_key(rl: list[dict]) -> str:
    return record.sha_text(
        record.canon(
            [
                {k: r.get(k) for k in ("rule", "verdict", "missing_fact", "frames", "evidence")}
                for r in rl
            ]
        )
    )


# ---------------------------------------------------------------- frames
class Frames:
    """Only the frames a call shows are decoded, one at a time (a whole window at 24 fps per worker
    ran the host out of memory).
    """

    def __init__(self, clip: Path, item: dict):
        self.clip, self.item = clip, item
        self.s, self.e = float(item.get("start_s", 0.0)), float(item.get("end_s", 0.0))
        self._jpg: dict[int, bytes] = {}

    def count(self) -> int:
        dur = video.probe(self.clip).get("duration") or self.e
        return max(0, int(round((min(self.e, dur) - self.s) * video.SRC_FPS)))

    def pick(self, idx: list[int]) -> list[int]:
        n = self.count()
        return sorted({min(max(int(i), 0), n - 1) for i in idx}) if n else []

    def jpeg(self, i: int) -> bytes:
        if i not in self._jpg:
            t = self.s + i / video.SRC_FPS
            self._jpg[i] = video._run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-threads",
                    "1",
                    "-ss",
                    f"{max(t - 0.5, 0):.3f}",
                    "-i",
                    str(self.clip),
                    "-ss",
                    f"{t - max(t - 0.5, 0):.4f}",
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale={W}:{H}",
                    "-q:v",
                    "5",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "mjpeg",
                    "-",
                ]
            )
        return self._jpg[i]

    def jpegs(self, idx: list[int]) -> list[bytes]:
        return [self.jpeg(i) for i in idx]


def _note_frames(rl: list[dict]) -> list[int]:
    out: set[int] = set()
    for r in rl:
        fr = sorted(r.get("frames") or [])
        if fr:
            out |= {fr[0], fr[len(fr) // 2], fr[-1]}
        else:
            out |= set(EMPTY_FRAMES)
    return sorted(out)


# ---------------------------------------------------------------- prompts
def note_prompt(
    rl: list[dict], rules_by_id: dict, frames: list[int], secs: float, attempt: int
) -> str:
    lines = [
        f"A fixed warehouse camera, one window of {secs:.1f} s. The images that follow are "
        f"frames {frames} "
        "(24 frames a second), in that order.",
        "For each ruling below write a note of exactly two sentences, 60 to 400 characters in all.",
        "Sentence 1: what the frames show that bears on the rule; it must contain the "
        "rule's title exactly as quoted below.",
        "Sentence 2: the measured fact that decided the script's verdict, taken from the "
        "script's evidence (for "
        "unable_to_rule, the fact that could not be measured).",
        "Describe only: give no verdict of your own and do not dispute the script's. "
        f"Never use the words {', '.join(BANNED)}. Name no file.",
        "",
        "Rulings:",
    ]
    for r in rl:
        meta = rules_by_id.get(r["rule"], {})
        lines.append(
            f'- id: {r["rule"]}; title: "{meta.get("title", r["rule"])}"; on video: '
            f"{meta.get('on_video', '')}; "
            f"script verdict: {r['verdict']}; missing fact: {r.get('missing_fact') or 'none'}; "
            f'ruled frames: {r.get("frames") or "none"}; script evidence: "{r["evidence"]}"'
        )
    lines += [
        "",
        'Answer with one JSON object only, keyed by rule id: {"<rule id>": "<note>", ...}.'
        + (f" (attempt {attempt})" if attempt > 1 else "")
        + (" Keep your reasoning short." if attempt > 2 else ""),
    ]
    return "\n".join(lines)


def read_prompt(rules: list[dict], site: dict, frames: list[int], secs: float, run: int) -> str:
    lines = [
        f"A fixed warehouse camera, one window of {secs:.1f} s. The images that follow are "
        f"frames {frames} "
        "(24 frames a second, 640x360), in that order.",
        f"The site: {site.get('note', '')} Pedestrian separation distance: "
        f"{site.get('pedestrian_separation_m')} m.",
        "",
        "The site's rules:",
    ]
    for r in rules:
        lines += [f"### {r['id']}: {r['title']}", r.get("text", "").strip(), ""]
    lines += [
        'For each rule, decide from these frames alone: "breach" if the frames show the '
        'rule broken, "clear" if they '
        'show it kept, "unable" if the frames cannot settle it.',
        f"This is independent read {run} of {READ_RUNS}.",
        'Answer with one JSON object only: {"<rule id>": {"verdict": "breach|clear|unable", '
        '"frames": [frame indexes], '
        '"why": "<one sentence>"}, ...}.',
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- calls (each reply kept as a
# record file)
def _ask(
    path: Path,
    prompt: str,
    model: str,
    frames: list[int],
    jpegs: list[bytes],
    max_tokens: int,
    temperature: float,
    system: str | None,
    tag: str,
) -> dict:
    msgs = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    r = client.chat(
        msgs, model=model, max_tokens=max_tokens, temperature=temperature, images=jpegs, tag=tag
    )
    doc = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "frames": frames,
        "images_sha256": [hashlib.sha256(j).hexdigest() for j in jpegs],
        "prompt": prompt,
        "system": system,
        "reply": r["text"],
        "finish": r["finish"],
        "usage": r["usage"],
        "est_usd": r["est_usd"],
        "cache": r["cache"],
    }
    _write(path, doc)
    return doc


def _load(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def reads(
    d: Path,
    frames_src: Frames | None,
    rules: list[dict],
    site: dict,
    secs: float,
    allow_calls: bool,
    tag: str,
) -> list[dict | None]:
    paths = [d / f"read-{k}.json" for k in range(1, READ_RUNS + 1)]
    have = [_load(p) for p in paths]
    todo = [k for k, h in enumerate(have) if h is None]
    if todo and allow_calls and frames_src is not None:
        idx = frames_src.pick(READ_FRAMES)
        jp = frames_src.jpegs(idx)

        def one(k):
            try:
                return _ask(
                    paths[k],
                    read_prompt(rules, site, idx, secs, k + 1),
                    READ_MODEL,
                    idx,
                    jp,
                    12000,
                    READ_TEMPERATURE,
                    None,
                    f"{tag}:read{k + 1}",
                )
            except client.ApiError:
                return None

        with cf.ThreadPoolExecutor(max_workers=READ_RUNS) as ex:
            for k, doc in zip(todo, ex.map(one, todo), strict=False):
                have[k] = doc
    return have


def read_verdicts(doc: dict | None, rule: str) -> str | None:
    if doc is None:
        return None
    j = _json_of(doc.get("reply") or "") or {}
    v = j.get(rule)
    v = v.get("verdict") if isinstance(v, dict) else v
    v = str(v).strip().lower() if v is not None else None
    return v if v in VERDICTS else None


def agreed(runs: list[str | None]) -> str | None:
    return (
        runs[0]
        if len(runs) == READ_RUNS
        and runs[0] in ("breach", "clear")
        and all(x == runs[0] for x in runs)
        else None
    )


# ---------------------------------------------------------------- the annotation
def load_ship() -> dict:
    return (
        json.loads(SHIP_PATH.read_text(encoding="utf-8"))
        if SHIP_PATH.is_file()
        else {"rules": {}, "note": "no ship test run yet"}
    )


def annotate(
    line: dict,
    manifest: dict,
    item: dict,
    pack_rules: list[dict],
    site: dict,
    allow_calls: bool,
    replay: dict | None = None,
) -> tuple[dict, dict]:
    """Add `note` (always tried) and `model_read` (only where shipped) to each ruling; the replies
    join the record.
    """
    csha = manifest.get("clip_sha256")
    rl = line["rulings"]
    if not csha or not rl:
        return line, manifest
    rules_by_id = {r["id"]: r for r in pack_rules}
    d = _dir(csha, item)
    inputs = manifest["inputs"]
    secs = float(item.get("end_s", 0.0)) - float(item.get("start_s", 0.0))
    clip = Path(item["clip"]) if replay is None and item.get("clip") else None
    src = Frames(clip, item) if clip is not None and clip.is_file() else None
    tag = csha[:8]
    calls = allow_calls and replay is None

    # the ship test, as a content-addressed input (replay reads the recorded blob, never the asset)
    if replay is not None and replay.get("wonder_ship_blob"):
        ship = record.get_json_blob(replay["wonder_ship_blob"])
    else:
        ship = load_ship()
    inputs["wonder/ship"] = manifest["wonder_ship_blob"] = record.put_json_blob(ship)
    shipped_rules = {k for k, v in (ship.get("rules") or {}).items() if v.get("ships")}

    # the three-run read (the frames and the rule text only)
    judged = [
        rules_by_id[r["rule"]]
        for r in rl
        if r["rule"] in rules_by_id and rules_by_id[r["rule"]].get("route") != "out"
    ]
    rdocs = reads(d, src, judged, site, secs, calls, tag) if judged else []
    for k, doc in enumerate(rdocs, 1):
        if doc is not None:
            p = d / f"read-{k}.json"
            inputs[_rel(p)] = record.sha_norm(p)

    # Wonder's note (the ruling, its evidence, the rule text and the frames)
    rk = _ruling_key(rl)
    notes: dict[str, str] = {}
    note_files = []
    for attempt in range(1, NOTE_ATTEMPTS + 1):
        p = d / ("note.json" if attempt == 1 else f"note-{attempt}.json")
        doc = _load(p)
        if doc is not None and doc.get("rulings_sha256") != rk:
            doc = (
                None if calls else doc
            )  # a ruling that moved since the note was written is described again
        if doc is None and calls and src is not None:
            idx = src.pick(_note_frames(rl))
            try:
                doc = _ask(
                    p,
                    note_prompt(rl, rules_by_id, idx, secs, attempt),
                    NOTE_MODEL,
                    idx,
                    src.jpegs(idx),
                    6000 if attempt < 3 else 12000,
                    0.0,
                    NOTE_SYSTEM,
                    f"{tag}:note{attempt}",
                )
                doc["rulings_sha256"] = rk
                _write(p, doc)
            except client.ApiError:
                doc = None
        if doc is None:
            break
        note_files.append(p)
        j = _json_of(doc.get("reply") or "") or {}
        for r in rl:
            title = rules_by_id.get(r["rule"], {}).get("title", r["rule"])
            if r["rule"] not in notes and note_ok(j.get(r["rule"]), title):
                notes[r["rule"]] = " ".join(str(j[r["rule"]]).split())
        if all(r["rule"] in notes for r in rl):
            break
    for p in note_files:
        inputs[_rel(p)] = record.sha_norm(p)

    runs_by_rule = {}
    for r in rl:
        runs = [read_verdicts(doc, r["rule"]) for doc in rdocs]
        runs_by_rule[r["rule"]] = runs
        r["note"] = notes.get(r["rule"])
        a = agreed(runs)
        if a is not None and r["rule"] in shipped_rules:
            r["model_read"] = a
    manifest["wonder"] = {
        "note_files": [_rel(p) for p in note_files],
        "read_files": [
            _rel(d / f"read-{k}.json") for k, doc in enumerate(rdocs, 1) if doc is not None
        ],
        "reads": runs_by_rule,
        "shipped_rules": sorted(shipped_rules),
        "notes_named": sum(1 for r in rl if r.get("note")),
    }
    manifest["inputs"] = dict(sorted(inputs.items()))
    line["record"] = record.inputs_hash(manifest["inputs"])
    return line, manifest


def annotate_many(
    jobs: list[tuple], allow_calls: bool, workers: int = 3
) -> list[tuple[dict, dict]]:
    """annotate() over many (line, manifest, item, pack_rules, site) jobs, in parallel, results in
    order.
    """

    def one(j):
        line, manifest, item, pack_rules, site = j
        try:
            return annotate(line, manifest, item, pack_rules, site, allow_calls)
        except client.BudgetSpent:
            return annotate(line, manifest, item, pack_rules, site, False)

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, jobs))
