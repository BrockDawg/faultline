"""Build the private racing inputs under data/racing/ from the league's own records. No model call.

Run from the repo root:  uv run python scripts/racing_prep.py [--data data/racing]

Reads `<data>/inputs.json`, a private file that names where each input lives (it is git-ignored
with the rest of `data/`, so no private path, stream id or league name sits in this script):

- `replays_dir`: the companion replay feeds, `replay-<subsession>.ndjson.gz`.
- `incidents_tsv`: the steward decisions export. It is not quoted CSV: rows end in LF, and a
  field's own line break is CR plus a literal backslash-n.
- `catalogue`: the 28 Oct catalogue (aligned sessions, stream offsets, decision joins).
- `answer_key_tsv`: the 27 Oct answer key (contact seconds and roles for 12 reports).
- `videos_dir` and `streams`: the broadcast file for each catalogue stream key.
- `pack_dir`, `pack_rule_id`: the league rules pack and the rule holding section 9.
- `season_one_subsessions`: the subsessions of Season 1, for the number map.

Writes, all inside `<data>`, sorted keys, UTF-8, `\\n` endings, no timestamps (two runs give
identical bytes):

- `league.json`: the 11 aligned race sessions (feed, stream, offset and its error, format and
  incident limit), the pack, and the number map from custId to league number.
- `reports.jsonl`: one protest per on-track decision with a feed match: the report fields, plus
  `session`, the race given as an input. A real steward always knows which race a protest is
  about, so the judge is told the race and does not find it. It comes from truth.json when that
  exists, else the catalogue's race join.
- `reports_nofeed.jsonl`: the same for the on-track decisions with no feed match; `session` is
  the catalogue's race where it names a subsession, else null.
- `truth.draft.json`: per decision, the three offender sources side by side, every disagreement
  as a conflict row (never resolved here), and the two offender constants with their scores.
  A key row that matches more than one decision is attached to none of them: each gets a
  blocking conflict and the draft it would carry under every possible assignment.

When `<data>/truth.json` (the table confirmed by hand) exists, both constants are rebuilt from it
under `constants.confirmed`: the car-behind guess is recomputed at each row's own session and
contact second, and a row with no contact second gets no guess. Its shape is one object with a
`decisions` list; each row holds `id` (decision id), `session` (`<subsession>/<session>`, one
of the aligned sessions), `offender_sim` (sim number or null), `victim_sim` (sim number or
null), `contact_te` (integer feed second or null), `contact_source` (`answer_key`, `video` or
null, null exactly when `contact_te` is), `duplicate_of` (null, or the id of the primary row
for the same incident), `verdict`, `confirmed_by` and `basis`. A row with `duplicate_of` set
is the same incident as its primary and is left out of every n, here and in
`scripts/racing_score.py`, which must do the same. A bad row refuses the whole file.

Refuses (exits with a message naming the file and the reason) when an input is missing, the
decisions file has a row of the wrong width, or one custId ran two numbers in Season 1.
Driver names are read into memory only, to resolve protest text to car numbers; no name is
written to any file except inside the protest fields of the two reports files, and none is
ever printed. Stdout carries counts only.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent

FEED_DECISIONS = ("1", "11", "13", "14", "15", "16", "18", "23", "24", "46")
NOFEED_DECISIONS = ("2", "3", "4", "5", "6", "7", "9", "10", "48")
REPORT_FIELDS = (
    "id",
    "created_at",
    "reporter_car",
    "involved",
    "description",
    "track",
    "race_number",
    "iracing_subsession_id",
)
# Given to the judge beside the report fields: a real steward always knows which race a
# protest is about, so the race is an input, not something the judge has to find.
GIVEN_FIELDS = ("session",)
OUTCOME_FIELDS = (
    "verdict",
    "penalty_points",
    "ruling_reason",
    "penalised",
    "penalised_car",
    "evidence_url",
)
FORMATS = {
    "2.1.1": {"sessions": ["FEATURE", "HEAT 1"], "incident_limit": 20, "clause": "9.2.1"},
    "2.1.2": {"sessions": ["RACE"], "incident_limit": 25, "clause": "9.2.2"},
}
OFFSET_ERROR_FLOOR_S = 2.0
TRACK_SHORT = {
    "Oulton Park Circuit": "Oulton",
    "Circuit de Spa-Francorchamps": "Spa",
    "Snetterton Racing Circuit": "Snetterton",
    "Brands Hatch Circuit": "Brands Hatch",
    "Donington Park Racing Circuit": "Donington",
    "Cadwell Park": "Cadwell",
    "Thruxton Circuit": "Thruxton",
}
CONSTANT_LEAD_S = 1
TRUTH_FIELDS = (
    "id",
    "session",
    "offender_sim",
    "victim_sim",
    "contact_te",
    "verdict",
    "confirmed_by",
    "basis",
    "contact_source",
    "duplicate_of",
)
CONTACT_SOURCES = ("answer_key", "video", None)


class PrepError(ValueError):
    """An input could not be read or joined; the message names the file and the reason."""


def numkey(n: object) -> tuple[int, str]:
    """Sort key for car numbers: digits as int first, anything else after, by text."""
    s = str(n)
    return (int(s), s) if s.isdigit() else (10**6, s)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.casefold()).split())


# ---------------------------------------------------------------- inputs


def _load_inputs(data: Path) -> dict[str, Any]:
    path = data / "inputs.json"
    if not path.is_file():
        raise PrepError(f"{path}: missing; it names where each private input lives.")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PrepError(f"{path}: is not valid JSON ({exc.msg}).") from exc
    need = (
        "answer_key_tsv",
        "catalogue",
        "incidents_tsv",
        "offset_error_override_s",
        "pack_dir",
        "pack_rule_id",
        "replays_dir",
        "season_one_subsessions",
        "streams",
        "videos_dir",
    )
    for key in need:
        if key not in cfg:
            raise PrepError(f"{path}: has no `{key}`.")
    for key in ("answer_key_tsv", "catalogue", "incidents_tsv"):
        if not Path(cfg[key]).is_file():
            raise PrepError(f"{path}: `{key}` points at a file that does not exist.")
    for key in ("pack_dir", "replays_dir", "videos_dir"):
        if not Path(cfg[key]).is_dir():
            raise PrepError(f"{path}: `{key}` points at a folder that does not exist.")
    # Per-session offset error, where the catalogue LOG found the witnesses further apart
    # than the floor (session key -> seconds); kept here so no subsession id sits in this script.
    over = cfg["offset_error_override_s"]
    if not isinstance(over, dict) or not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in over.values()
    ):
        raise PrepError(f"{path}: `offset_error_override_s` must map session keys to seconds.")
    return cfg


def read_decisions(path: Path) -> dict[str, dict[str, str | None]]:
    """The decisions export: split on LF only; a field's CR plus literal backslash-n is a break."""
    text = path.read_bytes().decode("utf-8", errors="replace")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    head = lines[0].rstrip("\r").split("\t")
    out: dict[str, dict[str, str | None]] = {}
    for i, ln in enumerate(lines[1:], start=2):
        cells = ln.rstrip("\r").split("\t")
        if len(cells) != len(head):
            raise PrepError(f"{path}: row {i} has {len(cells)} fields, the header has {len(head)}.")
        row = {
            k: (None if v == "NULL" else v.replace("\r", "").replace("\\n", "\n"))
            for k, v in zip(head, cells, strict=True)
        }
        out[str(row["id"])] = row
    return out


