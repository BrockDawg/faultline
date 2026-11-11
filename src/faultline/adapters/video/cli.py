"""faultline-video: judge, replay, roster, compile, scan, shift, report, lifecycle, demo.

faultline-video judge <items.jsonl> --rules <packdir> --out <preds.jsonl> [--words]
    --words also writes Wonder's notes to <out>.words.jsonl
faultline-video replay <preds.jsonl> --out <preds2.jsonl> [--words]
    network off; byte-identical to the judged file(s). The record is read from FAULTLINE_RECORD
    when it is set; otherwise from the preds file's own folder when that folder holds entries/
    (so demo/record/preds.jsonl replays from demo/record); otherwise from <repo>/record
faultline-video roster <preds.jsonl> [--clips-root DIR] [--external-ok]
    every input hash and its file; non-zero on a missing one
faultline-video compile <pack.md|packdir> --out <predicates.json> [--model]
faultline-video scan <video.mp4> --out <events.jsonl> [--start S --end S]
faultline-video shift <manifest.json> --out <shift/> [--key key.json] [--words]
faultline-video shift --replay <shift/> --out <shift2/>
    the forklift demo
faultline-video report honesty|wonder|score|replay
    racing report mode: the honesty card and Wonder's words
faultline-video lifecycle <lifecycle.json> <window>/<rule> <to> --by insurer|site
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from faultline.adapters.video import (
    client,
    gates,
    measure,
    perception,
    record,
    rules,
    vest_read,
    video,
)
from faultline.adapters.video import (
    compile as fcompile,
)
from faultline.adapters.video.video import FPS

LEAK_WORDS = (
    "spotter_ahead",
    "reversing_spotter",
    "loading_dock",
    "two_forklifts",
    "vest_group",
    "no_vest",
    "blind_corner",
    "no_spotter",
    "speeding",
    "collision",
    "near_miss",
    "bump_",
    "scrape",
    "speed_slow",
    "speed_normal",
    "speed_fast",
    "separation_far",
    "separation_close",
    "idle_empty",
    "non_compliant",
    "compliant",
)


def lint(text: str) -> list[str]:
    low = text.lower()
    return [w for w in LEAK_WORDS if w in low]


def _marks_for(csha: str) -> dict | None:
    hm = json.loads((perception.ASSETS / "marks" / "hand_marks.json").read_text(encoding="utf-8"))[
        "clips"
    ]
    return hm.get(csha)


def _unable_all(pack_rules: list[dict], why: str, missing: str) -> list[dict]:
    return [
        {
            "rule": r["id"],
            "verdict": "unable_to_rule",
            "missing_fact": missing,
            "frames": [],
            "evidence": why,
        }
        for r in pack_rules
    ]


def _refuse(pack_rules: list[dict], field: str, why: str) -> list[dict]:
    """Every rule refused by one gate, naming its field; a rule routed out keeps its own refusal."""
    out = []
    for r in pack_rules:
        if r.get("route") == "out":
            out += _unable_all(
                [r],
                f"{r['title']} is not a rule video can judge from this camera; it is routed out.",
                "route:out",
            )
        else:
            out += gates.refusal(field, [r["id"]], why)
    return out


def _posix(p) -> str | None:
    return Path(p).as_posix() if p else None


def load_pack_rules(rules_path: Path) -> list[dict]:
    packs = fcompile.load_rules_dir(rules_path)
    compiled = [r for p in packs for r in fcompile.compile_pack(p)["rules"]]
    texts = {r["id"]: r for p in packs for r in p["rules"]}
    # the rule text and its on-video line ride along for Wonder's words; the judge reads id, route,
    # kind and
    # the compiled predicates
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "route": r["route"],
            "kind": r.get("kind"),
            "predicates": r.get("predicates", []),
            "text": texts.get(r["id"], {}).get("text", ""),
            "on_video": texts.get(r["id"], {}).get("on_video", ""),
        }
        for r in compiled
    ]


EMPTY_NEED = 3  # admitted prompts per subject (pass marks)
PERSON_KINDS = ("hi_vis", "separation")
TRUCK_KINDS = ("spotter", "structure", "speed")


def empty_read(perc, admitted: dict, n_frames: int) -> dict:
    """{subject: {empty, reads}}: a subject is empty when its three admitted prompts each see no
    object on any frame and each reply reports at least the window's frame count processed (ruling
    1). A reply with no frame count, or one short of the window, is never empty."""
    from faultline.adapters.video import sam

    out = {}
    for subject in ("person", "truck"):
        prompts = list(admitted.get(subject) or [])[:EMPTY_NEED]
        reads = []
        if (
            len(prompts) < EMPTY_NEED
        ):  # fewer than three admitted prompts: this subject is never read empty, and not asked
            out[subject] = {"empty": False, "reads": [], "admitted": len(prompts)}
            continue
        for pr in prompts:
            text, meta = perc.empty_track(f"{subject}-{pr.replace(' ', '-')}", pr)
            objs = sam.frames_with_objects(text) if text is not None else None
            reads.append(
                {
                    "prompt": pr,
                    "read": text is not None,
                    "frames_with_objects": None if objs is None else len(objs),
                    "frames_processed": (meta or {}).get("video_frames_processed"),
                }
            )
        empty = len(reads) == EMPTY_NEED and all(
            r["read"] and r["frames_with_objects"] == 0 and (r["frames_processed"] or 0) >= n_frames
            for r in reads
        )
        out[subject] = {"empty": empty, "reads": reads}
    return out


def person_ran(run: dict | None, n_frames: int, start_s: float, end_s: float) -> bool:
    """(Person_run, beside frame counts): the "person" track's own run record shows SAM
    processed at least the window's frames, on a request made over a window that holds this one."""
    if not run:
        return False
    w0, w1 = float(run["window"][0]), float(run["window"][1])
    return (
        w0 <= start_s + 1e-6
        and end_s <= w1 + 1e-6
        and int(run.get("frames_processed") or 0) >= n_frames
    )


def attach_person_run(
    er: dict, run: dict | None, n_frames: int, start_s: float, end_s: float, notes: list[str]
) -> None:
    """The person track's run record goes beside the empty read for the evidence when it covers the
    window, and is set aside otherwise; it never changes er["person"]["empty"] (fix: the empty read
    decides exactly as did, and a fresh window, such as a scorer's, has no run record over it)."""
    if person_ran(run, n_frames, start_s, end_s):
        er["person"]["person_run"] = run
    else:
        er["person"]["person_run_outside"] = run
        notes.append(
            "empty-window read: the person track's run record does not cover the window, so "
            "it is left out of the "
            "evidence (never a precondition)"
        )


