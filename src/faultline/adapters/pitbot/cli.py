"""The `faultline racing` commands: incident-limit rulings and the protest judge (locate stage).

`register(parser)` adds two sub-commands to the `racing` parser built by `faultline.cli`:

`faultline racing limits --league <league.json> --out <preds.jsonl>`: every session's
incident-limit rulings (`limits.limits_for_league`), each with its `record` and bundle.

`faultline racing judge <reports.jsonl> [...] --league <league.json> --rules <packdir>
--out <preds.jsonl> --stage locate|frames|rule [--known-names <file>]`: one `contact` ruling
per protest line. Only `locate` is built; `frames` and `rule` exit 2 with a one-line message
before anything is read. Per report, in this order:

1. no `session` on the report: `unable_to_rule`, `NO_SESSION`, window `{"session": null}`;
2. a session absent from `league.json`, or one with no `feed`: `unable_to_rule`, `NO_FEED`,
   window `{"session": <session>}`;
3. a session with no stream offset: `unable_to_rule`, `NO_OFFSET`, window session only;
4. `protest.normalise` against the session's feed, then `locator.locate` on `all_events`;
   a `Refusal` gives `unable_to_rule` with the locator's own `missing_fact`;
5. on a `Window`: the closed set (`roster.closed_set`), as pre-registered: every car within
   `NEAR_M` metres of a protest car over the window padded `PAD_S` seconds either side. The
   focus is the protest cars the feed holds (the normalised cars plus the reporter's car),
   never the window event's own cars; out-of-world readings are dropped first. No protest car
   in the feed, or no protest car seen in the padded window, is an empty set and gives
   `unable_to_rule`, `EMPTY_SET`, with the session only on the line (the window found stays
   in `detail.locate.window`); otherwise `steward_review` with the
   window, the sorted candidates and `facts.facts` over the window.

Every line has the plan's ruling shape: `kind` "contact", `rule` from `league.json`
`pack.rule_id` (it must exist in the `--rules` pack), `clause` null, `offender` and `victim`
null, `frames` [], `model_read` null, and an `evidence` sentence of 40 to 600 characters built
here. `window.stream_s` is the padded window plus the session's `offset_s`, 1 decimal.

Names. The lint names are every driver name in every session feed of `league.json`, plus the
lines of `--known-names` (UTF-8, one name per line) when given; the same list is the
normaliser's `known_names`. Every text that leaves this module (each fact, the evidence, the
missing fact, the normalised protest and its unresolved placeholders)
passes `lint.assert_clean` against them before anything is written. Only the
fixed word list `ALLOW` is exempt, because the fact sheet's own wording uses it.

Records. Each line's bundle (see `faultline.cli`) holds, as `inputs`: the command, stage and
domain; the sha256 of the report's canonical JSON (the report text itself is never stored);
the session entry without its file paths; the feed file's sha256; the rule id and the sha256
of its text; the sha256 of the number map and of the sorted name list; the closed-set
parameters. `detail.locate` holds the window's contact second, its event, the candidates with
their gaps and the normalised (name-free) protest. Lines are sorted by id with `numkey`.

Refusals raise `RacingCliError` naming the file or report and the reason.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from faultline import cli, lint, record
from faultline.adapters.pitbot import DOMAIN
from faultline.adapters.pitbot.events import Event, all_events
from faultline.adapters.pitbot.facts import facts
from faultline.adapters.pitbot.feed import Feed
from faultline.adapters.pitbot.limits import limits_for_league
from faultline.adapters.pitbot.locator import Refusal, locate
from faultline.adapters.pitbot.protest import normalise, read_reports
from faultline.pack import load_pack
from faultline.roster import closed_set, numkey

__all__ = [
    "ALLOW",
    "BUILT_STAGES",
    "EMPTY_SET",
    "NEAR_M",
    "NO_FEED",
    "NO_OFFSET",
    "NO_SESSION",
    "PAD_S",
    "STAGES",
    "RacingCliError",
    "judge",
    "limits",
    "register",
]

STAGES = ("locate", "frames", "rule")
BUILT_STAGES = ("locate",)
NO_SESSION = "the protest names no session"
NO_FEED = "no feed for the session"
NO_OFFSET = "the stream has no offset"
EMPTY_SET = "the closed set is empty"
NEAR_M = 8.0
PAD_S = 3
# Words the fact sheet itself writes that a name token could also be ("rose": a counter rose).
ALLOW = ("rose",)
_PATH_KEYS = ("feed", "stream")
_EVIDENCE_MIN, _EVIDENCE_MAX = 40, 600


class RacingCliError(ValueError):
    """A racing command was refused; the message names the file or report and the reason."""


# ---------------------------------------------------------------- the league


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _League:
    """league.json in memory, with each session's feed, events and names loaded once."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise RacingCliError(
                f"{path}: cannot be read ({exc.strerror or type(exc).__name__})."
            ) from None
        except json.JSONDecodeError:
            raise RacingCliError(f"{path}: not JSON.") from None
        if not isinstance(data, dict):
            raise RacingCliError(f"{path}: not a JSON object.")
        pack = data.get("pack")
        rule_id = pack.get("rule_id") if isinstance(pack, dict) else None
        if not isinstance(rule_id, str) or not rule_id:
            raise RacingCliError(f"{path}: pack.rule_id is missing.")
        sessions = data.get("sessions")
        if not isinstance(sessions, dict):
            raise RacingCliError(f"{path}: sessions is not an object.")
        number_map = data.get("number_map", {})
        if not isinstance(number_map, dict):
            raise RacingCliError(f"{path}: number_map is not an object.")
        self.rule_id: str = rule_id
        self.sessions: dict[str, Any] = sessions
        self.number_map: dict[str, Any] = number_map
        self._feeds: dict[str, Feed] = {}
        self._events: dict[str, list[Event]] = {}
        self._names: dict[str, list[str]] = {}
        self._shas: dict[str, str] = {}

    def entry(self, key: str) -> dict[str, Any] | None:
        entry = self.sessions.get(key)
        if entry is None:
            return None
        if not isinstance(entry, dict):
            raise RacingCliError(f"{self.path}: session {key!r} is not an object.")
        return entry

    def has_feed(self, key: str) -> bool:
        entry = self.entry(key)
        return entry is not None and isinstance(entry.get("feed"), str) and bool(entry["feed"])

    def public_entry(self, key: str) -> dict[str, Any]:
        """The session entry without its file paths: what a record may hash."""
        entry = self.entry(key) or {}
        return {k: v for k, v in entry.items() if k not in _PATH_KEYS}

    def feed(self, key: str) -> Feed:
        if key not in self._feeds:
            entry = self.entry(key)
            if entry is None or not self.has_feed(key):
                raise RacingCliError(f"{self.path}: session {key!r} has no feed.")
            if not isinstance(entry.get("session"), str):
                raise RacingCliError(f"{self.path}: session {key!r} has no session name.")
            self._feeds[key] = Feed.load(entry["feed"], entry["session"])
        return self._feeds[key]

    def events(self, key: str) -> list[Event]:
        if key not in self._events:
            self._events[key] = all_events(self.feed(key))
        return self._events[key]

    def feed_sha(self, key: str) -> str:
        if key not in self._shas:
            entry = self.entry(key)
            if entry is None or not self.has_feed(key):
                raise RacingCliError(f"{self.path}: session {key!r} has no feed.")
            self._shas[key] = record.file_sha256(entry["feed"])
        return self._shas[key]

    def session_names(self, key: str) -> list[str]:
        if key not in self._names:
            self._names[key] = sorted(set(self.feed(key).private_names().values()))
        return self._names[key]

    def all_names(self) -> list[str]:
        names: set[str] = set()
        for key in self.sessions:
            if self.has_feed(key):
                names.update(self.session_names(key))
        return sorted(names)


