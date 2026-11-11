"""Score racing ruling lines against the confirmed truth table. Numbers only, no model call.

Run from the repo root:
    uv run python scripts/racing_score.py <preds.jsonl> [<more.jsonl> ...] [--data data/racing]
        [--out <score.json>]

Inputs, all read in place:

- One or more preds files in the ruling-line shape (the plan's "Ruling line"): the limits
  output (`kind` `incident_limit`) and the judge's contact output (`kind` `contact`). A ruling
  id that appears twice across the files is refused.
- `<data>/truth.json`, the table confirmed by hand (`decisions`: `id`, `session`,
  `offender_sim`, `victim_sim`, `contact_te`, `verdict`, `duplicate_of`, ...).
- `<data>/league.json` for each session's track, incident limit and clause.
- `<data>/inputs.json`, whose `catalogue` names the 28 Oct catalogue: its `incident_checks`
  give each incident-limit decision's stated total, the join rule A used.
- `<data>/truth.draft.json`, where `scripts/racing_prep.py` stores both offender constants
  under `constants.confirmed`. They are used as stored when their rows match truth.json; if
  they are absent or stale they are recomputed with racing_prep's own functions, and the
  output says which.

Writes `<data>/score.json`, or `--out` (sorted keys, UTF-8, `\\n` endings, no timestamps,
written to a temp file then renamed) and prints a table of numbers, car numbers, decision ids
and track names. Nothing in a protest, a ruling's evidence or the truth table's `basis`
is ever copied.

The marks are the ones pre-registered in `experiments/2026-10-29-racing-pipeline/LOG.md`,
with the confirmed truth's changes recorded there (scored set and the n of mark 4):

1. Incident limit: decisions 19, 20, 22, 25, 26, 27, 28 found (pass 7 of 7). Found means every
   one of the decision's incident checks matches at least one breaching car in its session
   with the stated total. Every breach is `ruled` or `no_ruling_on_record`; the second kind is
   listed as "over the limit, no ruling on record", never as a missed breach.
2. Locator: the window's `te` interval [a, b] holds the truth `contact_te` within 2 s, that is
   a - 2 <= contact_te <= b + 2, on 1, 11, 13, 15, 16, 24, 46 (pass 5 of 7). A refused or
   missing line is a miss. 14, 18 and 23 are reported, unscored. The no-feed protests (2, 3,
   4, 5, 6, 7, 9, 10, 48) are counted, and how many refused.
3. Closed set: every truth party (offender, and victim when there is one) is in `candidates`,
   on 1, 11, 13, 14, 15, 16, 18, 23, 24, 46 (pass 7 of 10), and the median set size over the
   same 10 is 4 or fewer. A refused or missing protest has size 0 and is a miss. Shown beside
   it: the 8 with duplicates dropped (a view, not the mark), the mark over 9 without decision
   1, and rule B's 2 of 9 from the 29 Oct test.
4. Model's read, offender: agreed reads naming the truth offender on the n non-duplicate rows
   with an offender, against the better constant. Pass: more than the better constant, or n of
   n when the constant already scores n.
5. Model's read, verdict: agreement with the truth verdict, reported only.

Marks 4 and 5 print "not run yet" while no line carries a `model_read`.

Refuses (exit 1, a message naming the file and the reason) when an input is missing or bad.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent

MARK1_DECISIONS = ("19", "20", "22", "25", "26", "27", "28")
MARK2_SCORED = ("1", "11", "13", "15", "16", "24", "46")
MARK2_PASS = 5
MARK2_TOLERANCE_S = 2
MARK2_UNSCORED = ("14", "18", "23")
NOFEED_DECISIONS = ("2", "3", "4", "5", "6", "7", "9", "10", "48")
MARK3_DECISIONS = ("1", "11", "13", "14", "15", "16", "18", "23", "24", "46")
MARK3_PASS = 7
MARK3_MEDIAN_MAX = 4
MARK3_WITHOUT = "1"
RULE_B = {"right": 2, "n": 9, "note": "29 Oct paired +4 count alone, decision 1 left out"}
NO_RULING = "over the limit, no ruling on record"
VIEW_NO_TOL = "view, not the mark: truth second inside the window with no tolerance"
_TOTAL = re.compile(r"\bon (\d+) incident points\b")


class ScoreError(ValueError):
    """An input could not be read or scored; the message names the file and the reason."""


def session_order(session: str) -> tuple[str, int, str]:
    """Race days in subsession order; inside a day the heat runs before the feature."""
    sub, _, name = session.partition("/")
    return (sub, 0 if name.startswith("HEAT") else 1, name)


def numkey(n: object) -> tuple[int, int, str]:
    """Sort key for car numbers and ids: all-digit strings by integer, others after them."""
    s = str(n)
    return (0, int(s), s) if s.isascii() and s.isdigit() else (1, 0, s)


# ---------------------------------------------------------------- reading


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ScoreError(
            f"{path}: cannot be read ({exc.strerror or type(exc).__name__})."
        ) from None
    except json.JSONDecodeError as exc:
        raise ScoreError(f"{path}: not JSON (line {exc.lineno}).") from None


def read_preds(paths: list[Path]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Every ruling line by id, and each file's name, line count and sha256."""
    lines: dict[str, dict[str, Any]] = {}
    files = []
    for path in paths:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ScoreError(
                f"{path}: cannot be read ({exc.strerror or type(exc).__name__})."
            ) from None
        count = 0
        for no, text in enumerate(raw.decode("utf-8").split("\n"), 1):
            if not text.strip():
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                raise ScoreError(f"{path}: line {no} is not JSON.") from None
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise ScoreError(f"{path}: line {no} has no string `id`.")
            if row.get("kind") not in ("contact", "incident_limit"):
                raise ScoreError(f"{path}: line {no} has `kind` {row.get('kind')!r}.")
            if row["id"] in lines:
                raise ScoreError(f"{path}: line {no} repeats ruling id {row['id']}.")
            lines[row["id"]] = row
            count += 1
        files.append({"file": path.name, "lines": count, "sha256": hashlib.sha256(raw).hexdigest()})
    return lines, files