def apply_empty(refused: list[dict], pack_rules: list[dict], er: dict, n_frames: int) -> list[dict]:
    """The base's no-truck refusals, with the person rules cleared when people read empty and the
    truck rules cleared when trucks read empty; every other rule keeps its refusal. Never a
    breach."""
    kinds = {
        r["id"]: (r.get("kind") or rules.BY_ID.get(r["id"]))
        for r in pack_rules
        if r.get("route") != "out"
    }
    secs = n_frames / FPS
    run = er["person"].get("person_run") or {}
    ran = (
        f" (the person track's own run record shows {run['frames_processed']} frames processed)"
        if run.get("frames_processed")
        else ""
    )
    out = []
    for r in refused:
        k = kinds.get(r["rule"])
        if r["missing_fact"] == "truck.moving" and k in PERSON_KINDS and er["person"]["empty"]:
            ps = ", ".join(f"'{x['prompt']}'" for x in er["person"]["reads"])
            what = (
                "so no one on foot went without hi-vis"
                if k == "hi_vis"
                else "so no person on foot came near a truck"
            )
            out.append(
                rules._r(
                    r["rule"],
                    "clear",
                    "Nobody was in view on any frame of the window: three person reads "
                    f"({ps}) over all "
                    f"{n_frames} frames ({secs:.1f} s){ran}, with the camera still and the "
                    "whole view in frame, "
                    f"found no one, {what}.",
                )
            )
        elif r["missing_fact"] == "truck.moving" and k in TRUCK_KINDS and er["truck"]["empty"]:
            ts = ", ".join(f"'{x['prompt']}'" for x in er["truck"]["reads"])
            what = {
                "spotter": "so nothing reversed",
                "structure": "so nothing touched a structure",
                "speed": "so nothing was driven",
            }[k]
            out.append(
                rules._r(
                    r["rule"],
                    "clear",
                    "No truck was in view on any frame of the window: three truck reads "
                    f"({ts}) over all "
                    f"{n_frames} frames ({secs:.1f} s), with the camera still and the whole "
                    "view in frame, "
                    f"found none, and no forklift box was found on the frames searched, {what}.",
                )
            )
        else:
            out.append(r)
    return out


