"""The live page's data: one JSON bundle built from the records the page rebuilds.

`faultline-video bundle --sources <sources.json> --out <dir>` writes:

  index.json         the clip list (the shipped three first, then the other graded clips, then the
                     real footage), each clip's stamps and record hash, the README numbers the
                     page quotes (each with the README line it sits on), the models and where each
                     is used, the open-weight line, and the two set-replay hashes
  clips/<id>.json    one clip's rulings: verdict, the number that decided a breach, the
                     measurement, the fact an unable ruling lacks and the pack's own words for it,
                     the frames a card shows (with their seconds), and the model words beside the
                     ruling, each labelled with its model
  shift.json         the demo shift's windows and their rulings (only when sources name a shift)

Every static number on the page comes from a named README line: `readme_number` reads it there and
the build fails if the pattern is not on that line. The graded set hash must sit on its own README
line, so a sources file whose `readme_line` for it is 0 fails the build.

The bundle is a pure function of its inputs: sorted keys, fixed separators, no clock, so two builds
are byte-identical. No host path enters it: clips are named by id only, and a guard refuses any
output that holds a path from an entry's `host_paths` or a drive path. Model words are shown only
when they pass the leak lint again at build time, and only beside the ruling they were written for.
No model is called and no network is used.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from faultline.adapters.video import perception, wonder
from faultline.adapters.video.dashboard import FACT_WORDS, decided_by, lacks
from faultline.adapters.video.demo import read_pack
from faultline.adapters.video.shift import TITLES, ruling_frames

SCHEMA = 1
SRC_FPS = 24  # frame numbers count the clip's own 24 fps frames from the window start
FEATURED = ["blind_corner_no_vest_07", "spotter_ahead_01", "idle_empty_aisle_40"]
GROUPS = [
    {"id": "shipped", "title": "Pick a clip"},
    {"id": "graded", "title": "More clips"},
    {"id": "real", "title": "Real footage, faces blurred"},
]
DEFAULT_PACK = perception.PACKS / "forklift-site-rules"
DEFAULT_README = perception.REPO / "README.md"
WORDS_SUFFIX = ".words.jsonl"

NOTE_LABEL = {"model": "Muse Wonder 1.0", "where": "Meta Model API"}
READS_LABEL = {"model": "Muse Spark Open", "where": "Baseten", "runs": wonder.READ_RUNS}

MODELS = [
    {"name": "SAM 3.1", "where": "Meta Model API", "use": "masks and tracks"},
    {"name": "Muse Spark Open", "where": "Baseten", "use": "compiles the rules pack"},
    {
        "name": "Muse Wonder 1.0",
        "where": "Meta Model API",
        "use": "writes the note beside a ruling",
    },
    {"name": "Muse Spark Open", "where": "Baseten", "use": "reads the frames three times"},
    {"name": "Muse Spark 1.3", "where": "Meta Model API", "use": "the racing judge's read, arm 2"},
]

# (key, README line, pattern): the text is the pattern's first group, or the whole match
NUMBERS = [
    ("breach_found", 275, r"Breach clips found \| (\d+ of \d+)"),
    ("false_breach", 276, r"False breaches on the compliant clips \| (\d+ of \d+)"),
    ("unable", 277, r"Unable to rule \| (\d+ of \d+) rulings"),
    (
        "replay",
        278,
        r"Replay \| (byte-identical on Windows and in a Linux container with no network)",
    ),
    ("shift_windows", 288, r"(\d+) windows and \d+ rulings"),
    ("shift_rulings", 288, r"\d+ windows and (\d+) rulings"),
    ("shift_breach", 288, r"(\d+) breaches to review"),
    ("shift_clear", 288, r"(\d+) clear and \d+ unable"),
    ("shift_unable", 288, r"(\d+) unable, \d+ of them"),
    ("shift_camera_moved", 288, r"(\d+) of them because the camera moved or was never marked"),
    ("real_camera_line", 316, r"(the line is [\d.]+ m)"),
    (
        "real_floor_unable",
        317,
        r"(every rule that reads the truck's floor position \([^)]*\) is unable to rule)",
    ),
    ("real_hi_vis", 317, r"(the hi-vis rule reads the torso, not the floor, and is still ruled)"),
    ("words_spend", 330, r"spent (\$[\d.]+) in all"),
    ("words_spend_meta", 330, r"(\$[\d.]+) on the Meta Model API over \d+ calls"),
    ("words_spend_baseten", 330, r"(\$[\d.]+) on Baseten over \d+ calls"),
    ("words_cap", 330, r"under a (\$\d+) cap in code"),
    ("notes_passed", 331, r"wrote a note on (\d+ of \d+) rulings"),
    ("reads_agreed", 332, r"the three runs agreed on (\d+ of \d+) reads"),
]
OPEN_WEIGHT = (
    759,
    re.escape(
        "Muse Spark Open is a Meta open-weight model, served by Baseten (partner inference, "
        "model id `meta-models/muse-spark-open-1026`)."
    ),
)
SHIPPED_REPLAY_LINE = 813

DRIVE_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]|\\\\|/Users/|/home/")


class BundleError(RuntimeError):
    pass


# ---------------------------------------------------------------- helpers


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _dump(o) -> bytes:
    return (json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode(
        "ascii"
    )


def readme_number(readme_text: str, line: int, pattern: str) -> str:
    """The text the pattern finds on README line `line` (1-based): its first group, or the whole
    match. Fails when the line is 0, past the end, or does not hold the pattern."""
    lines = readme_text.splitlines()
    if line < 1 or line > len(lines):
        raise BundleError(f"README line {line} does not exist")
    m = re.search(pattern, lines[line - 1])
    if not m:
        raise BundleError(f"README line {line} no longer holds {pattern!r}")
    return (m.group(1) if m.groups() else m.group(0)).strip()


def _path(base: Path, p: str | None) -> Path | None:
    if not p:
        return None
    q = Path(p)
    return q if q.is_absolute() else base / q


def _host_strings(entry: dict) -> set[str]:
    out = set()
    for d in (entry.get("host_paths") or {}, entry.get("item") or {}):
        for k, v in d.items():
            if k in ("clip", "site", "rules_dir") and isinstance(v, str) and v:
                out.add(v)
                out.add(v.replace("/", "\\"))
    return out


# ---------------------------------------------------------------- frames


def read_frames_manifest(p: Path | None) -> dict[tuple[str, str], str] | None:
    """`frames.json` (Task 1.7: file, clip, frame, sha256) as {(clip, frame): src}; None when there
    is no manifest. `frame` is a frame number or "poster"; `src` is relative to the bundle folder.
    """
    if p is None or not p.is_file():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    rows = raw.get("frames", []) if isinstance(raw, dict) else raw
    out = {}
    for r in rows:
        f = str(r["file"]).replace("\\", "/").lstrip("/")
        if DRIVE_PATH.search(f) or ".." in f.split("/"):
            raise BundleError(f"frames manifest holds a path, not a bundle file: {r['clip']}")
        src = f if f.startswith("frames/") else "frames/" + f
        out[(str(r["clip"]), str(r["frame"]))] = src
    return out


def _src(manifest, clip: str, frame) -> str | None:
    if manifest is None:  # no manifest yet: the layout Task 1.7 writes
        return f"frames/{clip}/{frame}.jpg"
    return manifest.get((clip, str(frame)))


def _pick3(fr: list[int]) -> list[int]:
    return ruling_frames({"frames": fr})


def _model_frames(root: Path, entry: dict) -> list[int]:
    """The frames shown to Wonder or Spark Open for this window (the stored note, else a read)."""
    csha, item = entry.get("clip_sha256"), entry.get("item") or {}
    if not csha:
        return []
    d = root / "clips" / csha / "wonder" / wonder._win(item)
    names = ["note.json"] + [f"note-{k}.json" for k in range(2, wonder.NOTE_ATTEMPTS + 1)]
    names += [f"read-{k}.json" for k in range(1, wonder.READ_RUNS + 1)]
    for n in names:
        p = d / n
        if p.is_file():
            fr = json.loads(p.read_text(encoding="utf-8")).get("frames") or []
            if fr:
                return _pick3([int(x) for x in fr])
    return []


def card_frames(
    ruling: dict, root: Path, entry: dict, clip: str, start_s: float, manifest
) -> tuple[list[dict], str]:
    """The frames a ruling card shows and their caption source: the ruling's own, else the
    model's, else the window's (EMPTY_FRAMES)."""
    fr, source = ruling_frames(ruling), "ruling"
    if not fr:
        fr, source = _model_frames(root, entry), "model"
    if not fr:
        fr, source = list(wonder.EMPTY_FRAMES), "window"
    out = []
    for n in fr:
        src = _src(manifest, clip, n)
        if src is not None:
            out.append({"n": n, "t_s": round(start_s + n / SRC_FPS, 3), "src": src})
    return out, source


# ---------------------------------------------------------------- rulings


def _words_by_rule(words_line: dict | None, line: dict, shipped: set[str]) -> dict[str, dict]:
    if not words_line:
        return {}
    canon = {r["rule"]: r["verdict"] for r in line["rulings"]}
    out = {}
    for r in words_line.get("rulings", []):
        rule = r.get("rule")
        if canon.get(rule) != r.get("verdict"):
            continue  # never beside a ruling it was not written for
        w: dict = {}
        note = r.get("note")
        if isinstance(note, str) and note.strip() and not wonder.leak(note):
            w["note"] = {**NOTE_LABEL, "text": " ".join(note.split())}
        if rule in shipped:
            w["reads"] = {**READS_LABEL, "agreed": r.get("model_read")}
        if w:
            out[rule] = w
    return out


def _ruling(r: dict, titles: dict, pack: list[dict]) -> dict:
    unable = r["verdict"] == "unable_to_rule"
    lk = lacks(r["missing_fact"], r["rule"], pack) if unable else None
    return {
        "rule": r["rule"],
        "title": titles.get(r["rule"], TITLES.get(r["rule"], r["rule"])),
        "verdict": r["verdict"],
        "decided_by": decided_by(r["rule"], r["evidence"]) if r["verdict"] == "breach" else None,
        "measurement": r["evidence"],
        "missing_fact": r["missing_fact"],
        "lacks": lk["words"] if lk else None,
        "pack_words": lk["pack"] if lk else None,
    }


def hint(rulings: list[dict]) -> str:
    vs = {r["verdict"] for r in rulings}
    if "breach" in vs:
        return "breach"
    if vs == {"clear"}:
        return "clear"
    if vs == {"unable_to_rule"}:
        return "unable"
    return "mixed"


# ---------------------------------------------------------------- roots


def _root(sources: dict, base: Path, group: str) -> dict | None:
    s = (sources.get("roots") or {}).get(group)
    if not s:
        return None
    preds = _path(base, s.get("preds"))
    if preds is None or not preds.is_file():
        raise BundleError(f"the {group} root's preds file is missing")
    pack_dir = _path(base, s.get("rules")) or DEFAULT_PACK
    return {"group": group, "src": s, "preds": preds, "root": preds.parent, "pack": pack_dir}


def _clips_of(r: dict, ids: list[str] | None, manifest, kind: str, ship: set[str]):
    pack = read_pack(r["pack"])
    titles = {x["id"]: x["title"] for x in pack}
    lines = {p["id"]: p for p in _jsonl(r["preds"])}
    wp = r["preds"].with_name(r["preds"].name.removesuffix(".jsonl") + WORDS_SUFFIX)
    words = {w["id"]: w for w in _jsonl(wp)} if wp.is_file() else {}
    host: set[str] = set()
    out = []
    for cid in ids if ids is not None else sorted(lines):
        line = lines.get(cid)
        if line is None:
            raise BundleError(f"{cid} is not in the {r['group']} record")
        ep = r["root"] / "entries" / f"{line['entry']}.json"
        if not ep.is_file():
            raise BundleError(f"{cid}: its entry is not in the {r['group']} record")
        entry = json.loads(ep.read_text(encoding="utf-8"))
        host |= _host_strings(entry)
        start_s = float((entry.get("item") or {}).get("start_s", 0.0))
        wl = words.get(cid)
        # A words line carries its own record (the hash of its words manifest), never the
        # ruling's, so it is matched to the ruling by entry; each rule's verdict is matched next.
        if wl is not None and wl.get("entry") != line["entry"]:
            wl = None  # words written for another entry of this clip
        wb = _words_by_rule(wl, line, ship)
        rulings = []
        for x in line["rulings"]:
            card = _ruling(x, titles, pack)
            card["frames"], card["frames_source"] = card_frames(
                x, r["root"], entry, cid, start_s, manifest
            )
            card["words"] = wb.get(x["rule"])
            rulings.append(card)
        clip = {
            "schema": SCHEMA,
            "id": cid,
            "entry": line["entry"],
            "record": line["record"],
            "root": r["group"],
            "kind": kind,
            "live": True,
            "rulings": rulings,
        }
        poster = _src(manifest, cid, "poster")
        summary = {
            "id": cid,
            "group": r["group"],
            "root": r["group"],
            "kind": kind,
            "hint": hint(line["rulings"]),
            "poster": poster,
            "record": line["record"],
            "stamps": {x["rule"]: x["verdict"] for x in line["rulings"]},
            "live": True,
        }
        out.append((summary, clip))
    return out, host


# ---------------------------------------------------------------- shift


def _shift(sources: dict, base: Path, manifest) -> tuple[dict | None, set[str]]:
    s = sources.get("shift")
    d = _path(base, ((s or {}).get("output") or {}).get("path")) if s else None
    if d is None:
        return None, set()
    for n in ("windows.jsonl", "preds.jsonl"):
        if not (d / n).is_file():
            raise BundleError(f"the shift output has no {n}")
    pack = read_pack(_path(base, s.get("rules")) or DEFAULT_PACK)
    titles = {x["id"]: x["title"] for x in pack}
    ship = _shipped_rules()
    preds = {p["id"]: p for p in _jsonl(d / "preds.jsonl")}
    wp = d / "preds.words.jsonl"
    words = {w["id"]: w for w in _jsonl(wp)} if wp.is_file() else {}
    host: set[str] = set()
    windows = []
    for w in _jsonl(d / "windows.jsonl"):
        host.add(w["clip"])
        host.add(w["clip"].replace("/", "\\"))
        line = preds[w["window"]]
        wb = _words_by_rule(words.get(w["window"]), line, ship)
        rl = []
        for x in line["rulings"]:
            card = _ruling(x, titles, pack)
            card["frames"] = [
                {"n": n, "t_s": round(float(w["start_s"]) + n / SRC_FPS, 3)}
                for n in ruling_frames(x)
            ]
            card["words"] = wb.get(x["rule"])
            rl.append(card)
        windows.append(
            {
                "window": w["window"],
                "clip": Path(w["clip"]).stem,
                "shift_start_s": w["shift_start_s"],
                "shift_end_s": w["shift_end_s"],
                "gap_before_s": w["gap_before_s"],
                "entry": line["entry"],
                "record": line["record"],
                "poster": _src(manifest, w["window"], "poster") if manifest is not None else None,
                "rulings": rl,
            }
        )
    counts = {"breach": 0, "clear": 0, "unable_to_rule": 0}
    facts: dict[str, int] = {}
    for w in windows:
        for r in w["rulings"]:
            counts[r["verdict"]] += 1
            if r["verdict"] == "unable_to_rule" and r["missing_fact"]:
                facts[r["missing_fact"]] = facts.get(r["missing_fact"], 0) + 1
    return (
        {
            "schema": SCHEMA,
            "windows": windows,
            "counts": counts,
            "facts": [
                {"field": k, "words": FACT_WORDS.get(k, k), "rulings": v}
                for k, v in sorted(facts.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
        },
        host,
    )


def _shipped_rules() -> set[str]:
    ship = wonder.load_ship()
    return {k for k, v in (ship.get("rules") or {}).items() if v.get("ships")}


# ---------------------------------------------------------------- build


def _numbers(readme: str) -> dict:
    return {
        k: {"text": readme_number(readme, ln, pat), "readme_line": ln} for k, ln, pat in NUMBERS
    }


def _replay(readme: str, root: dict, line: int, lines: int, group: str) -> dict:
    sha = root["src"].get("set_sha256")
    if not sha:
        raise BundleError(f"sources name no set hash for the {group} root")
    if not line:
        raise BundleError(
            f"the {group} set hash has no README line yet (readme_line 0); write it into the "
            "README and name its line in sources.json"
        )
    readme_number(readme, line, re.escape(sha))
    return {"lines": lines, "sha256": sha, "readme_line": line}


def gather(sources_path: Path, out: Path, readme_path: Path | None = None) -> dict[str, bytes]:
    """Every bundle file as {relative path: bytes}; nothing is written."""
    sources_path = Path(sources_path)
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    base = sources_path.parent
    rp = (
        Path(readme_path) if readme_path else (_path(base, sources.get("readme")) or DEFAULT_README)
    )
    readme = rp.read_text(encoding="utf-8")

    shipped = _root(sources, base, "shipped")
    if shipped is None:
        raise BundleError("sources name no shipped root")
    graded = _root(sources, base, "graded")
    real = _root(sources, base, "real")

    numbers = _numbers(readme)
    open_weight = readme_number(readme, *OPEN_WEIGHT)
    shipped_lines = len(_jsonl(shipped["preds"]))
    shipped_replay = _replay(
        readme,
        shipped,
        int(shipped["src"].get("readme_line") or SHIPPED_REPLAY_LINE),
        shipped_lines,
        "shipped",
    )
    graded_replay = None
    if graded is not None:
        graded_replay = _replay(
            readme,
            graded,
            int(graded["src"].get("readme_line") or 0),
            len(_jsonl(graded["preds"])),
            "graded",
        )

    fp = _path(base, (sources.get("frames") or {}).get("manifest")) or (
        Path(out) / "frames" / "frames.json"
    )
    manifest = read_frames_manifest(fp)
    ship = _shipped_rules()

    shipped_ids = sorted(p["id"] for p in _jsonl(shipped["preds"]))
    if shipped_ids != sorted(FEATURED):
        raise BundleError(f"the shipped root holds {shipped_ids}, the page features {FEATURED}")
    rows, host = _clips_of(shipped, FEATURED, manifest, "synthetic", ship)
    if graded is not None:
        ids = sorted(p["id"] for p in _jsonl(graded["preds"]) if p["id"] not in FEATURED)
        got, h = _clips_of(graded, ids, manifest, "synthetic", ship)
        rows += got
        host |= h
    if real is not None:
        got, h = _clips_of(real, None, manifest, "real", ship)
        rows += got
        host |= h
    seen: set[str] = set()
    for s, _ in rows:
        if s["id"] in seen:
            raise BundleError(f"{s['id']} appears twice in the bundle")
        seen.add(s["id"])

    groups = [g for g in GROUPS if any(s["group"] == g["id"] for s, _ in rows)]
    index = {
        "schema": SCHEMA,
        "featured": list(FEATURED),
        "groups": groups,
        "clips": [s for s, _ in rows],
        "numbers": numbers,
        "models": MODELS,
        "open_weight_line": open_weight,
        "graded_replay": graded_replay,
        "shipped_replay": shipped_replay,
    }
    files = {"index.json": _dump(index)}
    for s, clip in rows:
        files[f"clips/{s['id']}.json"] = _dump(clip)
    shift, h = _shift(sources, base, manifest)
    host |= h
    if shift is not None:
        files["shift.json"] = _dump(shift)

    # the invariant: no host path anywhere in what ships
    host |= {str(r["root"]) for r in (shipped, graded, real) if r}
    for name, b in files.items():
        text = b.decode("ascii")
        bad = [x for x in host if x and x in text]
        if bad or DRIVE_PATH.search(text):
            raise BundleError(f"{name} would carry a host path")
    return files


def bundle_sha(files: dict[str, bytes]) -> str:
    lines = "".join(f"{k}\t{hashlib.sha256(v).hexdigest()}\n" for k, v in sorted(files.items()))
    return hashlib.sha256(lines.encode("ascii")).hexdigest()


def build_bundle(sources: Path, out: Path, readme: Path | None = None) -> str:
    """Write the bundle into `out` (index.json, clips/, shift.json); returns its sha256 (over
    sorted '<relpath>\\t<sha256>' lines). Frames and racing.json in `out` are left alone."""
    out = Path(out)
    files = gather(Path(sources), out, readme)
    if (out / "clips").is_dir():
        shutil.rmtree(out / "clips")
    if not any(k == "shift.json" for k in files) and (out / "shift.json").is_file():
        (out / "shift.json").unlink()
    for name, b in sorted(files.items()):
        p = out / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    return bundle_sha(files)


def cmd(args) -> int:
    try:
        sha = build_bundle(Path(args.sources), Path(args.out))
    except BundleError as e:
        print(f"faultline-video bundle: {e}")
        return 2
    print(f"bundle {args.out} sha256 {sha}")
    return 0


__all__ = ["BundleError", "build_bundle", "bundle_sha", "gather", "readme_number"]
