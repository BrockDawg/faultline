"""Render BUILD_LOG.md, the dated build log, from git's own history.

Run from the repo root:  uv run python scripts/build_log.py [--write | --check]

No flag prints the log to stdout. --write writes BUILD_LOG.md at the repo root.
--check exits 1 if the committed BUILD_LOG.md (as of HEAD) is missing any commit older than
the last commit that changed it, and 0 with one line when nothing is missing.

Each row is one commit, oldest first: short sha, date-time, subject, Built-With, Meta-Models.
The date-time is the Built-On trailer, else the author date in the same
YYYY-MM-DDTHH:MM:SS+HHMM form. A commit with no trailers shows "(before the hook)".

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

LOG_FILE = "BUILD_LOG.md"
BEFORE_HOOK = "(before the hook)"
MISSING = "(missing)"
_FIELD = "\x1f"
_RECORD = "\x1e"
_FORMAT = (
    "%H%x1f%h%x1f%aI%x1f%s"
    "%x1f%(trailers:key=Built-On,valueonly)"
    "%x1f%(trailers:key=Built-With,valueonly,separator=%x2C )"
    "%x1f%(trailers:key=Meta-Models,valueonly,separator=%x2C )"
    "%x1e"
)
HEADER = (
    "Generated from git by `scripts/build_log.py`; covers every commit up to the one before "
    "the commit that wrote this file."
)
_ISO = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:Z|([+-])(\d{2}):?(\d{2}))$")
_ROW_SHA = re.compile(r"^\|\s*`?([0-9a-fA-F]{4,64})`?\s*\|")


class BuildLogError(Exception):
    """A plain-words reason the build log could not be made or checked."""


@dataclass(frozen=True)
class Entry:
    sha: str
    short: str
    when: str
    subject: str
    built_with: str
    meta_models: str


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True)


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", "replace")


def repo_root(start: Path) -> Path:
    done = _git(start, "rev-parse", "--show-toplevel")
    if done.returncode != 0:
        raise BuildLogError(f"{start} is not inside a git repository.")
    return Path(_text(done.stdout).strip())


def normalise_date(value: str) -> str:
    """`2026-10-26T12:45:04-05:00` (git's %aI) becomes `2026-10-26T12:45:04-0500`."""
    found = _ISO.match(value.strip())
    if not found:
        return value.strip()
    stamp, sign, hours, minutes = found.groups()
    if sign is None:
        return f"{stamp}+0000"
    return f"{stamp}{sign}{hours}{minutes}"


def _one_line(value: str) -> str:
    return ", ".join(part.strip() for part in value.splitlines() if part.strip())


def read_entries(root: Path) -> list[Entry]:
    """Every commit reachable from HEAD, oldest first. An empty repo gives an empty list."""
    if _git(root, "rev-parse", "--verify", "--quiet", "HEAD").returncode != 0:
        return []
    done = _git(root, "log", "--reverse", f"--format={_FORMAT}")
    if done.returncode != 0:
        raise BuildLogError(f"git log failed: {_text(done.stderr).strip()}")
    out = done.stdout.decode("utf-8")
    entries: list[Entry] = []
    for record in out.split(_RECORD):
        record = record.strip("\n")
        if not record:
            continue
        sha, short, author_date, subject, built_on, built_with, meta = record.split(_FIELD)
        built_on = _one_line(built_on)
        built_with = _one_line(built_with)
        meta = _one_line(meta)
        if not (built_on or built_with or meta):
            built_with = meta = BEFORE_HOOK
        entries.append(
            Entry(
                sha=sha,
                short=short,
                when=normalise_date(built_on) if built_on else normalise_date(author_date),
                subject=subject,
                built_with=built_with or MISSING,
                meta_models=meta or MISSING,
            )
        )
    return entries


def _cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|")


def render(entries: list[Entry]) -> str:
    lines = [
        "# Build log",
        "",
        HEADER,
        "",
        "| Commit | Date-time | Subject | Built-With | Meta-Models |",
        "| --- | --- | --- | --- | --- |",
    ]
    for e in entries:
        cells = (
            f"`{e.short}`",
            e.when,
            _cell(e.subject),
            _cell(e.built_with),
            _cell(e.meta_models),
        )
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def logged_shas(text: str) -> list[str]:
    """The short shas named in the first column of a rendered log."""
    shas = []
    for line in text.splitlines():
        found = _ROW_SHA.match(line.strip())
        if found:
            shas.append(found.group(1).lower())
    return shas


def check(root: Path) -> tuple[int, str, list[str]]:
    """Return (commits required, last log commit, required commits missing from the log)."""
    shown = _git(root, "show", f"HEAD:{LOG_FILE}")
    if shown.returncode != 0:
        raise BuildLogError(
            f"{LOG_FILE} is not committed yet. Run `uv run python scripts/build_log.py --write` "
            "and commit it."
        )
    rows = logged_shas(shown.stdout.decode("utf-8"))
    last = _text(_git(root, "log", "-1", "--format=%H", "--", LOG_FILE).stdout).strip()
    if _git(root, "rev-parse", "--verify", "--quiet", f"{last}^").returncode != 0:
        return 0, last, []
    listed = _git(root, "rev-list", f"{last}^")
    if listed.returncode != 0:
        raise BuildLogError(f"git rev-list failed: {_text(listed.stderr).strip()}")
    required = [line for line in _text(listed.stdout).split() if line]
    missing = [sha for sha in required if not any(sha.startswith(row) for row in rows)]
    return len(required), last, missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help=f"write {LOG_FILE}")
    mode.add_argument("--check", action="store_true", help=f"check the committed {LOG_FILE}")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    try:
        root = repo_root(Path.cwd())
        if args.check:
            count, last, missing = check(root)
        else:
            text = render(read_entries(root))
    except BuildLogError as err:
        print(f"build_log: {err}", file=sys.stderr)
        return 1
    if args.check:
        if missing:
            print(
                f"build_log: {LOG_FILE} (last written in {last[:7]}) is missing "
                f"{len(missing)} older commit(s): {', '.join(sha[:7] for sha in missing)}. "
                "Run --write and commit it."
            )
            return 1
        print(f"build_log: {LOG_FILE} covers all {count} commits before {last[:7]}.")
        return 0
    if args.write:
        (root / LOG_FILE).write_text(text, encoding="utf-8", newline="\n")
        print(f"build_log: wrote {LOG_FILE}.")
        return 0
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
