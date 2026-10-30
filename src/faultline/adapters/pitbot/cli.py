"""The `faultline racing` commands: incident-limit rulings and the protest judge.

`register(parser)` adds two sub-commands to the `racing` parser built by `faultline.cli`:

`faultline racing limits --league <league.json> --out <preds.jsonl>`: every session's
incident-limit rulings (`limits.limits_for_league`), each with its `record` and bundle.

`faultline racing judge <reports.jsonl> [...] --league <league.json> --rules <packdir>
--out <preds.jsonl> --stage locate|frames|rule [--known-names <file>] [--moments <json>]
[--masks <json>] [--frames-dir <dir>] [--model <id> --arm 1|2 --schema-form enum|pattern
--ledger <dir> --runs N --max-tokens N --images N]`: one `contact` ruling per protest line.
Per report, in this order:

1. no `session` on the report: `unable_to_rule`, `NO_SESSION`, window `{"session": null}`;
2. a session absent from `league.json`, or one with no `feed`: `unable_to_rule`, `NO_FEED`,
   window `{"session": <session>}`;
3. a session with no stream offset: `unable_to_rule`, `NO_OFFSET`, window session only;
4. `protest.normalise` against the session's feed, then `locator.locate` on `all_events`.
   Without a moment for the report, a `Refusal` gives `unable_to_rule` with the locator's own
   `missing_fact`, and a `Window` is the ruling's window.
   With a moment `m` (from `--moments`, the steward gives the moment): the window is te
   `[m - MOMENT_BEFORE_S, m + MOMENT_AFTER_S]` = `[m-3, m+2]`, its lap the leader lap at `m`,
   its stream seconds that window plus `offset_s`, and its contact second `m`; the locator's
   own answer (window or refusal) is kept in `detail.locate.locator` for reference only;
5. the closed set (`roster.closed_set`) over that window, as pre-registered: every car within
   `NEAR_M` metres of a protest car over the window padded `PAD_S` seconds either side. The
   focus is the protest cars the feed holds (the normalised cars plus the reporter's car),
   never the window event's own cars; out-of-world readings are dropped first. No protest car
   in the feed, or no protest car seen in the padded window, is an empty set and gives
   `unable_to_rule`, `EMPTY_SET`, with the session only on the line (the window found stays
   in `detail.locate.window`); otherwise `steward_review` with the
   window, the sorted candidates and `facts.facts` over the window.

Masks. masks.json must hold a non-empty `default` list, every mask (default and per
session) a filled box matching `MASK_PATTERN` (`^drawbox=[^,]*:t=fill$`), and a
`drop_layouts` key (an explicit `[]` is allowed), each rule checked by
`frames.check_drop_rules`. Anything else is refused before a frame is cut.

Stage `frames` (needs `--masks`): for each `steward_review` line, centre `c` = the moment, or
without one the window's contact second; `frames.cut(stream, c + offset_s, frames dir, masks,
error_s=offset_error_s)`, where the masks are masks.json's `default` plus that session's
extras, and the frames dir is `--frames-dir` or `<out>.frames`. The line's `frames` becomes
`[{"stream_s", "sha256"}]`, kept frames only: masks.json's `drop_layouts` rules
go to `frames.cut` as `drop_rules`, so a second showing another broadcast layout (and its
neighbours) is dropped. `NOT_COVERED` or `NO_STANDARD_VIEW` turns the line into
`unable_to_rule` with that missing fact (session-only window, no candidates, no facts); any
other `FramesError` stops the run.

Stage `rule` (needs `--model`): the frames stage, then for each `steward_review` line with
frames, `ruling.read` over the prompt `ruling.build_prompt` makes (the pack rule's own text,
the line's facts, the candidates, the normalised protest, the frame labels, subject noun
`SUBJECT_NOUN`) and the chosen frame files as images, through the ledger (`--ledger`, default
`ledger/` beside `--out`). The model is sent `--images N` frames at most (`DEFAULT_IMAGES`,
8, because one host refuses more than 8 images a request), picked by `pick_model_frames`:
one per whole second `c + k` for k from `-IMAGES_BEFORE_S` (-4) up, the unused cut frame
nearest that second within `IMAGES_SLOT_S` (0.5 s), the earlier on a tie, a slot with none
skipped; N at least the cut's size sends every frame. The frame labels (`frame 1..n`) name
the chosen frames only; the line's `frames` keeps every cut frame. Arm 1 sends no
`response_format` (reference `<id>`); arm 2 sends the strict schema (reference `<id>-arm2`).
The line's `model_read` is the read's `as_dict()`; its `offender` is the read's offender only
when the read agreed with a `penalty`, else null.
The verdict stays `steward_review`: the steward decides, the read sits beside it.
The verdict classes (`VERDICTS`, `penalty` the one naming a car) and the prompt's role and
document words (`WORDING`) are supplied here, never by the core. `--schema-form` (`enum`, the
default, or `pattern`) picks arm 2's offender schema. A fake read can never pass as real:
`FAULTLINE_FAKE_MODEL=1` is refused unless `--model fake`, `--model fake` is refused without
it, and the line's `model_read.source` says which. The cost cap is per ledger folder, so a
`--ledger` other than the default is refused unless `FAULTLINE_CAP_USD` is set; and the whole
rule stage holds an exclusive lock file (`LOCK_NAME`) in the ledger folder, so two judges
never spend against one ledger at once (a held lock is refused; it is released in a
`finally`).

Every line has the plan's ruling shape: `kind` "contact", `rule` from `league.json`
`pack.rule_id` (it must exist in the `--rules` pack), `clause` null, `victim` null, and an
`evidence` sentence of 40 to 600 characters built here. `window.stream_s` is the window
plus the session's `offset_s`, 1 decimal.

Names. The lint names are every driver name in every session feed of `league.json`, plus the
lines of `--known-names` (UTF-8, one name per line) when given; the same list is the
normaliser's `known_names`. Every text that leaves this module (each fact, the evidence, the
missing fact, the normalised protest and its unresolved placeholders, the prompt)
passes `lint.assert_clean` against them before anything is written or sent. Only the
fixed word list `ALLOW` is exempt, because the fact sheet's own wording uses it.

Records. Each line's bundle (see `faultline.cli`) holds, as `inputs`: the command, stage and
domain; the sha256 of the report's canonical JSON (the report text itself is never stored);
the session entry without its file paths; the feed file's sha256; the rule id and the sha256
of its text; the sha256 of the number map and of the sorted name list; the closed-set
parameters. With a moment: `moment` (`te`, `source`). Past the locate stage, on a line that
reached the frames step: `masks_sha256` (of the session's mask list), `drop_rules_sha256`
(of the `drop_layouts` list), `ffmpeg_version`, and
`frame_sha256` (the frame hashes in time order) when frames were cut. In the rule stage:
`ledger_keys` and `model_call` (model, arm, reference, runs, max tokens, JSON mode, schema
form, schema, prompt text, candidates, `images` (the `--images` N), the sent frames' labels
and hashes, and the ledger key's `source`); a bundle written before `images` existed sent
every cut frame and replays unchanged, since replay reads only the call.
`detail.locate` holds the window's contact second, its event (or the moment and the
locator's own answer), the candidates with their gaps and the normalised (name-free) protest;
`detail.frames` the centre second and the dropped seconds with their rule. Lines are sorted
by id with `numkey`. Without `--moments` and before the frames stage, the output is
byte-identical to the Checkpoint 3 locate stage.

Replay. Two verifiers are registered in `faultline.cli.VERIFIERS`: `frame_sha256` checks
every frame file is in `<preds>.frames/` (or `$FAULTLINE_FRAMES_DIR`) and hashes to its name,
never running ffmpeg; `model_call` requires every ledger key in `ledger/` beside the preds
(or `$FAULTLINE_LEDGER_DIR`) and rebuilds the read from the ledger alone
(`ruling.read(..., replay_only=True)`, which never calls the client) and refuses unless it
equals the line's `model_read`.

Refusals raise `RacingCliError` naming the file or report and the reason.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from faultline import cli, client, lint, record
from faultline import frames as framecut
from faultline import ruling as modelread
from faultline.adapters.pitbot import DOMAIN
from faultline.adapters.pitbot.events import Event, all_events
from faultline.adapters.pitbot.facts import facts
from faultline.adapters.pitbot.feed import Feed
from faultline.adapters.pitbot.limits import limits_for_league
from faultline.adapters.pitbot.locator import Refusal, Window, locate
from faultline.adapters.pitbot.protest import normalise, read_reports
from faultline.ledger import Ledger
from faultline.pack import load_pack
from faultline.roster import closed_set, numkey

__all__ = [
    "ALLOW",
    "ARMS",
    "FAKE_MODEL",
    "LOCK_NAME",
    "MASK_PATTERN",
    "BUILT_STAGES",
    "EMPTY_SET",
    "FRAMES_DIR_ENV",
    "FRAMES_SUFFIX",
    "LEDGER_DIR_ENV",
    "LEDGER_NAME",
    "MOMENT_AFTER_S",
    "MOMENT_BEFORE_S",
    "NEAR_M",
    "NOT_COVERED",
    "NO_STANDARD_VIEW",
    "NO_FEED",
    "NO_OFFSET",
    "NO_SESSION",
    "PAD_S",
    "SCHEMA_FORMS",
    "STAGES",
    "SUBJECT_NOUN",
    "VERDICTS",
    "WORDING",
    "DEFAULT_IMAGES",
    "IMAGES_BEFORE_S",
    "IMAGES_SLOT_S",
    "RacingCliError",
    "judge",
    "limits",
    "pick_model_frames",
    "read_moments",
    "register",
]

STAGES = ("locate", "frames", "rule")
BUILT_STAGES = STAGES
NO_SESSION = "the protest names no session"
NO_FEED = "no feed for the session"
NO_OFFSET = "the stream has no offset"
EMPTY_SET = "the closed set is empty"
NOT_COVERED = framecut.NOT_COVERED
NO_STANDARD_VIEW = framecut.NO_STANDARD_VIEW
NEAR_M = 8.0
PAD_S = 3
MOMENT_BEFORE_S = 3
MOMENT_AFTER_S = 2
ARMS = (1, 2)
SUBJECT_NOUN = "car"
VERDICTS = modelread.Verdicts(
    (
        ("penalty", "the rules hold one named car responsible and call for a penalty."),
        ("racing_incident", "the rules hold no single car responsible."),
        ("no_action", "the rules call for no action on this protest."),
        ("not_visible", "the frames do not show the moment well enough to rule."),
    ),
    naming="penalty",
)
WORDING = modelread.Wording(role="a steward", document="protest")
SCHEMA_FORMS = ("enum", "pattern")
FAKE_MODEL = "fake"
FAKE_ENV = "FAULTLINE_FAKE_MODEL"
CAP_ENV = "FAULTLINE_CAP_USD"
LOCK_NAME = ".judge.lock"
MASK_PATTERN = re.compile(r"^drawbox=[^,]*:t=fill$")
DEFAULT_RUNS = 3
DEFAULT_MAX_TOKENS = 12000
DEFAULT_IMAGES = 8
IMAGES_BEFORE_S = 4
IMAGES_SLOT_S = 0.5
FRAMES_SUFFIX = ".frames"
LEDGER_NAME = "ledger"
FRAMES_DIR_ENV = "FAULTLINE_FRAMES_DIR"
LEDGER_DIR_ENV = "FAULTLINE_LEDGER_DIR"
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


# ---------------------------------------------------------------- judge inputs


def _read_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise RacingCliError(
            f"{path}: cannot be read ({exc.strerror or type(exc).__name__})."
        ) from None
    except json.JSONDecodeError:
        raise RacingCliError(f"{path}: the {what} file is not JSON.") from None


def read_moments(path: Path | str) -> dict[str, dict[str, Any]]:
    """`{"moments": {"<report id>": {"te": int, "source": str}}, "note": str}` -> moments."""
    path = Path(path)
    data = _read_json(path, "moments")
    moments = data.get("moments") if isinstance(data, dict) else None
    if not isinstance(moments, dict):
        raise RacingCliError(f"{path}: moments is not an object of report ids.")
    out: dict[str, dict[str, Any]] = {}
    for rid, item in moments.items():
        te = item.get("te") if isinstance(item, dict) else None
        source = item.get("source") if isinstance(item, dict) else None
        if isinstance(te, bool) or not isinstance(te, int) or te < 0:
            raise RacingCliError(f"{path}: report {rid}: te is not a whole second.")
        if not isinstance(source, str) or not source.strip():
            raise RacingCliError(f"{path}: report {rid}: source is missing.")
        out[str(rid)] = {"source": source, "te": te}
    return out


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)


class _Masks:
    """masks.json: `{"default": [drawbox], "sessions": {"<session key>": [extra drawbox]},
    "drop_layouts": [drop rule]}`; `drop_layouts` is required (an explicit `[]` for none) and
    each rule is checked by `frames.check_drop_rules`."""

    def __init__(self, path: Path) -> None:
        data = _read_json(path, "masks")
        default = data.get("default") if isinstance(data, dict) else None
        sessions = data.get("sessions", {}) if isinstance(data, dict) else None
        if not isinstance(default, list) or not default or not _strings(default):
            raise RacingCliError(f"{path}: default is not a non-empty list of filter strings.")
        if not isinstance(sessions, dict) or not all(_strings(v) for v in sessions.values()):
            raise RacingCliError(f"{path}: sessions is not an object of filter-string lists.")
        for mask in [*default, *(m for v in sessions.values() for m in v)]:
            if not MASK_PATTERN.fullmatch(mask):
                raise RacingCliError(
                    f"{path}: mask {mask[:60]!r} is not one filled drawbox "
                    f"({MASK_PATTERN.pattern})."
                )
        if not isinstance(data, dict) or "drop_layouts" not in data:
            raise RacingCliError(f"{path}: drop_layouts is missing (write [] for none).")
        drops = data["drop_layouts"]
        if not isinstance(drops, list):
            raise RacingCliError(f"{path}: drop_layouts is not a list of rule objects.")
        try:
            framecut.check_drop_rules(drops)
        except framecut.FramesError as exc:
            raise RacingCliError(f"{path}: {exc}") from None
        self.default: list[str] = list(default)
        self.sessions: dict[str, list[str]] = {k: list(v) for k, v in sessions.items()}
        self.drop_layouts: list[dict[str, Any]] = drops

    def for_session(self, key: str) -> list[str]:
        return [*self.default, *self.sessions.get(key, [])]


@dataclass
class _Built:
    """One ruling before its bundle: what later stages add to, and what they need."""

    inputs: dict[str, Any]
    ruling: dict[str, Any]
    detail: dict[str, Any] | None
    ctx: dict[str, Any] | None = None  # set only on a steward_review line


# ---------------------------------------------------------------- judge, locate stage


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


def _empty_moment_evidence(rid: str, label: str, m: int, te: list[int]) -> str:
    return (
        f"Report {rid}: the steward gave second {m} of the {label} session as the moment, but "
        f"no protest car has a position in the feed from second {te[0]} to second {te[1]} "
        f"plus or minus {PAD_S} seconds, so {EMPTY_SET}."
    )


def _moment_why(m: int) -> str:
    return (
        f"The steward gave feed second {m} as the moment; the window runs {MOMENT_BEFORE_S} "
        f"seconds before it to {MOMENT_AFTER_S} seconds after it."
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


def _locator_detail(found: Window | Refusal) -> dict[str, Any]:
    """The locator's own answer, kept for reference when the steward gives the moment."""
    if isinstance(found, Refusal):
        return {"result": "refusal", **found.as_dict()}
    return {
        "result": "window",
        **found.as_dict(),
        "event_cars": list(found.event_cars),
        "event_kind": found.event_kind,
        "protest_cars_held": list(found.protest_cars_held),
        "why": found.why,
    }


