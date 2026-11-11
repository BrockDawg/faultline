"""The verdict seat: compiled predicates over the fact sheet. A field the sheet could not measure is
"unable to rule".

Every rule reads the closed field vocabulary only. A band is proven when AGREE of the ensemble draws
agree; a band that straddles its line is the missing fact. The evidence text is written by script
from the measured numbers, in fixed wording, so a replay writes the same bytes.
"""

from __future__ import annotations

import math

from faultline.adapters.video import gates as gatemod
from faultline.adapters.video import measure
from faultline.adapters.video.video import FPS, SRC_FPS

VOCAB = [
    "truck.moving",
    "truck.speed_mps",
    "truck.reversing",
    "truck.direction",
    "truck.front_in_strip",
    "person.on_foot",
    "person.vested",
    "person.distance_m",
    "person.in_rear_cone",
    "person.still",
    "person.in_dock_zone",
    "contact.consequence",
    "camera.static",
    "window.one_shot",
    "window.covers_second",
]
GRADED = [
    "hi_vis_in_truck_zone",
    "spotter_when_reversing",
    "pedestrian_separation",
    "structure_contact",
    "site_speed_limit",
]

# rulings 2 and 6 (Brock, 30 Oct 2026): the words every structure-contact ruling that lacks
# contact.consequence opens with
NO_CONSEQUENCE = "Touch not provable from this camera; no consequence seen."

# the measuring seat per rule id, used when a compiled rule carries no kind of its own
BY_ID = {
    "hi_vis_in_truck_zone": "hi_vis",
    "spotter_when_reversing": "spotter",
    "pedestrian_separation": "separation",
    "structure_contact": "structure",
    "site_speed_limit": "speed",
}


# the site key each measured line is read against when no compiled predicate names one
DEFAULT_LINES = {
    "person.distance_m": "pedestrian_separation_m",
    "truck.speed_mps": "speed_limit_mps",
}


def compiled_lines(pack_rules: list[dict]) -> dict[str, str]:
    """{field: site key} for every `line` threshold a compiled window predicate names.

    The judge reads the separation and speed lines from here, so the compiled pack, not a constant
    in this file, says which site value a distance or a speed is banded against; a field no compiled
    predicate names keeps its default.
    An explicit site value ({site, explicit}) names its key the same way a spanned one does."""
    out = dict(DEFAULT_LINES)
    for r in pack_rules:
        if r.get("route") != "window":
            continue
        for p in r.get("predicates") or []:
            for c in p.get("all", []):
                ln = c.get("line")
                if (
                    c.get("field") in DEFAULT_LINES
                    and isinstance(ln, dict)
                    and isinstance(ln.get("site"), str)
                ):
                    out[c["field"]] = ln["site"]
    return out