def read_answer_key(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    head = lines[0].split("\t")
    rows = []
    for ln in lines[1:]:
        if ln.strip():
            rows.append(dict(zip(head, ln.split("\t"), strict=False)))
    return rows


# ---------------------------------------------------------------- feeds


@dataclass
class Session:
    """One race session of a replay feed: per-car track position, lap, counter, custId, names."""

    key: str
    track: str = ""
    tes: list[int] = field(default_factory=list)
    pct: dict[str, dict[int, float]] = field(default_factory=lambda: defaultdict(dict))
    lap: dict[str, dict[int, int]] = field(default_factory=lambda: defaultdict(dict))
    inc: dict[str, dict[int, int]] = field(default_factory=lambda: defaultdict(dict))
    cust: dict[str, str] = field(default_factory=dict)  # sim number -> custId
    names: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # memory only

    def cars(self) -> list[str]:
        return sorted(set(self.pct) | set(self.lap), key=numkey)

    def counter_shown(self) -> bool:
        return all(self.inc.get(n) for n in self.cars())

    def frame_at_or_before(self, te: int) -> int | None:
        best = None
        for t in self.tes:
            if t <= te:
                best = t
        return best

    def order(self, n: str, te: int) -> float | None:
        """Track order at the last frame at or before te with both lap and pct: laps plus pct."""
        ts = [t for t in self.tes if t <= te and t in self.pct[n] and t in self.lap[n]]
        if not ts:
            return None
        return self.lap[n][ts[-1]] + self.pct[n][ts[-1]]


def load_feeds(replays: Path, keys: list[str]) -> dict[str, Session]:
    wanted: dict[str, list[str]] = defaultdict(list)
    for key in keys:
        sub, session = key.split("/", 1)
        wanted[sub].append(session)
    out: dict[str, Session] = {}
    for sub, sessions in sorted(wanted.items()):
        path = replays / f"replay-{sub}.ndjson.gz"
        if not path.is_file():
            raise PrepError(f"{path}: replay feed missing.")
        by_name = {s: Session(key=f"{sub}/{s}") for s in sessions}
        frames: dict[str, list[dict[str, Any]]] = defaultdict(list)
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                j = json.loads(line)
                if j.get("session") in by_name and j.get("timeElapsed") is not None:
                    frames[j["session"]].append(j)
        for s, fs in frames.items():
            fs.sort(key=lambda j: j["timeElapsed"])
            sess = by_name[s]
            sess.track = fs[0].get("track") or ""
            for j in fs:
                te = int(j["timeElapsed"])
                sess.tes.append(te)
                for p in j.get("positions") or []:
                    n = str(p["num"])
                    if p.get("pct") is not None:
                        sess.pct[n][te] = float(p["pct"])
                    if p.get("custId") is not None:
                        sess.cust[n] = str(p["custId"])
                    if p.get("name"):
                        sess.names[n].add(_norm(p["name"]))
                for r in j.get("rows") or []:
                    n = str(r["num"])
                    if r.get("inc", -1) != -1 and r.get("inc") is not None:
                        sess.inc[n][te] = int(r["inc"])
                    if r.get("lap") is not None:
                        sess.lap[n][te] = int(r["lap"])
                    if r.get("name"):
                        sess.names[n].add(_norm(r["name"]))
        for s, sess in by_name.items():
            if not sess.tes:
                raise PrepError(f"{path}: has no frames for session {s}.")
            out[sess.key] = sess
    return out


# ---------------------------------------------------------------- number map


def build_number_map(feeds: dict[str, Session], season_one: list[str]) -> dict[str, Any]:
    """custId -> league number: the number it ran in Season 1, else its first number after."""
    seen: dict[str, dict[str, str]] = defaultdict(dict)  # custId -> session key -> sim number
    for key in sorted(feeds):
        for n, cust in feeds[key].cust.items():
            seen[cust][key] = n
    entries = []
    users: dict[str, set[str]] = defaultdict(set)  # any number seen -> custIds that ran it
    for cust in sorted(seen, key=numkey):
        sims = seen[cust]
        for n in sims.values():
            users[n].add(cust)
        s1 = sorted({n for k, n in sims.items() if k.split("/")[0] in season_one}, key=numkey)
        if len(s1) > 1:
            raise PrepError(
                f"number map: a custId ran {len(s1)} numbers in Season 1 "
                f"(sessions {', '.join(sorted(k for k in sims if k.split('/')[0] in season_one))})."
            )
        league = s1[0] if s1 else sims[sorted(sims)[0]]
        entries.append(
            {
                "cust_id": cust,
                "league_num": league,
                "rule": "season_one" if s1 else "first_session_after",
                "sim_nums": dict(sorted(sims.items())),
            }
        )
    shared = sorted((n for n, cs in users.items() if len(cs) > 1), key=numkey)
    return {
        "rule": (
            "A custId's league number is the number it ran in Season 1. A custId first seen in"
            " Season 2 keeps its first Season 2 number. Numbers are reused by different drivers"
            " across sessions, so a written number resolves inside one session: a sim number"
            " present in that session reads as itself; otherwise it is the league number of a"
            " car present, and resolves to that car's sim number; a league number two cars"
            " present share resolves to nothing."
        ),
        "entries": entries,
        "numbers_run_by_more_than_one_custid": shared,
    }


class Numbers:
    """League and sim numbers of one session, through the number map."""

    def __init__(self, sess: Session, number_map: dict[str, Any]) -> None:
        self.sess = sess
        self.cust_league = {e["cust_id"]: e["league_num"] for e in number_map["entries"]}
        pairs = [(self.cust_league[c], n) for n, c in sess.cust.items() if c in self.cust_league]
        counts: dict[str, int] = defaultdict(int)
        for league, _ in pairs:
            counts[league] += 1
        self.league_sim = {league: n for league, n in pairs if counts[league] == 1}

    def to_sim(self, num: str | None) -> str | None:
        """A number a steward or protest wrote (a league number) to this session's sim number."""
        if not num:
            return None
        num = num.strip()
        if num in self.sess.cust or num in self.sess.lap:
            return num
        return self.league_sim.get(num)

    def to_league(self, sim: str | None) -> str | None:
        if sim is None:
            return None
        cust = self.sess.cust.get(sim)
        return self.cust_league.get(cust, sim) if cust else sim


# ---------------------------------------------------------------- names (memory only)


def resolve_name(text: str | None, sess: Session) -> tuple[str | None, str]:
    """A name to a sim number: the exact name, else every word of 3 letters or more in one name."""
    if not text:
        return None, "empty"
    q = _norm(re.sub(r"#\s?\d+", " ", text))
    if not q:
        return None, "no name"
    exact = sorted({n for n, names in sess.names.items() if q in names}, key=numkey)
    if len(exact) == 1:
        return exact[0], "full name"
    words = [w for w in q.split() if len(w) >= 3]
    if not words:
        return None, "unresolved"
    hits = sorted(
        {
            n
            for n, names in sess.names.items()
            if any(all(w in name.split() for w in words) for name in names)
        },
        key=numkey,
    )
    if len(hits) == 1:
        return hits[0], "name words"
    return None, "ambiguous" if hits else "unresolved"


def numbers_in(text: str | None) -> list[str]:
    t = text or ""
    found = re.findall(r"#\s?(\d{1,3})\b", t)
    found += re.findall(r"\b(?:Car|Nr\.?)\s*#?\s?(\d{1,3})\b", t, re.IGNORECASE)
    return found


def names_in(text: str | None, sess: Session) -> list[str]:
    """Cars whose full name, or a surname of 4 letters or more unique in the session, is in text."""
    low = f" {_norm(text or '')} "
    surnames: dict[str, set[str]] = defaultdict(set)
    for n, names in sess.names.items():
        for name in names:
            if name:
                surnames[name.split()[-1]].add(n)
    out = set()
    for n, names in sess.names.items():
        for name in names:
            if not name:
                continue
            last = name.split()[-1]
            if f" {name} " in low or (
                len(last) >= 4 and len(surnames[last]) == 1 and f" {last} " in low
            ):
                out.add(n)
    return sorted(out, key=numkey)


def involved_cars(report: dict[str, str | None], nums: Numbers) -> list[str]:
    """Sim numbers named in `involved`, in written order: a part's `#N` first, else its name."""
    out: list[str] = []
    for part in re.split(r"[;\n]|\band\b|&|,", report.get("involved") or ""):
        if not part.strip():
            continue
        sims = [s for s in (nums.to_sim(x) for x in numbers_in(part)) if s]
        if not sims:
            sim, _ = resolve_name(part, nums.sess)
            sims = [sim] if sim else []
        for s in sims:
            if s not in out:
                out.append(s)
    return out


def protest_cars(report: dict[str, str | None], nums: Numbers) -> list[str]:
    """Every car a protest names: reporter, involved, and numbers or names in the description."""
    cars = set(involved_cars(report, nums))
    rep = nums.to_sim(report.get("reporter_car"))
    if rep:
        cars.add(rep)
    for x in numbers_in(report.get("description")):
        s = nums.to_sim(x)
        if s:
            cars.add(s)
    cars |= set(names_in(report.get("description"), nums.sess))
    return sorted(cars, key=numkey)


# ---------------------------------------------------------------- constants


def car_behind(sess: Session, cars: list[str], contact_te: int) -> tuple[str | None, str]:
    """The car behind, 1 s before contact, in the closest pair of the protest's cars.

    At the last frame at or before contact - 1 s: take the protest's cars present; with one, pair
    it with the car nearest to it on track; the pair is the two closest; the car behind is the
    one later in track order (laps plus pct). No car present gives no guess.
    """
    t = sess.frame_at_or_before(contact_te - CONSTANT_LEAD_S)
    if t is None:
        return None, "no frame before contact"

    def gap(a: str, b: str) -> float:
        d = sess.pct[a][t] - sess.pct[b][t]
        d = d - 1 if d > 0.5 else d + 1 if d < -0.5 else d
        return abs(d)

    here = [c for c in cars if t in sess.pct[c]]
    if not here:
        return None, "no protest car in the feed at that second"
    if len(here) == 1:
        others = [c for c in sess.cars() if c != here[0] and t in sess.pct[c]]
        if not others:
            return None, "no other car at that second"
        here.append(min(others, key=lambda c: (gap(here[0], c), numkey(c))))
    pairs = [(gap(a, b), a, b) for i, a in enumerate(here) for b in here[i + 1 :]]
    _, a, b = min(pairs, key=lambda p: (p[0], numkey(p[1]), numkey(p[2])))
    oa, ob = sess.order(a, t), sess.order(b, t)
    if oa is None or ob is None or oa == ob:
        return None, "track order unknown"
    return (a if oa < ob else b), f"closest pair {sorted([a, b], key=numkey)}"


def accused(report: dict[str, str | None], nums: Numbers) -> tuple[str | None, str]:
    """The first car in `involved` that is not the reporter's car."""
    if not (report.get("involved") or "").strip():
        return None, "involved is empty"
    rep = nums.to_sim(report.get("reporter_car"))
    cars = involved_cars(report, nums)
    for c in cars:
        if c != rep:
            return c, "first involved car that is not the reporter"
    if cars:
        return None, "involved names only the reporter's car"
    return None, "involved resolves to no car in this session"


# ---------------------------------------------------------------- build


def build(data: Path) -> dict[str, int]:
    cfg = _load_inputs(data)
    catalogue = json.loads(Path(cfg["catalogue"]).read_text(encoding="utf-8"))
    decisions = read_decisions(Path(cfg["incidents_tsv"]))
    key_rows = read_answer_key(Path(cfg["answer_key_tsv"]))
    cat_dec = {d["id"]: d for d in catalogue["decisions"]}
    for did in FEED_DECISIONS + NOFEED_DECISIONS:
        if did not in decisions or did not in cat_dec:
            raise PrepError(f"decision {did}: missing from the decisions export or the catalogue.")

    session_keys = sorted(catalogue["sessions"])
    feeds = load_feeds(Path(cfg["replays_dir"]), session_keys)
    number_map = build_number_map(feeds, list(cfg["season_one_subsessions"]))

    # league.json
    sessions_out = {}
    for key in session_keys:
        cs = catalogue["sessions"][key]
        sub, name = key.split("/", 1)
        fmt = next(f for f, v in FORMATS.items() if name in v["sessions"])
        stream_file = cfg["streams"].get(cs["stream"])
        if not stream_file:
            raise PrepError(f"{data / 'inputs.json'}: no stream file for key {cs['stream']}.")
        stream = Path(cfg["videos_dir"]) / stream_file
        if not stream.is_file():
            raise PrepError(f"{stream}: stream file missing.")
        bracket = float(cs["offset"]["error_s"])
        sessions_out[key] = {
            "subsession": sub,
            "session": name,
            "track": cs["track"],
            "track_short": TRACK_SHORT.get(cs["track"], cs["track"]),
            "format": fmt,
            "incident_limit": FORMATS[fmt]["incident_limit"],
            "clause": FORMATS[fmt]["clause"],
            "feed": (Path(cfg["replays_dir"]) / f"replay-{sub}.ndjson.gz").as_posix(),
            "stream": stream.as_posix(),
            "offset_s": float(cs["offset"]["offset"]),
            "offset_bracket_s": bracket,
            "offset_error_s": float(
                cfg["offset_error_override_s"].get(key, max(OFFSET_ERROR_FLOOR_S, bracket))
            ),
            "counter_shown": feeds[key].counter_shown(),
            "cars": len(feeds[key].cars()),
        }
    league = {
        "formats": FORMATS,
        "offset_rule": (
            "video_t = te + offset_s; offset_error_s is the bracket half-width with a floor of"
            " 2.0 s, and 4.0 s for Brands Hatch HEAT 1 (catalogue LOG, section 2)."
        ),
        "pack": {"path": Path(cfg["pack_dir"]).as_posix(), "rule_id": cfg["pack_rule_id"]},
        "sessions": sessions_out,
        "number_map": number_map,
    }

    # truth, once it is confirmed by hand
    truth_path = data / "truth.json"
    truth_rows = _read_truth(truth_path, feeds) if truth_path.is_file() else None
    truth_session = {r["id"]: r["session"] for r in truth_rows or []}

    # reports: the report fields, plus the race given as an input
    def given_session(did: str) -> str | None:
        if did in truth_session:
            return truth_session[did]
        race = cat_dec[did].get("race") or {}
        if race.get("subsession") and race.get("session"):
            return f"{race['subsession']}/{race['session']}"
        return None

    def report_line(did: str) -> dict[str, Any]:
        row = decisions[did]
        line = {k: row.get(k) for k in REPORT_FIELDS}
        for k in GIVEN_FIELDS:
            line[k] = given_session(did)
        return line

    reports = [report_line(d) for d in sorted(FEED_DECISIONS, key=numkey)]
    nofeed = [report_line(d) for d in sorted(NOFEED_DECISIONS, key=numkey)]

    # truth draft
    def key_match(dec: dict[str, Any], row: dict[str, str]) -> bool:
        race = dec.get("race") or {}
        if race.get("subsession") != row["subsession"] or race.get("session") != row["session"]:
            return False
        if not row["lap"].isdigit() or int(row["lap"]) not in dec["laps"]:
            return False
        sess = feeds.get(f"{row['subsession']}/{row['session']}")
        if sess is None:
            return False
        nums = Numbers(sess, number_map)
        dec_sims = {nums.to_sim(c) or c for c in dec["cars_all"]}
        key_cars = {c for c in (row["car_a"], row["car_b"]) if c}
        return bool(key_cars) and key_cars <= dec_sims

    on_track = [d for d in catalogue["decisions"] if d["kind"] == "on_track"]
    key_claims: dict[str, list[str]] = {}
    for row in key_rows:
        hits = [d["id"] for d in on_track if key_match(d, row)]
        key_claims[row["report"]] = sorted(hits, key=numkey)
    key_by_report = {r["report"]: r for r in key_rows}

    rows_out = []
    conflicts = []
    for did in sorted(FEED_DECISIONS, key=numkey):
        dec, tsv = cat_dec[did], decisions[did]
        race = dec["race"]
        skey = f"{race['subsession']}/{race['session']}"
        sess = feeds[skey]
        nums = Numbers(sess, number_map)

        cat_off_league = dec.get("penalised_car")
        src_cat = {
            "verdict": dec["verdict"],
            "offender_league": cat_off_league,
            "offender_sim": nums.to_sim(cat_off_league),
            "cars_all": dec["cars_all"],
        }
        claims = [rid for rid, hits in key_claims.items() if did in hits]
        # A key row that matches exactly one decision is its source; a row that matches several
        # is attached to none of them until a person says which.
        owned = [rid for rid in claims if len(key_claims[rid]) == 1]
        ambiguous = [rid for rid in claims if len(key_claims[rid]) > 1]
        src_key = _key_source(key_by_report[owned[0]]) if owned else None
        tsv_sim, tsv_how = resolve_name(tsv.get("penalised"), sess)
        src_tsv = {"verdict": tsv.get("verdict"), "offender_sim": tsv_sim, "resolved_by": tsv_how}

        dconf: list[dict[str, Any]] = []

        def conflict(
            kind: str, note: str, blocking: bool, did: str = did, dconf: list = dconf
        ) -> None:
            dconf.append({"blocking": blocking, "decision": did, "kind": kind, "note": note})

        for c in dec.get("join_conflicts") or []:
            conflict("session", f"catalogue race join: {c}", False)
        assignments = []
        for rid in ambiguous:
            held = key_claims[rid]
            conflict(
                "key_join",
                f"answer key report {rid} matches decisions {', '.join(held)} by session, lap and"
                " cars; it is attached to none until a person says which",
                True,
            )
            for target in held:
                alt_key = _key_source(key_by_report[rid]) if target == did else src_key
                alt, alt_found = _draft(src_cat, alt_key, src_tsv, nums)
                assignments.append(
                    {
                        "key_report": rid,
                        "assigned_to": target,
                        "draft": alt,
                        "source_conflicts": [f"{k}: {note}" for k, note in alt_found],
                    }
                )
        for kr in key_rows:
            if kr["report"] in claims or kr["subsession"] + "/" + kr["session"] != skey:
                continue
            if not kr["lap"].isdigit() or int(kr["lap"]) not in dec["laps"]:
                continue
            shared = sorted(
                {c for c in (kr["car_a"], kr["car_b"]) if c}
                & {nums.to_sim(c) or c for c in dec["cars_all"]},
                key=numkey,
            )
            if shared:
                held = key_claims[kr["report"]]
                conflict(
                    "key_partial",
                    f"answer key report {kr['report']} (same session and lap, cars"
                    f" {kr['car_a']} and {kr['car_b']}) shares car {', '.join(shared)} with this"
                    f" decision but not both cars"
                    + (f"; it matches decision {', '.join(held)}" if held else ""),
                    False,
                )
        if src_key and src_key["report"] != did:
            conflict(
                "key_join", f"answer key report id {src_key['report']} differs from {did}", False
            )
        draft, source_conflicts = _draft(src_cat, src_key, src_tsv, nums)
        for kind, note in source_conflicts:
            conflict(kind, note, kind in ("offender", "verdict"))
        if src_tsv["offender_sim"] is None and tsv.get("penalised"):
            conflict("offender", f"decisions file penalised name {src_tsv['resolved_by']}", True)
        if cat_off_league and src_cat["offender_sim"] and cat_off_league != src_cat["offender_sim"]:
            conflict(
                "number_map",
                f"league #{cat_off_league} is sim #{src_cat['offender_sim']} in this session"
                " (same custId)",
                False,
            )
        if cat_off_league and src_cat["offender_sim"] is None:
            conflict("number_map", f"league #{cat_off_league} has no car in this session", True)

        blocking = [c for c in dconf if c["blocking"]]
        if blocking:
            draft["offender_sim"] = None
            draft["offender_league"] = None
        draft["open_conflicts"] = len(blocking)
        contact = draft["contact_te"]
        rows_out.append(
            {
                "id": did,
                "session": skey,
                "session_chosen_by": dec.get("join_rule"),
                "track_short": TRACK_SHORT.get(sess.track, sess.track),
                "laps": dec["laps"],
                "counter": "shown" if sess.counter_shown() else "no counter",
                "sources": {"catalogue": src_cat, "answer_key": src_key, "tsv": src_tsv},
                "draft": draft,
                "key_assignments": assignments,
                "locator_scorable": contact is not None,
                "conflicts": dconf,
            }
        )
        conflicts.extend(dconf)

    # constants
    report_by_id = {r["id"]: r for r in reports}
    spec = [
        {
            "id": r["id"],
            "session": r["session"],
            "contact_te": r["draft"]["contact_te"],
            "offender_sim": r["draft"]["offender_sim"],
            "duplicate_of": None,
        }
        for r in rows_out
    ]
    const_rows = _constant_rows(spec, report_by_id, feeds, number_map)
    n, score_b, score_a = _score(const_rows)
    confirmed = None
    if truth_rows is not None:
        c_rows = _constant_rows(truth_rows, report_by_id, feeds, number_map)
        c_n, c_b, c_a = _score(c_rows)
        confirmed = {
            "duplicates_excluded": sorted(
                (r["id"] for r in c_rows if r["duplicate_of"]), key=numkey
            ),
            "n": c_n,
            "car_behind_score": c_b,
            "accused_score": c_a,
            "better": _better(c_b, c_a),
            "rows": c_rows,
        }
    constants = {
        "definitions": {
            "car_behind": (
                "At the last frame at or before the truth contact second minus 1 s, the two"
                " closest of the protest's cars (reporter, involved, numbers and names in the"
                " description; one car is paired with its nearest car on track); the one later"
                " in track order (laps plus pct). No truth contact second gives no guess."
            ),
            "accused": "The first car named in `involved` that is not the reporter's car.",
        },
        "scored_on": "decisions whose draft offender has no open conflict",
        "n": n,
        "car_behind_score": score_b,
        "accused_score": score_a,
        "better": _better(score_b, score_a),
        "rows": const_rows,
        "confirmed": confirmed,
        "rescore_note": (
            "Scored against the draft offender and contact second; once truth.json exists, a"
            " rerun rebuilds both constants from its own sessions, contact seconds and"
            " offenders under `confirmed`. The definitions above are fixed."
        ),
    }

    unmatched_key = sorted(
        (
            {"report": rid, "session": f"{r['subsession']}/{r['session']}", "lap": r["lap"]}
            for rid, r in key_by_report.items()
            if not key_claims[rid]
        ),
        key=lambda x: numkey(x["report"]),
    )
    truth = {
        "status": "draft: each row is confirmed by hand before truth.json is written",
        "join_rules": {
            "session": "the catalogue's race join (ruling text, then form fields, then race day)",
            "answer_key": (
                "same subsession and session, key lap among the decision's laps, and both key"
                " cars inside the decision's cars (through the number map); never by id; a key"
                " row that matches several decisions is attached to none, with a blocking"
                " conflict on each and every possible assignment listed under key_assignments"
            ),
            "tsv_name": (
                "the decisions file's penalised name, without any #N, matched to the session"
                " feed's names (exact, then every word of 3 letters or more); in memory only"
            ),
            "draft_offender": (
                "set only when every source that gives an offender agrees, the verdicts agree,"
                " the verdict is penalty, and the decision has no blocking conflict"
            ),
        },
        "decisions": rows_out,
        "conflicts": conflicts,
        "constants": constants,
        "answer_key_rows_unmatched": unmatched_key,
    }

    data.mkdir(parents=True, exist_ok=True)
    _write_json(data / "league.json", league)
    _write_lines(data / "reports.jsonl", reports)
    _write_lines(data / "reports_nofeed.jsonl", nofeed)
    _write_json(data / "truth.draft.json", truth)
    return {
        "sessions": len(sessions_out),
        "sessions_with_counter": sum(s["counter_shown"] for s in sessions_out.values()),
        "number_map_entries": len(number_map["entries"]),
        "number_map_renumbered": sum(
            len(set(e["sim_nums"].values())) > 1 for e in number_map["entries"]
        ),
        "reports": len(reports),
        "reports_nofeed": len(nofeed),
        "decisions_with_contact_te": sum(r["locator_scorable"] for r in rows_out),
        "decisions_with_draft_offender": n,
        "conflict_rows": len(conflicts),
        "car_behind_score": score_b,
        "accused_score": score_a,
        "answer_key_rows_unmatched": len(unmatched_key),
        "truth_rows": len(truth_rows) if truth_rows is not None else 0,
        "confirmed_duplicates_excluded": len(confirmed["duplicates_excluded"]) if confirmed else 0,
        "confirmed_n": confirmed["n"] if confirmed else 0,
        "confirmed_car_behind_score": confirmed["car_behind_score"] if confirmed else 0,
        "confirmed_accused_score": confirmed["accused_score"] if confirmed else 0,
    }


def _key_source(kr: dict[str, str]) -> dict[str, Any]:
    off = kr["penalised"] if kr["penalised"] not in ("", "unresolved") else None
    return {
        "report": kr["report"],
        "verdict": kr["verdict"],
        "offender_sim": off,
        "offender_note": "unresolved" if kr["penalised"] == "unresolved" else None,
        "victim_sim": kr["victim"] or None,
        "contact_te": int(kr["closest_te"]) if kr["closest_te"].isdigit() else None,
        "lap": int(kr["lap"]),
    }


def _draft(
    src_cat: dict[str, Any],
    src_key: dict[str, Any] | None,
    src_tsv: dict[str, Any],
    nums: Numbers,
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """The draft row the three sources give, and the source disagreements found on the way."""
    found: list[tuple[str, str]] = []
    verdicts = {"catalogue": src_cat["verdict"]}
    if src_key:
        verdicts["answer_key"] = src_key["verdict"]
    if len(set(verdicts.values())) > 1:
        found.append(("verdict", " vs ".join(f"{k} {v}" for k, v in sorted(verdicts.items()))))
    offs = {
        "catalogue": src_cat["offender_sim"],
        "answer_key": src_key["offender_sim"] if src_key else None,
        "tsv_name": src_tsv["offender_sim"],
    }
    given = {k: v for k, v in offs.items() if v}
    if len(set(given.values())) > 1:
        found.append(
            (
                "offender",
                " vs ".join(f"{k} {v}" for k, v in sorted(given.items())) + " (sim numbers)",
            )
        )
    if src_key and src_key["offender_note"] == "unresolved":
        found.append(("offender", "answer key leaves the offender unresolved"))
    if src_cat["verdict"] == "penalty" and not given and not (src_key and src_key["offender_note"]):
        found.append(("offender", "verdict penalty, and no source names an offender"))
    verdict = src_cat["verdict"] if len(set(verdicts.values())) == 1 else None
    offender = None
    if not found and given and verdict == "penalty":
        offender = next(iter(given.values()))
    victim = src_key["victim_sim"] if src_key else None
    return {
        "verdict": verdict,
        "offender_sim": offender,
        "offender_league": nums.to_league(offender),
        "victim_sim": victim,
        "victim_league": nums.to_league(victim),
        "contact_te": src_key["contact_te"] if src_key else None,
    }, found


def _constant_rows(
    spec: list[dict[str, Any]],
    reports: dict[str, dict[str, Any]],
    feeds: dict[str, Session],
    number_map: dict[str, Any],
) -> list[dict[str, Any]]:
    """Both constants per decision, from that decision's session, contact second and offender."""
    rows = []
    for d in spec:
        sess = feeds[d["session"]]
        nums = Numbers(sess, number_map)
        rep = reports[d["id"]]
        if d["contact_te"] is None:
            behind, why_b = None, "no truth contact second"
        else:
            behind, why_b = car_behind(sess, protest_cars(rep, nums), int(d["contact_te"]))
        acc, why_a = accused(rep, nums)
        rows.append(
            {
                "id": d["id"],
                "session": d["session"],
                "contact_te": d["contact_te"],
                "truth_offender_sim": d["offender_sim"],
                "duplicate_of": d["duplicate_of"],
                "car_behind": behind,
                "car_behind_why": why_b,
                "accused": acc,
                "accused_why": why_a,
            }
        )
    return rows


def _score(rows: list[dict[str, Any]]) -> tuple[int, int, int]:
    scored = [r for r in rows if r["truth_offender_sim"] and not r["duplicate_of"]]
    b = sum(r["car_behind"] == r["truth_offender_sim"] for r in scored)
    a = sum(r["accused"] == r["truth_offender_sim"] for r in scored)
    return len(scored), b, a


def _better(b: int, a: int) -> str:
    return "tie" if a == b else "car_behind" if b > a else "accused"


def _read_truth(path: Path, feeds: dict[str, Session]) -> list[dict[str, Any]]:
    """The truth.json rows, checked field by field; any bad row refuses the whole file."""
    try:
        truth = json.loads(path.read_text(encoding="utf-8"))
        rows = truth["decisions"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PrepError(f"{path}: cannot read `decisions` ({exc}).") from exc
    out = []
    for i, d in enumerate(rows):
        if not isinstance(d, dict):
            raise PrepError(f"{path}: decisions[{i}] is not an object.")
        for k in TRUTH_FIELDS:
            if k not in d:
                raise PrepError(f"{path}: decisions[{i}] has no `{k}`.")
        did = str(d["id"])
        if did not in FEED_DECISIONS:
            raise PrepError(f"{path}: decisions[{i}] names decision {did}, which has no report.")
        if d["session"] not in feeds:
            raise PrepError(f"{path}: decision {did} names session {d['session']}, not aligned.")
        te = d["contact_te"]
        if te is not None and (not isinstance(te, int) or isinstance(te, bool)):
            raise PrepError(f"{path}: decision {did} `contact_te` must be an integer or null.")
        if d["contact_source"] not in CONTACT_SOURCES:
            raise PrepError(
                f"{path}: decision {did} `contact_source` must be answer_key, video or null."
            )
        if (te is None) != (d["contact_source"] is None):
            raise PrepError(
                f"{path}: decision {did} has a contact second without a source, or the reverse."
            )
        out.append(
            {
                "id": did,
                "session": d["session"],
                "contact_te": te,
                "offender_sim": d["offender_sim"],
                "duplicate_of": None if d["duplicate_of"] is None else str(d["duplicate_of"]),
            }
        )
    ids = [r["id"] for r in out]
    if len(set(ids)) != len(ids):
        raise PrepError(f"{path}: a decision id appears twice.")
    primary = {r["id"] for r in out if r["duplicate_of"] is None}
    for r in out:
        dup = r["duplicate_of"]
        if dup is not None and dup not in primary:
            raise PrepError(
                f"{path}: decision {r['id']} is a duplicate of {dup}, which is not a primary row."
            )
    return sorted(out, key=lambda r: numkey(r["id"]))


def _write_json(path: Path, obj: object) -> None:
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_lines(path: Path, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        for k in OUTCOME_FIELDS:
            if k in row:
                raise PrepError(f"{path}: refusing to write outcome field `{k}`.")
    text = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows)
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=str(REPO / "data" / "racing"), help="the private folder")
    args = ap.parse_args(argv)
    try:
        counts = build(Path(args.data))
    except PrepError as exc:
        print(f"racing_prep: {exc}", file=sys.stderr)
        return 1
    for k, v in counts.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