def _judge_one(
    rep: dict[str, Any],
    league: _League,
    rule_in: dict[str, str],
    names: list[str],
    names_sha: str,
    stage: str,
    moments: dict[str, dict[str, Any]] | None = None,
) -> _Built:
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
    moment = (moments or {}).get(rid)
    if moment is not None:
        inputs["moment"] = dict(moment)

    def refuse(
        missing: str,
        window: dict[str, Any],
        label: str | None,
        detail: Any = None,
        evidence: str | None = None,
    ) -> _Built:
        if evidence is None:
            evidence = _refusal_evidence(rid, missing, label)
        _assert_clean(rid, [missing, evidence], names)
        _check_evidence(rid, evidence)
        ruling = _contact(rid, rule_in["id"], "unable_to_rule", missing, window, [], [], evidence)
        return _Built(inputs, ruling, {"locate": detail} if detail else None)

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

    if moment is None:
        if isinstance(found, Refusal):
            return refuse(found.missing_fact, {"session": key}, label, {"normalised": norm_detail})
        assert found.stream_s is not None
        te_lo, te_hi, contact_te = found.te_lo, found.te_hi, found.contact_te
        window = {
            "session": key,
            "te": [te_lo, te_hi],
            "lap": found.lap,
            "stream_s": list(found.stream_s),
            "offset_error_s": found.offset_error_s,
        }
        why, car_only = found.why, found.car_only
    else:
        contact_te = int(moment["te"])
        te_lo, te_hi = contact_te - MOMENT_BEFORE_S, contact_te + MOMENT_AFTER_S
        window = {
            "session": key,
            "te": [te_lo, te_hi],
            "lap": feed.leader_lap(contact_te),
            "stream_s": [round(te_lo + offset_s, 1), round(te_hi + offset_s, 1)],
            "offset_error_s": offset_error_s,
        }
        why, car_only = _moment_why(contact_te), False

    focus = set(norm.cars)
    if norm.reporter_car:
        focus.add(norm.reporter_car)
    focus &= set(feed.nums)
    cands = []
    if focus:
        positions = _focus_positions(feed, te_lo, te_hi)
        cands = closed_set(positions, feed.track_m, focus, te_lo, te_hi, near_m=NEAR_M, pad_s=PAD_S)
    detail: dict[str, Any] = {
        "candidates": [
            {"closest_m": c.closest_m, "num": c.num, "relation": c.relation, "why": c.why}
            for c in cands
        ],
        "car_only": car_only,
        "contact_te": contact_te,
        "focus": sorted(focus, key=numkey),
        "normalised": norm_detail,
        "window": window,
    }
    if isinstance(found, Window) and moment is None:
        detail.update(
            event_cars=list(found.event_cars),
            event_kind=found.event_kind,
            protest_cars_held=list(found.protest_cars_held),
            why=found.why,
        )
    else:
        detail.update(locator=_locator_detail(found), moment=moment, why=why)
    if not cands:
        # A refused line carries the session only; the window found stays in the detail.
        if moment is None:
            evidence = _empty_set_evidence(rid, label, [te_lo, te_hi])
        else:
            evidence = _empty_moment_evidence(rid, label, contact_te, [te_lo, te_hi])
        return refuse(EMPTY_SET, {"session": key}, label, detail, evidence)
    nums = [c.num for c in cands]
    fact_lines = facts(feed, events, nums, te_lo, te_hi, contact_te)
    evidence = _window_evidence(rid, label, window, why, car_only, nums)
    _assert_clean(rid, [*fact_lines, evidence], names)
    _check_evidence(rid, evidence)
    ruling = _contact(
        rid, rule_in["id"], "steward_review", None, window, nums, fact_lines, evidence
    )
    ctx = {
        "centre_te": contact_te,
        "key": key,
        "label": label,
        "offset_error_s": offset_error_s,
        "offset_s": offset_s,
        "report_text": norm.text,
    }
    return _Built(inputs, ruling, {"locate": detail}, ctx)


