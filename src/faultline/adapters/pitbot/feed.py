"""Read one session of a PitBot companion replay feed into per-car traces by second.

A feed file is NDJSON, gzip-compressed or plain (told apart by the gzip magic bytes), one JSON
object per line. A frame holds `timeElapsed` (seconds into the session), `session` (such as
"RACE" or "HEAT 1"), `track`, `leaderLap`, `positions[]` (`num`, `pct`, `pos`, `pit`, `carIdx`,
`custId`, `name`) and `rows[]` (`num`, `inc`, `lap`, `name`). Other keys are ignored.

`Feed.load(path, session)` keeps the frames whose `session` equals `session` and whose
`timeElapsed` is set. Each `timeElapsed` becomes an int second `te` (truncated). When two
frames share a second, the later line wins car by car (a car missing from the later frame keeps
the earlier reading), and an `inc` of -1 or a `lap` of -1 never overwrites a shown value.

Attributes: `path`, `session`, `track`, `track_m` (approximate lap length in metres, from
`TRACK_M`), `seconds` (sorted distinct seconds that hold a frame), `nums` (every car number in
`positions[]` or `rows[]`, sorted by `faultline.roster.numkey`) and `cadence_s` (the mean step
between frames, rounded half up, at least 1: 2 on the older feeds such as Oulton and
Snetterton, whose frames come every 1 to 3 seconds, and 1 elsewhere).

Time. Every accessor taking `te` answers for the frame at `second_at(te)`: the latest frame
second at or before `te`, if it is at most `HOLD_S` (2) seconds before; otherwise there is no
frame and the accessor returns None. On a 1 s feed this is the frame at `te` itself; on a 2 s
feed a second between frames answers from the frame before it.

Per car at that frame: `pct` (fraction of a lap, as the feed gives it), `pit`, `inc` (the
incident counter, None when the feed shows -1 or the car is absent), `lap` (the car's own lap
as `rows[].lap` shows it, None when -1), `lap_at` (the car's own lap, filled in between shown
rows: the last shown lap read where the car was mid-lap, 0.1 to 0.9 of a lap, plus the line
crossings its `pct` made since; before any mid-lap row the first shown row anchors it; None
before any row is shown). `leader_lap(te)` is the frame's `leaderLap`. `cust_id(num)` is the
car's last `custId`. `last_inc(num)` is the last shown counter, `counter_shown(num)` whether
any counter was shown.

Measures: `gap_m(a, b, te)` is the signed along-track gap in metres, positive when `a` is ahead
of `b`, wrapped into half a lap either way. `speed_mps(num, te)` is the mean speed from the
previous frame second when it is at most `MAX_STEP_S` (3) seconds earlier and holds the car,
else None; a backward step of more than half a lap is a line crossing, a forward step of more
than half a lap gives None. `order_at(te)` lists the cars in that frame by laps plus fraction,
leader first (cars with no known lap after the rest, by fraction; ties by `numkey`).

Rounding: no accessor rounds. `pct` is the feed's own value (4 decimals in the PitBot feeds);
`gap_m` and `speed_mps` are unrounded so thresholds compare against the same numbers the
catalogue used. A caller rounds to 1 decimal where a measure enters a record.

`positions_by_te(te_lo, te_hi)` gives `{second: {num: laps + fraction}}` for every frame second
in the closed range, the shape `faultline.roster.closed_set` takes. A car with no known lap
gives its fraction alone (the closed set ignores whole laps). A negative or non-finite `pct`
(a car not in the world) is dropped at load and appears in no accessor.

Names. `private_names()` re-reads the file and returns `{num: name}` from `rows[].name` and
`positions[].name`. Only the protest normaliser and the leak lint may call it. No attribute,
`repr` or error message of a `Feed` holds a name: the names are read on demand, never kept.

Refusals raise `FeedError` naming the file and the reason: a file that cannot be read, a line
that is not a JSON object, a frame with a bad second, car number or fraction, no frame for the
session (the sessions present are named), more than one track in the session, or a track with
no length in `TRACK_M`.
"""

