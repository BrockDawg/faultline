"""Render the running count of the hackathon work into README.md, from tally.json and this repo.

Run from the repo root:  uv run python scripts/tally.py [--write | --check]

No flag prints the block. --write writes it into README.md between the tally markers.
--check exits 1 when the block in README.md differs from a fresh render, and 0 when it matches.

The working-repo counts come from tally.json, which the working repo's own counter writes.
The public counts are read live from this repo: every commit up to the one before the commit
that wrote the block (the build log's rule, so later commits never make it stale), the
experiment logs, the design notes, the rules packs and their rules, and the tests.
While the block in the working tree differs from the committed one, the count runs to HEAD,
because the commit that will carry the block has HEAD as its parent.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

README = "README.md"
TALLY = "tally.json"
MARK_START = "<!-- tally:start -->"
MARK_END = "<!-- tally:end -->"
PRIVATE_KEYS = (
    "as_of",
    "build_plans",
    "kickoff",
    "paid_calls",
    "paid_dollars",
    "private_design_notes",
    "private_experiment_files",
    "private_experiment_records",
    "private_experiment_scripts",
)
_TEST_DEF = re.compile(r"^\s*(?:async\s+)?def test_", re.MULTILINE)
_BLOCK = re.compile(re.escape(MARK_START) + r"\n(.*?)" + re.escape(MARK_END), re.DOTALL)


class TallyError(Exception):
    """A plain-words reason the count could not be rendered or checked."""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)


def _out(root: Path, *args: str) -> str:
    done = _git(root, *args)
    if done.returncode != 0:
        err = done.stderr.decode("utf-8", "replace").strip()
        raise TallyError(f"git {' '.join(args)} failed: {err}")
    return done.stdout.decode("utf-8")


def repo_root(start: Path) -> Path:
    done = _git(start, "rev-parse", "--show-toplevel")
    if done.returncode != 0:
        raise TallyError(f"{start} is not inside a git repository.")
    return Path(done.stdout.decode("utf-8").strip())


def block_of(text: str) -> str | None:
    """The text between the tally markers, or None when the markers are missing."""
    found = _BLOCK.search(text)
    return found.group(1) if found else None


def _committed_block(root: Path, rev: str) -> str | None:
    shown = _git(root, "show", f"{rev}:{README}")
    if shown.returncode != 0:
        return None
    return block_of(shown.stdout.decode("utf-8"))


def count_ref(root: Path, working_block: str | None) -> str:
    """The last commit the count covers: HEAD while the block is uncommitted, else the parent
    of the newest commit that changed the block."""
    if working_block != _committed_block(root, "HEAD"):
        return "HEAD"
    shas = _out(root, "log", "--format=%H", "--", README).split()
    for sha in shas:
        parent_has = _git(root, "rev-parse", "--verify", "--quiet", f"{sha}^").returncode == 0
        before = _committed_block(root, f"{sha}^") if parent_has else None
        if _committed_block(root, sha) != before:
            if not parent_has:
                raise TallyError(f"the block was written in the root commit {sha[:7]}.")
            return f"{sha}^"
    return "HEAD"


def public_commits(root: Path, ref: str) -> int:
    """Every commit reachable from `ref`, the two before the hook included, as the build log
    lists them."""
    return int(_out(root, "rev-list", "--count", ref).strip())


def public_counts(root: Path, ref: str) -> dict[str, int]:
    from faultline.pack import load_packs

    packs = load_packs(root / "packs")
    experiments = root / "experiments"
    tests = sorted((root / "tests").rglob("*.py"))
    return {
        "public_commits": public_commits(root, ref),
        "public_experiment_logs": sum(
            1 for d in experiments.iterdir() if d.is_dir() and (d / "LOG.md").is_file()
        ),
        "public_design_notes": sum(1 for _ in (root / "docs").rglob("*.md")),
        "rules_packs": len(packs),
        "rules": sum(len(p.rules) for p in packs),
        "tests": sum(len(_TEST_DEF.findall(p.read_text(encoding="utf-8"))) for p in tests),
    }


def load_tally(root: Path) -> dict[str, Any]:
    path = root / TALLY
    if not path.is_file():
        raise TallyError(f"{TALLY} is missing; the private tooling writes it.")
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in PRIVATE_KEYS if k not in data]
    if missing:
        raise TallyError(f"{TALLY} has no {', '.join(missing)}.")
    return data


def _when(value: str) -> str:
    stamp = datetime.fromisoformat(value)
    return f"{stamp:%A} {stamp.day} {stamp:%b %Y}, {stamp:%H:%M} UTC"


def render_block(tally: dict[str, Any], public: dict[str, int]) -> str:
    rows = (
        ("Commits in this repo", public["public_commits"]),
        ("Experiment logs published here", public["public_experiment_logs"]),
        ("Experiment records in the working repo", tally["private_experiment_records"]),
        ("Experiment scripts in the working repo", tally["private_experiment_scripts"]),
        ("Experiment data files in the working repo", tally["private_experiment_files"]),
        ("Design notes published here", public["public_design_notes"]),
        ("Design notes in the working repo", tally["private_design_notes"]),
        ("Build plans in the working repo", tally["build_plans"]),
        ("Rules packs", public["rules_packs"]),
        ("Rules", public["rules"]),
        ("Tests", public["tests"]),
        ("Paid calls to Meta models", tally["paid_calls"]),
        ("Dollars metered on Meta models", f"${float(tally['paid_dollars']):,.2f}"),
    )
    lines = ["#### The running count", "", "| What | Count |", "|---|--:|"]
    lines += [f"| {what} | {count} |" for what, count in rows]
    lines += [
        "",
        "Counted by `scripts/tally.py` from this repo and from the working repo's own count, "
        f"last run {_when(str(tally['as_of']))}; "
        "every item is dated at or after the kickoff on 26 Oct 2026.",
        "The meter covers the Meta Model API and Baseten; "
        "Modal GPU time is billed by the hour and the coding tools run on a subscription, "
        "so neither is in it.",
        "The working repo holds the scripts, data and notes behind every experiment, "
        "and this repo keeps the logs, the packs and the loader, so it stays small and readable; "
        "PROVENANCE.md says what the working tooling is.",
    ]
    return "\n".join(lines) + "\n"


def fresh_block(root: Path, working_block: str | None) -> str:
    return render_block(load_tally(root), public_counts(root, count_ref(root, working_block)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help=f"write the block into {README}")
    mode.add_argument("--check", action="store_true", help=f"check the block in {README}")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    try:
        root = repo_root(Path.cwd())
        readme = (root / README).read_text(encoding="utf-8")
        current = block_of(readme)
        if current is None and (args.write or args.check):
            raise TallyError(f"{README} has no {MARK_START} ... {MARK_END} markers.")
        if args.write:
            block = render_block(load_tally(root), public_counts(root, "HEAD"))
        else:
            block = fresh_block(root, current)
    except (TallyError, OSError, ValueError) as err:
        print(f"tally: {err}", file=sys.stderr)
        return 1
    if args.check:
        if current != block:
            print(f"tally: the running count in {README} is stale. Run --write and commit it.")
            return 1
        print(f"tally: the running count in {README} matches {TALLY} and this repo.")
        return 0
    if args.write:
        updated = _BLOCK.sub(lambda _: f"{MARK_START}\n{block}{MARK_END}", readme, count=1)
        (root / README).write_text(updated, encoding="utf-8", newline="\n")
        print(f"tally: wrote the running count into {README}.")
        return 0
    sys.stdout.write(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
