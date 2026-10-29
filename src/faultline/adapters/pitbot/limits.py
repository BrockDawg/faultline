"""Incident-limit rulings for the PitBot adapter: one ruling per car over the session limit.

`incident_limit(feed, limit, rule_id, clause, session_id)` reads one loaded `Feed` and returns
a list of ruling dicts in the ruling-line shape (see the plan's "Ruling line"), without the
`record` hash, which the CLI adds later:

- A car breaches when its last shown incident counter (`feed.last_inc`) is over `limit`
  (strictly greater: a car exactly on the limit does not breach). One ruling per breaching car,
  sorted by `numkey` of the car: `id` `"<session_id>/<car>"`, `kind` `"incident_limit"`,
  `verdict` `"breach"`, `offender` the car, `candidates` `[car]`, `victim` null,
  `missing_fact` null, `window` `{"session": session_id}`, `frames` `[]`, `model_read` null,
  one blame-neutral fact sentence stating the shown total and the limit, and an `evidence`
  line of 40 to 600 characters built by code that names the total, the limit and the clause.
- A session where the counter is not shown for every car in the feed (`feed.counter_shown`
  false for any of `feed.nums`) refuses: one ruling with `id` session_id, `verdict`
  `"unable_to_rule"`, `offender` null, `candidates` `[]`, and `missing_fact`
  `"incident counter not shown for every car"`. No partial breaches are reported for it.
- No breach and a counter for every car: an empty list.

This reproduces rule A of the 29 Oct racing telemetry judge (ai-steward
`experiments/2026-10-29-racing-telemetry-judge`): the limits 20 for `HEAT 1` and `FEATURE`
(format 2.1.1, clause 9.2.1) and 25 for `RACE` (format 2.1.2, clause 9.2.2) arrive through
`league.json`, the "over" test is `total > limit`, and the skip is "a counter shown for fewer
cars than the feed holds". Counters are shown only now and then, so the last shown value is
the read; the counter never falls, so it equals the highest shown value rule A used.

`limits_for_league(league_json_path)` loads every session of `league.json` in its own order
(`sessions[*].feed`, `session`, `subsession`, `incident_limit`, `clause`; the rule id is
`pack.rule_id`) and concatenates the rulings. The session id is `"<subsession>/<session>"`.

No text built here holds a name, a path or a slash-joined session id: the sentences say
"the <session> session", so they pass `faultline.lint`.

Refusals raise `LimitsError` naming the file and the reason: a league file that cannot be read,
is not JSON, or has a session missing a field. A feed that cannot be read raises the
`FeedError` from `Feed.load`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from faultline.adapters.pitbot.feed import Feed
from faultline.roster import numkey

__all__ = ["MISSING_COUNTER", "LimitsError", "incident_limit", "limits_for_league"]

MISSING_COUNTER = "incident counter not shown for every car"
_SESSION_FIELDS = ("feed", "session", "subsession", "incident_limit", "clause")


class LimitsError(ValueError):
    """A league file could not be read for limits; the message names the file and the reason."""


def _session_label(session_id: str) -> str:
    """The session name alone ("HEAT 1"), never the slash-joined id."""
    return session_id.rsplit("/", 1)[-1]


def _ruling(
    *,
    rid: str,
    rule_id: str,
    clause: str,
    verdict: str,
    missing_fact: str | None,
    session_id: str,
    car: str | None,
    facts: list[str],
    evidence: str,
) -> dict[str, Any]:
    return {
        "id": rid,
        "kind": "incident_limit",
        "rule": rule_id,
        "clause": clause,
        "verdict": verdict,
        "missing_fact": missing_fact,
        "window": {"session": session_id},
        "candidates": [] if car is None else [car],
        "offender": car,
        "victim": None,
        "facts": facts,
        "frames": [],
        "model_read": None,
        "evidence": evidence,
    }


def incident_limit(
    feed: Feed, limit: int, rule_id: str, clause: str, session_id: str
) -> list[dict[str, Any]]:
    """Rulings for every car over `limit` in `feed`, or one refusal (see the module docstring)."""
    label = _session_label(session_id)
    if not feed.nums or not all(feed.counter_shown(num) for num in feed.nums):
        shown = sum(1 for num in feed.nums if feed.counter_shown(num))
        evidence = (
            f"The incident counter is shown for {shown} of {len(feed.nums)} cars in the "
            f"{label} session, so the limit of {limit} under clause {clause} cannot be checked."
        )
        return [
            _ruling(
                rid=session_id,
                rule_id=rule_id,
                clause=clause,
                verdict="unable_to_rule",
                missing_fact=MISSING_COUNTER,
                session_id=session_id,
                car=None,
                facts=[],
                evidence=evidence,
            )
        ]
    out: list[dict[str, Any]] = []
    for num in sorted(feed.nums, key=numkey):
        total = feed.last_inc(num)
        if total is None or total <= limit:
            continue
        fact = (
            f"Car {num} shows {total} incident points at its last shown counter in the "
            f"{label} session; the session limit is {limit}."
        )
        evidence = (
            f"Car {num} ended the {label} session on {total} incident points, over the limit "
            f"of {limit} set by clause {clause}, read from the last shown counter."
        )
        out.append(
            _ruling(
                rid=f"{session_id}/{num}",
                rule_id=rule_id,
                clause=clause,
                verdict="breach",
                missing_fact=None,
                session_id=session_id,
                car=num,
                facts=[fact],
                evidence=evidence,
            )
        )
    return out


def limits_for_league(league_json_path: str | Path) -> list[dict[str, Any]]:
    """Run `incident_limit` on every session of `league.json`, in the file's session order."""
    path = Path(league_json_path)
    try:
        league = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LimitsError(
            f"{path}: cannot be read ({exc.strerror or type(exc).__name__})."
        ) from None
    except json.JSONDecodeError:
        raise LimitsError(f"{path}: not JSON.") from None
    if not isinstance(league, dict):
        raise LimitsError(f"{path}: not a JSON object.")
    pack = league.get("pack")
    rule_id = pack.get("rule_id") if isinstance(pack, dict) else None
    if not isinstance(rule_id, str) or not rule_id:
        raise LimitsError(f"{path}: pack.rule_id is missing.")
    sessions = league.get("sessions")
    if not isinstance(sessions, dict):
        raise LimitsError(f"{path}: sessions is not an object.")
    out: list[dict[str, Any]] = []
    for key, entry in sessions.items():
        if not isinstance(entry, dict):
            raise LimitsError(f"{path}: session {key!r} is not an object.")
        for field in _SESSION_FIELDS:
            if field not in entry:
                raise LimitsError(f"{path}: session {key!r} has no {field!r}.")
        limit = entry["incident_limit"]
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise LimitsError(f"{path}: session {key!r} has a non-integer incident_limit.")
        session_id = f"{entry['subsession']}/{entry['session']}"
        feed = Feed.load(entry["feed"], entry["session"])
        out.extend(incident_limit(feed, limit, rule_id, str(entry["clause"]), session_id))
    return out