def judge_item(
    item: dict,
    pack_rules: list[dict],
    pack_rec: dict,
    site: dict,
    site_sha: str,
    allow_calls: bool,
    replay: dict | None = None,
    host: dict | None = None,
) -> tuple[dict, dict]:
    """One ruling line and its manifest.

    Judging: the clip is read from item["clip"]. Replay (`replay` is the recorded manifest): nothing
    is read from a host path; the clip is known by its recorded sha256, the marks, site and pack
    come from the record's blobs, and pixels come from the recorded pixel facts, so the line is a
    pure function of the record.
    """
    start_s, end_s = float(item.get("start_s", 0.0)), float(item.get("end_s", 0.0))
    if replay is None:
        clip = Path(item["clip"])
        csha = record.sha_file(clip) if clip.is_file() else None
    else:
        clip = None
        csha = replay.get("clip_sha256")
    eid = record.entry_id(csha or "missing", start_s, end_s)
    inputs: dict[str, str] = {
        "constants": record.put_json_blob(record.constants()),
        "rule_constants": record.put_json_blob(record.rule_constants()),
        "site.json": site_sha,
        **record.pack_inputs_from(pack_rec),
    }
    manifest: dict = {
        "entry": eid,
        "item": item,
        "clip_sha256": csha,
        "site_blob": site_sha,
        "pack": pack_rec,
        "constants_blob": inputs["constants"],
        "host_paths": host or (replay or {}).get("host_paths", {}),
        "notes": [],
        "gates": {},
    }

    # gate 5b's floor-rule refusals (set only when the marked camera is low): applied to every line
    # written after the gate, so a floor rule can never be ruled from a low camera
    low: dict = {}

    def done(rl):
        if low:
            rl = [
                gates.refusal("camera.height", [r["rule"]], low["why"])[0]
                if r["rule"] in low["ids"]
                else r
                for r in rl
            ]
        manifest["inputs"] = dict(sorted(inputs.items()))
        return {
            "id": item["id"],
            "entry": eid,
            "rulings": rl,
            "record": record.inputs_hash(inputs),
        }, manifest

    if csha is None:
        return done(
            _unable_all(pack_rules, "The clip file was not found, so nothing was measured.", "clip")
        )
    inputs["clip"] = csha
    perc = perception.Perception(
        clip,
        start_s,
        end_s,
        csha=csha,
        allow_calls=allow_calls and replay is None,
        allow_decode=replay is None,
    )
    g = manifest["gates"]
    # the marks this clip's own bytes carry; a clip with none is matched to a marked camera by its
    # stills (gate 5)
    if replay is None:
        marks = _marks_for(csha)
        direct = marks is not None
    else:
        marks = record.get_json_blob(replay["marks_blob"]) if replay.get("marks_blob") else None
        direct = bool(replay.get("marks_direct"))
    manifest["marks_direct"] = direct
    fp_path = perception.ASSETS / "marks" / "fingerprints.npz"
    gate_key = {
        "window": [f"{start_s:.3f}", f"{end_s:.3f}"],
        "gates": gates.constants(),
        "constants": record.constants(),
        "fingerprints": None if direct else record.sha_file(fp_path),
    }
    if not direct:
        inputs["fingerprints"] = gate_key["fingerprints"]

    def make(grey):
        """Gates 1 to 3 and the camera's stills: the frames alone, before any model call."""
        secs = gates.window_seconds(start_s, end_s, video.probe(clip)["duration"], len(grey))
        cam = {k: v for k, v in measure.camera_static(grey).items() if k != "offsets"}
        view = gates.view_blocks(grey) if len(grey) else None
        out = {
            "window_s": round(secs, 3),
            "frames": int(len(grey)),
            "cuts": gates.shot_cuts(grey),
            "camera": cam,
            "view": ["".join("1" if v else "0" for v in row) for row in view]
            if view is not None
            else None,
            "camera_match": None,
        }
        if not direct and len(grey) >= FPS:
            key, best, top = gates.match_camera(
                gates.fingerprint(grey), view, gates.load_refs(fp_path)
            )
            out["camera_match"] = {"matched": key, "best": round(best, 4), "top": top}
        return out

    try:
        G = perc.gate_facts(gate_key, make)
    except client.ApiError as exc:
        inputs.update(perc.inputs())
        return done(
            _unable_all(
                pack_rules,
                "The window's frames could not be read and no gate facts are recorded for "
                f"it: {exc}",
                "window.covers_second",
            )
        )
    secs = G["window_s"]
    g["window_s"], g["frames"], g["cuts"], g["camera"] = secs, G["frames"], G["cuts"], G["camera"]
    if secs < gates.MIN_WINDOW_S or G["frames"] < FPS:
        g["fired"] = "window.covers_second"
        inputs.update(perc.inputs())
        return done(
            _refuse(
                pack_rules, "window.covers_second", gates.text("window.covers_second", secs=secs)
            )
        )
    cuts = G["cuts"]
    if cuts:
        c = max(cuts, key=lambda x: x["d"])
        g["fired"] = "window.one_shot"
        inputs.update(perc.inputs())
        return done(
            _refuse(
                pack_rules,
                "window.one_shot",
                gates.text("window.one_shot", frame=c["frame"] * 2, d=c["d"], ratio=c["ratio"]),
            )
        )
    cam = G["camera"]
    if cam["static"] is False:
        g["fired"] = "camera.static"
        inputs.update(perc.inputs())
        return done(
            _refuse(
                pack_rules,
                "camera.static",
                gates.text(
                    "camera.static", shift=cam["shift_px"] or 0.0, held=cam["held_frames"] / FPS
                ),
            )
        )
    view = np.array([[ch == "1" for ch in row] for row in G["view"]], dtype=bool)
    g["view_share"] = round(float(view.mean()), 4)
    # a camera matched to no marked camera is refused before the vision model is asked (merge: saves
    # the calls a
    # track would cost on footage no floor plane covers; the refusal names the same field gate 5
    # names)
    if not direct and not (G.get("camera_match") or {}).get("matched"):
        cm = G.get("camera_match") or {"matched": None, "best": 0.0, "top": {}}
        g["camera_match"] = cm
        g["fired"] = "camera.static"
        inputs.update(perc.inputs())
        return done(
            _refuse(
                pack_rules,
                "camera.unmatched",
                gates.text("camera.unmatched", best=cm["best"], line=gates.FP_MATCH),
            )
        )
    # gate 5b: a low camera, read from the camera's four floor marks alone, before any model call.
    # From under LOW_CAMERA_M the truck's lowest outline row is not where it meets the floor, so
    # every rule that reads its floor position is refused; the hi-vis rule reads the torso, goes on
    if replay is None and not direct:
        gate_marks = _marks_for((G.get("camera_match") or {}).get("matched") or "")
    else:
        gate_marks = marks
    low_h = gates.low_camera(gate_marks)
    if low_h is not None and gate_marks is not None:
        g["camera_height"] = {"height_m": round(low_h, 3), "line": gates.LOW_CAMERA_M}
        inputs["camera_height"] = record.put_json_blob(g["camera_height"])
        inputs["marks"] = manifest["marks_blob"] = record.put_json_blob(
            json.loads(record.canon(gate_marks))
        )
        low["why"] = gates.text("camera.height", height=low_h, line=gates.LOW_CAMERA_M)
        live = [r for r in pack_rules if r.get("route") != "out"]
        low["ids"] = {
            r["id"]
            for r in live
            if (r.get("kind") or rules.BY_ID.get(r["id"])) in gates.FLOOR_KINDS
        }
        if all(r["id"] in low["ids"] for r in live):
            g["fired"] = "camera.height"
            inputs.update(perc.inputs())
            return done(_refuse(pack_rules, "camera.height", low["why"]))
    # gate 4: a truck track (the first model call)
    try:
        tm = perc.truck_masks()
        # the box prompt is read for the refusal's words only when the track is short (a judged clip
        # that smoke G's
        # recorded track covers never needed a box, and asking for one would spend a call)
        tb = perc.truck_box() if sum(1 for f in tm if f < G["frames"]) < FPS else None
    except client.BudgetSpent:
        raise
    except client.ApiError as exc:
        inputs.update(perc.inputs())
        return done(
            _unable_all(
                pack_rules,
                "The vision model could not be reached and no recorded masks exist for "
                f"this clip: {exc}",
                "truck.moving",
            )
        )
    n_truck = sum(1 for f in tm if f < G["frames"])
    g["truck_frames"] = n_truck
    if n_truck < FPS:
        why = (
            "the vision model found no forklift on the frames it was shown (one a second, "
            f"up to {perception.MAX_BOX_STEPS})"
            if tb is None
            else f"the vision model tracked a forklift on only {n_truck} frame(s), under a second"
        )
        g["fired"] = "truck.moving"
        refused = _refuse(pack_rules, "truck.moving", gates.text("truck.moving", why=why))
        # (Ruling 1): where no forklift box was found, the camera held still and the whole view is
        # in frame,
        # the empty-window read may clear the person rules (nobody on any frame, three admitted
        # prompts, each reply's own
        # frame count covering the window) and the truck rules (no truck on any frame; never, while
        # fewer than three truck
        # prompts are admitted). run record of the "person" track goes into the evidence where it
        # covers the
        # window; it is never a precondition (fix: a fresh window, such as a scorer's, has no run
        # record over it)
        if tb is None and cam["static"] is True and bool(view.all()):
            try:
                if replay is None:
                    adm = json.loads(
                        (perception.ASSETS / "empty" / "admitted.json").read_text(encoding="utf-8")
                    )["admitted"]
                else:
                    adm = (
                        record.get_json_blob(replay["empty_admitted_blob"])
                        if replay.get("empty_admitted_blob")
                        else None
                    )
                if adm is not None:
                    inputs["empty_admitted"] = manifest["empty_admitted_blob"] = (
                        record.put_json_blob(adm)
                    )
                    er = empty_read(perc, adm, G["frames"])
                    if er["person"]["empty"]:
                        try:
                            run = perc.person_run()
                        except client.BudgetSpent:
                            raise
                        except client.ApiError as exc:
                            run = None
                            manifest["notes"].append(
                                "empty-window read: the person track's run record could "
                                f"not be read: {exc}"
                            )
                        attach_person_run(er, run, G["frames"], start_s, end_s, manifest["notes"])
                    manifest["empty_read"] = er
                    refused = apply_empty(refused, pack_rules, er, G["frames"])
            except client.BudgetSpent:
                raise
            except client.ApiError as exc:
                manifest["notes"].append(f"empty-window read not made: {exc}")
        inputs.update(perc.inputs())
        manifest["notes"] += perc.notes
        return done(refused)
    # gate 5: a marked camera, by its bytes or by its reference stills
    if direct:
        g["camera_match"] = {"matched": csha, "by": "clip bytes"}
    else:
        cm = G.get("camera_match") or {"matched": None, "best": 0.0, "top": {}}
        g["camera_match"] = cm
        if cm["matched"] is None:
            g["fired"] = "camera.static"
            inputs.update(perc.inputs())
            return done(
                _refuse(
                    pack_rules,
                    "camera.unmatched",
                    gates.text("camera.unmatched", best=cm["best"], line=gates.FP_MATCH),
                )
            )
        if replay is None:
            marks = _marks_for(cm["matched"])
        manifest["notes"].append(f"camera matched by reference stills ({cm['best']:.3f})")
    if marks is None:
        manifest["notes"].append("no hand marks for this clip")
        inputs.update(perc.inputs())
        return done(
            _unable_all(
                pack_rules,
                "No floor plane is marked for this camera, so no metre, speed or direction "
                "can be measured; "
                "a site marks four floor points once per camera.",
                "truck.moving",
            )
        )
    marks = json.loads(record.canon(marks))
    inputs["marks"] = manifest["marks_blob"] = record.put_json_blob(marks)
    try:
        ctx = measure.build_context(perc, marks, site)
    except client.BudgetSpent:
        raise
    except client.ApiError as exc:
        inputs.update(perc.inputs())
        return done(
            _unable_all(
                pack_rules,
                "The vision model could not be reached and no recorded masks exist for "
                f"this clip: {exc}",
                "truck.moving",
            )
        )
    ctx["shot_cuts"] = [c["frame"] for c in cuts]
    ctx["view"] = view
    ctx["window_s"] = secs
    manifest["notes"] += perc.notes
    point, draws = measure.ensemble(ctx, site)
    f = rules.fields(ctx, point, draws, site, rules.compiled_lines(pack_rules))
    # (Wonder vest read, scoping): asked only for a person on foot whose colour read is
    # "unknown" and only when the pack has a hi-vis rule; the answers go to the hi-vis rule alone
    # (rules.judge's
    # vest_reads), never into p["vest"], the fact sheet or the ensemble, so no other rule can see
    # them
    vest_reads: dict[str, dict] = {}
    if any(
        (r.get("kind") or rules.BY_ID.get(r["id"])) == "hi_vis" and r.get("route") != "out"
        for r in pack_rules
    ):
        for p in ctx["people"]:
            if p["operator"] or not p["frames_read"] or p.get("vest") != "unknown":
                continue
            try:
                rd = vest_read.read(
                    perc, p["id"], p["frames"], allow_calls=allow_calls and replay is None
                )
            except client.BudgetSpent:
                raise
            except client.ApiError as exc:
                rd = None
                manifest["notes"].append(f"vest read not made for person {p['id']}: {exc}")
            if rd is not None:
                vest_reads[str(p["id"])] = {
                    "agreed": rd["agreed"],
                    "answers": list(rd["answers"]),
                    "src_frames": list(rd["src_frames"]),
                }
    manifest["vest_reads"] = vest_reads
    rl = rules.judge(f, site, pack_rules, ctx, vest_reads=vest_reads)
    for r in rl:
        hits = lint(r["evidence"])
        if hits:
            r["evidence"] = (
                " ".join(w for w in r["evidence"].split() if not lint(w))
                or "Evidence text withheld by the leak lint."
            )
            manifest["notes"].append(f"leak lint cut {hits} from {r['rule']}")
    inputs.update(perc.inputs())
    g["rear_cone_visible"] = f.get("rear_cone_visible")
    manifest["fields"] = _clean(f)
    manifest["perception"] = {
        "truck_frames": len(ctx["truck_frames"]),
        "people": len(ctx["people"]),
        "onsets": ctx["onsets"],
        "drops": ctx.get("drops", []),
        "drops_by_prompt": ctx.get("drops_by_prompt", {}),
        "shot_cuts": ctx["shot_cuts"],
        "camera": ctx["camera"],
        "zone_source": ctx["zone_source"],
    }
    return done(rl)


