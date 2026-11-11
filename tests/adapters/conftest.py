"""Fixtures for the PitBot adapter tests: a synthetic replay feed written at test time.

`tests/fixtures/racing/feed_small.json` is a JSON list of frames (made-up cars "1" to "6",
invented names "Test Driver A" to "Test Driver F", Thruxton, session "RACE", seconds 100 to
160 with 158 missing, plus one "QUALIFY" frame at 90 that a "RACE" load must skip).
A feed file (`.ndjson.gz`) is never committed: `small_feed_path` writes one into `tmp_path`.

What the fixture holds, by second (each car moves 0.01 of a lap, 37.92 m, a second unless stated):

- Car 1 leads; it crosses the line at 105 (leader lap 3 to 4). Its row lap shows -1 at 120.
- Car 3 starts 19.5 m behind car 2 and closes 3 m a second: 10.5 m at 103, 1.5 m at 106
  (a collapse from over 8 m to under 2 m within 3 s). At 107 both counters go 0 to 4 (a +4/+4
  pair within 8 m); car 2 stalls at 6 metres a second from 107 to 112, car 3 passes.
- Car 4: a +2 rise at 130 (0 to 2), a +1 at 140 (2 to 3), on pit road 150 to 155.
- Car 5: its counter is never shown (-1 in every row).
- Car 6 runs a lap down (lap 2 while the leader is on 3 and 4), crosses the line at 130,
  and is missing from the frame at 145.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from faultline.adapters.pitbot.feed import Feed

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "racing"
SMALL_FEED_JSON = FIXTURES / "feed_small.json"
SMALL_SESSION = "RACE"


def write_feed(frames: list[dict], path: Path) -> Path:
    """Write `frames` as gzip NDJSON at `path` (no timestamp in the gzip header)."""
    text = "".join(json.dumps(f, sort_keys=True) + "\n" for f in frames)
    path.write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
    return path


@pytest.fixture
def feed_writer() -> Callable[[list[dict], Path], Path]:
    """`feed_writer(frames, path)` writes frames as a gzip NDJSON feed and returns the path."""
    return write_feed


@pytest.fixture
def small_feed_frames() -> list[dict]:
    """The synthetic frames, freshly read (safe to change in a test)."""
    return json.loads(SMALL_FEED_JSON.read_text(encoding="utf-8"))


@pytest.fixture
def small_feed_path(tmp_path: Path, small_feed_frames: list[dict]) -> Path:
    """The synthetic feed written as `replay-small.ndjson.gz` into `tmp_path`."""
    return write_feed(small_feed_frames, tmp_path / "replay-small.ndjson.gz")


@pytest.fixture
def small_feed(small_feed_path: Path) -> Feed:
    """The synthetic feed loaded for session "RACE"."""
    return Feed.load(small_feed_path, SMALL_SESSION)
