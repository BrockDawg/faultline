"""The racing panel's data: `racing.json` for the demo page, and the server's session map.

`build_racing(racing_dir, readme, out, source=None, limits=None) -> str` writes
`<out>/racing.json` and `<racing_dir>/session_map.json`, and returns racing.json's sha256.

Inputs:

- `racing_dir`, the server copy of the racing record: `preds-arm1.jsonl`, `preds-arm2.jsonl`
  and `limits.jsonl`, each with its `.record/` bundles (and the arms' `.frames/`, the
  `ledger/`), plus `league.json`, whose feed paths are relative to `racing_dir`.
- `source`, the private folder the record was built from (default `racing_dir`). It is read
  through `scripts/racing_card.py`'s own loaders (`load_corpus`, `gather_names`), so it must
  hold what they read: both arms' lines, `truth.json` (the steward's rulings), `league.json`
  with readable feeds (the lint's names), and `inputs.json` (the league's name, the
  catalogue). `limits` names the limits output in it (default `limits.jsonl`, else
  `limits-a.jsonl`). Both arms' lines and the limits lines in `source` must be byte-identical
  to the ones in `racing_dir`, so every record hash on the page is the one the server replays.
- `readme`, the repo README: every static number is read from a README line found by its own
  words (`README_NUMBERS`, the racing scoreboard table), with that line's number kept beside
  it. A missing or ambiguous line refuses the build, and so does a count the data disagrees
  with (protests, cars over the limit, cars with and without a ruling on record, the model's
  read numerator per arm).

Sessions. The sim's session number never reaches racing.json. Sessions are ordered as
`racing_score.session_order` orders them (race day, heat before feature); each race day is
"Race N" in that order and keeps the session's own name ("HEAT 1"). The table back to the
league's keys is `session_map.json` beside the racing record, for the server only.

`limits_mode` is "rerule" when every feed `racing_dir/league.json` names is present under
`racing_dir`, else "checked" (the page's limits button then replays the stored lines instead
of re-ruling from the feed); `replay_one --limits` follows the same rule.

Before anything is written, every text field passes `faultline.lint` with racing_card's
names and the league's banned name (`racing_card.check_page`), and no session number of the
league appears anywhere in the file. Output is canonical JSON (sorted keys, UTF-8, `\\n`), so
the same inputs give the same bytes; each file is written to a temp file then renamed.

Racing card lives in `scripts/`, outside the package; it is imported on first use by putting
the repo's `scripts/` folder on `sys.path` (`_card`), the same way the card's own tests do.
Building runs only where the repo is checked out; the server only reads the result.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

__all__ = [
    "MODELS",
    "SESSION_MAP",
    "BundleError",
    "build_racing",
    "feeds_present",
    "limits_mode",
    "read_readme_numbers",
    "read_session_map",
    "session_labels",
]

REPO = Path(__file__).resolve().parents[4]
SCHEMA = 1
RACING_JSON = "racing.json"
SESSION_MAP = "session_map.json"
ARM_FILES = {1: "preds-arm1.jsonl", 2: "preds-arm2.jsonl"}
LIMITS_FILE = "limits.jsonl"
# Model id on a line -> (the page's name, where it ran). An unknown model refuses the build.
MODELS: dict[str, tuple[str, str]] = {
    "meta-models/muse-spark-open-1026": ("Muse Spark Open", "Baseten"),
    "muse-spark-1.3": ("Muse Spark 1.3", "Meta Model API"),
}
ARM_MODELS = {1: "meta-models/muse-spark-open-1026", 2: "muse-spark-1.3"}
# key -> (the words that find the README line, a pattern for the text kept from it).
README_NUMBERS: dict[str, tuple[str, str]] = {
    "read_mark": ("The model's read did not pass its mark:", r"\d+ of \d+ on both arms"),
    "read_mark_target": ("The model's read did not pass its mark:", r"a mark of \d+ of \d+"),
    "named_right": ("Every agreed read that named a car named the right one", r"\d+ of \d+"),
    "over_limit": ("The incident limit also found", r"\d+ cars over the limit"),
    "on_record": ("The incident limit also found", r"\d+ match a ruling on record"),
    "no_ruling": ("The incident limit also found", r"\d+ are over the limit, no ruling on record"),
    "spend": ("| Spend |", r"\$\d+(?:\.\d+)?"),
}
# The session limit as a limits line's evidence states it ("over the limit of 25 set by ...").
_LIMIT = re.compile(r"\bthe limit of (\d+)\b")
# key -> how the served text wraps the figure pulled from the README line.
SERVED_WORDS = {"spend": "{} spent"}
SCOREBOARD_ANCHOR = "The model's read did not pass its mark:"
SCOREBOARD_HEADER = "| Mark | Result | Pass mark | Verdict |"
SCOREBOARD_KEYS = {
    "Rule A, incident limit": "limit_found",
    "Locator": "locator",
    "Closed set": "closed_set",
    "Model's read, offender": "read_offender",
    "Replay": "replay",
    "Spend": "spend_mark",
}
HONESTY_ID = "18"
HONESTY_ANCHOR = "On decision 18"


class BundleError(ValueError):
    """The racing data could not be built; the message names the file or line and the reason."""


# ---------------------------------------------------------------- racing_card, from scripts/


def _card() -> ModuleType:
    """`scripts/racing_card.py`, imported once with the repo's `scripts/` on `sys.path`."""
    scripts = str(REPO / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import racing_card  # type: ignore[import-not-found]

    return racing_card  # type: ignore[no-any-return]


# ---------------------------------------------------------------- small readers


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BundleError(
            f"{path}: cannot be read ({exc.strerror or type(exc).__name__})."
        ) from None
    except json.JSONDecodeError:
        raise BundleError(f"{path}: not JSON.") from None


def _canonical(obj: object) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


# ---------------------------------------------------------------- sessions


def session_labels(sessions: dict[str, Any]) -> dict[str, dict[str, str]]:
    """League key -> {"race": "Race N", "session": "HEAT 1", "label": "Race N · HEAT 1"}."""
    score = _card().score
    out: dict[str, dict[str, str]] = {}
    days: dict[str, int] = {}
    for key in sorted(sessions, key=score.session_order):
        entry = sessions[key]
        day = key.partition("/")[0]
        days.setdefault(day, len(days) + 1)
        name = entry.get("session") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name:
            raise BundleError(f"league session {len(out) + 1} has no session name.")
        race = f"Race {days[day]}"
        out[key] = {"race": race, "session": name, "label": f"{race} · {name}"}
    return out


def read_session_map(racing_dir: Path) -> dict[str, dict[str, str]]:
    """The server's table: league key -> labels, from `<racing_dir>/session_map.json`."""
    data = _read_json(Path(racing_dir) / SESSION_MAP)
    rows = data.get("sessions") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise BundleError(f"{Path(racing_dir) / SESSION_MAP}: no `sessions` list.")
    return {
        r["key"]: {"race": r["race"], "session": r["session"], "label": r["label"]} for r in rows
    }


def _feed_paths(league: dict[str, Any]) -> list[str]:
    sessions = league.get("sessions") if isinstance(league, dict) else None
    if not isinstance(sessions, dict):
        return []
    return [
        e["feed"]
        for e in sessions.values()
        if isinstance(e, dict) and isinstance(e.get("feed"), str)
    ]


def feeds_present(racing_dir: Path) -> bool:
    """True when every feed `racing_dir/league.json` names is a file, resolved from racing_dir."""
    racing_dir = Path(racing_dir)
    feeds = _feed_paths(_read_json(racing_dir / "league.json"))
    return bool(feeds) and all((racing_dir / f).is_file() for f in feeds)


def limits_mode(racing_dir: Path) -> str:
    """ "rerule" when the feeds sit in the racing dir, else "checked"."""
    return "rerule" if feeds_present(racing_dir) else "checked"


# ---------------------------------------------------------------- the README


def _find_line(lines: list[str], words: str, readme: Path) -> int:
    hits = [i for i, line in enumerate(lines) if words in line]
    if len(hits) != 1:
        raise BundleError(f"{readme}: {len(hits)} lines hold {words!r}; exactly one is needed.")
    return hits[0]


def read_readme_numbers(readme: Path) -> dict[str, Any]:
    """Each static number with its README line (1-based), and the racing scoreboard rows."""
    try:
        lines = Path(readme).read_text(encoding="utf-8").split("\n")
    except OSError as exc:
        raise BundleError(
            f"{readme}: cannot be read ({exc.strerror or type(exc).__name__})."
        ) from None
    numbers: dict[str, Any] = {}
    for key, (words, pattern) in README_NUMBERS.items():
        i = _find_line(lines, words, readme)
        m = re.search(pattern, lines[i])
        if not m:
            raise BundleError(f"{readme}: line {i + 1} no longer states {key}.")
        text = SERVED_WORDS[key].format(m.group(0)) if key in SERVED_WORDS else m.group(0)
        numbers[key] = {"text": text, "readme_line": i + 1}
    start = _find_line(lines, SCOREBOARD_ANCHOR, readme)
    try:
        head = next(i for i in range(start, len(lines)) if lines[i].strip() == SCOREBOARD_HEADER)
    except StopIteration:
        raise BundleError(f"{readme}: no racing scoreboard after line {start + 1}.") from None
    board: list[dict[str, Any]] = []
    i = head + 2
    while i < len(lines) and lines[i].startswith("|"):
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if len(cells) != 4:
            raise BundleError(f"{readme}: line {i + 1} is not a four-cell scoreboard row.")
        mark, result, pass_mark, verdict = cells
        if SCOREBOARD_KEYS.get(mark) == "spend_mark":
            # Only the dollar figure is served; the README's own words name the tooling.
            spent = re.search(README_NUMBERS["spend"][1], result)
            if not spent:
                raise BundleError(f"{readme}: line {i + 1} no longer states the spend.")
            result = SERVED_WORDS["spend"].format(spent.group(0))
        board.append(
            {
                "key": SCOREBOARD_KEYS.get(mark),
                "mark": mark,
                "result": result,
                "pass_mark": pass_mark,
                "verdict": verdict,
                "readme_line": i + 1,
            }
        )
        i += 1
    if sorted(r["key"] for r in board if r["key"]) != sorted(SCOREBOARD_KEYS.values()):
        raise BundleError(f"{readme}: the racing scoreboard at line {head + 1} lost a row.")
    for row in board:
        if row["key"]:
            numbers[row["key"]] = {
                "text": row["result"],
                "verdict": row["verdict"],
                "readme_line": row["readme_line"],
            }
    h = _find_line(lines, HONESTY_ANCHOR, readme)
    honesty = [lines[h].strip().lstrip("- ").strip()]
    j = h + 1
    while j < len(lines) and lines[j].startswith("  ") and lines[j].strip():
        honesty.append(lines[j].strip())
        j += 1
    return {
        "numbers": numbers,
        "scoreboard": board,
        "honesty": {"lines": honesty, "readme_line": h + 1},
    }


def _ints(text: str) -> list[int]:
    return [int(n) for n in re.findall(r"\d+", text)]


# ---------------------------------------------------------------- the rows


def _car(num: object) -> str:
    return f"car {num}"


def _read_row(card: ModuleType, line: dict[str, Any] | None, arm: int, did: str) -> dict[str, Any]:
    read = (line or {}).get("model_read") or None
    if read is None:
        name, where = MODELS[ARM_MODELS[arm]]  # a line with no read still names its arm
        return {
            "arm": arm,
            "model": name,
            "where": where,
            "runs": 0,
            "agreed": False,
            "offender": None,
            "verdict": None,
            "no_text": False,
        }
    model = str(read.get("model"))
    if model not in MODELS:
        raise BundleError(f"protest {did}: arm {arm} names a model the page does not know.")
    name, where = MODELS[model]
    agreed = read.get("agreed") is True
    runs = read.get("runs") if isinstance(read.get("runs"), int) else 0
    offender = read.get("offender") if agreed else None
    verdict = read.get("verdict") if agreed else None
    return {
        "arm": arm,
        "model": name,
        "where": where,
        "runs": runs,
        "agreed": agreed,
        "offender": _car(offender) if offender else None,
        "verdict": card.VERDICT_WORDS.get(str(verdict), str(verdict)) if verdict else None,
        "no_text": bool(runs) and read.get("parse_failures") == runs,
    }


def _steward(card: ModuleType, truth: dict[str, Any]) -> str:
    verdict = card.VERDICT_WORDS.get(str(truth.get("verdict")), str(truth.get("verdict")))
    car = truth.get("offender_sim")
    text = f"{verdict}, {_car(car)}" if car else f"{verdict}, no car named"
    victim = truth.get("victim_sim")
    return f"{text} (contact with {_car(victim)})" if victim else text


def _protests(
    card: ModuleType, corpus: Any, labels: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    score = card.score
    rows = []
    for did in sorted(corpus.arms[2], key=score.numkey):
        line = corpus.arms[2][did]
        other = corpus.arms[1].get(did)
        w = line.get("window") or {}
        lab = labels[w["session"]]
        at = card.moment(corpus, did)
        row: dict[str, Any] = {
            "id": did,
            "label": f"Protest {did}",
            "rule": line.get("rule"),
            "clause": line.get("clause"),
            "kind": line.get("kind"),
            "window": {
                "race": lab["race"],
                "session": lab["session"],
                "label": lab["label"],
                "lap": w.get("lap"),
                "feed_s": list(w.get("te") or []),
                "moment_feed_s": None if at is None else at[0],
            },
            "candidates": [_car(c) for c in sorted(line.get("candidates") or [], key=score.numkey)],
            "facts": list(line.get("facts") or []),
            "evidence": line.get("evidence"),
            "missing_fact": line.get("missing_fact"),
            "steward_ruling": _steward(card, corpus.truth[did]),
            "verdict": line.get("verdict"),
            "reads": [_read_row(card, other, 1, did), _read_row(card, line, 2, did)],
            "frames_checked": len(line.get("frames") or []),
            "record": {"arm1": (other or {}).get("record"), "arm2": line.get("record")},
        }
        rows.append(row)
    return rows


def _limits(
    card: ModuleType, corpus: Any, limit_lines: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:  # fmt: skip
    score = card.score
    names = {}
    for key, s in corpus.sessions.items():
        pair = (s.get("track_short"), s.get("session"))
        if pair in names:
            raise BundleError("two league sessions share a track and a session name.")
        names[pair] = key
    no_ruling = set()
    for b in corpus.no_ruling:
        no_ruling.add((names[(b["track"], b["session"])], str(b["car"])))
    ordered = sorted(
        limit_lines.values(),
        key=lambda r: (
            score.session_order(r["window"]["session"]),
            score.numkey(r.get("offender") or ""),
        ),
    )
    rows = []
    for n, r in enumerate(ordered, 1):
        key = r["window"]["session"]
        lab = labels[key]
        on_record = None
        if r.get("verdict") == "breach":
            on_record = (key, str(r.get("offender"))) not in no_ruling
        rows.append(
            {
                "id": f"s{n}",
                "race": lab["race"],
                "session": lab["session"],
                "label": lab["label"],
                "verdict": r.get("verdict"),
                "offender": _car(r["offender"]) if r.get("offender") else None,
                "clause": r.get("clause"),
                "evidence": r.get("evidence"),
                "facts": list(r.get("facts") or []),
                "missing_fact": r.get("missing_fact"),
                "ruling_on_record": on_record,
                "record": r.get("record"),
                **_stated_numbers(score, r, corpus.sessions[key]),
            }
        )
    return rows


def _stated_numbers(score: ModuleType, line: dict[str, Any], session: dict[str, Any]) -> dict:
    """`incidents` and `limit` as the stored line's evidence states them; None where it does not.

    Read, never computed: the car's total with `racing_score`'s own pattern (`_TOTAL`, "on N
    incident points"), the limit from "the limit of N". A stated limit that differs from the
    league's session limit refuses the build.
    """
    text = line.get("evidence") or ""
    total = score._TOTAL.search(text)
    limit = _LIMIT.search(text)
    got = {
        "incidents": int(total.group(1)) if total else None,
        "limit": int(limit.group(1)) if limit else None,
    }
    if got["limit"] is not None and got["limit"] != session.get("incident_limit"):
        raise BundleError(
            f"a limits line states a limit its session does not hold ({got['limit']})."
        )
    return got


# ---------------------------------------------------------------- checks


def _texts(obj: object) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k != "record":
                yield from _texts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _texts(v)


def _check_counts(
    readme: dict[str, Any], protests: list[dict[str, Any]], limits: list[dict]
) -> None:
    n = readme["numbers"]
    breaches = [r for r in limits if r["verdict"] == "breach"]
    want = {
        "over_limit": len(breaches),
        "on_record": sum(1 for r in breaches if r["ruling_on_record"]),
        "no_ruling": sum(1 for r in breaches if r["ruling_on_record"] is False),
    }
    for key, got in want.items():
        if _ints(n[key]["text"])[0] != got:
            raise BundleError(
                f"README line {n[key]['readme_line']} states {n[key]['text']!r}; "
                f"the data holds {got}."
            )
    total = _ints(n["read_offender"]["text"])[1]
    if total != len(protests):
        raise BundleError(
            f"README line {n['read_offender']['readme_line']} counts {total} protests; "
            f"the data holds {len(protests)}."
        )


def _check_clean(card: ModuleType, doc: dict[str, Any], names: list[str], banned: list[str],
                 session_numbers: list[str]) -> None:  # fmt: skip
    text = "\n".join(_texts(doc))
    try:
        card.check_page(RACING_JSON, html.escape(text, quote=True), names, banned)
    except card.CardError as exc:
        raise BundleError(str(exc)) from None
    raw = _canonical(doc).decode("utf-8")
    for num in session_numbers:
        if num and num in raw:
            raise BundleError(f"{RACING_JSON}: refused, a league session number appears in it.")


def _same_bytes(a: Path, b: Path) -> None:
    try:
        same = a.read_bytes() == b.read_bytes()
    except OSError as exc:
        raise BundleError(f"{exc.filename}: cannot be read ({exc.strerror}).") from None
    if not same:
        raise BundleError(f"{b}: differs from {a}; the page would show another record.")


# ---------------------------------------------------------------- build


def build_racing(
    racing_dir: Path,
    readme: Path,
    out: Path,
    source: Path | None = None,
    limits: Path | None = None,
) -> str:
    """Write `<out>/racing.json` and `<racing_dir>/session_map.json`; return the first's sha256."""
    racing_dir, out = Path(racing_dir), Path(out)
    source = Path(source) if source else racing_dir
    if limits is None:
        limits = source / LIMITS_FILE
        if not limits.is_file():
            limits = source / "limits-a.jsonl"
    for name in ARM_FILES.values():
        _same_bytes(source / name, racing_dir / name)
    _same_bytes(Path(limits), racing_dir / LIMITS_FILE)

    card = _card()
    try:
        corpus = card.load_corpus(source, Path(limits))
        names, banned = card.gather_names(source, None)
        if HONESTY_ID in corpus.arms[2]:
            card.check_honesty(corpus)
        limit_lines, _ = card.score.read_preds([Path(limits)])
    except (card.CardError, card.score.ScoreError) as exc:
        raise BundleError(str(exc)) from None

    league = _read_json(racing_dir / "league.json")
    if sorted(league.get("sessions") or {}) != sorted(corpus.sessions):
        raise BundleError(f"{racing_dir / 'league.json'}: holds other sessions than the source.")
    labels = session_labels(corpus.sessions)
    readme_data = read_readme_numbers(readme)
    protests = _protests(card, corpus, labels)
    limit_rows = _limits(card, corpus, limit_lines, labels)
    _check_counts(readme_data, protests, limit_rows)
    honesty = readme_data["honesty"]
    for p in protests:
        p["honesty"] = honesty if p["id"] == HONESTY_ID else None

    doc = {
        "schema": SCHEMA,
        "limits_mode": limits_mode(racing_dir),
        "protests": protests,
        "limits": limit_rows,
        "numbers": readme_data["numbers"],
        "scoreboard": readme_data["scoreboard"],
    }
    session_numbers = sorted({k.partition("/")[0] for k in corpus.sessions})
    _check_clean(card, doc, names, banned, session_numbers)

    data = _canonical(doc)
    smap = {
        "schema": SCHEMA,
        "sessions": [{"key": k, **v} for k, v in labels.items()],
    }
    _write_atomic(out / RACING_JSON, data)
    _write_atomic(racing_dir / SESSION_MAP, _canonical(smap))
    return hashlib.sha256(data).hexdigest()
