"""The forklift demo: one command replays a shift of clips into windows, rulings and a dashboard.

    faultline shift <manifest.json> --out <shift/> [--key key.json] [--offline] [--words] faultline
    shift --replay <shift/> --out <shift2/>        network off; every built file byte-identical
    (words too)

A manifest stitches clips into one shift without touching them: clip order, the gap before each
clip, and the window of the clip that is judged. Each clip becomes one window on the shift's clock.
Every window is judged by the same `judge_item` the 26-clip smoke runs, so a window's ruling line is
the smoke's line under the window's id. A window gets a ruling or a named "unable to rule" for every
rule, never nothing (0 idle), and the build refuses to finish otherwise.

Out:
  manifest.json            the manifest as read, paths resolved (the replay reads this)
  windows.jsonl            one line per window: clip, its sha256, the judged span, the span on the
  shift's clock preds.jsonl              one ruling line per window, the judge's contract
  entries/<entry>.json     the record of each ruling (every input hashed), for replay
  frames/<window>-<n>.jpg  the frames each ruling names, plus one poster frame per window
  lifecycle.initial.json   every breach ruling, identified (rebuilt byte-identical by a replay)
  lifecycle.json           the live lifecycle; created once from the initial file and never
  overwritten by a build dashboard.html           static, no server and no CDN; opens from disk
  preds.words.jsonl        only with --words: Wonder's recorded notes beside each ruling (the side
  file) entries/<entry>.words.json   only with --words: the words line's record

--words reads the notes and three-run reads already in the record for each window and makes no model
call: a note is shown only for the rulings it was written for (its rulings hash must match them), so
a rule the recorded note did not cover (the site speed limit, on this pack) and every window refused
at a gate carry no note. Asking Wonder from the shift would overwrite the smoke's own recorded note
for the same window, so the shift never asks. The dashboard shows the words panel only when
preds.words.jsonl is present; a build without --words removes a stale side file, so the page and the
folder always agree. `--replay` rebuilds the words when the source shift has them.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from faultline.adapters.video import lifecycle, perception, record
from faultline.adapters.video.video import SRC_FPS

BUILT = (
    "windows.jsonl",
    "preds.jsonl",
    "lifecycle.initial.json",
    "dashboard.html",
    "manifest.json",
    "preds.words.jsonl",
)
WORDS_FILE = "preds.words.jsonl"
MAX_RULING_FRAMES = 3
THUMB_W = 480

TITLES = {
    "hi_vis_in_truck_zone": "Hi-vis in the truck zone",
    "spotter_when_reversing": "Spotter when reversing",
    "pedestrian_separation": "Pedestrian separation",
    "structure_contact": "Structure contact",
    "site_speed_limit": "Site speed limit",
}


def _dump(o) -> str:
    return json.dumps(o, ensure_ascii=False, sort_keys=True) + "\n"


def _resolve(base: Path, p: str | None, default: Path) -> Path:
    if not p:
        return default
    q = Path(p)
    return q if q.is_absolute() else (base / q)


def read_manifest(path: Path) -> dict:
    """The manifest with every path made absolute (relative paths are read against the manifest's
    folder).
    """
    path = Path(path).resolve()
    m = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    clips_root = _resolve(base, m.get("clips_root"), base)
    out = {
        "name": m.get("name", path.stem),
        "note": m.get("note", ""),
        "rules": _resolve(base, m.get("rules"), perception.PACKS / "forklift-site-rules")
        .resolve()
        .as_posix(),
        "site": _resolve(base, m.get("site"), perception.ASSETS / "site.json").resolve().as_posix(),
        "default_gap_s": float(m.get("default_gap_s", 0.0)),
        "clips": [],
    }
    for c in m["clips"]:
        e = c if isinstance(c, dict) else {"clip": c}
        out["clips"].append(
            {
                "clip": _resolve(clips_root, e["clip"], clips_root).resolve().as_posix(),
                "gap_before_s": float(e.get("gap_before_s", out["default_gap_s"])),
                "start_s": float(e.get("start_s", 0.0)),
                "end_s": float(e.get("end_s", 5.0)),
            }
        )
    return out


def make_windows(m: dict) -> list[dict]:
    windows, t, seen = [], 0.0, {}
    for i, c in enumerate(m["clips"]):
        stem = Path(c["clip"]).stem
        seen[stem] = seen.get(stem, 0) + 1
        wid = f"w{i + 1:02d}-{stem}" + (f"-{seen[stem]}" if seen[stem] > 1 else "")
        t += c["gap_before_s"]
        span = c["end_s"] - c["start_s"]
        clip = Path(c["clip"])
        windows.append(
            {
                "window": wid,
                "clip": c["clip"],
                "clip_sha256": record.sha_file(clip) if clip.is_file() else None,
                "start_s": round(c["start_s"], 3),
                "end_s": round(c["end_s"], 3),
                "gap_before_s": round(c["gap_before_s"], 3),
                "shift_start_s": round(t, 3),
                "shift_end_s": round(t + span, 3),
            }
        )
        t += span
    return windows


def idle(windows: list[dict], preds: list[dict], rule_ids: list[str]) -> list[str]:
    """Windows with no ruling line, a rule left without a verdict, or an 'unable to rule' that names
    no fact.
    """
    by = {p["id"]: p for p in preds}
    bad = []
    for w in windows:
        p = by.get(w["window"])
        if p is None:
            bad.append(f"{w['window']}: no ruling line")
            continue
        got = {r["rule"]: r for r in p["rulings"]}
        for rid in rule_ids:
            r = got.get(rid)
            if r is None or r["verdict"] not in ("breach", "clear", "unable_to_rule"):
                bad.append(f"{w['window']}: {rid} has no verdict")
            elif r["verdict"] == "unable_to_rule" and not r.get("missing_fact"):
                bad.append(f"{w['window']}: {rid} is unable to rule but names no fact")
    return bad


# ---------------------------------------------------------------- frames


def _frames_for(line: dict) -> list[int]:
    out = set()
    for r in line["rulings"]:
        fr = sorted(set(int(x) for x in r.get("frames") or []))
        if len(fr) > MAX_RULING_FRAMES:
            fr = [fr[0], fr[len(fr) // 2], fr[-1]]
        out.update(fr)
    return sorted(out)


def ruling_frames(r: dict) -> list[int]:
    fr = sorted(set(int(x) for x in r.get("frames") or []))
    return [fr[0], fr[len(fr) // 2], fr[-1]] if len(fr) > MAX_RULING_FRAMES else fr


def extract_frames(
    clip: Path, start_s: float, idx: list[int], dest: Path, wid: str
) -> dict[int, str]:
    """JPEG thumbnails of frame indexes (the clip's own 24 fps numbering, counted from the window
    start).
    """
    if not idx or not clip.is_file():
        return {}
    dest.mkdir(parents=True, exist_ok=True)
    first = int(round(start_s * SRC_FPS))
    sel = "+".join(f"eq(n\\,{first + i})" for i in idx)
    tmp = dest / f".{wid}-tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-threads",
            "1",
            "-i",
            str(clip),
            "-vf",
            f"select='{sel}',scale={THUMB_W}:-2",
            "-fps_mode",
            "passthrough",
            "-q:v",
            "5",
            "-bitexact",
            "-flags",
            "+bitexact",
            "-f",
            "image2",
            str(tmp / "%03d.jpg"),
        ],
        capture_output=True,
        check=True,
        timeout=300,
    )
    got = sorted(tmp.glob("*.jpg"))
    out = {}
    for i, p in zip(idx, got, strict=False):
        name = f"{wid}-{i:04d}.jpg"
        shutil.move(str(p), dest / name)
        out[i] = f"frames/{name}"
    shutil.rmtree(tmp, ignore_errors=True)
    return out


# ---------------------------------------------------------------- build


def _note_files_match(wm: dict, rulings: list[dict]) -> bool:
    """Every recorded note the words line used was written for these rulings: its rulings hash
    equals the hash of the rulings its prompt carried (the shift's pack may carry a rule the note's
    run did not)."""
    import re

    from faultline.adapters.video import wonder

    for rel in (wm.get("wonder") or {}).get("note_files", []):
        doc = json.loads((perception.RECORD / rel).read_text(encoding="utf-8"))
        asked = set(re.findall(r"^- id: (\S+);", doc.get("prompt") or "", re.M))
        covered = [r for r in rulings if r["rule"] in asked]
        if not covered or doc.get("rulings_sha256") != wonder._ruling_key(covered):
            return False
    return True


def shift_words(
    preds: list[dict], entries: dict[str, dict], pack_rules: list[dict], site: dict
) -> tuple[list[dict], dict[str, dict]]:
    """The words side lines for a shift, from the record only (no model call). Returns (lines, words
    manifests).
    """
    from faultline.adapters.video import cli

    lines, manifests = [], {}
    for line in preds:
        m = entries[line["entry"]]
        side, wm = cli.words_line(line, m, m["item"], pack_rules, site, allow_calls=False)
        if not _note_files_match(wm, line["rulings"]):
            for r in side["rulings"]:
                r["note"] = None
            wm.setdefault("wonder", {})["notes_dropped"] = (
                "a recorded note was written for other rulings"
            )
        lines.append(side)
        manifests[line["entry"]] = wm
    return lines, manifests


def build(
    manifest_path: Path,
    out: Path,
    allow_calls: bool,
    key_path: Path | None = None,
    manifest: dict | None = None,
    words: bool = False,
) -> dict:
    from faultline.adapters.video import cli  # judge_item lives with the judge command

    m = manifest if manifest is not None else read_manifest(manifest_path)
    if key_path:
        m["key"] = Path(key_path).resolve().as_posix()
    out.mkdir(parents=True, exist_ok=True)
    rules_dir = Path(m["rules"])
    pack_rec = record.store_pack(rules_dir)
    pack_rules = cli.load_pack_rules(rules_dir)
    site_path = Path(m["site"])
    site_sha = record.put_blob(site_path.read_bytes())
    site = json.loads(record.get_blob(site_sha).decode("utf-8"))
    windows = make_windows(m)
    preds, posters, rframes, entries = [], {}, {}, {}
    (out / "entries").mkdir(exist_ok=True)
    for i, w in enumerate(windows):
        item = {
            "id": w["window"],
            "clip": w["clip"],
            "start_s": w["start_s"],
            "end_s": w["end_s"],
            "site": m["site"],
        }
        host = {
            "clip": Path(w["clip"]).as_posix(),
            "site": site_path.as_posix(),
            "rules_dir": rules_dir.as_posix(),
        }
        try:
            line, entry = cli.judge_item(
                item, pack_rules, pack_rec, site, site_sha, allow_calls=allow_calls, host=host
            )
        except cli.client.BudgetSpent as exc:
            print(f"budget stop: {exc}", file=sys.stderr)
            allow_calls = False
            line, entry = cli.judge_item(
                item, pack_rules, pack_rec, site, site_sha, allow_calls=False, host=host
            )
        (out / "entries" / f"{line['entry']}.json").write_text(
            json.dumps(entry, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        entries[line["entry"]] = entry
        w["entry"], w["record"] = line["entry"], line["record"]
        preds.append(line)
        n_src = int(round((w["end_s"] - w["start_s"]) * SRC_FPS))
        poster = n_src // 2
        got = extract_frames(
            Path(w["clip"]),
            w["start_s"],
            sorted(set(_frames_for(line)) | {poster}),
            out / "frames",
            w["window"],
        )
        posters[w["window"]] = got.get(poster)
        rframes[w["window"]] = got
        v = "".join(
            "B" if r["verdict"] == "breach" else "c" if r["verdict"] == "clear" else "?"
            for r in line["rulings"]
        )
        print(f"{i + 1}/{len(windows)} {w['window']}: {v}", flush=True)

    bad = idle(windows, preds, [r["id"] for r in pack_rules])
    (out / "manifest.json").write_text(
        json.dumps(m, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    (out / "windows.jsonl").write_text(
        "".join(_dump(w) for w in windows), encoding="utf-8", newline="\n"
    )
    (out / "preds.jsonl").write_text(
        "".join(_dump(p) for p in preds), encoding="utf-8", newline="\n"
    )
    init = lifecycle.initial(preds)
    lifecycle.save(init, out / "lifecycle.initial.json")
    if not (out / "lifecycle.json").exists():
        lifecycle.save(init, out / "lifecycle.json")
    wp = out / WORDS_FILE
    if words:
        wl, wms = shift_words(preds, entries, pack_rules, site)
        for eid, wm in wms.items():
            (out / "entries" / f"{eid}.words.json").write_text(
                json.dumps(wm, indent=1, sort_keys=True, ensure_ascii=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        wp.write_text("".join(_dump(x) for x in wl), encoding="utf-8", newline="\n")
        rl = [r for x in wl for r in x["rulings"]]
        print(
            f"words: notes on {sum(1 for r in rl if r.get('note'))} of {len(rl)} rulings, "
            "model reads shown on "
            f"{sum(1 for r in rl if r.get('model_read'))}, from the record (no model call)"
        )
    else:
        stale = [wp] + sorted((out / "entries").glob("*.words.json"))
        for p in stale:
            if p.exists():
                p.unlink()
                print(f"removed a stale words file: {p.name}", file=sys.stderr)
    side = (
        [json.loads(x) for x in wp.read_text(encoding="utf-8").splitlines() if x.strip()]
        if wp.exists()
        else None
    )
    key = json.loads(Path(m["key"]).read_text(encoding="utf-8"))["clips"] if m.get("key") else None
    from faultline.adapters.video import dashboard

    html = dashboard.render(m, windows, preds, pack_rules, posters, rframes, init, key, words=side)
    (out / "dashboard.html").write_text(html, encoding="utf-8", newline="\n")
    span = windows[-1]["shift_end_s"] if windows else 0.0
    summary = {"windows": len(windows), "idle": len(bad), "shift_s": span, "idle_detail": bad}
    print(
        f"shift {m['name']}: {len(windows)} clips into {len(windows)} windows over "
        f"{span:.1f} s, {len(bad)} idle"
    )
    for b in bad:
        print(f"  idle: {b}", file=sys.stderr)
    return summary


def _files(d: Path) -> dict[str, str]:
    names = [n for n in BUILT if (d / n).exists()]
    names += sorted(
        p.relative_to(d).as_posix()
        for sub in ("frames", "entries")
        if (d / sub).is_dir()
        for p in (d / sub).iterdir()
    )
    return {n: hashlib.sha256((d / n).read_bytes()).hexdigest() for n in names}


def replay(src: Path, out: Path) -> int:
    m = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    summary = build(
        src / "manifest.json", out, allow_calls=False, manifest=m, words=(src / WORDS_FILE).exists()
    )
    a, b = _files(src), _files(out)
    diff = sorted(n for n in set(a) | set(b) if a.get(n) != b.get(n))
    same = len(set(a) | set(b)) - len(diff)
    print(f"replayed shift: {same} of {len(set(a) | set(b))} built files byte-identical to {src}")
    for n in diff[:20]:
        print(f"  differs: {n}", file=sys.stderr)
    return 0 if not diff and summary["idle"] == 0 else 1


def cmd(args) -> int:
    if args.replay:
        return replay(Path(args.replay), Path(args.out))
    if not args.manifest:
        print("give a manifest, or --replay <shift dir>", file=sys.stderr)
        return 2
    s = build(
        Path(args.manifest),
        Path(args.out),
        allow_calls=not args.offline,
        key_path=Path(args.key) if args.key else None,
        words=bool(getattr(args, "words", False)),
    )
    return 0 if s["idle"] == 0 else 1
