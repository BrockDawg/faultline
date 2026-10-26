"""scripts/build_log.py over real commits in temp repos, and over this repo."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from conftest import REPO_ROOT, GitRunner

SCRIPT = REPO_ROOT / "scripts" / "build_log.py"
FULL = "Built-With: Brock (by hand)\nMeta-Models: none\nBuilt-On: 2026-10-26T12:40:05-0500"
CLAUDE = (
    "Built-With: claude-opus-5-5 via Claude Code\nMeta-Models: llama-a, llama-b\n"
    "Built-On: 2026-10-26T13:05:10-0500"
)


def commit(git: GitRunner, repo: Path, message: str) -> str:
    path = repo / "a.txt"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(old + "x\n", encoding="utf-8")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "--short", "HEAD").stdout.strip()


def run_log(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def rows(output: str) -> list[list[str]]:
    table = [line for line in output.splitlines() if line.startswith("| `")]
    return [[cell.strip() for cell in line.strip("|").split(" | ")] for line in table]


def write_and_commit(git: GitRunner, repo: Path) -> None:
    done = run_log(repo, "--write")
    assert done.returncode == 0, done.stderr
    git(repo, "add", "BUILD_LOG.md")
    git(repo, "commit", "-q", "-m", f"docs: build log\n\n{FULL}")


def test_three_commits_render_three_rows_in_order_with_the_right_cells(repo, git) -> None:
    first = commit(git, repo, "scaffold, before the hook")
    second = commit(git, repo, f"feat: one\n\n{FULL}")
    third = commit(git, repo, f"feat: two\n\n{CLAUDE}")
    done = run_log(repo)
    assert done.returncode == 0, done.stderr
    table = rows(done.stdout)
    assert [r[0] for r in table] == [f"`{first}`", f"`{second}`", f"`{third}`"]
    assert table[0][2:] == ["scaffold, before the hook", "(before the hook)", "(before the hook)"]
    assert table[0][1].startswith("20")
    assert table[1] == [
        f"`{second}`",
        "2026-10-26T12:40:05-0500",
        "feat: one",
        "Brock (by hand)",
        "none",
    ]
    assert table[2][1:] == [
        "2026-10-26T13:05:10-0500",
        "feat: two",
        "claude-opus-5-5 via Claude Code",
        "llama-a, llama-b",
    ]


def test_the_header_line_says_where_the_log_comes_from(repo, git) -> None:
    commit(git, repo, f"feat: one\n\n{FULL}")
    done = run_log(repo)
    assert "Generated from git by `scripts/build_log.py`; covers every commit up to" in done.stdout


def test_a_commit_without_built_on_shows_its_author_date_in_the_same_form(repo, git) -> None:
    commit(git, repo, "scaffold, before the hook")
    when = rows(run_log(repo).stdout)[0][1]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}", when)


def test_a_pipe_in_a_subject_is_escaped(repo, git) -> None:
    commit(git, repo, f"feat: a | b\n\n{FULL}")
    done = run_log(repo)
    assert "| feat: a \\| b |" in done.stdout
    assert len(rows(done.stdout)[0]) == 5


def test_a_non_ascii_subject_survives(repo, git) -> None:
    commit(git, repo, f"feat: café résumé ✓\n\n{FULL}")
    done = run_log(repo)
    assert done.returncode == 0, done.stderr
    assert "feat: café résumé ✓" in done.stdout


def test_a_non_ascii_subject_survives_write(repo, git) -> None:
    commit(git, repo, f"feat: café résumé ✓\n\n{FULL}")
    assert run_log(repo, "--write").returncode == 0
    text = (repo / "BUILD_LOG.md").read_bytes().decode("utf-8")
    assert "feat: café résumé ✓" in text
    assert "\r\n" not in text


def test_cold_start_on_a_repo_with_one_commit(repo, git) -> None:
    only = commit(git, repo, "scaffold, before the hook")
    done = run_log(repo)
    assert done.returncode == 0, done.stderr
    assert [r[0] for r in rows(done.stdout)] == [f"`{only}`"]


def test_no_flag_writes_nothing(repo, git) -> None:
    commit(git, repo, f"feat: one\n\n{FULL}")
    run_log(repo)
    assert not (repo / "BUILD_LOG.md").exists()


def test_check_passes_right_after_a_write_and_commit(repo, git) -> None:
    commit(git, repo, "scaffold, before the hook")
    commit(git, repo, f"feat: one\n\n{FULL}")
    write_and_commit(git, repo)
    done = run_log(repo, "--check")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "covers all 2 commits" in done.stdout
    assert len(done.stdout.strip().splitlines()) == 1


def test_check_still_passes_once_newer_commits_land(repo, git) -> None:
    commit(git, repo, f"feat: one\n\n{FULL}")
    write_and_commit(git, repo)
    commit(git, repo, f"feat: after the log\n\n{FULL}")
    assert run_log(repo, "--check").returncode == 0


def test_check_fails_once_a_missing_commit_is_older_than_the_last_write(repo, git) -> None:
    commit(git, repo, f"feat: one\n\n{FULL}")
    write_and_commit(git, repo)
    skipped = commit(git, repo, f"feat: never logged\n\n{FULL}")
    log = repo / "BUILD_LOG.md"
    log.write_text(log.read_text(encoding="utf-8") + "\nA hand note.\n", encoding="utf-8")
    git(repo, "add", "BUILD_LOG.md")
    git(repo, "commit", "-q", "-m", f"docs: hand edit\n\n{FULL}")
    done = run_log(repo, "--check")
    assert done.returncode == 1
    assert skipped in done.stdout


def test_check_without_a_committed_log_fails_with_a_plain_message(repo, git) -> None:
    commit(git, repo, f"feat: one\n\n{FULL}")
    done = run_log(repo, "--check")
    assert done.returncode == 1
    assert "BUILD_LOG.md is not committed yet" in done.stderr


def test_the_real_repo_renders_without_error(git_env) -> None:
    done = run_log(REPO_ROOT)
    assert done.returncode == 0, done.stderr
    table = rows(done.stdout)
    assert len(table) >= 5
    assert table[0][3] == "(before the hook)"
    assert table[1][3] == "(before the hook)"