def _clean(o):
    import math

    if isinstance(o, float):
        return None if not math.isfinite(o) else round(o, 4)
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def _dump(line: dict) -> str:
    return json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n"


def words_path(out: Path) -> Path:
    """The side file Wonder's words go to: <out>.words.jsonl (never the canonical preds)."""
    out = Path(out)
    return out.with_name(
        out.name[: -len(".jsonl")] + ".words.jsonl"
        if out.name.endswith(".jsonl")
        else out.name + ".words.jsonl"
    )


def words_entry(eid: str) -> Path:
    return perception.RECORD / "entries" / f"{eid}.words.json"


def words_line(
    line: dict,
    manifest: dict,
    item: dict,
    pack_rules: list[dict],
    site: dict,
    allow_calls: bool,
    replay: dict | None = None,
) -> tuple[dict, dict]:
    """(Notes and three-run read, OFF unless --words): the words for one judged line, as a side
    line.

    The canonical line and its manifest are never touched: Wonder works on copies, and the side line
    carries the script's verdict beside the note and (where three runs agree on a shipped rule) the
    model's read. Its record hashes the canonical inputs plus every Wonder reply, so `faultline
    replay --words` rebuilds it from the record offline."""
    import copy

    from faultline.adapters.video import wonder

    wl, wm = wonder.annotate(
        copy.deepcopy(line),
        copy.deepcopy(manifest),
        item,
        pack_rules,
        site,
        allow_calls,
        replay=replay,
    )
    side = {
        "id": line["id"],
        "entry": line["entry"],
        "words": True,
        "record": wl["record"],
        "rulings": [
            {
                "rule": r["rule"],
                "verdict": r["verdict"],
                "note": r.get("note"),
                **({"model_read": r["model_read"]} if "model_read" in r else {}),
            }
            for r in wl["rulings"]
        ],
    }
    return side, wm


MEMORY_RETRIES, MEMORY_PAUSE_S = 6, 10.0  # A shared host that refuses memory mid-item is retried


