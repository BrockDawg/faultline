"""Protest reader and normaliser for the PitBot adapter.

`read_reports(path)` reads `data/racing/reports.jsonl`: one JSON object per line, holding
exactly the keys in `REPORT_KEYS` (the race is given by `session`, never found). A line holding
any outcome key (`OUTCOME_KEYS`: a verdict, penalty points, a ruling reason, the penalised
driver or car, an evidence link) is refused with `ProtestError` naming the file, the line and
the key, so nothing downstream can read what the stewards decided. A missing or extra key, a
blank or non-object line, is refused the same way.

`normalise(report, feed, number_map, known_names=(), allow=())` turns one report into a
`Normalised`, using only `feed.session`, `feed.nums`, `feed.cust_id(num)` and
`feed.private_names()` (sim number to name, held in memory only):

- A written car number resolves inside the report's own session: a sim number present in the
  session reads as itself; otherwise it is read as a league number through the `number_map`
  entry (from `league.json`) whose `sim_nums` holds this session, and when that entry's
  customer id is known to the feed it must agree. Failing both, `roster.snap` may correct a
  clear digit misread onto a session number, but never a number that is itself a real entry
  (a sim number in this session, or any league or sim number in the map, from any session).
  Anything else becomes
  `car [unresolved N]`.
- Car numbers are found by fixed patterns only: `#N`, `Car N` / `car N`, `Nr. N`, `No. N`.
- Driver names in `description` and `involved` are resolved as mentions. A name token is a
  letter run of 2 or more letters from a session name (`private_names()`) or from
  `known_names`; names are compared with digits and car numbers dropped, so a feed's
  "First Last2" is "First Last". A mention is a run of adjacent tokens (joined by spaces or
  one hyphen) made of name tokens (4+ letters in any case, or capitalised 2-3 letter ones)
  and capitalised words that are not sentence-initial and not in `_NOT_NAMES`:
  - a mention of 2 or more tokens becomes `car N` only when car N's name is the one session
    name holding every token in it (so a prefix tag every feed name carries can be written
    or dropped); a capitalised word that is no one's name token, or any token that is not
    N's, makes the whole mention `[unresolved driver]` and adds no car;
  - a lone token resolves only when it is written capitalised somewhere in the text. One
    never written capitalised never becomes a car: a 2-3 letter one is left, a 4+ letter one
    is masked `[unresolved driver]` (the lint would refuse it), so "on the main straight"
    keeps "main" only when the caller passes it in `allow`. A capitalised one becomes `car N` only
    when it is car N's surname (4+ letters) or first name (a prefix tag skipped), held by
    no other driver in the session and by no other person in `known_names` (two names are
    the same person when one's tokens are a subset of the other's). Otherwise it becomes
    `[unresolved driver]`, except a 2-3 letter word no session name holds, which is left;
  - once a mention is `car N`, a 2-3 letter token of N's name beside it (any case) joins it,
    so a short first name never survives next to its surname.
  The caller must pass in `known_names` every name in every league feed (and every name
  the league's own records hold): a driver absent from this session's feed can only be
  caught, and refused as `[unresolved driver]`, through that list.
- A link (`scheme://...`, `www....`) becomes `[link]`, and a slash joining words
  ("brake/steering") is spaced (" / ") so the lint does not read it as a file path.
- Outcome words (`penalty`, `penalties`, `penalise(d)`/`penalize(d)`, `no action`, `ruling`,
  `ruled`) become `[outcome word]`.
- Laps by fixed patterns: `lap N`, `laps N & M` (also `and`, `/`, `,`), `L N` / `LN`, and
  `last lap` (a flag, not a number).

`Normalised.text` is the normalised description, followed by a line `Involved: ...` when the
report names who was involved. `cars` holds the sim numbers named in the text (not the
reporter), sorted by `numkey`; `reporter_car` is the reporter's sim number or None;
`unresolved` lists each placeholder in order of appearance (the reporter's number included
when it does not resolve). The record holds no outcome field and no name.

Before it is returned, the text must pass `lint.assert_clean` against every name given (the
session's and `known_names`); a failure raises `ProtestError` giving the report id and the
lint's hit kinds, never the text.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from faultline import lint, roster

__all__ = [
    "LINK",
    "OUTCOME_KEYS",
    "OUTCOME_WORD",
    "REPORT_KEYS",
    "UNRESOLVED_DRIVER",
    "Normalised",
    "ProtestError",
    "normalise",
    "read_reports",
]

REPORT_KEYS = (
    "created_at",
    "description",
    "id",
    "involved",
    "iracing_subsession_id",
    "race_number",
    "reporter_car",
    "session",
    "track",
)
OUTCOME_KEYS = (
    "evidence_url",
    "penalised",
    "penalised_car",
    "penalty_points",
    "ruling_reason",
    "verdict",
)
UNRESOLVED_DRIVER = "[unresolved driver]"
OUTCOME_WORD = "[outcome word]"

_CAR = re.compile(r"(?:(?<!\w)(?:car|nr\.?|no\.)\s*#?\s?|#\s?)(\d{1,3})(?!\d)", re.IGNORECASE)
_OUTCOME = re.compile(
    r"(?<!\w)(?:penalt(?:y|ies)|penali[sz]e[sd]?|no\s+action|ruling|ruled)(?!\w)",
    re.IGNORECASE,
)
_LAPS = re.compile(r"\blaps?\s*(\d{1,3})(?:\s*(?:&|and|/|,)\s*(\d{1,3}))?(?!\d)", re.IGNORECASE)
_L_LAP = re.compile(r"\bL\s?(\d{1,2})\b")
_LAST_LAP = re.compile(r"\blast\s+lap\b", re.IGNORECASE)
_DOUBLE_CAR = re.compile(r"\bcar (\w+)(?:\s+car \1\b)+")
_LINK = re.compile(r"\b(?:[a-z][a-z0-9+.\-]*://|www\.)\S+", re.IGNORECASE)
_WORD_SLASH = re.compile(r"(?<=[^\W\d_])[\\/](?=\w)|(?<=\w)[\\/](?=[^\W\d_])")
LINK = "[link]"
_TOKEN = re.compile(r"[^\W\d_]{2,}")
_BETWEEN = re.compile(r"[ \t]+|[ \t]*-[ \t]*")
# Capitalised words that are never part of a name mention.
_NOT_NAMES = frozenset(
    {"car", "cars", "lap", "laps", "turn", "race", "heat", "feature", "the", "and", "he", "she"}
)


class ProtestError(ValueError):
    """A report was refused; the message names the file or report and the reason, never text."""


class FeedView(Protocol):
    """The four members of a `Feed` the normaliser may read."""

    @property
    def session(self) -> str: ...

    @property
    def nums(self) -> Iterable[str]: ...

    def cust_id(self, num: str) -> Any: ...

    def private_names(self) -> Mapping[str, str]: ...


@dataclass(frozen=True)
class Normalised:
    """One report with names and numbers resolved to sim numbers; no outcome, no name."""

    id: str
    session: str
    text: str
    cars: tuple[str, ...]
    reporter_car: str | None
    laps: tuple[int, ...]
    last_lap: bool
    unresolved: tuple[str, ...]


def read_reports(path: str | Path) -> list[dict[str, Any]]:
    """Read protest lines, refusing any outcome key, a missing or extra key, or a bad line."""
    path = Path(path)
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProtestError(f"{path}: line {n}: not JSON ({exc.msg}).") from None
            if not isinstance(record, dict):
                raise ProtestError(f"{path}: line {n}: not a JSON object.")
            for key in OUTCOME_KEYS:
                if key in record:
                    raise ProtestError(
                        f"{path}: line {n}: outcome key {key!r} is present; "
                        "a protest line must not carry the stewards' decision."
                    )
            missing = sorted(set(REPORT_KEYS) - set(record))
            extra = sorted(set(record) - set(REPORT_KEYS))
            if missing or extra:
                raise ProtestError(
                    f"{path}: line {n}: keys differ from the protest contract "
                    f"(missing {missing}, unexpected {extra})."
                )
            out.append(record)
    return out


# ---------------------------------------------------------------- number resolution


def _same_session(report_session: str, feed_session: str) -> bool:
    return feed_session == report_session or report_session.endswith("/" + feed_session)


class _Numbers:
    """Resolve a written number to a sim number inside one session."""

    def __init__(self, session: str, feed: FeedView, number_map: Mapping[str, Any]) -> None:
        self.nums = sorted({str(n) for n in feed.nums}, key=roster.numkey)
        self.num_set = set(self.nums)
        self.feed = feed
        self.by_league: dict[str, set[str]] = {}
        # Every number that is a real entry somewhere: never snapped onto a neighbour here.
        self.real_nums: set[str] = set(self.nums)
        for entry in number_map.get("entries", []):
            self.real_nums.update(str(v) for v in (entry.get("sim_nums") or {}).values())
            league_num = str(entry.get("league_num") or "")
            if not league_num:
                continue
            self.real_nums.add(league_num)
            sim = (entry.get("sim_nums") or {}).get(session)
            if sim is None or str(sim) not in self.num_set:
                continue
            known = feed.cust_id(str(sim))
            if known is not None and str(known) != str(entry.get("cust_id")):
                continue
            self.by_league.setdefault(league_num, set()).add(str(sim))

    def resolve(self, written: str) -> str | None:
        if written in self.num_set:
            return written
        mapped = self.by_league.get(written, set())
        if len(mapped) == 1:
            return next(iter(mapped))
        if mapped or written in self.real_nums:
            return None
        return roster.snap(written, self.nums, roster=self.nums)


# ---------------------------------------------------------------- names


def _name_key(name: str) -> str:
    """A name compared loosely: car numbers, digits and stray marks dropped, case folded.

    The same person can appear with a digit suffix in a feed and without it in a list.
    """
    name = re.sub(r"#\s*\d+|\d+", " ", name)
    name = re.sub(r"[^\w' .-]+", " ", name)
    return " ".join(name.split()).strip(" .-'").casefold()


def _name_tokens(name: str) -> tuple[str, ...]:
    """Every letter run of 2 or more letters in a name, casefolded, in order."""
    return tuple(m.group().casefold() for m in _TOKEN.finditer(name))


def _sentence_initial(text: str, start: int) -> bool:
    before = text[:start].rstrip(" \t")
    return not before or before[-1] in ".!?:\n(\"'"


class _Names:
    """Who a name mention in one session's protest refers to (see the module docstring)."""

    def __init__(self, session_names: Mapping[str, str], known_names: Iterable[str]) -> None:
        self.car_tokens = {num: _name_tokens(name) for num, name in session_names.items()}
        self.owners: dict[str, set[str]] = {}
        for num, toks in self.car_tokens.items():
            for tok in toks:
                self.owners.setdefault(tok, set()).add(num)
        people = {frozenset(t) for t in self.car_tokens.values() if t}
        people |= {frozenset(_name_tokens(_name_key(n))) for n in known_names}
        people.discard(frozenset())
        self.people = people
        self.all_tokens = set().union(*people) if people else set()
        # A prefix tag every name in a feed carries is not a first name.
        floor = max(3, (len(self.car_tokens) + 1) // 2)
        self.tags = {tok for tok, cars in self.owners.items() if len(cars) >= floor}

    def _held_by_someone_else(self, tok: str, num: str) -> bool:
        mine = frozenset(self.car_tokens[num])
        return any(tok in p and not (p <= mine or mine <= p) for p in self.people)

    def lone(self, tok: str) -> str | None:
        """The one session car a lone token names, or None."""
        cars = self.owners.get(tok, set())
        if len(cars) != 1:
            return None
        num = next(iter(cars))
        core = [t for t in self.car_tokens[num] if t not in self.tags]
        if not core or self._held_by_someone_else(tok, num):
            return None
        is_surname = tok == core[-1] and len(tok) >= 4
        is_first = tok == core[0]
        return num if (is_surname or is_first) else None

    def unit(self, toks: list[str]) -> str | None:
        """The one session car whose name holds every token of a mention, or None."""
        cars: set[str] | None = None
        for tok in toks:
            held = self.owners.get(tok, set())
            cars = set(held) if cars is None else cars & held
        if cars is None or len(cars) != 1:
            return None
        return next(iter(cars))


def _name_spans(text: str, names: _Names, allow: Iterable[str]) -> list[tuple[int, int, str]]:
    """Spans of name mentions in `text`, each with `car N` or the unresolved mark."""
    allowed = {a.casefold() for a in allow}
    found = list(_TOKEN.finditer(text))
    capitalised = {m.group().casefold() for m in found if m.group()[0].isupper()}

    def kind(m: re.Match[str]) -> str | None:
        tok = m.group().casefold()
        cap = m.group()[0].isupper()
        if tok in allowed:
            return None
        if tok in names.all_tokens and (len(tok) >= 4 or cap):
            return "name"
        if cap and tok not in _NOT_NAMES and not _sentence_initial(text, m.start()):
            return "word"
        return None

    groups: list[list[tuple[re.Match[str], str]]] = []
    current: list[tuple[re.Match[str], str]] = []
    for m in found:
        k = kind(m)
        if k and current and _BETWEEN.fullmatch(text[current[-1][0].end() : m.start()]):
            current.append((m, k))
            continue
        if current:
            groups.append(current)
        current = [(m, k)] if k else []
    if current:
        groups.append(current)

    spans: list[tuple[int, int, str]] = []
    for group in groups:
        toks = [m.group().casefold() for m, _k in group]
        kinds = [k for _m, k in group]
        if "name" not in kinds:
            continue
        start, end = group[0][0].start(), group[-1][0].end()
        num: str | None
        if len(group) == 1:
            tok = toks[0]
            if tok not in capitalised:
                # Never written capitalised: never resolved to a car. A 4+ letter name token
                # would be refused by the lint, so it is masked instead (pass ordinary words
                # such as "main" in `allow` to keep them); a short one is left.
                if len(tok) >= 4:
                    spans.append((start, end, UNRESOLVED_DRIVER))
                continue
            num = names.lone(tok)
            if num is None and len(tok) < 4 and not names.owners.get(tok):
                continue  # a short word held only outside the session: not a name here
        else:
            num = None if "word" in kinds else names.unit(toks)
        if num is None:
            spans.append((start, end, UNRESOLVED_DRIVER))
            continue
        # A short token of the same driver beside the mention goes with it.
        mine = set(names.car_tokens[num])
        for m in reversed(found):
            if m.end() <= start and m.group().casefold() in mine:
                if _BETWEEN.fullmatch(text[m.end() : start]):
                    start = m.start()
        for m in found:
            if m.start() >= end and m.group().casefold() in mine:
                if _BETWEEN.fullmatch(text[end : m.start()]):
                    end = m.end()
        spans.append((start, end, f"car {num}"))
    return spans


# ---------------------------------------------------------------- the pass


def _rewrite(
    text: str,
    names: list[tuple[int, int, str]],
    numbers: _Numbers,
    cars: set[str],
    unresolved: list[str],
) -> str:
    spans: list[tuple[int, int, str]] = list(names)
    for m in _CAR.finditer(text):
        written = m.group(1)
        sim = numbers.resolve(written)
        spans.append((m.start(), m.end(), f"car {sim}" if sim else f"car [unresolved {written}]"))
    for m in _OUTCOME.finditer(text):
        spans.append((m.start(), m.end(), OUTCOME_WORD))
    for m in _LINK.finditer(text):
        spans.append((m.start(), m.end(), LINK))
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    out: list[str] = []
    pos = 0
    for start, end, repl in spans:
        if start < pos:
            continue
        out.append(text[pos:start])
        out.append(repl)
        pos = end
        if repl.startswith("car [unresolved") or repl == UNRESOLVED_DRIVER:
            unresolved.append(repl)
        elif repl.startswith("car "):
            cars.add(repl[4:])
    out.append(text[pos:])
    joined = _WORD_SLASH.sub(" / ", "".join(out))
    return _DOUBLE_CAR.sub(lambda m: f"car {m.group(1)}", joined)


def _laps(text: str) -> tuple[tuple[int, ...], bool]:
    found: set[int] = set()
    for m in _LAPS.finditer(text):
        found.update(int(g) for g in m.groups() if g)
    for m in _L_LAP.finditer(text):
        found.add(int(m.group(1)))
    return tuple(sorted(found)), bool(_LAST_LAP.search(text))


def normalise(
    report: Mapping[str, Any],
    feed: FeedView,
    number_map: Mapping[str, Any],
    known_names: Iterable[str] = (),
    allow: Iterable[str] = (),
) -> Normalised:
    """Normalise one report against its session's feed (see the module docstring)."""
    rid = str(report.get("id"))
    session = str(report.get("session") or "")
    if not session or not _same_session(session, str(feed.session)):
        raise ProtestError(f"report {rid}: the feed is not the report's session.")
    for key in OUTCOME_KEYS:
        if key in report:
            raise ProtestError(f"report {rid}: outcome key {key!r} is present.")
    allow = list(allow)
    known_names = [n for n in known_names if n]
    session_names = {str(k): v for k, v in feed.private_names().items() if v}
    numbers = _Numbers(session, feed, number_map)
    names = _Names(session_names, known_names)

    cars: set[str] = set()
    unresolved: list[str] = []
    reporter_car: str | None = None
    written_reporter = str(report.get("reporter_car") or "").strip()
    if written_reporter:
        reporter_car = numbers.resolve(written_reporter.lstrip("#").strip())
        if reporter_car is None:
            unresolved.append(f"car [unresolved {written_reporter}]")

    parts: list[str] = []
    raw = ""
    for label, field in (("", "description"), ("Involved: ", "involved")):
        value = report.get(field)
        if not value:
            continue
        value = str(value)
        raw += value + "\n"
        spans = _name_spans(value, names, allow)
        parts.append(label + _rewrite(value, spans, numbers, cars, unresolved))
    text = "\n".join(parts)
    laps, last_lap = _laps(raw)

    all_names = list(session_names.values()) + known_names
    try:
        lint.assert_clean(text, names=all_names, allow=allow)
    except lint.LintError as exc:
        kinds = sorted(set(exc.kinds))
        raise ProtestError(
            f"report {rid}: the normalised text failed the leak lint "
            f"({len(exc.kinds)} hit(s), kinds {kinds}); the text is not repeated here."
        ) from None
    return Normalised(
        id=rid,
        session=session,
        text=text,
        cars=tuple(sorted(cars, key=roster.numkey)),
        reporter_car=reporter_car,
        laps=laps,
        last_lap=last_lap,
        unresolved=tuple(unresolved),
    )