# ---------------------------------------------------------------- judge, frames stage


# The frames refusals that become `unable_to_rule`; any other `FramesError` stops the run.
_FRAMES_REFUSALS = {
    NOT_COVERED: "the " + NOT_COVERED,
    NO_STANDARD_VIEW: NO_STANDARD_VIEW,
}


def _frames_refusal_evidence(
    rid: str, label: str, centre_te: int, centre_s: float, reason: str
) -> str:
    return (
        f"Report {rid}: the window in the {label} session centres on feed second {centre_te}, "
        f"stream second {centre_s}, but {_FRAMES_REFUSALS[reason]}, so no frames could be cut."
    )


def _frames_step(
    built: _Built,
    league: _League,
    masks: _Masks,
    frames_dir: Path,
    ffmpeg: str,
    names: list[str],
) -> None:
    """Cut the line's frames, or turn it into `unable_to_rule` when the stream ends too soon."""
    ctx = built.ctx
    if ctx is None:
        return
    rid = built.ruling["id"]
    key = ctx["key"]
    stream = (league.entry(key) or {}).get("stream")
    if not isinstance(stream, str) or not stream:
        raise RacingCliError(f"{league.path}: session {key!r} has no stream file.")
    session_masks = masks.for_session(key)
    built.inputs["masks_sha256"] = record.record_hash(session_masks)
    built.inputs["drop_rules_sha256"] = record.record_hash(masks.drop_layouts)
    built.inputs["ffmpeg_version"] = ffmpeg
    centre_s = round(ctx["centre_te"] + ctx["offset_s"], 1)
    error_s = float(ctx["offset_error_s"] or 0.0)
    detail = built.detail if built.detail is not None else {}
    try:
        cut = framecut.cut(
            stream,
            centre_s,
            frames_dir,
            session_masks,
            error_s=error_s,
            drop_rules=masks.drop_layouts,
        )
    except framecut.FramesError as exc:
        reason = exc.reason
        if reason not in _FRAMES_REFUSALS:
            raise
        evidence = _frames_refusal_evidence(rid, ctx["label"], ctx["centre_te"], centre_s, reason)
        _assert_clean(rid, [evidence], names)
        _check_evidence(rid, evidence)
        built.ruling.update(
            verdict="unable_to_rule",
            missing_fact=reason,
            window={"session": key},
            candidates=[],
            facts=[],
            evidence=evidence,
        )
        detail["frames"] = {
            "centre_s": centre_s,
            "centre_te": ctx["centre_te"],
            "refused": reason,
        }
        built.detail = detail
        built.ctx = None
        return
    built.ruling["frames"] = [{"sha256": f.sha256, "stream_s": f.stream_s} for f in cut]
    built.inputs["frame_sha256"] = [f.sha256 for f in cut]
    detail["frames"] = {
        "centre_s": centre_s,
        "centre_te": ctx["centre_te"],
        "dropped": [{"rule": d.rule, "stream_s": d.stream_s} for d in cut.dropped],
    }
    built.detail = detail


