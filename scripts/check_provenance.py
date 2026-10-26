"""Check that every commit since the hook was installed carries the provenance trailers.

Run from the repo root:  uv run python scripts/check_provenance.py [--since <sha>]

Walks `git log <since>^..HEAD` (every commit reachable from HEAD that is not an ancestor of the
parent of <since>, so merged-in side branches are checked too). Without --since, <since> is
read from the one-line PROVENANCE_START file at the repo root.

Exits 0 when every commit holds a non-blank Built-With, Meta-Models and Built-On trailer.
Exits 1 naming each commit that misses one or holds a blank one.
Exits 2 when the starting commit is not known yet or cannot be found.

Trailers are read through git's own %(trailers) format, never by parsing message bodies.
Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

KEYS = ("Built-With", "Meta-Models", "Built-On")
START_FILE = "PROVENANCE_START"
_SHA = re.compile(r"^[0-9a-fA-F]{4,64}$")
_FIELD = "\x1f"
_RECORD = "\x1e"
_VALUE = "\x1d"


class SetupError(Exception):
    """A plain-words reason the check could not run."""


@dataclass(frozen=True)
class Problem:
    sha: str
    subject: str
    reasons: tuple[str, ...]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8"
    )


def _repo_root(start: Path) -> Path:
    done = _git(start, "rev-parse", "--show-toplevel")
    if done.returncode != 0:
        raise SetupError(f"{start} is not inside a git repository.")
    return Path(done.stdout.strip())


def read_start(root: Path) -> str:
    """The first hooked commit named in PROVENANCE_START, or SetupError in plain words."""
    path = root / START_FILE
    if not path.is_file():
        raise SetupError(f"{path} is missing. Pass --since <sha> instead.")
    value = path.read_text(encoding="utf-8").strip()
    if not _SHA.match(value):
        raise SetupError(
            f"{path} does not hold a commit sha yet (it says '{value}'). Write the first "
            "hooked commit's sha into it, or pass --since <sha>."
        )
    return value


def _range(root: Path, since: str) -> list[str]:
    found = _git(root, "rev-parse", "--verify", "--quiet", f"{since}^{{commit}}")
    if found.returncode != 0:
        raise SetupError(f"commit {since!r} was not found in {root}.")
    has_parent = _git(root, "rev-parse", "--verify", "--quiet", f"{since}^")
    if has_parent.returncode == 0:
        return [f"{since}^..HEAD"]
    return ["HEAD"]


def check(root: Path, since: str) -> tuple[int, list[Problem]]:
    """Return (commits checked, problems) for the range starting at `since`."""
    fields = ["%H", "%s"]
    for key in KEYS:
        fields.append(f"%(trailers:key={key},keyonly,separator=%x1d)")
        fields.append(f"%(trailers:key={key},valueonly,separator=%x1d)")
    fmt = "%x1f".join(fields) + "%x1e"
    done = subprocess.run(
        ["git", "log", f"--format={fmt}", *_range(root, since)],
        cwd=root,
        capture_output=True,
    )
    if done.returncode != 0:
        raise SetupError(f"git log failed: {done.stderr.decode('utf-8', 'replace').strip()}")
    out = done.stdout.decode("utf-8")

    count = 0
    problems: list[Problem] = []
    for record in out.split(_RECORD):
        record = record.strip("\n")
        if not record:
            continue
        count += 1
        parts = record.split(_FIELD)
        sha, subject = parts[0], parts[1]
        reasons: list[str] = []
        for i, key in enumerate(KEYS):
            keys_raw = parts[2 + 2 * i]
            values_raw = parts[3 + 2 * i]
            if not keys_raw.strip():
                reasons.append(f"no {key}")
                continue
            n_keys = len(keys_raw.split(_VALUE))
            values = values_raw.split(_VALUE)
            if len(values) < n_keys or any(not v.strip() for v in values):
                reasons.append(f"blank {key}")
        if reasons:
            problems.append(Problem(sha, subject, tuple(reasons)))
    return count, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", help="the first commit that must carry the trailers")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    try:
        root = _repo_root(Path.cwd())
        since = args.since or read_start(root)
        count, problems = check(root, since)
    except SetupError as err:
        print(f"check_provenance: {err}", file=sys.stderr)
        return 2
    if problems:
        print(f"check_provenance: {len(problems)} of {count} commits lack provenance trailers:")
        for p in problems:
            print(f"  {p.sha[:7]} {p.subject}: {', '.join(p.reasons)}")
        return 1
    print(f"check_provenance: all {count} commits from {since[:7]} carry {', '.join(KEYS)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