def _label(league: _League, key: str) -> str:
    """The session's own name ("HEAT 1"), never the slash-joined id the lint reads as a path."""
    entry = league.entry(key) or {}
    name = entry.get("session")
    return name if isinstance(name, str) and name else key.rsplit("/", 1)[-1]


def _assert_clean(rid: str, texts: list[str], names: list[str]) -> None:
    for text in texts:
        try:
            lint.assert_clean(text, names=names, allow=ALLOW)
        except lint.LintError as exc:
            raise RacingCliError(
                f"ruling {rid}: an outgoing text failed the leak lint: {exc}"
            ) from None


def _check_evidence(rid: str, evidence: str) -> str:
    if not _EVIDENCE_MIN <= len(evidence) <= _EVIDENCE_MAX:
        raise RacingCliError(
            f"ruling {rid}: evidence is {len(evidence)} characters, "
            f"outside {_EVIDENCE_MIN} to {_EVIDENCE_MAX}."
        )
    return evidence


def _sort_pairs(pairs: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, dict[str, Any]]]:
    ids = [bundle["ruling"]["id"] for _sha, bundle in pairs]
    dupes = sorted({i for i in ids if ids.count(i) > 1}, key=numkey)
    if dupes:
        raise RacingCliError(f"ruling ids appear more than once: {dupes}.")
    return sorted(pairs, key=lambda pair: numkey(pair[1]["ruling"]["id"]))