# ---------------------------------------------------------------- judge, rule stage


def pick_model_frames(stream_seconds: Sequence[float], centre_s: float, n: int) -> list[int]:
    """The indices (time order) of the cut frames the model is sent: `n` at most.

    All of them when `n` is at least their number. Otherwise one slot per whole second
    `centre_s + k`, k in `range(-IMAGES_BEFORE_S, n - IMAGES_BEFORE_S)`: the unused frame
    whose second is nearest, within `IMAGES_SLOT_S`, earlier on a tie; a slot with none is
    skipped, so a cut with dropped seconds may send fewer than `n`.
    """
    if n < 1:
        raise RacingCliError(f"--images {n} must be at least 1.")
    if n >= len(stream_seconds):
        return list(range(len(stream_seconds)))
    used: set[int] = set()
    for k in range(-IMAGES_BEFORE_S, n - IMAGES_BEFORE_S):
        target = centre_s + k
        near = [
            (round(abs(float(s) - target), 6), float(s), i)
            for i, s in enumerate(stream_seconds)
            if i not in used and round(abs(float(s) - target), 6) <= IMAGES_SLOT_S
        ]
        if near:
            used.add(min(near)[2])
    return sorted(used, key=lambda i: (float(stream_seconds[i]), i))


def _rule_step(
    built: _Built,
    rule_text: str,
    frames_dir: Path,
    ledger_dir: Path,
    names: list[str],
    model: str,
    arm: int,
    runs: int,
    max_tokens: int,
    schema_form: str = "enum",
    images: int = DEFAULT_IMAGES,
) -> None:
    """Ask the model through the ledger and put its read beside the steward's review."""
    ctx = built.ctx
    line = built.ruling
    if ctx is None or line["verdict"] != "steward_review" or not line["frames"]:
        return
    rid = line["id"]
    cands = list(line["candidates"])
    centre_s = round(ctx["centre_te"] + ctx["offset_s"], 1)
    chosen = [
        line["frames"][i]
        for i in pick_model_frames([f["stream_s"] for f in line["frames"]], centre_s, images)
    ]
    shas = [f["sha256"] for f in chosen]
    labels = modelread.label_frames([f["stream_s"] for f in chosen])
    prompt = modelread.build_prompt(
        rule_text,
        line["facts"],
        cands,
        ctx["report_text"],
        labels,
        SUBJECT_NOUN,
        VERDICTS,
        WORDING,
    )
    json_mode = arm == 2
    call = {
        "arm": arm,
        "candidates": cands,
        "frame_labels": [label for label, _second in labels],
        "frame_sha256": shas,
        "id": rid,
        "images": images,
        "json_mode": json_mode,
        "max_tokens": max_tokens,
        "model": model,
        "prompt": prompt,
        "ref": rid if arm == 1 else f"{rid}-arm2",
        "runs": runs,
        "schema": (
            modelread.schema(cands, VERDICTS, enum=schema_form == "enum") if json_mode else None
        ),
        "schema_form": schema_form,
        "source": client.request_params(model)["source"],
    }
    got = _model_read(call, frames_dir, Ledger(ledger_dir), names)
    line["model_read"] = got.as_dict()
    named = got.agreed and got.verdict == VERDICTS.naming
    line["offender"] = got.offender if named else None
    built.inputs["ledger_keys"] = list(got.keys)
    built.inputs["model_call"] = call


