"""Entry roster, closed candidate set and digit snapping.

An entry is one subject in one session: its number inside the source (`num`), its stable
customer id (`cust_id`) and, where the source knows it, its league number (`league_num`).
Numbers are strings: "01" and "1" are two different entries.

`closed_set(positions_by_te, track_m, focus, te_lo, te_hi, near_m=8.0, pad_s=3)`:

- `positions_by_te` maps an integer second (an `int` key; string keys such as those left by
  `json.load` are refused) to `{num: progress}`, where progress is loops-plus-fraction along a
  closed loop whose length is `track_m` metres. Progress must be zero or more: a source that
  marks a subject out of the world with a negative value (such as -1) must have its adapter
  drop those readings before calling, or the call is refused.
- Over every second from `te_lo - pad_s` to `te_hi + pad_s` (inclusive) that the map holds,
  a subject joins the set when it is one of `focus`, or when it comes within `near_m` metres of
  any focus subject. Distance is measured along the loop between the two positions on it, so
  whole loops of difference are ignored (a subject one loop down, beside a focus subject, is near).
- Each `Candidate` holds `num`, `closest_m` (metres, rounded to 1 decimal), `relation` and `why`.
  For a non-focus subject, `relation` is "ahead" or "behind" the nearest focus subject at its
  closest moment ("level" at exactly zero gap), and `closest_m` is that gap. A focus subject has
  relation "focus" and `closest_m` is its closest gap to any other subject seen in the window,
  or None when it was alone. Ties on the closest moment go to the earliest second, then to the
  focus subject first by `numkey`.
- A focus subject never seen in the window is left out; an empty list means nothing to rule on.
- The list is sorted by `numkey`.

`snap(read, candidates, roster=None)` turns a number read by a model or OCR into a candidate
number: the digits of `read` are compared with each candidate's digits by Levenshtein edit
distance. It returns the one candidate at the smallest distance when that distance is 0 or 1,
and refuses (returns None):

- when `read` holds no digit;
- on a tie, or on a distance over 1;
- on a distance of 1 when the read has a single digit (one edit turns any one digit into any
  other, so "7" would reach "3" and "1" would reach "12");
- when `roster` (every entry number in the session) is given and the read exactly matches a
  roster entry that is not a candidate: that subject is real but outside the set, so the read
  is never re-pinned onto a neighbour.

`numkey(num)` is the sort key for numbers: all-digit strings by integer value then by string
(so "01" sorts before "1", and both before "2"), anything else after them by string.

Bad input (a non-positive loop length, a window that ends before it starts, a negative reach
or pad, a non-integer second, a non-finite or negative progress) raises `RosterError` naming
the reason.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

__all__ = [
    "Candidate",
    "Entry",
    "RosterError",
    "WHY_FOCUS",
    "WHY_NEAR",
    "closed_set",
    "numkey",
    "snap",
]

WHY_FOCUS = "focus subject"
WHY_NEAR = "came within reach of a focus subject"


class RosterError(ValueError):
    """Roster input was refused; the message names the reason."""


@dataclass(frozen=True)
class Entry:
    """One subject in one session: source number, customer id and league number if known."""

    num: str
    cust_id: int
    league_num: str | None = None


@dataclass(frozen=True)
class Candidate:
    """One member of a closed set: its number, closest gap, relation and why it is in."""

    num: str
    closest_m: float | None
    relation: str
    why: str


def numkey(num: str) -> tuple[int, int, str]:
    """Sort key: all-digit strings by integer then string, any other string after them."""
    if num.isascii() and num.isdigit():
        return (0, int(num), num)
    return (1, 0, num)


def _loop_gap(other: float, ref: float) -> float:
    """Signed fraction of a loop from `ref` to `other`, wrapped into [-0.5, 0.5)."""
    diff = (other - ref) % 1.0
    if diff >= 0.5:
        diff -= 1.0
    return diff


def _check_progress(te: int, num: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RosterError(f"second {te}, subject {num}: progress is not a number ({value!r}).")
    if not math.isfinite(value):
        raise RosterError(f"second {te}, subject {num}: progress is not finite ({value!r}).")
    if value < 0:
        raise RosterError(
            f"second {te}, subject {num}: progress is negative ({value!r}); "
            "drop out-of-world readings before calling."
        )
    return float(value)


def closed_set(
    positions_by_te: Mapping[int, Mapping[str, float]],
    track_m: float,
    focus: Iterable[str],
    te_lo: int,
    te_hi: int,
    near_m: float = 8.0,
    pad_s: int = 3,
) -> list[Candidate]:
    """Return the closed candidate set around `focus` over the padded window (see module doc)."""
    if not (isinstance(track_m, (int, float)) and math.isfinite(track_m) and track_m > 0):
        raise RosterError(f"loop length must be a positive number of metres, not {track_m!r}.")
    if te_hi < te_lo:
        raise RosterError(f"window ends before it starts ({te_lo} to {te_hi}).")
    if not (math.isfinite(near_m) and near_m >= 0):
        raise RosterError(f"reach must be zero or more metres, not {near_m!r}.")
    if pad_s < 0:
        raise RosterError(f"pad must be zero or more seconds, not {pad_s!r}.")
    focus_nums = sorted(set(focus), key=numkey)
    if not focus_nums:
        raise RosterError("no focus subject was given.")
    focus_set = set(focus_nums)
    for key in positions_by_te:
        if isinstance(key, bool) or not isinstance(key, int):
            raise RosterError(f"seconds must be int keys, not {key!r} ({type(key).__name__}).")

    # num -> (abs gap metres, second, focus num, signed gap metres)
    best_near: dict[str, tuple[float, int, str, float]] = {}
    best_focus: dict[str, float | None] = {}
    for te in range(te_lo - pad_s, te_hi + pad_s + 1):
        frame = positions_by_te.get(te)
        if not frame:
            continue
        progress = {num: _check_progress(te, num, value) for num, value in frame.items()}
        present_focus = [num for num in focus_nums if num in progress]
        for fnum in present_focus:
            best_focus.setdefault(fnum, None)
            for other, value in progress.items():
                if other == fnum:
                    continue
                gap = abs(_loop_gap(value, progress[fnum])) * track_m
                current = best_focus[fnum]
                if current is None or gap < current:
                    best_focus[fnum] = gap
        for other, value in progress.items():
            if other in focus_set:
                continue
            for fnum in present_focus:
                signed = _loop_gap(value, progress[fnum]) * track_m
                gap = abs(signed)
                if gap > near_m:
                    continue
                held = best_near.get(other)
                if held is None or gap < held[0]:
                    best_near[other] = (gap, te, fnum, signed)

    out: list[Candidate] = []
    for fnum, best in best_focus.items():
        closest = None if best is None else round(best, 1)
        out.append(Candidate(fnum, closest, "focus", WHY_FOCUS))
    for other, (gap, _te, _fnum, signed) in best_near.items():
        if signed > 0:
            relation = "ahead"
        elif signed < 0:
            relation = "behind"
        else:
            relation = "level"
        out.append(Candidate(other, round(gap, 1), relation, WHY_NEAR))
    out.sort(key=lambda c: numkey(c.num))
    return out


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance between two strings."""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isascii() and ch.isdigit())


def snap(
    read: str,
    candidates: Iterable[str | Candidate],
    roster: Iterable[str | Entry] | None = None,
) -> str | None:
    """Snap a read number to the one nearest candidate by digit edit distance, or refuse."""
    read_digits = _digits(read)
    if not read_digits:
        return None
    nums = {c.num if isinstance(c, Candidate) else c for c in candidates}
    if roster is not None:
        for entry in roster:
            num = entry.num if isinstance(entry, Entry) else entry
            if num not in nums and _digits(num) == read_digits:
                return None
    scored = sorted(
        ((_edit_distance(read_digits, _digits(num)), num) for num in nums if _digits(num)),
        key=lambda pair: (pair[0], numkey(pair[1])),
    )
    if not scored or scored[0][0] > 1:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    if scored[0][0] == 1 and len(read_digits) == 1:
        return None
    return scored[0][1]