def _retry_memory(fn, what: str):
    """Run fn(); on MemoryError free what can be freed, wait and run it again (the same inputs give
    the same bytes).
    """
    import gc

    for k in range(MEMORY_RETRIES):
        try:
            return fn()
        except MemoryError:
            if k == MEMORY_RETRIES - 1:
                raise
            gc.collect()
            print(
                f"{what}: the host refused memory, retry {k + 1} of {MEMORY_RETRIES - 1}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(MEMORY_PAUSE_S)


def _judge_retrying(fn, offline: bool, what: str):
    """The limit on retry: only a run that can make no model call is retried, because a retry with
    calls allowed could pay again for a reply that had not been recorded when the memory ran out."""
    return _retry_memory(fn, what) if offline else fn()


def cmd_judge(args) -> int:
    items = [
        json.loads(s)
        for s in Path(args.items).read_text(encoding="utf-8").splitlines()
        if s.strip()
    ]
    rules_dir = Path(args.rules)
    pack_rec = record.store_pack(rules_dir)
    pack_rules = load_pack_rules(rules_dir)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    spent0 = client.spent()
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for i, item in enumerate(items):
            site_path = Path(item["site"]) if item.get("site") else perception.ASSETS / "site.json"
            site_sha = record.put_blob(site_path.read_bytes())
            site = json.loads(record.get_blob(site_sha).decode("utf-8"))
            host = {
                "clip": _posix(item.get("clip")),
                "site": _posix(site_path),
                "rules_dir": _posix(rules_dir),
            }
            try:
                line, manifest = _judge_retrying(
                    lambda item=item, site=site, site_sha=site_sha, host=host: judge_item(
                        item,
                        pack_rules,
                        pack_rec,
                        site,
                        site_sha,
                        allow_calls=not args.offline,
                        host=host,
                    ),
                    bool(args.offline),
                    str(item.get("id")),
                )
            except client.BudgetSpent as exc:
                print(f"budget stop: {exc}", file=sys.stderr)
                line, manifest = judge_item(
                    item, pack_rules, pack_rec, site, site_sha, allow_calls=False, host=host
                )
            record.write_entry(line["entry"], manifest)
            fh.write(_dump(line))
            fh.flush()
            v = {r["rule"]: r["verdict"] for r in line["rulings"]}
            print(
                f"{i + 1}/{len(items)} {item['id']}: "
                + ", ".join(
                    f"{k.split('_')[0]}={'B' if x == 'breach' else 'c' if x == 'clear' else '?'}"
                    for k, x in v.items()
                )
                + f"  [{time.monotonic() - t0:.0f}s, ${client.spent() - spent0:.3f}]",
                flush=True,
            )
    print(
        f"wrote {len(items)} rulings to {out}; model spend this run ${client.spent() - spent0:.4f}"
    )
    if getattr(args, "words", False):
        _judge_words(args, out, pack_rules)
    return 0


def _judge_words(args, out: Path, pack_rules: list[dict]) -> None:
    """--words: Wonder's notes and the three-run read for every judged line, to <out>.words.jsonl (a
    side file).
    """
    import concurrent.futures as cf

    spent0 = client.spent()
    lines = [json.loads(s) for s in out.read_text(encoding="utf-8").splitlines() if s.strip()]
    jobs = []
    for line in lines:
        m = record.read_entry(line["entry"])
        site = json.loads(record.get_blob(m["site_blob"]).decode("utf-8"))
        jobs.append((line, m, m["item"], pack_rules, site))

    def one(j):
        line, m, item, pr, site = j
        try:
            return words_line(line, m, item, pr, site, allow_calls=not args.offline)
        except client.BudgetSpent:
            return words_line(line, m, item, pr, site, allow_calls=False)

    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        done = list(ex.map(one, jobs))
    wp = words_path(out)
    with wp.open("w", encoding="utf-8", newline="\n") as fh:
        for side, wm in done:
            words_entry(side["entry"]).write_text(
                json.dumps(wm, indent=1, sort_keys=True, ensure_ascii=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            fh.write(_dump(side))
    rl = [r for side, _ in done for r in side["rulings"]]
    print(
        f"words: notes on {sum(1 for r in rl if r.get('note'))} of {len(rl)} rulings; model "
        "reads shipped on "
        f"{sum(1 for r in rl if 'model_read' in r)}; to {wp}; model spend "
        f"${client.spent() - spent0:.4f}"
    )


def replay_line(old: dict, cache: dict) -> tuple[str, list[str]]:
    """Rebuild one ruling line from its record alone. Returns (the line's bytes, what differs from
    the record).
    """
    m = record.read_entry(old["entry"])
    problems = []
    pack_key = record.canon(m["pack"])
    if pack_key not in cache:
        tmp = Path(tempfile.mkdtemp(prefix="faultline-pack-"))
        try:
            cache[pack_key] = load_pack_rules(record.materialise_pack(m["pack"], tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    site = json.loads(record.get_blob(m["site_blob"]).decode("utf-8"))
    line, manifest = judge_item(
        m["item"], cache[pack_key], m["pack"], site, m["site_blob"], allow_calls=False, replay=m
    )
    changed = sorted(
        k
        for k in set(m["inputs"]) | set(manifest["inputs"])
        if m["inputs"].get(k) != manifest["inputs"].get(k)
    )
    if changed:
        problems.append(f"inputs changed since the record: {changed[:5]}")
    if record.inputs_hash(m["inputs"]) != old["record"]:
        problems.append("the entry's inputs do not hash to the line's record")
    return _dump(line), problems


def replay_record_root(src: Path) -> Path:
    """Where a replay of `src` reads its record: FAULTLINE_RECORD when set, else the preds file's
    own folder when it holds entries/, else the default record root."""
    if os.environ.get("FAULTLINE_RECORD"):
        return perception.RECORD
    here = Path(src).resolve().parent
    return here if (here / "entries").is_dir() else perception.RECORD


def cmd_replay(args) -> int:
    root = replay_record_root(Path(args.src))
    saved = perception.RECORD
    perception.RECORD = root
    try:
        return _replay(args)
    finally:
        perception.RECORD = saved


def _replay(args) -> int:
    src = Path(args.src)
    raw = src.read_bytes().replace(b"\r\n", b"\n")
    lines = [json.loads(s) for s in raw.decode("utf-8").splitlines() if s.strip()]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    same = 0
    cache: dict = {}
    buf = []
    for old in lines:
        s, problems = _retry_memory(
            lambda old=old: replay_line(old, cache), str(old.get("id"))
        )  # replay never calls a model
        for p in problems:
            print(f"{old['id']}: {p}", file=sys.stderr)
        same += s == _dump(old)
        buf.append(s)
    data = "".join(buf).encode("utf-8")
    out.write_bytes(data)
    print(
        f"replayed {len(lines)} rulings to {out}; {same} of {len(lines)} lines identical to "
        f"{src.name}; sha256 {record.sha_bytes(data)}"
    )
    ok = same == len(lines)
    if getattr(args, "words", False):
        ok = _replay_words(src, out, cache) and ok
    return 0 if ok else 1


def _replay_words(src: Path, out: Path, cache: dict) -> bool:
    """Rebuild <src>.words.jsonl from the record alone (no clip, no network) into <out>.words.jsonl
    and compare.
    """
    wsrc, wout = words_path(src), words_path(out)
    olds = [
        json.loads(s)
        for s in wsrc.read_bytes().replace(b"\r\n", b"\n").decode("utf-8").splitlines()
        if s.strip()
    ]
    buf, same = [], 0
    for old in olds:
        m = record.read_entry(old["entry"])
        wm = json.loads(words_entry(old["entry"]).read_text(encoding="utf-8"))
        pack_key = record.canon(m["pack"])
        if pack_key not in cache:
            tmp = Path(tempfile.mkdtemp(prefix="faultline-pack-"))
            try:
                cache[pack_key] = load_pack_rules(record.materialise_pack(m["pack"], tmp))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        site = json.loads(record.get_blob(m["site_blob"]).decode("utf-8"))
        line, manifest = judge_item(
            m["item"], cache[pack_key], m["pack"], site, m["site_blob"], allow_calls=False, replay=m
        )
        side, _ = words_line(
            line, manifest, m["item"], cache[pack_key], site, allow_calls=False, replay=wm
        )
        s = _dump(side)
        same += s == _dump(old)
        buf.append(s)
    data = "".join(buf).encode("utf-8")
    wout.write_bytes(data)
    print(
        f"replayed {len(olds)} words lines to {wout}; {same} of {len(olds)} identical to "
        f"{wsrc.name}; sha256 {record.sha_bytes(data)}"
    )
    return same == len(olds)


def roster_rows(preds: Path, clips_root: Path | None) -> list[dict]:
    """Every input hash the records name, with the file it came from and whether that file still
    hashes to it.
    """
    raw = Path(preds).read_bytes().replace(b"\r\n", b"\n")
    rows = []
    for s in raw.decode("utf-8").splitlines():
        if not s.strip():
            continue
        line = json.loads(s)
        ep = (
            perception.RECORD
            / "entries"
            / (f"{line['entry']}.words.json" if line.get("words") else f"{line['entry']}.json")
        )
        if not ep.is_file():
            rows.append(
                {
                    "id": line["id"],
                    "name": "entry",
                    "sha256": line["record"],
                    "file": ep,
                    "status": "missing",
                }
            )
            continue
        m = json.loads(ep.read_text(encoding="utf-8"))
        rows.append(
            {
                "id": line["id"],
                "name": "record",
                "sha256": line["record"],
                "file": ep,
                "status": "ok" if record.inputs_hash(m["inputs"]) == line["record"] else "mismatch",
            }
        )
        for name, h in sorted(m["inputs"].items()):
            rows.append(
                {"id": line["id"], "name": name, "sha256": h, **_resolve(name, h, m, clips_root)}
            )
    return rows


def _resolve(name: str, h: str, m: dict, clips_root: Path | None) -> dict:
    if name in (
        "constants",
        "rule_constants",
        "site.json",
        "marks",
        "wonder/ship",
    ) or name.startswith("pack/"):
        p = record.blob_dir() / h
        if not p.is_file():
            return {"file": p, "status": "missing"}
        return {"file": p, "status": "ok" if record.sha_norm_blob(p) == h else "mismatch"}
    if (
        name == "fingerprints"
    ):  # the gate's marked-camera fingerprints ship in assets, hashed as raw bytes
        p = perception.ASSETS / "marks" / "fingerprints.npz"
        if not p.is_file():
            return {"file": p, "status": "missing"}
        return {"file": p, "status": "ok" if record.sha_file(p) == h else "mismatch"}
    if name == "frames":
        for k in m["inputs"]:
            if k.startswith("clips/") and "/pixels/" in k:
                p = perception.RECORD.joinpath(*k.split("/"))
                if (
                    p.is_file()
                    and json.loads(p.read_text(encoding="utf-8")).get("frames_sha256") == h
                ):
                    return {"file": p, "status": "ok"}
                return {"file": p, "status": "mismatch" if p.is_file() else "missing"}
        return {"file": None, "status": "missing"}
    if name == "clip":
        cands = []
        hp = (m.get("host_paths") or {}).get("clip") or m["item"].get("clip")
        if hp:
            cands.append(Path(hp))
        if clips_root is not None and hp:
            parts = hp.replace("\\", "/").split("/")
            cands += [clips_root.joinpath(*parts[i:]) for i in range(1, len(parts))]
        for p in cands:
            if p.is_file():
                return {"file": p, "status": "ok" if record.sha_file(p) == h else "mismatch"}
        return {"file": cands[0] if cands else None, "status": "missing"}
    p = perception.RECORD.joinpath(*name.split("/"))
    if not p.is_file():
        return {"file": p, "status": "missing"}
    return {"file": p, "status": "ok" if record.sha_norm(p) == h else "mismatch"}


def cmd_roster(args) -> int:
    rows = roster_rows(Path(args.preds), Path(args.clips_root) if args.clips_root else None)
    uniq: dict[tuple[str, str], dict] = {}
    for r in rows:
        k = (r["name"] if r["name"] != "record" else r["id"], r["sha256"])
        uniq.setdefault(k, {**r, "ids": []})["ids"].append(r["id"])
    bad = 0
    ext = 0
    for (_, h), r in sorted(uniq.items(), key=lambda kv: (kv[1]["name"], kv[0][1])):
        status = r["status"]
        if status == "missing" and r["name"] == "clip" and args.external_ok:
            status = "external"
            ext += 1
        elif status != "ok":
            bad += 1
        f = r["file"]
        try:
            shown = (
                Path(f).resolve().relative_to(perception.RECORD.parent.resolve()).as_posix()
                if f
                else "-"
            )
        except ValueError:
            shown = Path(f).as_posix()
        n = len(r["ids"])
        print(f"{h}  {status:8}  {r['name']:58}  {shown}  ({n} ruling{'s' if n != 1 else ''})")
    print(
        f"roster: {len(uniq)} distinct inputs over {len({r['id'] for r in rows})} rulings; "
        f"{bad} with no file or a wrong hash"
        + (f"; {ext} clip(s) external to this host, not checked" if ext else "")
    )
    return 1 if bad else 0


def cmd_compile(args) -> int:
    packs = fcompile.load_rules_dir(Path(args.pack))
    rec = perception.RECORD / "compile"
    if args.model:
        allr = [r for p in packs for r in p["rules"]]
        try:
            fcompile.ask_model(allr, rec)
        except (client.ApiError, client.BudgetSpent) as exc:
            print(f"model seat stopped: {exc}", file=sys.stderr)
    docs = [fcompile.compile_pack(p, use_model=False, record_dir=rec) for p in packs]
    doc = (
        docs[0]
        if len(docs) == 1
        else {
            "packs": docs,
            "vocabulary": rules.VOCAB,
            "rules": [{**r, "pack": d["pack"]} for d in docs for r in d["rules"]],
        }
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    rows = [r for d in docs for r in d["rules"]]
    routes: dict[str, int] = {}
    for r in rows:
        routes[r["route"]] = routes.get(r["route"], 0) + 1
    agree = {n: sum(1 for r in rows if r["agreement"] == n) for n in range(fcompile.RUNS, -1, -1)}
    shipped = sum(1 for r in rows if "model" in r)
    differ = sorted({r["id"] for r in rows if "model" in r and not r["model"]["agrees_with_key"]})
    print(
        f"compiled {len(rows)} rules: routes {routes}; model agreement (runs agreeing: "
        f"rules) {agree}; "
        f"model predicates shipped {shipped}; shipped but differing from the route key: "
        f"{differ or 'none'}; "
        "0 fields outside the vocabulary, 0 unspanned numbers, 0 bait (checked per row)"
    )
    if args.verbose:
        for r in rows:
            print(
                f"  {r['id']:32s} {r['route']:6s} agree {r['agreement']}/{r['runs']}"
                + (
                    f"  model {r['model']['route']}"
                    f"{'' if r['model']['agrees_with_key'] else ' (differs from key)'}"
                    if "model" in r
                    else ""
                )
            )
    return 0


def _scan_roi(value: str) -> tuple[int, int, int, int]:
    try:
        roi = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ROI must be x,y,width,height in source pixels") from exc
    if len(roi) != 4 or any(part < 0 for part in roi) or roi[2] < 2 or roi[3] < 2:
        raise argparse.ArgumentTypeError("ROI must be x,y,width,height in source pixels")
    return roi


def _encode_scan_roi(
    source: Path, start_s: float, end_s: float, roi: tuple[int, int, int, int], out: Path
) -> bytes:
    """Encode one selected review window and its caller-selected replay pane for SAM."""
    info = video.probe(source)
    x, y, width, height = roi
    if x + width > info["width"] or y + height > info["height"]:
        raise ValueError(
            f"ROI {roi} is outside the {info['width']}x{info['height']} source-video frame."
        )
    scale = min(video.W / width, video.H / height)
    scaled_w = max(2, int(round(width * scale / 2)) * 2)
    scaled_h = max(2, int(round(height * scale / 2)) * 2)
    pad_x, pad_y = (video.W - scaled_w) // 2, (video.H - scaled_h) // 2
    vf = (
        f"crop={width}:{height}:{x}:{y},scale={scaled_w}:{scaled_h},"
        f"pad={video.W}:{video.H}:{pad_x}:{pad_y},fps={FPS}"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            f"{start_s:.3f}",
            "-t",
            f"{max(0.05, end_s - start_s):.3f}",
            "-i",
            str(source),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    return out.read_bytes()


def _source_sha256(path: Path) -> str:
    with path.open("rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def _scan_telemetry(args) -> list[dict]:
    """Read supporting feed events without letting them choose a visual candidate."""
    if args.feed is None and args.session is None:
        return []
    if args.feed is None or args.session is None:
        raise ValueError("--feed and --session must be provided together.")
    from dataclasses import asdict

    from faultline.adapters.pitbot.events import all_events
    from faultline.adapters.pitbot.feed import Feed

    result = []
    for event in all_events(Feed.load(args.feed, args.session)):
        item = asdict(event)
        item["feed_time_s"] = item["te_lo"]
        item["t_s"] = round(item["te_lo"] + args.telemetry_offset_s, 3)
        item["source"] = "PitBot feed event; supporting context only"
        result.append(item)
    return result


def _legacy_scan_fields(windows: list[dict], spikes: list[dict], source_hash: str) -> None:
    """Keep the old point-candidate fields on every grouped JSONL record."""
    for window in windows:
        matching = [
            spike
            for spike in spikes
            if float(window["start_s"]) <= float(spike["t_s"]) <= float(window["end_s"])
        ]
        if matching:
            strongest = max(
                matching,
                key=lambda spike: (
                    float((spike.get("motion") or {}).get("z_score", 0.0)),
                    -float(spike["t_s"]),
                ),
            )
            for name in ("t_s", "frames", "evidence"):
                if name in strongest:
                    window[name] = strongest[name]
        window["source_video_sha256"] = source_hash


def _attach_scan_telemetry(args, windows: list[dict]) -> list[dict]:
    """Attach optional telemetry without allowing a feed failure to stop video review."""
    try:
        from faultline.adapters.video.review_windows import annotate_telemetry

        return annotate_telemetry(windows, _scan_telemetry(args))
    except Exception as exc:  # telemetry is contextual; an unreadable feed must not hide video
        message = f"telemetry was not attached: {type(exc).__name__}: {exc}"
        for window in windows:
            window["telemetry_context"] = {
                "events": [],
                "error": message,
                "meaning": (
                    "Telemetry is supporting context only; video candidate order is unchanged."
                ),
            }
        print(f"scan note: {message}", file=sys.stderr)
        return windows


def _refine_scan_window(args, windows: list[dict]) -> dict | None:
    """Run SAM only for the one window, ROI, and paid call the steward selected."""
    if not args.sam_refine:
        return None
    if args.candidate is None or args.roi is None:
        raise ValueError("--sam-refine requires both --candidate N and --roi x,y,width,height.")
    if not args.confirm:
        raise ValueError(
            "--sam-refine makes a paid SAM call; pass --confirm after reviewing its cost."
        )
    if not 0 <= args.candidate < len(windows):
        raise ValueError(f"--candidate must name one of 0 through {len(windows) - 1}.")

    chosen = windows[args.candidate]
    start_s, end_s = float(chosen["start_s"]), float(chosen["end_s"])
    frames_hint = max(1, int(math.ceil((end_s - start_s) * FPS)))
    reserved_usd = max(client.SAM_MIN_FRAMES, 2 * frames_hint) * client.SAM_FRAME_USD
    remaining_usd = client.cap_usd() - client.spent(client.WAVE_START_TS)
    print(
        "SAM refinement preflight: "
        f"window {args.candidate}, {frames_hint} frame hint, reserves ${reserved_usd:.4f}; "
        f"${remaining_usd:.4f} remains under the local cap."
    )
    if reserved_usd > remaining_usd:
        raise client.BudgetSpent(
            f"SAM refinement would reserve ${reserved_usd:.4f}, above the ${remaining_usd:.4f} "
            "remaining local cap; no model call is made."
        )

    source = Path(args.video)
    source_hash = _source_sha256(source)
    with tempfile.TemporaryDirectory(prefix="faultline-scan-sam-") as temp:
        encoded = _encode_scan_roi(source, start_s, end_s, args.roi, Path(temp) / "review.mp4")
    result = client.sam_video(
        encoded,
        args.sam_prompt,
        tag=f"racing-review-window:{source_hash[:12]}:{args.candidate}",
        frames_hint=frames_hint,
    )
    reply = result["text"]
    reply_path = Path(args.out).with_suffix(".sam.txt")
    reply_path.write_text(reply, encoding="utf-8", newline="\n")
    from faultline.adapters.pitbot.moment_candidates import rank_moments
    from faultline.adapters.video import sam

    cache_dir = Path(args.out).parent / f"{Path(args.out).stem}.sam-cache"
    candidates = rank_moments(
        sam.track_stats(reply, cache_dir),
        sam.mask_crops(reply, cache_dir),
        frame_count=frames_hint,
    )
    for candidate in candidates:
        candidate["source_time_s"] = round(start_s + candidate["clip_time_s"], 3)
        candidate["review_source_time_range_s"] = [
            round(start_s + frame / FPS, 3) for frame in candidate["review_frame_range"]
        ]
        candidate["review_frame_times_source_s"] = [
            round(start_s + time_s, 3) for time_s in candidate.pop("review_frame_times_s")
        ]
    return {
        "meaning": (
            "SAM mask motion is a follow-up search hint for this steward-selected replay pane; "
            "it is not a contact finding or a verdict."
        ),
        "candidate_index": args.candidate,
        "source_video_sha256": source_hash,
        "window_s": [round(start_s, 3), round(end_s, 3)],
        "roi_xywh": list(args.roi),
        "prompt": args.sam_prompt,
        "reserved_usd": round(reserved_usd, 6),
        "estimated_usd": result.get("est_usd"),
        "frames_processed": (result.get("usage") or {}).get("video_frames_processed"),
        "cache": result.get("cache"),
        "reply": str(reply_path),
        "reply_sha256": hashlib.sha256(reply.encode("utf-8")).hexdigest(),
        "candidates": candidates,
    }


def cmd_scan(args) -> int:
    from faultline.adapters.video.racing import scan
    from faultline.adapters.video.review_gate import assess_window
    from faultline.adapters.video.review_windows import build_windows

    source = Path(args.video)
    info = video.probe(source)
    end_s = args.end if args.end is not None else info.get("duration")
    if end_s is None or end_s <= args.start:
        print("scan needs a readable, positive video range.", file=sys.stderr)
        return 2
    if args.before_s < 0 or args.after_s < 0:
        print("scan refused: --before-s and --after-s must be non-negative.", file=sys.stderr)
        return 2
    spikes = scan(source, args.start, end_s)
    windows = build_windows(
        spikes,
        start_s=args.start,
        end_s=end_s,
        before_s=args.before_s,
        after_s=args.after_s,
    )
    try:
        _legacy_scan_fields(windows, spikes, _source_sha256(source))
    except OSError as exc:
        print(f"scan refused: {exc}", file=sys.stderr)
        return 2
    windows = _attach_scan_telemetry(args, windows)
    try:
        refinement = _refine_scan_window(args, windows)
    except (ValueError, client.ApiError, client.BudgetSpent, OSError) as exc:
        print(f"scan refused: {exc}", file=sys.stderr)
        return 2
    if refinement is not None:
        windows[args.candidate]["sam_refinement"] = refinement
    for window in windows:
        assessment = assess_window(window, video_duration_s=end_s)
        window["reviewability"] = {
            "disposition": assessment["disposition"],
            "reason": assessment["reason"],
            "explanation": assessment["explanation"],
        }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for window in windows:
            fh.write(json.dumps(window, sort_keys=True) + "\n")
    counts = {
        status: sum(window["reviewability"]["disposition"] == status for window in windows)
        for status in ("accept_for_review", "insufficient", "reject")
    }
    print(
        f"{len(windows)} video-only review window(s) to {out}; "
        f"{counts['accept_for_review']} eligible for review, "
        f"{counts['insufficient']} insufficient, {counts['reject']} invalid; no verdict"
    )
    return 0


def cmd_review_gate(args) -> int:
    from faultline.adapters.video.review_gate import gate_document

    source = Path(args.candidates)
    out = Path(args.out)
    try:
        if source.resolve() == out.resolve():
            print("review-gate refused: input and output paths must differ", file=sys.stderr)
            return 2
        windows = [
            json.loads(line)
            for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        print(f"review-gate refused: {exc}", file=sys.stderr)
        return 2
    if any(not isinstance(window, dict) for window in windows):
        print("review-gate refused: each JSONL line must be an object", file=sys.stderr)
        return 2
    document = gate_document(windows, video_duration_s=args.duration_s)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    counts = document["counts"]
    print(
        "review-gate: "
        f"{counts['accept_for_review']} eligible for review, "
        f"{counts['insufficient']} insufficient, {counts['reject']} invalid; no verdict"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "report":
        print(
            "faultline: racing report mode reads a league's own records and is not part of "
            "this tree",
            file=sys.stderr,
        )
        return 2
    ap = argparse.ArgumentParser(prog="faultline-video")
    sub = ap.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("judge")
    j.add_argument("items")
    j.add_argument("--rules", required=True)
    j.add_argument("--out", required=True)
    j.add_argument(
        "--offline", action="store_true", help="never call a model; rule from the record only"
    )
    j.add_argument(
        "--words",
        action="store_true",
        help="also write Wonder's notes and the three-run read to <out>.words.jsonl "
        "(off by default: without it judge makes no Wonder or Spark Open call)",
    )
    j.set_defaults(fn=cmd_judge)
    r = sub.add_parser("replay")
    r.add_argument("src")
    r.add_argument("--out", required=True)
    r.add_argument(
        "--words",
        action="store_true",
        help="also rebuild <src>.words.jsonl offline into <out>.words.jsonl",
    )
    r.set_defaults(fn=cmd_replay)
    ro = sub.add_parser(
        "roster",
        help="every input hash the records name, with the file it came from; fails on a hash "
        "with no file",
    )
    ro.add_argument("preds")
    ro.add_argument(
        "--clips-root",
        default=None,
        help="look for clips under this folder too (a container's mount)",
    )
    ro.add_argument(
        "--external-ok",
        action="store_true",
        help="a clip not on this host is listed as external, not a failure",
    )
    ro.set_defaults(fn=cmd_roster)
    sh = sub.add_parser(
        "shift", help="the forklift demo: a manifest of clips into windows, rulings and a dashboard"
    )
    sh.add_argument("manifest", nargs="?")
    sh.add_argument("--out", required=True)
    sh.add_argument(
        "--key",
        default=None,
        help="a reviewed key.json; the dashboard shows each window's reviewed label",
    )
    sh.add_argument(
        "--offline", action="store_true", help="never call a model; rule from the record only"
    )
    sh.add_argument(
        "--replay",
        default=None,
        metavar="SHIFT_DIR",
        help="rebuild a shift offline and compare every file",
    )
    sh.add_argument(
        "--words",
        action="store_true",
        help="also write the recorded notes beside each ruling to preds.words.jsonl "
        "and show them on the dashboard (from the record; no model call)",
    )
    sh.set_defaults(
        fn=lambda a: __import__("faultline.adapters.video.shift", fromlist=["cmd"]).cmd(a)
    )
    lc = sub.add_parser(
        "lifecycle",
        help="move one ruling of a shift: identified, confirmed or denied, disputed, final",
    )
    lc.add_argument("file")
    lc.add_argument("ruling", nargs="?")
    lc.add_argument("to", nargs="?")
    lc.add_argument("--by", choices=["insurer", "site"])
    lc.add_argument("--note", default="")
    lc.add_argument("--show", action="store_true")
    lc.set_defaults(
        fn=lambda a: __import__("faultline.adapters.video.lifecycle", fromlist=["cmd"]).cmd(a)
    )
    dm = sub.add_parser(
        "demo",
        help="the three-minute walk: one page from the smoke and the shift, or one still per "
        "script line",
    )
    dm.add_argument(
        "--smoke", default=None, help="a smoke folder holding preds.jsonl and replay.jsonl"
    )
    dm.add_argument(
        "--shift",
        default=None,
        help="a shift folder built with --words (windows, preds, frames, notes)",
    )
    dm.add_argument("--rules", default=None, help="the rules pack as the site wrote it")
    dm.add_argument(
        "--stills",
        default=None,
        metavar="SCRIPT_MD",
        help="render one PNG per script line from --page into --out",
    )
    dm.add_argument("--page", default=None)
    dm.add_argument("--out", required=True)
    dm.set_defaults(
        fn=lambda a: __import__("faultline.adapters.video.demo", fromlist=["cmd"]).cmd(a)
    )
    bd = sub.add_parser(
        "bundle", help="the live page's data: index, one file per clip and the shift, as JSON"
    )
    bd.add_argument("--sources", required=True, help="the sources.json naming every record root")
    bd.add_argument("--out", required=True, help="the bundle folder (site/data)")
    bd.set_defaults(
        fn=lambda a: __import__("faultline.adapters.video.bundle", fromlist=["cmd"]).cmd(a)
    )
    c = sub.add_parser("compile")
    c.add_argument("pack")
    c.add_argument("--out", required=True)
    c.add_argument(
        "--model",
        action="store_true",
        help="also ask Spark Open, three runs, ship only on agreement",
    )
    c.add_argument(
        "--verbose", action="store_true", help="print the route and agreement count of every rule"
    )
    c.set_defaults(fn=cmd_compile)
    s = sub.add_parser("scan")
    s.add_argument("video")
    s.add_argument("--out", required=True)
    s.add_argument("--start", type=float, default=0.0)
    s.add_argument("--end", type=float, default=None)
    s.add_argument(
        "--before-s",
        type=float,
        default=3.0,
        help="seconds of footage before each grouped visual spike (default: 3)",
    )
    s.add_argument(
        "--after-s",
        type=float,
        default=3.0,
        help="seconds of footage after each grouped visual spike (default: 3)",
    )
    s.add_argument("--feed", type=Path, help="optional PitBot feed JSONL for context only")
    s.add_argument("--session", help="feed session name, required with --feed")
    s.add_argument(
        "--telemetry-offset-s",
        type=float,
        default=0.0,
        help="add this offset to feed seconds before attaching context (default: 0)",
    )
    s.add_argument(
        "--sam-refine",
        action="store_true",
        help="run one paid SAM mask-motion follow-up for a selected review window",
    )
    s.add_argument(
        "--candidate",
        type=int,
        help="zero-based visual review-window index for --sam-refine",
    )
    s.add_argument(
        "--roi",
        type=_scan_roi,
        help="replay-view ROI as x,y,width,height in source pixels for --sam-refine",
    )
    s.add_argument(
        "--sam-prompt",
        default="race car",
        help="SAM object prompt for --sam-refine (default: race car)",
    )
    s.add_argument(
        "--confirm",
        action="store_true",
        help="authorize the single paid SAM request requested by --sam-refine",
    )
    s.set_defaults(fn=cmd_scan)
    g = sub.add_parser(
        "review-gate",
        help="classify existing review windows for reviewability; never decide an incident",
    )
    g.add_argument(
        "candidates",
        help="JSONL review-window candidates, such as faultline-video scan output",
    )
    g.add_argument("--out", required=True, help="write the reviewability results here")
    g.add_argument(
        "--duration-s",
        type=float,
        default=None,
        help="source video duration; candidates extending beyond it are rejected as invalid",
    )
    g.set_defaults(fn=cmd_review_gate)
    args = ap.parse_args(argv)
    os.environ.setdefault("PYTHONHASHSEED", "0")
    return args.fn(args)