# ---------------------------------------------------------------- limits


def limits(league_path: Path | str, out: Path | str) -> Path:
    """Write every session's incident-limit rulings, with records, to `out`."""
    league = _League(Path(league_path))
    by_id = {
        f"{e.get('subsession')}/{e.get('session')}": key
        for key, e in league.sessions.items()
        if isinstance(e, dict)
    }
    pairs: list[tuple[str, dict[str, Any]]] = []
    for ruling in limits_for_league(league.path):
        rid = str(ruling["id"])
        window = ruling.get("window")
        session_id = window.get("session") if isinstance(window, dict) else None
        if session_id not in by_id:
            raise RacingCliError(
                f"{league.path}: ruling {rid} names a session the league does not hold."
            )
        key = by_id[session_id]
        texts = [*ruling["facts"], ruling["evidence"]]
        if ruling["missing_fact"]:
            texts.append(ruling["missing_fact"])
        _assert_clean(rid, texts, league.session_names(key))
        _check_evidence(rid, ruling["evidence"])
        inputs = {
            "command": "limits",
            "domain": DOMAIN,
            "feed_sha256": league.feed_sha(key),
            "rule_id": league.rule_id,
            "session": league.public_entry(key),
        }
        pairs.append(cli.bundle_for(inputs, ruling))
    return cli.write_rulings(out, _sort_pairs(pairs))


# ---------------------------------------------------------------- judge


def _contact(
    rid: str,
    rule_id: str,
    verdict: str,
    missing_fact: str | None,
    window: dict[str, Any],
    candidates: list[str],
    fact_lines: list[str],
    evidence: str,
) -> dict[str, Any]:
    return {
        "id": rid,
        "kind": "contact",
        "rule": rule_id,
        "clause": None,
        "verdict": verdict,
        "missing_fact": missing_fact,
        "window": window,
        "candidates": candidates,
        "offender": None,
        "victim": None,
        "facts": fact_lines,
        "frames": [],
        "model_read": None,
        "evidence": evidence,
    }


def _cars_text(nums: list[str]) -> str:
    items = [f"car {n}" for n in nums]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _refusal_evidence(rid: str, missing: str, label: str | None) -> str:
    where = f" in the {label} session" if label else ""
    return f"Report {rid} could not be placed in the feed{where}: {missing}."


def _empty_set_evidence(rid: str, label: str, te: list[int]) -> str:
    return (
        f"Report {rid}: a feed event in the {label} session holds a protest car from second "
        f"{te[0]} to second {te[1]}, but no protest car has a position in the feed over that "
        f"window plus or minus {PAD_S} seconds, so {EMPTY_SET}."
    )


def _window_evidence(
    rid: str, label: str, window: dict[str, Any], why: str, car_only: bool, cands: list[str]
) -> str:
    te_lo, te_hi = window["te"]
    lap = "an unknown leader lap" if window["lap"] is None else f"leader lap {window['lap']}"
    s_lo, s_hi = window["stream_s"]
    head = (
        f"Report {rid}: the feed places this protest in the {label} session from second "
        f"{te_lo} to second {te_hi}, {lap}, stream seconds {s_lo} to {s_hi} "
        f"(plus or minus {window['offset_error_s']} seconds)."
    )
    scope = " No lap was stated, so the whole session was searched." if car_only else ""
    tail = f" The closed set holds {len(cands)} cars: {_cars_text(cands)}."
    text = head + " " + why + scope + tail
    if len(text) > _EVIDENCE_MAX:
        text = head + " " + why + scope + f" The closed set holds {len(cands)} cars."
    if len(text) > _EVIDENCE_MAX:
        text = head + scope + f" The closed set holds {len(cands)} cars."
    return text