def _model_read(
    call: dict[str, Any],
    frames_dir: Path,
    ledger: Ledger,
    names: list[str],
    replay_only: bool = False,
) -> modelread.ModelRead:
    images = [frames_dir / f"{sha}.jpg" for sha in call["frame_sha256"]]
    return modelread.read(
        call["prompt"],
        images,
        call["model"],
        ledger,
        call["ref"],
        candidates=call["candidates"],
        frame_labels=call["frame_labels"],
        verdicts=VERDICTS,
        names=names,
        allow=ALLOW,
        runs=call["runs"],
        schema=call["schema"],
        json_mode=call["json_mode"],
        max_tokens=call["max_tokens"],
        replay_only=replay_only,
        source=call["source"] if replay_only else None,
    )


# ---------------------------------------------------------------- replay verifiers


def _frames_dir_for(preds: Path) -> Path:
    override = os.environ.get(FRAMES_DIR_ENV, "")
    return Path(override) if override else Path(f"{preds}{FRAMES_SUFFIX}")


def _ledger_dir_for(preds: Path) -> Path:
    override = os.environ.get(LEDGER_DIR_ENV, "")
    return Path(override) if override else Path(preds).parent / LEDGER_NAME


def _verify_frames(preds: Path, shas: Any) -> None:
    """Replay: every frame the bundle names is on disk and hashes to its name; no ffmpeg."""
    if not isinstance(shas, list):
        raise RacingCliError(f"{preds}: frame_sha256 is not a list.")
    framecut.verify([{"sha256": s} for s in shas], _frames_dir_for(Path(preds)))