def read_truth(path: Path) -> dict[str, dict[str, Any]]:
    truth = _read_json(path)
    rows = truth.get("decisions") if isinstance(truth, dict) else None
    if not isinstance(rows, list):
        raise ScoreError(f"{path}: no `decisions` list.")
    out: dict[str, dict[str, Any]] = {}
    for i, d in enumerate(rows):
        need = ("id", "session", "offender_sim", "victim_sim", "contact_te", "duplicate_of")
        if not isinstance(d, dict) or any(k not in d for k in need):
            raise ScoreError(f"{path}: decisions[{i}] lacks one of {', '.join(need)}.")
        did = str(d["id"])
        if did in out:
            raise ScoreError(f"{path}: decision {did} appears twice.")
        out[did] = d
    for did in MARK3_DECISIONS:
        if did not in out:
            raise ScoreError(f"{path}: decision {did} is missing.")
    return out


def _labels(league: dict[str, Any], path: Path) -> dict[str, str]:
    sessions = league.get("sessions") if isinstance(league, dict) else None
    if not isinstance(sessions, dict):
        raise ScoreError(f"{path}: no `sessions` object.")
    return {k: f"{s['track_short']} {s['session']}" for k, s in sessions.items()}


# ---------------------------------------------------------------- mark 1


def mark1(
    lines: dict[str, dict[str, Any]],
    league: dict[str, Any],
    catalogue: dict[str, Any],
    labels: dict[str, str],
) -> dict[str, Any]:
    limits = [r for r in lines.values() if r["kind"] == "incident_limit"]
    if not limits:
        return {"status": "no incident_limit lines", "pass": None}
    sessions = league["sessions"]
    breaches: dict[tuple[str, str], int] = {}
    refused = []
    for r in limits:
        session = (r.get("window") or {}).get("session")
        if session not in sessions:
            raise ScoreError(f"ruling {r['id']}: session not in league.json.")
        if r.get("verdict") == "unable_to_rule":
            refused.append(labels[session])
            continue
        if r.get("verdict") != "breach" or not r.get("offender"):
            raise ScoreError(
                f"ruling {r['id']}: an incident_limit line is neither breach nor refusal."
            )
        m = _TOTAL.search(r.get("evidence") or "")
        if not m:
            raise ScoreError(f"ruling {r['id']}: evidence does not state the total.")
        if (session, r["offender"]) in breaches:
            raise ScoreError(
                f"ruling {r['id']}: a second breach line for car {r['offender']}"
                f" in {labels[session]}."
            )
        breaches[(session, r["offender"])] = int(m.group(1))
    cat = {str(d["id"]): d for d in catalogue.get("decisions", [])}
    ruled: set[tuple[str, str]] = set()
    rows = []
    for did in MARK1_DECISIONS:
        checks = (cat.get(did) or {}).get("incident_checks") or []
        found = bool(checks)
        parts = []
        for chk in checks:
            session, stated = chk["session"], int(chk["incidents"])
            cars = sorted(
                (c for (s, c), t in breaches.items() if s == session and t == stated), key=numkey
            )
            ruled.update((session, c) for c in cars)
            found = found and bool(cars)
            parts.append({"session": labels.get(session, "unknown"), "total": stated, "cars": cars})
        rows.append({"id": did, "found": found, "checks": parts})
    found_n = sum(r["found"] for r in rows)
    listed = []
    for (session, car), total in sorted(
        breaches.items(), key=lambda x: (session_order(x[0][0]), numkey(x[0][1]))
    ):
        s = sessions[session]
        listed.append(
            {
                "session": s["session"],
                "track": s["track_short"],
                "car": car,
                "total": total,
                "limit": s["incident_limit"],
                "clause": s["clause"],
                "status": "ruled" if (session, car) in ruled else "no_ruling_on_record",
            }
        )
    no_ruling = [b for b in listed if b["status"] == "no_ruling_on_record"]
    return {
        "status": "scored",
        "numerator": found_n,
        "denominator": len(MARK1_DECISIONS),
        "pass": found_n == len(MARK1_DECISIONS),
        "rows": rows,
        "breaches": listed,
        "no_ruling_on_record": no_ruling,
        "no_ruling_on_record_label": NO_RULING,
        "refused_sessions": sorted(refused),
    }