def _focus_positions(feed: Feed, te_lo: int, te_hi: int) -> dict[int, dict[str, float]]:
    """Positions over the padded window, with any out-of-world (negative) reading dropped."""
    raw = feed.positions_by_te(te_lo - PAD_S, te_hi + PAD_S)
    return {te: {n: v for n, v in frame.items() if v >= 0} for te, frame in raw.items()}


def _judge_one(
    rep: dict[str, Any],
    league: _League,
    rule_in: dict[str, str],
    names: list[str],
    names_sha: str,
    stage: str,
) -> tuple[str, dict[str, Any]]:
    rid = str(rep.get("id"))
    raw_key = rep.get("session")
    key = raw_key if isinstance(raw_key, str) and raw_key else None
    inputs: dict[str, Any] = {
        "command": "judge",
        "domain": DOMAIN,
        "feed_sha256": None,
        "known_names_sha256": names_sha,
        "number_map_sha256": record.record_hash(league.number_map),
        "params": {"near_m": NEAR_M, "pad_s": PAD_S},
        "report_sha256": record.record_hash(rep),
        "rule": rule_in,
        "session": None,
        "stage": stage,
    }

    def refuse(
        missing: str,
        window: dict[str, Any],
        label: str | None,
        detail: Any = None,
        evidence: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        if evidence is None:
            evidence = _refusal_evidence(rid, missing, label)
        _assert_clean(rid, [missing, evidence], names)
        _check_evidence(rid, evidence)
        ruling = _contact(rid, rule_in["id"], "unable_to_rule", missing, window, [], [], evidence)
        return cli.bundle_for(inputs, ruling, {"locate": detail} if detail else None)

    if key is None:
        return refuse(NO_SESSION, {"session": None}, None)
    if not league.has_feed(key):
        return refuse(NO_FEED, {"session": key}, None)
    inputs["session"] = league.public_entry(key)
    inputs["feed_sha256"] = league.feed_sha(key)
    label = _label(league, key)
    entry = league.entry(key) or {}
    offset_s, offset_error_s = entry.get("offset_s"), entry.get("offset_error_s")
    if offset_s is None:
        return refuse(NO_OFFSET, {"session": key}, label)

    feed, events = league.feed(key), league.events(key)
    norm = normalise(rep, feed, league.number_map, known_names=names)
    norm_detail = {
        "cars": list(norm.cars),
        "laps": list(norm.laps),
        "last_lap": norm.last_lap,
        "reporter_car": norm.reporter_car,
        "text": norm.text,
        "unresolved": list(norm.unresolved),
    }
    # Everything from the protest that the bundle keeps passes the lint too: an unresolved
    # reporter number is copied as written and is not part of the normaliser's own lint.
    _assert_clean(rid, [norm.text, *norm.unresolved], names)
    found = locate(norm, feed, events, offset_s, offset_error_s)
    if isinstance(found, Refusal):
        return refuse(found.missing_fact, {"session": key}, label, {"normalised": norm_detail})

    assert found.stream_s is not None
    window = {
        "session": key,
        "te": [found.te_lo, found.te_hi],
        "lap": found.lap,
        "stream_s": list(found.stream_s),
        "offset_error_s": found.offset_error_s,
    }
    focus = set(norm.cars)
    if norm.reporter_car:
        focus.add(norm.reporter_car)
    focus &= set(feed.nums)
    cands = []
    if focus:
        positions = _focus_positions(feed, found.te_lo, found.te_hi)
        cands = closed_set(
            positions, feed.track_m, focus, found.te_lo, found.te_hi, near_m=NEAR_M, pad_s=PAD_S
        )
    detail = {
        "candidates": [
            {"closest_m": c.closest_m, "num": c.num, "relation": c.relation, "why": c.why}
            for c in cands
        ],
        "car_only": found.car_only,
        "contact_te": found.contact_te,
        "event_cars": list(found.event_cars),
        "event_kind": found.event_kind,
        "focus": sorted(focus, key=numkey),
        "normalised": norm_detail,
        "protest_cars_held": list(found.protest_cars_held),
        "why": found.why,
        "window": window,
    }
    if not cands:
        # A refused line carries the session only; the window found stays in the detail.
        evidence = _empty_set_evidence(rid, label, [found.te_lo, found.te_hi])
        return refuse(EMPTY_SET, {"session": key}, label, detail, evidence)
    nums = [c.num for c in cands]
    fact_lines = facts(feed, events, nums, found.te_lo, found.te_hi, found.contact_te)
    evidence = _window_evidence(rid, label, window, found.why, found.car_only, nums)
    _assert_clean(rid, [*fact_lines, evidence], names)
    _check_evidence(rid, evidence)
    ruling = _contact(
        rid, rule_in["id"], "steward_review", None, window, nums, fact_lines, evidence
    )
    return cli.bundle_for(inputs, ruling, {"locate": detail})


def _read_known_names(path: Path | None) -> list[str]:
    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise RacingCliError(
            f"{path}: cannot be read ({exc.strerror or type(exc).__name__})."
        ) from None
    return [line.strip() for line in text.splitlines() if line.strip()]


def judge(
    reports: list[Path | str],
    league_path: Path | str,
    rules: Path | str,
    out: Path | str,
    stage: str,
    known_names: Path | str | None = None,
) -> Path:
    """Write one contact ruling per report line, with records, to `out` (locate stage only)."""
    if stage not in STAGES:
        raise RacingCliError(f"stage {stage!r} is not one of {list(STAGES)}.")
    if stage not in BUILT_STAGES:
        raise RacingCliError(
            f"stage {stage!r} arrives in a later checkpoint; only 'locate' is built."
        )
    league = _League(Path(league_path))
    pack = load_pack(rules)
    rule = next((r for r in pack.rules if r.id == league.rule_id), None)
    if rule is None:
        raise RacingCliError(f"{rules}: the pack has no rule {league.rule_id!r}.")
    rule_in = {"id": rule.id, "text_sha256": _sha_text(rule.text)}
    extra = _read_known_names(None if known_names is None else Path(known_names))
    names = sorted(set(league.all_names()) | set(extra))
    names_sha = record.record_hash(names)
    rows: list[dict[str, Any]] = []
    for path in reports:
        rows.extend(read_reports(path))
    pairs = [_judge_one(rep, league, rule_in, names, names_sha, stage) for rep in rows]
    return cli.write_rulings(out, _sort_pairs(pairs))


# ---------------------------------------------------------------- the parser


def _summary(path: Path) -> str:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    parts = ", ".join(f"{v} {counts[v]}" for v in sorted(counts))
    return f"{len(rows)} lines ({parts or 'none'})"


def _cmd_limits(args: argparse.Namespace) -> int:
    path = limits(args.league, args.out)
    print(f"faultline {DOMAIN} limits: {_summary(path)}")
    return 0


def _cmd_judge(args: argparse.Namespace) -> int:
    path = judge(args.reports, args.league, args.rules, args.out, args.stage, args.known_names)
    print(f"faultline {DOMAIN} judge --stage {args.stage}: {_summary(path)}")
    return 0


def register(parser: argparse.ArgumentParser) -> None:
    """Add `limits` and `judge` to the `racing` parser."""
    sub = parser.add_subparsers(dest="racing_command", required=True, metavar="command")
    lp = sub.add_parser("limits", help="incident-limit rulings for every session")
    lp.add_argument("--league", type=Path, required=True, help="league.json")
    lp.add_argument("--out", type=Path, required=True, help="ruling lines to write")
    lp.set_defaults(func=_cmd_limits)
    jp = sub.add_parser("judge", help="one contact ruling per protest")
    jp.add_argument("reports", type=Path, nargs="+", help="protest lines (JSONL)")
    jp.add_argument("--league", type=Path, required=True, help="league.json")
    jp.add_argument("--rules", type=Path, required=True, help="the rules pack folder")
    jp.add_argument("--out", type=Path, required=True, help="ruling lines to write")
    jp.add_argument("--stage", required=True, choices=STAGES, help="how far to go")
    jp.add_argument("--known-names", type=Path, help="more names to refuse, one per line")
    jp.set_defaults(func=_cmd_judge)