from __future__ import annotations

import bisect
import gzip
import json
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TypeGuard

from faultline.roster import numkey

__all__ = ["HOLD_S", "MAX_STEP_S", "TRACK_M", "Feed", "FeedError"]

# Approximate lap lengths in metres, by the feed's `track` name. Copied as data from the
# 27 Oct discovery-3 answer key (the private working repo's `telem.py`); good to a few metres, not surveyed.
TRACK_M: dict[str, float] = {
    "Circuit de Spa-Francorchamps": 7004.0,
    "Oulton Park Circuit": 4307.0,
    "Cadwell Park": 3497.0,
    "Brands Hatch Circuit": 3908.0,
    "Silverstone Circuit": 5891.0,
    "Snetterton Racing Circuit": 4779.0,
    "Donington Park Racing Circuit": 4020.0,
    "Thruxton Circuit": 3792.0,
}

HOLD_S = 2
MAX_STEP_S = 3
_MID_LAP = (0.1, 0.9)
_GZIP_MAGIC = b"\x1f\x8b"


class FeedError(ValueError):
    """A feed could not be read; the message names the file and the reason."""


def _is_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _lines(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    """(line number, frame) for each non-blank line of the feed."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FeedError(f"{path}: cannot be read ({exc.strerror or type(exc).__name__}).") from None
    if raw[:2] == _GZIP_MAGIC:
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError):
            raise FeedError(f"{path}: gzip data is damaged.") from None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise FeedError(f"{path}: not UTF-8 text.") from None
    for no, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            raise FeedError(f"{path}: line {no} is not JSON.") from None
        if not isinstance(frame, dict):
            raise FeedError(f"{path}: line {no} is not a JSON object.")
        yield no, frame


def _num(path: Path, no: int, item: Any, where: str) -> str:
    if not isinstance(item, dict):
        raise FeedError(f"{path}: line {no}: an entry in {where} is not an object.")
    num = item.get("num")
    if isinstance(num, bool) or not isinstance(num, (str, int)) or str(num) == "":
        raise FeedError(f"{path}: line {no}: an entry in {where} has no car number.")
    return str(num)


def _session_frames(path: Path, session: str) -> list[tuple[int, int, dict[str, Any]]]:
    """(second, line number, frame) for the session, in second then file order."""
    out: list[tuple[int, int, dict[str, Any]]] = []
    seen: set[str] = set()
    for no, frame in _lines(path):
        name = frame.get("session")
        if isinstance(name, str):
            seen.add(name)
        te = frame.get("timeElapsed")
        if name != session or te is None:
            continue
        if not _is_number(te) or not math.isfinite(te) or te < 0:
            raise FeedError(f"{path}: line {no}: timeElapsed is not a second ({te!r}).")
        out.append((int(te), no, frame))
    if not out:
        present = ", ".join(sorted(seen)) or "none"
        raise FeedError(f"{path}: no frame for session {session!r} (sessions present: {present}).")
    out.sort(key=lambda item: (item[0], item[1]))
    return out


class Feed:
    """One session of a replay feed: per-car traces by second (see the module docstring)."""

    def __init__(self, path: Path, session: str) -> None:
        self.path = Path(path)
        self.session = session
        frames = _session_frames(self.path, session)

        tracks = {f.get("track") for _te, _no, f in frames}
        if len(tracks) != 1:
            raise FeedError(f"{self.path}: session {session!r} names {len(tracks)} tracks.")
        track = tracks.pop()
        if not isinstance(track, str) or track not in TRACK_M:
            raise FeedError(f"{self.path}: track {track!r} has no length in TRACK_M.")
        self.track: str = track
        self.track_m: float = TRACK_M[track]

        self._pct: dict[str, dict[int, float]] = {}
        self._pit: dict[str, dict[int, bool]] = {}
        self._inc: dict[str, dict[int, int]] = {}
        self._lap: dict[str, dict[int, int]] = {}
        self._cust: dict[str, int] = {}
        self._leader: dict[int, int] = {}
        nums: set[str] = set()
        for te, no, frame in frames:
            leader = frame.get("leaderLap")
            if _is_number(leader):
                self._leader[te] = int(leader)
            for item in frame.get("positions") or []:
                num = _num(self.path, no, item, "positions")
                nums.add(num)
                pct = item.get("pct")
                if not _is_number(pct):
                    raise FeedError(f"{self.path}: line {no}: car {num} has no pct.")
                if math.isfinite(pct) and pct >= 0:
                    self._pct.setdefault(num, {})[te] = float(pct)
                    self._pit.setdefault(num, {})[te] = bool(item.get("pit"))
                cust = item.get("custId")
                if _is_number(cust):
                    self._cust[num] = int(cust)
            for item in frame.get("rows") or []:
                num = _num(self.path, no, item, "rows")
                nums.add(num)
                inc = item.get("inc", -1)
                if _is_number(inc) and inc != -1:
                    self._inc.setdefault(num, {})[te] = int(inc)
                lap = item.get("lap", -1)
                if _is_number(lap) and lap != -1:
                    self._lap.setdefault(num, {})[te] = int(lap)

        self.seconds: list[int] = sorted({te for te, _no, _f in frames})
        self.nums: list[str] = sorted(nums, key=numkey)
        if len(self.seconds) > 1:
            mean = (self.seconds[-1] - self.seconds[0]) / (len(self.seconds) - 1)
            self.cadence_s: int = max(1, math.floor(mean + 0.5))
        else:
            self.cadence_s = 1
        self._laps: dict[str, dict[int, int]] = {n: self._fill_laps(n) for n in self._pct}

    @classmethod
    def load(cls, path: str | Path, session: str) -> Feed:
        """Load one session of the feed at `path`."""
        return cls(Path(path), session)

    def __repr__(self) -> str:
        return (
            f"Feed(session={self.session!r}, track={self.track!r}, "
            f"frames={len(self.seconds)}, cars={len(self.nums)})"
        )

    # ------------------------------------------------------------------ time

    def second_at(self, te: int) -> int | None:
        """The frame second that answers for `te`, or None (see the module docstring)."""
        i = bisect.bisect_right(self.seconds, te) - 1
        if i < 0:
            return None
        sec = self.seconds[i]
        return sec if te - sec <= HOLD_S else None

    def _at(self, table: dict[str, dict[int, Any]], num: str, te: int) -> Any:
        sec = self.second_at(te)
        if sec is None:
            return None
        return table.get(num, {}).get(sec)

    # ------------------------------------------------------------------ per car

    def pct(self, num: str, te: int) -> float | None:
        """Fraction of a lap at `te`, or None."""
        return self._at(self._pct, num, te)

    def pit(self, num: str, te: int) -> bool | None:
        """Whether the car is on pit road at `te`, or None when absent."""
        return self._at(self._pit, num, te)

    def inc(self, num: str, te: int) -> int | None:
        """Incident counter at `te`; None when the feed shows -1 or the car is absent."""
        return self._at(self._inc, num, te)

    def lap(self, num: str, te: int) -> int | None:
        """The car's own lap as the row shows it at `te`; None when -1 or absent."""
        return self._at(self._lap, num, te)

    def lap_at(self, num: str, te: int) -> int | None:
        """The car's own lap at `te`, filled in between shown rows from line crossings."""
        return self._at(self._laps, num, te)

    def cust_id(self, num: str) -> int | None:
        """The car's last `custId`, or None."""
        return self._cust.get(num)

    def leader_lap(self, te: int) -> int | None:
        """The frame's `leaderLap` at `te`, or None."""
        sec = self.second_at(te)
        return None if sec is None else self._leader.get(sec)

    def last_inc(self, num: str) -> int | None:
        """The last shown incident counter, or None when the counter was never shown."""
        shown = self._inc.get(num)
        if not shown:
            return None
        return shown[max(shown)]

    def counter_shown(self, num: str) -> bool:
        """Whether the car's incident counter was shown at least once."""
        return bool(self._inc.get(num))

    # ------------------------------------------------------------------ measures

    def gap_m(self, a: str, b: str, te: int) -> float | None:
        """Signed along-track gap in metres, positive when `a` is ahead of `b`; unrounded."""
        pa, pb = self.pct(a, te), self.pct(b, te)
        if pa is None or pb is None:
            return None
        d = pa - pb
        if d > 0.5:
            d -= 1.0
        elif d < -0.5:
            d += 1.0
        return d * self.track_m

    def speed_mps(self, num: str, te: int) -> float | None:
        """Mean speed in metres a second from the previous frame within 3 s; unrounded."""
        sec = self.second_at(te)
        if sec is None:
            return None
        i = bisect.bisect_left(self.seconds, sec)
        if i == 0:
            return None
        before = self.seconds[i - 1]
        trace = self._pct.get(num, {})
        if sec - before > MAX_STEP_S or sec not in trace or before not in trace:
            return None
        d = trace[sec] - trace[before]
        if d < -0.5:
            d += 1.0
        if d > 0.5:
            return None
        return d * self.track_m / (sec - before)

    def order_at(self, te: int) -> list[str]:
        """Cars in the frame at `te` by laps plus fraction, leader first."""
        sec = self.second_at(te)
        if sec is None:
            return []
        known: list[tuple[float, str]] = []
        unknown: list[tuple[float, str]] = []
        for num, trace in self._pct.items():
            if sec not in trace:
                continue
            lap = self._laps[num].get(sec)
            if lap is None:
                unknown.append((trace[sec], num))
            else:
                known.append((lap + trace[sec], num))
        known.sort(key=lambda pair: (-pair[0], numkey(pair[1])))
        unknown.sort(key=lambda pair: (-pair[0], numkey(pair[1])))
        return [num for _p, num in known] + [num for _p, num in unknown]

    def positions_by_te(self, te_lo: int, te_hi: int) -> dict[int, dict[str, float]]:
        """`{second: {num: laps + fraction}}` over the closed range, for `roster.closed_set`."""
        lo = bisect.bisect_left(self.seconds, te_lo)
        hi = bisect.bisect_right(self.seconds, te_hi)
        out: dict[int, dict[str, float]] = {}
        for sec in self.seconds[lo:hi]:
            frame: dict[str, float] = {}
            for num in self.nums:
                pct = self._pct.get(num, {}).get(sec)
                if pct is None:
                    continue
                lap = self._laps[num].get(sec)
                frame[num] = pct if lap is None else lap + pct
            out[sec] = frame
        return out

    # ------------------------------------------------------------------ names

    def private_names(self) -> dict[str, str]:
        """`{num: name}` re-read from the file. Only the protest normaliser and the lint call it."""
        names: dict[str, str] = {}
        for _te, no, frame in _session_frames(self.path, self.session):
            for where in ("positions", "rows"):
                for item in frame.get(where) or []:
                    num = _num(self.path, no, item, where)
                    name = item.get("name")
                    if isinstance(name, str) and name.strip():
                        names[num] = name
        return {num: names[num] for num in sorted(names, key=numkey)}

    # ------------------------------------------------------------------ internals

    def _fill_laps(self, num: str) -> dict[int, int]:
        """Per second the car is present: its own lap, from rows and line crossings."""
        trace = self._pct[num]
        shown = self._lap.get(num, {})
        out: dict[int, int] = {}
        anchor: int | None = None
        crossings = 0
        prev: float | None = None
        for sec in sorted(trace):
            pct = trace[sec]
            if prev is not None:
                if pct - prev < -0.5:
                    crossings += 1
                elif pct - prev > 0.5:
                    crossings -= 1
            prev = pct
            row = shown.get(sec)
            if row is not None and (anchor is None or _MID_LAP[0] <= pct <= _MID_LAP[1]):
                anchor, crossings = row, 0
            if anchor is not None:
                out[sec] = anchor + crossings
        return out