# ---------------------------------------------------------------- marks 2 and 3


def _window_te(line: dict[str, Any] | None) -> list[float] | None:
    te = ((line or {}).get("window") or {}).get("te")
    if isinstance(te, list) and len(te) == 2 and all(isinstance(x, int | float) for x in te):
        return [te[0], te[1]]
    return None


def _located(line: dict[str, Any] | None) -> bool:
    """A contact line the judge located: verdict steward_review. Anything else is a miss."""
    return line is not None and line.get("verdict") == "steward_review"


def _outcome(line: dict[str, Any] | None) -> str:
    if line is None:
        return "absent"
    if line.get("verdict") == "unable_to_rule":
        return "refused"
    if not _located(line):
        return f"verdict {line.get('verdict')}"
    return "window" if _window_te(line) else "no window te"


def _width(line: dict[str, Any] | None) -> float | None:
    te = _window_te(line) if _located(line) else None
    return None if te is None else round(float(te[1] - te[0]), 1)


def _held(
    line: dict[str, Any] | None, truth_te: int | None, tol: int = MARK2_TOLERANCE_S
) -> bool | None:
    te = _window_te(line) if _located(line) else None
    if truth_te is None:
        return None
    if te is None:
        return False
    return te[0] - tol <= truth_te <= te[1] + tol


