"""scripts/tally.py: the running count in README.md matches tally.json and this repo."""

from __future__ import annotations

import json
import subprocess
import sys

from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "tally.py"
README = REPO_ROOT / "README.md"
TALLY = REPO_ROOT / "tally.json"
sys.path.insert(0, str(SCRIPT.parent))
import tally  # noqa: E402

COUNT_KEYS = {
    "build_plans",
    "paid_calls",
    "paid_dollars",
    "private_design_notes",
    "private_experiment_files",
    "private_experiment_records",
    "private_experiment_scripts",
}
ROWS = [
    "Commits in this repo",
    "Experiment logs published here",
    "Experiment records in the working repo",
    "Experiment scripts in the working repo",
    "Experiment data files in the working repo",
    "Design notes published here",
    "Design notes in the working repo",
    "Build plans in the working repo",
    "Rules packs",
    "Rules",
    "Tests",
    "Paid model calls",
    "Dollars metered",
]


def test_tally_json_parses_with_the_expected_keys() -> None:
    data = json.loads(TALLY.read_text(encoding="utf-8"))
    assert set(data) == COUNT_KEYS | {"as_of", "kickoff"}
    for key in COUNT_KEYS - {"paid_dollars"}:
        assert isinstance(data[key], int) and data[key] >= 0, key
    assert isinstance(data["paid_dollars"], int | float) and data["paid_dollars"] >= 0
    assert data["kickoff"] == "2026-10-26T16:00:00+00:00"
    assert data["as_of"] >= data["kickoff"]


def test_the_readme_block_is_current(git_env) -> None:
    current = tally.block_of(README.read_text(encoding="utf-8"))
    assert current is not None, "README.md has lost its tally markers"
    assert current == tally.fresh_block(REPO_ROOT, current), (
        "The running count in README.md is stale. "
        "Run `uv run python scripts/tally.py --write` and commit it."
    )


def test_the_block_has_its_heading_rows_in_order_and_its_two_lines() -> None:
    block = tally.block_of(README.read_text(encoding="utf-8"))
    assert block is not None
    lines = block.splitlines()
    assert lines[0] == "#### The running count"
    rows = [line.strip("|").split(" | ")[0].strip() for line in lines if line.startswith("| ")]
    assert rows == ["What", *ROWS]
    assert lines[-2].startswith("Counted by `scripts/tally.py` from this repo")
    assert lines[-1].endswith("PROVENANCE.md says what the working tooling is.")


def test_the_block_sits_at_the_end_of_built_during_the_hackathon() -> None:
    text = README.read_text(encoding="utf-8")
    built = text.index("### Built during the hackathon")
    end = text.index(tally.MARK_END)
    assert built < text.index(tally.MARK_START) < end < text.index("### Existed before")


def test_render_formats_dollars_and_the_run_time() -> None:
    data = {k: 1 for k in COUNT_KEYS}
    data.update(paid_dollars=1234.5, as_of="2026-10-27T19:30:16+00:00")
    public = dict.fromkeys(
        ("public_commits", "public_experiment_logs", "public_design_notes", "rules_packs"), 2
    ) | {"rules": 3, "tests": 4}
    block = tally.render_block(data, public)
    assert "| Dollars metered | $1,234.50 |" in block
    assert "last run Tuesday 27 Oct 2026, 19:30 UTC." in block


def test_check_passes_on_this_repo(git_env) -> None:
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr


def _readme(block: str, tail: str = "") -> str:
    return f"# r\n\n{tally.MARK_START}\n{block}{tally.MARK_END}\n{tail}"


def _commit_file(git, repo, name: str, text: str, message: str) -> str:
    (repo / name).write_text(text, encoding="utf-8", newline="\n")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def test_the_commit_count_lags_by_the_commit_that_wrote_the_block(repo, git) -> None:
    _commit_file(git, repo, "README.md", _readme(""), "scaffold")
    _commit_file(git, repo, "a.txt", "a", "first work")
    (repo / "README.md").write_text(_readme("X\n"), encoding="utf-8", newline="\n")
    assert tally.count_ref(repo, "X\n") == "HEAD"
    assert tally.public_commits(repo, "HEAD") == 2
    writer = _commit_file(git, repo, "README.md", _readme("X\n"), "the block")
    assert tally.count_ref(repo, "X\n") == f"{writer}^"
    _commit_file(git, repo, "README.md", _readme("X\n", "more prose\n"), "prose only")
    _commit_file(git, repo, "other.txt", "x", "later work")
    ref = tally.count_ref(repo, "X\n")
    assert ref == f"{writer}^"
    assert tally.public_commits(repo, ref) == 2