def src_frames(frames12: list[int]) -> list[int]:
    """12 fps measuring frames to the clip's own 24 fps frame indexes."""
    return sorted({int(f) * (SRC_FPS // FPS) for f in frames12})


def share(draws: list[dict], pred) -> float:
    return sum(1 for d in draws if pred(d)) / max(1, len(draws))


def band(point_value, draws_values, line: float) -> str:
    """'over', 'under' or 'straddles' the line, by the ensemble."""
    vals = [v for v in draws_values if v is not None and math.isfinite(v)]
    if not vals or point_value is None or not math.isfinite(point_value):
        return "unmeasured"
    over = sum(v > line for v in vals) / len(vals)
    if over >= measure.AGREE:
        return "over"
    if 1 - over >= measure.AGREE:
        return "under"
    return "straddles"


def fields(
    ctx: dict, point: dict, draws: list[dict], site: dict, lines: dict[str, str] | None = None
) -> dict:
    """The fact sheet in the closed vocabulary, every value banded (against the compiled lines, see
    compiled_lines).
    """
    lines = {**DEFAULT_LINES, **(lines or {})}
    SEP, LIMIT = site[lines["person.distance_m"]], site[lines["truck.speed_mps"]]
    n = ctx["n_frames"]
    one_shot = not ctx["shot_cuts"]
    f: dict = {
        "window.one_shot": one_shot,
        "window.covers_second": n >= FPS and ctx.get("window_s", n / FPS) >= gatemod.MIN_WINDOW_S,
        "camera.static": None
        if ctx["camera"]["static"] is None
        else ctx["camera"]["static"] is not False,
        "camera.held_frames": ctx["camera"].get("held_frames"),
        "camera.partial": ctx["camera"]["static"] == "held",
        "camera.compensated": ctx["camera"]["static"] == "compensated",
        "camera.shift_px": ctx["camera"].get("shift_px"),
        "truck.present": bool(point["truck"]),
    }
    f["rear_cone_visible"] = point.get("cone_visible")
    if point["truck"]:
        f["truck.moving"] = {
            "moving_frames": point["moving_frames"],
            "stopped_frames": point.get("stopped_frames", 0),
            "unknown_frames": len(ctx["truck_frames"])
            - point["moving_frames"]
            - point.get("stopped_frames", 0),
            "truck_frames": len(ctx["truck_frames"]),
            "cut_frames": point.get("cut_frames", 0),
            "cut_unread_frames": point.get("cut_unread", 0),
        }
        pk = [d.get("peak_speed") for d in draws]
        f["truck.speed_mps"] = {
            "peak": point["peak_speed"],
            "interval": measure.interval(pk),
            "band": band(point["peak_speed"], pk, LIMIT),
            "limit": LIMIT,
            "line_key": lines["truck.speed_mps"],
        }
        f["truck.direction"] = {
            "known": point["fork_known"],
            "forward_frames": point["forward_frames"],
            "reversing_frames": point["reversing_frames"],
            "unknown_moving_frames": point["direction_unknown_moving"],
        }
        rev_share = share(draws, lambda d: d["reversing_frames"] >= FPS)
        f["truck.reversing"] = {
            "point": point["reversing_frames"] >= FPS,
            "share": rev_share,
            "runs": point["rev_runs"],
            "band": "yes"
            if rev_share >= measure.AGREE
            else ("no" if rev_share <= 1 - measure.AGREE else "straddles"),
            # ruling 4: the reverse read across an edge-cut footpoint, and the share that stands on
            # uncut reads
            "cut_frames": list(point.get("rev_cut_frames", [])),
            "clean_share": share(
                draws, lambda d: d.get("rev_clean_frames", d["reversing_frames"]) >= FPS
            ),
        }
        s = point["structure"]
        f["truck.front_in_strip"] = {
            "marked": len(ctx["structures"]),
            "zone_source": ctx["zone_source"],
            "longest_run": s["longest_run"] if s else 0,
            "first_run_frame": s["first_run_frame"] if s else None,
            "min_front_dist": s["min_front_dist"] if s else None,
            "run_share": share(
                draws,
                lambda d: (
                    bool(d["structure"])
                    and d["structure"]["longest_run"] >= site["structure_run_frames"]
                ),
            ),
            "structure": s["name"] if s else None,
        }
        docks = ctx.get("dock_faces", [])
        pairs = measure.contact_pairs(point, ctx["onsets"], site, docks)
        f["contact.consequence"] = {
            "onsets": ctx["onsets"],
            "pairs": pairs,
            "dock_faces": docks,
            "pair_share": share(
                draws, lambda d: bool(measure.contact_pairs(d, ctx["onsets"], site, docks))
            ),
        }
    people = []
    for i, p in enumerate(ctx["people"]):
        pp = point["people"][i] if i < len(point["people"]) else {"frames": 0}
        dmv = [
            next((q.get("min_dist_moving") for q in d["people"] if q["id"] == p["id"]), None)
            for d in draws
        ]
        dmv = [v for v in dmv if v is not None]
        row = {
            "id": p["id"],
            "on_foot": not p["operator"],
            "operator_share": p["operator_share"],
            "frames": pp.get("frames", 0),
            "vested": p["vest"],
            "vest_share": {k: round(v, 3) for k, v in p["vest_share"].items()},
            "frames_read": p["frames_read"],
            "still": pp.get("span_m") is not None and pp["span_m"] < measure.STILL_M,
            "span_m": pp.get("span_m"),
            "in_rear_cone_share": pp.get("cone_share"),
            "distance_m": {
                "min_moving": pp.get("min_dist_moving"),
                "min_any": pp.get("min_dist_all"),
                "frame_min": pp.get("frame_min"),
                "interval_moving": measure.interval(dmv),
                "band": band(pp.get("min_dist_moving"), dmv, SEP)
                if pp.get("frames")
                else "unmeasured",
                "line": SEP,
                "close_unknown_frames": pp.get("close_unknown_frames", 0),
                "close_exempt_frames": pp.get("close_exempt_frames", 0),
                "close_unknown_cut": pp.get("close_unknown_cut", 0),
                "close_unknown_dock": pp.get("close_unknown_dock", 0),
                "dock_frames": pp.get("dock_frames", 0),
            },
        }
        people.append(row)
    f["people"] = people
    f["person.on_foot"] = [p["id"] for p in people if p["on_foot"] and p["frames"]]
    return f


def _r(
    rule: str, verdict: str, text: str, frames: list[int] | None = None, missing: str | None = None
) -> dict:
    text = " ".join(text.split())
    if len(text) < 40:
        text = (text + " Measured by script from the recorded masks and the clip's frames.").strip()
    return {
        "rule": rule,
        "verdict": verdict,
        "missing_fact": missing if verdict == "unable_to_rule" else None,
        "frames": src_frames(frames or []),
        "evidence": text[:600],
    }


def gates(f: dict) -> dict | None:
    """A window the camera or the cut makes unjudgeable: the rule is not ruled, naming the gate."""
    if not f["window.covers_second"]:
        return _r(
            "",
            "unable_to_rule",
            "The window is under a second, so no one-second speed or state can be measured.",
            missing="window.covers_second",
        )
    if not f["window.one_shot"]:
        return _r(
            "",
            "unable_to_rule",
            "The window holds a shot cut, so one measurement cannot follow the truck across it.",
            missing="window.one_shot",
        )
    if f["camera.static"] is False:
        return _r(
            "",
            "unable_to_rule",
            "The camera moved; this judge reads fixed site cameras, so the floor plane "
            "marked for a still camera does not hold.",
            missing="camera.static",
        )
    return None


def _weak_state(f: dict) -> bool:
    """The moving state is unread on more than half the truck's frames, so 'never reversed' rests on
    the frames that were read; that clear stands unless the rear cone is also cropped out of view
    (then a reverse and its spotter are both unseen)."""
    m = f["truck.moving"]
    return m["truck_frames"] >= FPS and m["unknown_frames"] * 2 > m["truck_frames"]


def _pdesc(p: dict) -> str:
    return f"person {p['id']}"


def judge(
    f: dict, site: dict, pack_rules: list[dict], ctx: dict, vest_reads: dict | None = None
) -> list[dict]:
    """One ruling per rule in the pack, from the fields alone.

    vest_reads holds the three-run Wonder vest read per person id; only the hi-vis rule reads it,
    and only for a person the colour read left "unknown": three of three "yes" counts that person as
    vested there. It never makes a breach (a "no" leaves the person unknown) and no other rule ever
    sees it."""
    vest_reads = vest_reads or {}
    out = []
    g = gates(f)
    for rule in pack_rules:
        rid = rule["id"]
        ped = [p for p in f["people"] if p["on_foot"] and p["frames"]]
        if rule.get("route") == "out":
            out.append(
                _r(
                    rid,
                    "unable_to_rule",
                    f"{rule['title']} is not a rule video can judge from this camera; it is "
                    "routed out.",
                    missing="route:out",
                )
            )
            continue
        if g is not None:
            out.append({**g, "rule": rid})
            continue
        kind = rule.get("kind") or BY_ID.get(rid)
        if kind == "hi_vis":
            # the whole view is a truck zone, so a vest is read wherever a person on foot is seen,
            # floor metres or not
            ped = [p for p in f["people"] if p["on_foot"] and p["frames_read"]]
            if not ped:
                out.append(
                    _r(
                        rid,
                        "clear",
                        "No one on foot was seen in the truck zone during the window; "
                        "seated operators are set aside. "
                        f"{len(f['people'])} person track(s) read, "
                        f"{len(f['people']) - len(ped)} set aside as operator or too short.",
                    )
                )
                continue
            unv = [p for p in ped if p["vested"] == "unvested"]
            seen = [
                p
                for p in ped
                if p["vested"] == "unknown"
                and (vest_reads.get(str(p["id"])) or {}).get("agreed") == "yes"
            ]
            unk = [p for p in ped if p["vested"] in ("unknown", "unclear") and p not in seen]
            if unv:
                p = unv[0]
                out.append(
                    _r(
                        rid,
                        "breach",
                        f"{_pdesc(p)} on foot reads no hi-vis band on the torso on "
                        f"{p['vest_share']['unvested']:.0%} of "
                        f"{p['frames_read']} read frames (vested "
                        f"{p['vest_share']['vested']:.0%}, unreadable "
                        f"{p['vest_share']['unknown']:.0%}); "
                        f"the site line is {site.get('hivis_rule_share', 0.7):.0%}.",
                        ctx["people"][[q["id"] for q in ctx["people"]].index(p["id"])]["frames"][
                            :: FPS // 2
                        ],
                    )
                )
            elif unk:
                p = unk[0]
                vr = vest_reads.get(str(p["id"]))
                out.append(
                    _r(
                        rid,
                        "unable_to_rule",
                        f"{_pdesc(p)} on foot could not be read for a vest: "
                        f"{p['frames_read']} readable frames, "
                        f"{p['vest_share']['unknown']:.0%} unreadable (too small, cut by "
                        "the edge or hidden)."
                        + (
                            f" Three frame reads answered {', '.join(vr['answers'])}; only "
                            "three agreeing yes reads "
                            "complete the fact, and a no never makes a breach."
                            if vr
                            else ""
                        ),
                        missing="person.vested",
                    )
                )
            else:
                out.append(
                    _r(
                        rid,
                        "clear",
                        "Every person on foot reads a hi-vis band: "
                        + ", ".join(
                            (
                                f"{_pdesc(q)} too small or cut for the colour read on "
                                f"{q['vest_share']['unknown']:.0%} of {q['frames_read']} "
                                "frames, and three of three "
                                "frame reads (frames "
                                f"{', '.join(map(str, vest_reads[str(q['id'])]['src_frames']))}"
                                ") see a hi-vis vest"
                            )
                            if q in seen
                            else f"{_pdesc(q)} vested on {q['vest_share']['vested']:.0%} of "
                            f"{q['frames_read']} frames"
                            for q in ped
                        )
                        + ".",
                    )
                )
        elif kind == "spotter":
            if not f["truck.present"]:
                out.append(
                    _r(rid, "clear", "No truck was seen in the window, so nothing reversed.")
                )
                continue
            d = f["truck.direction"]
            rv = f["truck.reversing"]
            if (
                rv["band"] == "yes"
                and measure.CUT_REVERSE_CHECK
                and rv["clean_share"] < measure.AGREE
            ):
                # ruling 4 (30 Oct 2026): a reverse seen only through an edge-cut mask is never
                # ruled
                cf = rv["cut_frames"]
                out.append(
                    _r(
                        rid,
                        "unable_to_rule",
                        "The truck reads as travelling against its fork end for "
                        f"{d['reversing_frames'] / FPS:.1f} s, but on {len(cf)} of "
                        f"those frames (12 fps frames {cf[0] if cf else '-'} to "
                        f"{cf[-1] if cf else '-'}) the frame's bottom edge cuts the truck's "
                        "mask, so its "
                        "footpoint is the frame edge, not where it meets the floor, and no "
                        "floor measurement proves the reverse; only "
                        f"{rv['clean_share']:.0%} of the ensemble reads a second of reverse "
                        "from uncut frames.",
                        cf[:: FPS // 2],
                        missing="truck.reversing",
                    )
                )
            elif f["truck.reversing"]["band"] == "yes":
                spot = [
                    p
                    for p in ped
                    if p["vested"] == "vested" and (p["in_rear_cone_share"] or 0) >= 0.5
                ]
                runs = f["truck.reversing"]["runs"]
                fr = list(range(runs[0][0], runs[0][1] + 1, FPS // 2)) if runs else []
                if spot:
                    out.append(
                        _r(
                            rid,
                            "clear",
                            f"The truck reversed for {d['reversing_frames'] / FPS:.1f} s "
                            f"and {_pdesc(spot[0])}, vested, stood in the rear cone on "
                            f"{spot[0]['in_rear_cone_share']:.0%} of those frames: a "
                            "spotter was present.",
                            fr,
                        )
                    )
                elif (
                    f.get("rear_cone_visible") is not None
                    and f["rear_cone_visible"] < gatemod.CONE_VISIBLE
                ):
                    out.append(
                        _r(
                            rid,
                            "unable_to_rule",
                            f"The truck reversed for {d['reversing_frames'] / FPS:.1f} s "
                            "and no vested person was seen behind it, but only "
                            f"{f['rear_cone_visible']:.0%} of the rear cone the frame "
                            "covers is in view (the rest is cropped out), "
                            "so a spotter could stand there unseen; an absent spotter is "
                            "not proven.",
                            fr,
                            missing="person.in_rear_cone",
                        )
                    )
                else:
                    who = (
                        "nobody on foot in frame"
                        if not ped
                        else "no vested person in the rear cone ("
                        + ", ".join(
                            f"{_pdesc(p)} in the cone on "
                            f"{(p['in_rear_cone_share'] or 0):.0%}, {p['vested']}"
                            for p in ped
                        )
                        + ")"
                    )
                    out.append(
                        _r(
                            rid,
                            "breach",
                            "The truck travelled against its fork end for "
                            f"{d['reversing_frames'] / FPS:.1f} s "
                            f"({len(runs)} reverse run(s)) with {who}; this site requires a "
                            "spotter for every reverse.",
                            fr,
                        )
                    )
            elif not d["known"]:
                out.append(
                    _r(
                        rid,
                        "unable_to_rule",
                        "Which end of the truck is the fork end is not marked for this "
                        "camera, so travel direction cannot be read.",
                        missing="truck.direction",
                    )
                )
            elif f["truck.reversing"]["band"] == "straddles":
                out.append(
                    _r(
                        rid,
                        "unable_to_rule",
                        "Whether the truck reversed for a full second is not proven: "
                        f"{f['truck.reversing']['share']:.0%} of the ensemble reads a "
                        "reverse.",
                        missing="truck.reversing",
                    )
                )
            elif d["unknown_moving_frames"] >= FPS:
                out.append(
                    _r(
                        rid,
                        "unable_to_rule",
                        f"The truck moved for {d['unknown_moving_frames'] / FPS:.1f} s with "
                        "its travel direction unread.",
                        missing="truck.direction",
                    )
                )
            elif (
                _weak_state(f)
                and f.get("rear_cone_visible") is not None
                and f["rear_cone_visible"] < gatemod.CONE_VISIBLE
            ):
                out.append(
                    _r(
                        rid,
                        "unable_to_rule",
                        "The truck's moving state is unread on "
                        f"{f['truck.moving']['unknown_frames']} of "
                        f"{f['truck.moving']['truck_frames']} frames, so a "
                        f"reverse is not excluded, and only {f['rear_cone_visible']:.0%} of "
                        "the rear cone the frame covers is in view "
                        "(the rest is cropped out), so a spotter could not be seen either way.",
                        missing="person.in_rear_cone",
                    )
                )
            else:
                out.append(
                    _r(
                        rid,
                        "clear",
                        "The truck never reversed for a second: forward "
                        f"{d['forward_frames'] / FPS:.1f} s, "
                        f"reversing {d['reversing_frames'] / FPS:.1f} s, moving "
                        f"{f['truck.moving']['moving_frames'] / FPS:.1f} s of "
                        f"{f['truck.moving']['truck_frames'] / FPS:.1f} s in frame.",
                    )
                )
        elif kind == "separation":
            if not f["truck.present"] or not ped:
                out.append(
                    _r(
                        rid,
                        "clear",
                        "No moving truck and a person on foot shared the window."
                        if not f["truck.present"]
                        else f"No one on foot was near the truck: {len(f['people'])} person "
                        f"track(s), {len(f['people']) - len(ped)} set aside as operator or "
                        "too short.",
                    )
                )
                continue
            line = ped[0]["distance_m"]["line"]  # the compiled line the bands were read against
            breach = [p for p in ped if p["distance_m"]["band"] == "under"]
            strad = [p for p in ped if p["distance_m"]["band"] == "straddles"]
            unk = [
                p
                for p in ped
                if p["distance_m"]["close_unknown_frames"]
                and p["distance_m"]["band"] in ("over", "unmeasured")
            ]
            if breach:
                p = breach[0]
                dm = p["distance_m"]
                iv = dm["interval_moving"] or [dm["min_moving"], dm["min_moving"]]
                out.append(
                    _r(
                        rid,
                        "breach",
                        f"{_pdesc(p)} on foot came within {dm['min_moving']:.2f} m "
                        f"(interval {iv[0]:.2f} to {iv[1]:.2f}) of the truck's "
                        "floor outline while the truck was moving; the site line is "
                        f"{line:.1f} m and the whole interval is under it.",
                        [dm["frame_min"]] if dm["frame_min"] is not None else [],
                    )
                )
            elif strad:
                p = strad[0]
                dm = p["distance_m"]
                iv = dm["interval_moving"]
                out.append(
                    _r(
                        rid,
                        "unable_to_rule",
                        f"{_pdesc(p)}'s closest floor distance to the moving truck reads "
                        f"{dm['min_moving']:.2f} m with an interval "
                        f"{iv[0]:.2f} to {iv[1]:.2f} m that straddles the {line:.1f} m "
                        "line; not proven either way.",
                        missing="person.distance_m",
                    )
                )
            elif unk:
                p = unk[0]
                nc = p["distance_m"].get("close_unknown_cut", 0)
                why = (
                    "under a second of track either side"
                    if not nc
                    else f"on {nc} of them the truck's mask is cut by the frame's bottom edge, "
                    "so its floor contact is out of view and neither the "
                    "footpoint nor the mask's top point reads it stopped"
                )
                nd = p["distance_m"].get("close_unknown_dock", 0)
                if nd:
                    # ruling 3: the guide in the dock zone is recorded; the exemption needs the
                    # truck's speed into the zone read
                    why += (
                        f"; {_pdesc(p)} stood inside the dock zone on {nd} of them, so the "
                        "dock-guide exemption applies to "
                        f"{_pdesc(p)}, but it excuses a frame only where the truck's speed "
                        "into the zone reads under the dock line, "
                        "and the cut mask reads that speed on none of them"
                    )
                out.append(
                    _r(
                        rid,
                        "unable_to_rule",
                        f"{_pdesc(p)} was within {line:.1f} m on "
                        f"{p['distance_m']['close_unknown_frames']} frames where the "
                        "truck's "
                        f"moving state could not be read ({why}).",
                        missing="truck.moving",
                    )
                )
            else:
                parts = []
                for p in ped:
                    dm = p["distance_m"]
                    if dm["min_moving"] is not None and math.isfinite(dm["min_moving"]):
                        parts.append(
                            f"{_pdesc(p)} no closer than {dm['min_moving']:.2f} m while the "
                            "truck moved"
                        )
                    elif dm["close_exempt_frames"]:
                        parts.append(
                            f"{_pdesc(p)} within the line only while the truck was stopped "
                            f"or as its still spotter ({dm['close_exempt_frames']} frames)"
                        )
                    else:
                        parts.append(f"{_pdesc(p)} never near a moving truck")
                out.append(
                    _r(
                        rid,
                        "clear",
                        f"Separation held at the {line:.1f} m line: " + "; ".join(parts) + ".",
                    )
                )
        elif kind == "structure":
            if not f["truck.present"]:
                out.append(
                    _r(
                        rid,
                        "clear",
                        "No truck was seen in the window, so nothing touched a structure.",
                    )
                )
                continue
            s = f["truck.front_in_strip"]
            if not s["marked"]:
                out.append(
                    _r(
                        rid,
                        "unable_to_rule",
                        "No structure base is marked for this camera, so the truck's "
                        "distance to racking cannot be measured.",
                        missing="truck.front_in_strip",
                    )
                )
                continue
            run = (
                s["longest_run"] >= site["structure_run_frames"] and s["run_share"] >= measure.AGREE
            )
            cq = f["contact.consequence"]
            onsets = cq["onsets"]
            if run and cq["pairs"] and cq["pair_share"] >= measure.AGREE:
                p = cq["pairs"][0]
                out.append(
                    _r(
                        rid,
                        "breach",
                        "The truck's floor footprint (the mask's near edge, forks "
                        "included, carried to the site's "
                        f"{site['truck_m']['length']:.1f} by {site['truck_m']['width']:.2f} "
                        "m truck on the hidden side) held within "
                        f"{site['structure_strip_m']:.2f} m of the {p['structure']} base "
                        f"from frame {p['run'][0] * 2} to {p['run'][1] * 2} while not "
                        "stopped, "
                        f"and a consequence followed at frame {p['event'] * 2} ({p['why']}) "
                        f"within {site['consequence_window_s']:.1f} s; "
                        f"{cq['pair_share']:.0%} of the ensemble reads the run and the "
                        "consequence together.",
                        [p["run"][0], p["event"]],
                    )
                )
            elif run and cq["pairs"]:
                p = cq["pairs"][0]
                out.append(
                    _r(
                        rid,
                        "unable_to_rule",
                        f"The truck's footprint held in the {p['structure']} base strip and "
                        f"a consequence ({p['why']}) followed at frame "
                        f"{p['event'] * 2}, but only {cq['pair_share']:.0%} of the ensemble "
                        "reads the run and the consequence together; "
                        "not proven either way.",
                        [p["run"][0], p["event"]],
                        missing="truck.front_in_strip",
                    )
                )
            elif run:
                # No breach without a pair the ensemble proves (the base's first-run read, which
                # paired any
                # onset up to the run's minimum length plus the window, is gone with the long-run
                # pairing)
                f0 = s["first_run_frame"]
                near = [o for o in onsets if f0 <= o[0]]
                # rulings 2 and 6 (30 Oct 2026): the pack's rule stands (a touch with no visible
                # consequence is still a
                # breach); the consequence is this judge's standard of evidence, so the ruling says
                # what it cannot see
                out.append(
                    _r(
                        rid,
                        "unable_to_rule",
                        f"{NO_CONSEQUENCE} The truck's floor footprint came within "
                        f"{site['structure_strip_m']:.2f} m of the {s['structure']} base "
                        f"for {s['longest_run']} frames "
                        f"(closest {s['min_front_dist']:.2f} m) and no consequence followed "
                        f"within {site['consequence_window_s']:.1f} s of its entering "
                        f"the strip or of its leaving it ({len(near)} later consequence "
                        "event(s) fell outside those windows).",
                        [f0],
                        missing="contact.consequence",
                    )
                )
            elif s["longest_run"] >= site["structure_run_frames"]:
                out.append(
                    _r(
                        rid,
                        "unable_to_rule",
                        f"Only {s['run_share']:.0%} of the ensemble puts the truck's "
                        f"footprint inside the {site['structure_strip_m']:.2f} m strip for "
                        f"{site['structure_run_frames']} frames (closest "
                        f"{s['min_front_dist']:.2f} m); not proven either way.",
                        missing="truck.front_in_strip",
                    )
                )
            else:
                dm = s["min_front_dist"]
                out.append(
                    _r(
                        rid,
                        "clear",
                        "The truck's footprint never held within "
                        f"{site['structure_strip_m']:.2f} m of a marked structure base for "
                        f"{site['structure_run_frames']} frames: "
                        f"closest {dm:.2f} m to the {s['structure']} base, longest run "
                        f"{s['longest_run']} frame(s); "
                        f"{len(onsets)} consequence event(s) seen.",
                    )
                )
        elif kind == "speed":
            if not f["truck.present"]:
                out.append(
                    _r(rid, "clear", "No truck was seen in the window, so no speed was measured.")
                )
                continue
            sp = f["truck.speed_mps"]
            if sp["band"] == "unmeasured":
                out.append(
                    _r(
                        rid,
                        "unable_to_rule",
                        "The truck was not in frame for a full second of track, so no "
                        "one-second speed exists.",
                        missing="truck.speed_mps",
                    )
                )
            elif sp["band"] == "over":
                out.append(
                    _r(
                        rid,
                        "breach",
                        f"Peak floor speed {sp['peak']:.2f} m/s (interval "
                        f"{sp['interval'][0]:.2f} to {sp['interval'][1]:.2f}), smoothed "
                        "over one second, "
                        f"against the site limit of {sp['limit']:.1f} m/s; the whole "
                        "interval is over the line.",
                    )
                )
            elif sp["band"] == "under":
                out.append(
                    _r(
                        rid,
                        "clear",
                        f"Peak floor speed {sp['peak']:.2f} m/s (interval "
                        f"{sp['interval'][0]:.2f} to {sp['interval'][1]:.2f}) stays under "
                        f"the site limit of {sp['limit']:.1f} m/s.",
                    )
                )
            else:
                out.append(
                    _r(
                        rid,
                        "unable_to_rule",
                        f"Peak floor speed {sp['peak']:.2f} m/s with an interval "
                        f"{sp['interval'][0]:.2f} to {sp['interval'][1]:.2f} that straddles "
                        "the "
                        f"{sp['limit']:.1f} m/s limit; not proven either way.",
                        missing="truck.speed_mps",
                    )
                )
        else:
            out.append(
                _r(
                    rid,
                    "unable_to_rule",
                    f"{rule['title']}: no predicate over the measured fields compiles for "
                    "this rule.",
                    missing="route:unmapped",
                )
            )
    if f.get("camera.compensated"):
        note = (
            f"The camera drifted by up to {f['camera.shift_px']:.0f} px after "
            f"{f['camera.held_frames'] / FPS:.1f} s; every measured point was moved "
            "back by its frame's measured drift onto the marked view. "
        )
        for r in out:
            if r["missing_fact"] not in ("camera.static", "route:out"):
                r["evidence"] = (note + r["evidence"])[:600]
    if f.get("camera.partial"):
        held = (
            f"The camera held for the first {f['camera.held_frames'] / FPS:.1f} s and then "
            "moved; only that span was measured. "
        )
        for r in out:
            if r["missing_fact"] not in ("camera.static", "route:out"):
                r["evidence"] = (held + r["evidence"])[:600]
    return out