def mark2(
    lines: dict[str, dict[str, Any]], truth: dict[str, dict[str, Any]], labels: dict[str, str]
) -> dict[str, Any]:
    contact = {k: v for k, v in lines.items() if v["kind"] == "contact"}
    if not contact:
        return {"status": "no contact lines", "pass": None}

    def row(did: str) -> dict[str, Any]:
        t = truth[did]
        line = contact.get(did)
        return {
            "id": did,
            "session": labels.get(t["session"], "unknown"),
            "truth_te": t["contact_te"],
            "window_te": _window_te(line),
            "outcome": _outcome(line),
            "held": _held(line, t["contact_te"]),
            "held_no_tolerance": _held(line, t["contact_te"], 0),
            "width_s": _width(line),
            "duplicate_of": t["duplicate_of"],
        }

    scored = [row(d) for d in MARK2_SCORED]
    for r in scored:
        if r["truth_te"] is None:
            raise ScoreError(
                f"truth.json: decision {r['id']} is scored for the locator but has no contact_te."
            )
    hits = sum(bool(r["held"]) for r in scored)
    widths = [r["width_s"] for r in scored if r["width_s"] is not None]
    nofeed = [{"id": d, "outcome": _outcome(contact.get(d))} for d in NOFEED_DECISIONS]
    return {
        "status": "scored",
        "numerator": hits,
        "denominator": len(MARK2_SCORED),
        "pass": hits >= MARK2_PASS,
        "pass_at": MARK2_PASS,
        "tolerance_s": MARK2_TOLERANCE_S,
        "window_width": {
            "median_s": _median(widths) if widths else None,
            "over": len(widths),
            "of": len(scored),
        },
        "view_no_tolerance": {
            "label": VIEW_NO_TOL,
            "numerator": sum(bool(r["held_no_tolerance"]) for r in scored),
            "denominator": len(scored),
            "rows": [{"id": r["id"], "held": bool(r["held_no_tolerance"])} for r in scored],
        },
        "rows": scored,
        "unscored": [row(d) for d in MARK2_UNSCORED],
        "nofeed": {
            "rows": nofeed,
            "count": len(NOFEED_DECISIONS),
            "present": sum(r["outcome"] != "absent" for r in nofeed),
            "refused": sum(r["outcome"] == "refused" for r in nofeed),
        },
    }


def _median(xs: list[int] | list[float]) -> float:
    return round(float(statistics.median(xs)), 1) if xs else 0.0


def mark3(
    lines: dict[str, dict[str, Any]], truth: dict[str, dict[str, Any]], labels: dict[str, str]
) -> dict[str, Any]:
    contact = {k: v for k, v in lines.items() if v["kind"] == "contact"}
    if not contact:
        return {"status": "no contact lines", "pass": None}
    rows = []
    for did in MARK3_DECISIONS:
        t = truth[did]
        line = contact.get(did)
        outcome = _outcome(line)
        cands = list((line or {}).get("candidates") or []) if _located(line) else []
        parties = [p for p in (t["offender_sim"], t["victim_sim"]) if p]
        if not parties:
            raise ScoreError(f"truth.json: decision {did} names no party.")
        inside = _located(line) and all(p in cands for p in parties)
        rows.append(
            {
                "id": did,
                "session": labels.get(t["session"], "unknown"),
                "parties": parties,
                "candidates": sorted(cands, key=numkey),
                "size": len(cands),
                "outcome": outcome,
                "located": _located(line),
                "inside": inside,
                "duplicate_of": t["duplicate_of"],
            }
        )
    hits = sum(r["inside"] for r in rows)
    median = _median([r["size"] for r in rows])
    located = [r["size"] for r in rows if r["located"]]
    median_located = _median(located) if located else None
    median_located_pass = median_located is not None and median_located <= MARK3_MEDIAN_MAX
    dedup = [r for r in rows if not r["duplicate_of"]]
    no1 = [r for r in rows if r["id"] != MARK3_WITHOUT]
    return {
        "status": "scored",
        "numerator": hits,
        "denominator": len(rows),
        "pass_at": MARK3_PASS,
        "parties_pass": hits >= MARK3_PASS,
        "median_size": median,
        "median_max": MARK3_MEDIAN_MAX,
        "median_pass": median <= MARK3_MEDIAN_MAX,
        "median_size_located": median_located,
        "located": len(located),
        "median_located_pass": median_located_pass,
        "pass": hits >= MARK3_PASS and median <= MARK3_MEDIAN_MAX and median_located_pass,
        "refused_counts_as": "size 0 and a miss",
        "rows": rows,
        "view_deduplicated": {
            "numerator": sum(r["inside"] for r in dedup),
            "denominator": len(dedup),
            "median_size": _median([r["size"] for r in dedup]),
            "dropped": sorted((r["id"] for r in rows if r["duplicate_of"]), key=numkey),
        },
        "without_decision_1": {
            "numerator": sum(r["inside"] for r in no1),
            "denominator": len(no1),
        },
        "rule_b": RULE_B,
    }