def _verify_model_call(preds: Path, call: Any) -> None:
    """Replay: every ledger key exists and the read rebuilt from the ledger alone is the line's."""
    if not isinstance(call, dict) or not isinstance(call.get("id"), str):
        raise RacingCliError(f"{preds}: model_call is not an object with an id.")
    rid = call["id"]
    ledger = Ledger(_ledger_dir_for(Path(preds)))
    got = _model_read(call, _frames_dir_for(Path(preds)), ledger, [], replay_only=True)
    for key in got.keys:
        ledger.require(key)
    rows = [
        json.loads(line)
        for line in Path(preds).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    row = next((r for r in rows if r.get("id") == rid), None)
    if row is None or row.get("model_read") != got.as_dict():
        raise RacingCliError(
            f"line {rid!r}: the model read rebuilt from the ledger differs from the line."
        )


cli.VERIFIERS["frame_sha256"] = _verify_frames
cli.VERIFIERS["model_call"] = _verify_model_call


# ---------------------------------------------------------------- judge


@contextlib.contextmanager
def _ledger_lock(ledger_dir: Path) -> Iterator[None]:
    """Hold `LOCK_NAME` in the ledger folder for the whole rule stage; refuse a held one."""
    ledger_dir.mkdir(parents=True, exist_ok=True)
    lock = ledger_dir / LOCK_NAME
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RacingCliError(
            f"{lock}: the ledger is locked: another judge is spending against it, or one "
            "stopped without clearing the lock. Delete the file only when no judge is running."
        ) from None
    try:
        try:
            os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        finally:
            os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


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
    *,
    moments: Path | str | None = None,
    masks: Path | str | None = None,
    frames_dir: Path | str | None = None,
    model: str | None = None,
    arm: int = 1,
    ledger: Path | str | None = None,
    runs: int = DEFAULT_RUNS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    schema_form: str = "enum",
    images: int = DEFAULT_IMAGES,
) -> Path:
    """Write one contact ruling per report line, with records, to `out`, up to `stage`."""
    if stage not in STAGES:
        raise RacingCliError(f"stage {stage!r} is not one of {list(STAGES)}.")
    out = Path(out)
    needs_frames = stage in ("frames", "rule")
    if needs_frames and masks is None:
        raise RacingCliError(f"stage {stage!r} needs --masks: no frame is cut unmasked.")
    if stage == "rule":
        if not model:
            raise RacingCliError("stage 'rule' needs --model.")
        if arm not in ARMS:
            raise RacingCliError(f"arm {arm!r} is not one of {list(ARMS)}.")
        if runs < 1 or max_tokens < 1:
            raise RacingCliError("--runs and --max-tokens must be at least 1.")
        if isinstance(images, bool) or not isinstance(images, int) or images < 1:
            raise RacingCliError(
                f"--images {images!r} must be a whole number of at least 1: the model is "
                "sent at least one frame."
            )
        if schema_form not in SCHEMA_FORMS:
            raise RacingCliError(f"schema form {schema_form!r} is not one of {SCHEMA_FORMS}.")
        fake = os.environ.get(FAKE_ENV) == "1"
        if fake and model != FAKE_MODEL:
            raise RacingCliError(
                f"{FAKE_ENV}=1 is set, so only --model {FAKE_MODEL} may run: a fake read never "
                "carries a real model's name."
            )
        if model == FAKE_MODEL and not fake:
            raise RacingCliError(f"--model {FAKE_MODEL} needs {FAKE_ENV}=1.")
        if ledger is not None:
            default_ledger = (out.parent / LEDGER_NAME).resolve()
            if Path(ledger).resolve() != default_ledger and not os.environ.get(CAP_ENV):
                raise RacingCliError(
                    f"--ledger {ledger} is not the default ledger beside --out; the cost cap "
                    f"is per ledger folder, so set {CAP_ENV} explicitly to use another one."
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
    given = None if moments is None else read_moments(moments)
    loaded = None if not needs_frames or masks is None else _Masks(Path(masks))
    rows: list[dict[str, Any]] = []
    for path in reports:
        rows.extend(read_reports(path))
    built = [_judge_one(rep, league, rule_in, names, names_sha, stage, given) for rep in rows]
    if loaded is not None:
        fdir = Path(frames_dir) if frames_dir is not None else Path(f"{out}{FRAMES_SUFFIX}")
        version = framecut.ffmpeg_version()
        for item in built:
            _frames_step(item, league, loaded, fdir, version, names)
        if stage == "rule" and model:
            ldir = Path(ledger) if ledger is not None else out.parent / LEDGER_NAME
            with _ledger_lock(ldir):
                for item in built:
                    _rule_step(
                        item,
                        rule.text,
                        fdir,
                        ldir,
                        names,
                        model,
                        arm,
                        runs,
                        max_tokens,
                        schema_form,
                        images,
                    )
    pairs = [cli.bundle_for(b.inputs, b.ruling, b.detail) for b in built]
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
    path = judge(
        args.reports,
        args.league,
        args.rules,
        args.out,
        args.stage,
        args.known_names,
        moments=args.moments,
        masks=args.masks,
        frames_dir=args.frames_dir,
        model=args.model,
        arm=args.arm,
        ledger=args.ledger,
        runs=args.runs,
        max_tokens=args.max_tokens,
        schema_form=args.schema_form,
        images=args.images,
    )
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
    jp.add_argument("--moments", type=Path, help="the steward's moment per report (JSON)")
    jp.add_argument("--masks", type=Path, help="drawbox masks per session (JSON)")
    jp.add_argument("--frames-dir", type=Path, help="where frames go (default <out>.frames)")
    jp.add_argument("--model", help="the model id (rule stage)")
    jp.add_argument("--arm", type=int, choices=ARMS, default=1, help="1: no JSON mode; 2: strict")
    jp.add_argument("--ledger", type=Path, help="reply ledger folder (default beside --out)")
    jp.add_argument(
        "--schema-form", choices=SCHEMA_FORMS, default="enum", help="arm 2's offender schema"
    )
    jp.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="runs per read")
    jp.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help="per run")
    jp.add_argument(
        "--images",
        type=int,
        default=DEFAULT_IMAGES,
        help=f"frames sent to the model per read, 1 a second from {IMAGES_BEFORE_S} s before "
        f"the centre (rule stage; default {DEFAULT_IMAGES}; every cut frame stays on the line)",
    )
    jp.set_defaults(func=_cmd_judge)