# ---------------------------------------------------------------- constants, marks 4 and 5


def _stored_constants(draft_path: Path, truth: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """The confirmed constants racing_prep stored, or None when absent or not from this truth."""
    if not draft_path.is_file():
        return None
    draft = _read_json(draft_path)
    if not isinstance(draft, dict):
        raise ScoreError(f"{draft_path}: not a JSON object.")
    block = draft.get("constants")
    if block is None:
        return None
    if not isinstance(block, dict):
        raise ScoreError(f"{draft_path}: `constants` is not an object.")
    conf = block.get("confirmed")
    if conf is None:
        return None
    if (
        not isinstance(conf, dict)
        or not isinstance(conf.get("rows"), list)
        or not all(isinstance(r, dict) and "id" in r for r in conf["rows"])
        or any(not isinstance(conf.get(k), int) for k in ("n", "car_behind_score", "accused_score"))
        or not isinstance(conf.get("better"), str)
    ):
        raise ScoreError(f"{draft_path}: `constants.confirmed` has the wrong shape.")
    by_id = {str(r["id"]): r for r in conf["rows"]}
    if set(by_id) != set(truth):
        return None
    for did, t in truth.items():
        r = by_id[did]
        if (
            r.get("truth_offender_sim") != t["offender_sim"]
            or r.get("contact_te") != t["contact_te"]
            or r.get("duplicate_of") != t["duplicate_of"]
            or r.get("session") != t["session"]
        ):
            return None
    return conf


def _recompute_constants(data: Path) -> dict[str, Any]:
    """Rebuild the confirmed constants with racing_prep's own functions (reads the feeds)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import racing_prep as prep

    try:
        cfg = prep._load_inputs(data)
        league = _read_json(data / "league.json")
        feeds = prep.load_feeds(Path(cfg["replays_dir"]), sorted(league["sessions"]))
        number_map = prep.build_number_map(feeds, list(cfg["season_one_subsessions"]))
        rows = prep._read_truth(data / "truth.json", feeds)
        reports = {}
        for text in (data / "reports.jsonl").read_text(encoding="utf-8").split("\n"):
            if text.strip():
                rep = json.loads(text)
                reports[rep["id"]] = rep
        c_rows = prep._constant_rows(rows, reports, feeds, number_map)
    except prep.PrepError as exc:
        raise ScoreError(str(exc)) from None
    n, b, a = prep._score(c_rows)
    return {
        "n": n,
        "car_behind_score": b,
        "accused_score": a,
        "better": prep._better(b, a),
        "rows": c_rows,
    }


def constants(data: Path, truth: dict[str, dict[str, Any]]) -> dict[str, Any]:
    conf = _stored_constants(data / "truth.draft.json", truth)
    source = "stored in truth.draft.json constants.confirmed"
    if conf is None:
        conf = recompute(data)
        source = "recomputed with racing_prep (stored copy absent or stale)"
    b, a = int(conf["car_behind_score"]), int(conf["accused_score"])
    return {
        "source": source,
        "n": int(conf["n"]),
        "car_behind": b,
        "accused": a,
        "better": conf["better"],
        "better_score": max(a, b),
    }


recompute = _recompute_constants  # the seam tests replace; the real one reads private feeds


def _offender_n(truth: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(
        (d for d, t in truth.items() if t["offender_sim"] and not t["duplicate_of"]), key=numkey
    )


def marks45(
    lines: dict[str, dict[str, Any]], truth: dict[str, dict[str, Any]], const: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    contact = {k: v for k, v in lines.items() if v["kind"] == "contact"}
    if not any(v.get("model_read") for v in contact.values()):
        return ({"status": "not run yet", "pass": None}, {"status": "not run yet"})
    ids = _offender_n(truth)
    if len(ids) != const["n"]:
        raise ScoreError(f"truth.json gives n {len(ids)} for mark 4, the constants {const['n']}.")
    rows = []
    for did in ids:
        line = contact.get(did)
        read = (line or {}).get("model_read") or None
        status = "none"
        if read:
            status = "agreed" if read.get("agreed") is True else "not agreed"
            if status == "agreed" and not _located(line):
                status = "not counted: line not located"
            elif (
                status == "agreed"
                and read.get("offender") is not None
                and read.get("offender") not in (line or {}).get("candidates", [])
            ):
                # A null offender (not_visible, no_action, racing_incident) named no car,
                # so it is not outside the set: it stays agreed, not right on mark 4, and
                # its verdict counts on mark 5.
                status = "not counted: offender outside candidates"
        agreed = status == "agreed"
        rows.append(
            {
                "id": did,
                "truth_offender": truth[did]["offender_sim"],
                "truth_verdict": truth[did].get("verdict"),
                "read": status,
                "offender": read.get("offender") if agreed and read else None,
                "verdict": read.get("verdict") if agreed and read else None,
                "offender_right": agreed and read.get("offender") == truth[did]["offender_sim"],
                "verdict_right": agreed and read.get("verdict") == truth[did].get("verdict"),
            }
        )
    n = len(rows)
    right = sum(r["offender_right"] for r in rows)
    better = const["better_score"]
    passed = right == n if better >= n else right > better
    m4 = {
        "status": "scored",
        "numerator": right,
        "denominator": n,
        "better_constant": const["better"],
        "better_constant_score": better,
        "pass_at": n if better >= n else better + 1,
        "pass": passed,
        "agreed": sum(r["read"] == "agreed" for r in rows),
        "rows": rows,
    }
    m5 = {
        "status": "reported, no mark",
        "numerator": sum(r["verdict_right"] for r in rows),
        "denominator": n,
        "agreed": m4["agreed"],
        "rows": [
            {k: r[k] for k in ("id", "truth_verdict", "verdict", "verdict_right")} for r in rows
        ],
    }
    return m4, m5


# ---------------------------------------------------------------- output


def _pf(ok: bool | None) -> str:
    return "n/a" if ok is None else "pass" if ok else "fail"


def render(score: dict[str, Any]) -> str:
    out: list[str] = []
    c = score["constants"]
    out.append(f"constants ({c['source']}), n {c['n']}:")
    out.append(f"  car behind {c['car_behind']} of {c['n']}")
    out.append(f"  accused    {c['accused']} of {c['n']}")
    out.append(f"  better: {c['better']} at {c['better_score']} of {c['n']}")

    m = score["mark_1"]
    out.append("")
    if m["status"] != "scored":
        out.append(f"mark 1 incident limit: {m['status']}")
    else:
        out.append(
            f"mark 1 incident limit: {m['numerator']} of {m['denominator']} found"
            f" -> {_pf(m['pass'])} (pass {m['denominator']} of {m['denominator']})"
        )
        for r in m["rows"]:
            parts = "; ".join(
                f"{p['session']} total {p['total']} cars {','.join(p['cars']) or '-'}"
                for p in r["checks"]
            )
            out.append(
                f"  decision {r['id']:>3}: {'found' if r['found'] else 'not found'}  {parts}"
            )
        ruled = sum(b["status"] == "ruled" for b in m["breaches"])
        out.append(
            f"  breaches {len(m['breaches'])}: ruled {ruled},"
            f" {NO_RULING} {len(m['no_ruling_on_record'])}"
        )
        if m["refused_sessions"]:
            out.append(f"  sessions refused (no counter): {', '.join(m['refused_sessions'])}")
        out.append(f"  {NO_RULING}:")
        out.append(f"    {'track':<13}{'session':<9}{'car':>5}{'total':>7}{'limit':>7}  clause")
        for b in m["no_ruling_on_record"]:
            out.append(
                f"    {b['track']:<13}{b['session']:<9}{b['car']:>5}{b['total']:>7}"
                f"{b['limit']:>7}  {b['clause']}"
            )

    m = score["mark_2"]
    out.append("")
    if m["status"] != "scored":
        out.append(f"mark 2 locator: {m['status']}")
    else:
        out.append(
            f"mark 2 locator: {m['numerator']} of {m['denominator']} within {m['tolerance_s']} s"
            f" -> {_pf(m['pass'])} (pass {m['pass_at']} of {m['denominator']})"
        )
        ww = m["window_width"]
        med_w = "-" if ww["median_s"] is None else f"{ww['median_s']:g} s"
        out.append(
            f"  window width: median {med_w} over {ww['over']} located of {ww['of']}"
            " (a refused protest is a miss, whatever te it carries)"
        )
        for r in m["rows"] + m["unscored"]:
            te = r["window_te"]
            win = f"{te[0]:g}-{te[1]:g}" if te else "-"
            truth_te = "-" if r["truth_te"] is None else str(r["truth_te"])
            width = "-" if r["width_s"] is None else f"{r['width_s']:g}"
            held = {True: "held", False: "missed", None: "no truth second"}[r["held"]]
            tag = "" if r["id"] in MARK2_SCORED else "  (unscored"
            if tag:
                tag += f", duplicate of {r['duplicate_of']})" if r["duplicate_of"] else ")"
            out.append(
                f"  decision {r['id']:>3} {r['session']:<22} truth {truth_te:>5}  window"
                f" {win:<12} width {width:>5} {r['outcome']:<8} {held}{tag}"
            )
        v = m["view_no_tolerance"]
        out.append(f"  {v['label']}: {v['numerator']} of {v['denominator']}")
        out.append(
            "    " + ", ".join(f"{r['id']} {'held' if r['held'] else 'missed'}" for r in v["rows"])
        )
        nf = m["nofeed"]
        out.append(
            f"  no-feed protests: {nf['count']}, lines present {nf['present']},"
            f" refused {nf['refused']} of {nf['count']} (expected {nf['count']} of {nf['count']})"
        )

    m = score["mark_3"]
    out.append("")
    if m["status"] != "scored":
        out.append(f"mark 3 closed set: {m['status']}")
    else:
        out.append(
            f"mark 3 closed set: parties inside {m['numerator']} of {m['denominator']}"
            f" -> {_pf(m['parties_pass'])} (pass {m['pass_at']} of {m['denominator']});"
            f" mark 3 -> {_pf(m['pass'])}"
        )
        med_l = m["median_size_located"]
        out.append(
            f"  median size over all {m['denominator']}: {m['median_size']:g}"
            f" -> {_pf(m['median_pass'])}; over the {m['located']} located:"
            f" {'-' if med_l is None else format(med_l, 'g')} -> {_pf(m['median_located_pass'])}"
            f" (both must be {m['median_max']} or fewer)"
        )
        out.append("  a refused or absent protest counts as size 0 and as a miss")
        for r in m["rows"]:
            dup = f"  (duplicate of {r['duplicate_of']})" if r["duplicate_of"] else ""
            out.append(
                f"  decision {r['id']:>3} {r['session']:<22} parties {','.join(r['parties']):<9}"
                f" size {r['size']:>2} {r['outcome']:<8} {'inside' if r['inside'] else 'miss'}{dup}"
            )
        v = m["view_deduplicated"]
        w = m["without_decision_1"]
        b = m["rule_b"]
        out.append(
            f"  view, not the mark: {v['numerator']} of {v['denominator']} with duplicates"
            f" {','.join(v['dropped'])} dropped, median size {v['median_size']:g}"
        )
        out.append(
            f"  beside rule B: mark 3 {m['numerator']} of {m['denominator']},"
            f" {w['numerator']} of {w['denominator']} without decision {MARK3_WITHOUT};"
            f" rule B {b['right']} of {b['n']}"
        )

    m4, m5 = score["mark_4"], score["mark_5"]
    out.append("")
    if m4["status"] != "scored":
        out.append(f"mark 4 model's read, offender: {m4['status']}")
        out.append(f"mark 5 model's read, verdict: {m5['status']}")
    else:
        out.append(
            f"mark 4 model's read, offender: {m4['numerator']} of {m4['denominator']} agreed and"
            f" right -> {_pf(m4['pass'])} (pass {m4['pass_at']} of {m4['denominator']}; better"
            f" constant {m4['better_constant_score']} of {m4['denominator']})"
        )
        for r in m4["rows"]:
            out.append(
                f"  decision {r['id']:>3} truth {r['truth_offender']:>4}  read {r['read']:<10}"
                f" offender {r['offender'] or '-':>4}"
                f"  {'right' if r['offender_right'] else 'not right'}"
            )
        out.append(
            f"mark 5 model's read, verdict (reported, no mark): {m5['numerator']} of"
            f" {m5['denominator']} agreed reads match the truth verdict"
        )
    return "\n".join(out) + "\n"


def write_atomic(path: Path, obj: object) -> None:
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def score(preds: list[Path], data: Path) -> dict[str, Any]:
    lines, files = read_preds(preds)
    truth = read_truth(data / "truth.json")
    league = _read_json(data / "league.json")
    labels = _labels(league, data / "league.json")
    for did, t in truth.items():
        if t["session"] not in labels:
            raise ScoreError(
                f"{data / 'truth.json'}: decision {did} names a session not in league.json."
            )
    inputs = _read_json(data / "inputs.json")
    if not isinstance(inputs, dict) or "catalogue" not in inputs:
        raise ScoreError(f"{data / 'inputs.json'}: no `catalogue`.")
    catalogue = _read_json(Path(inputs["catalogue"]))
    const = constants(data, truth)
    m4, m5 = marks45(lines, truth, const)
    return {
        "preds": files,
        "constants": const,
        "mark_1": mark1(lines, league, catalogue, labels),
        "mark_2": mark2(lines, truth, labels),
        "mark_3": mark3(lines, truth, labels),
        "mark_4": m4,
        "mark_5": m5,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("preds", nargs="+", help="ruling-line files (limits and contact)")
    ap.add_argument("--data", default=str(REPO / "data" / "racing"), help="the private folder")
    ap.add_argument("--out", default=None, help="the score file (default <data>/score.json)")
    args = ap.parse_args(argv)
    data = Path(args.data)
    out = Path(args.out) if args.out else data / "score.json"
    try:
        result = score([Path(p) for p in args.preds], data)
        write_atomic(out, result)
    except ScoreError as exc:
        print(f"racing_score: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
