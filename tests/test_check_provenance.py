"""scripts/check_provenance.py over real commits in temp repos."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from conftest import REPO_ROOT, GitRunner

SCRIPT = REPO_ROOT / "scripts" / "check_provenance.py"
HOOK_SOURCE = REPO_ROOT / ".githooks" / "commit-msg"
FULL = "Built-With: Brock (by hand)\nMeta-Models: none\nBuilt-On: 2026-10-26T12:40:05-0500"


def commit(git: GitRunner, repo: Path, message: str, *extra: str) -> str:
    path = repo / "a.txt"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(old + "x\n", encoding="utf-8")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", *extra, "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def run_check(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def hooked(git: GitRunner, repo: Path) -> None:
    shutil.copyfile(HOOK_SOURCE, repo / ".git" / "hooks" / "commit-msg")
    git(repo, "config", "faultline.builtWith", "claude-opus-5-5 via Claude Code")
    git(repo, "config", "faultline.metaModels", "none")


def test_a_clean_range_passes(repo, git) -> None:
    commit(git, repo, "scaffold, before the hook")
    hooked(git, repo)
    first = commit(git, repo, "feat: one")
    commit(git, repo, f"feat: two\n\n{FULL}")
    done = run_check(repo, "--since", first)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "all 2 commits" in done.stdout


def test_commits_before_the_start_are_not_checked(repo, git) -> None:
    commit(git, repo, "scaffold, before the hook")
    commit(git, repo, "boundary, before the hook")
    first = commit(git, repo, f"feat: one\n\n{FULL}")
    assert run_check(repo, "--since", first).returncode == 0


def test_a_no_verify_commit_without_trailers_fails_and_is_named(repo, git) -> None:
    hooked(git, repo)
    first = commit(git, repo, "feat: one")
    bad = commit(git, repo, "feat: skipped the hook", "--no-verify")
    commit(git, repo, "feat: three")
    done = run_check(repo, "--since", first)
    assert done.returncode == 1
    assert f"{bad[:7]} feat: skipped the hook" in done.stdout
    assert "no Built-With" in done.stdout
    assert "no Meta-Models" in done.stdout
    assert "no Built-On" in done.stdout
    assert "1 of 3" in done.stdout


def test_a_blank_value_fails(repo, git) -> None:
    first = commit(git, repo, f"feat: one\n\n{FULL}")
    message = (
        "feat: blank\n\nBuilt-With: Brock (by hand)\nMeta-Models:\n"
        "Built-On: 2026-10-26T13:00:00-0500"
    )
    bad = commit(git, repo, message)
    done = run_check(repo, "--since", first)
    assert done.returncode == 1
    assert f"{bad[:7]} feat: blank: blank Meta-Models" in done.stdout


def test_a_root_commit_as_the_start_is_checked(repo, git) -> None:
    first = commit(git, repo, f"feat: root\n\n{FULL}")
    commit(git, repo, f"feat: next\n\n{FULL}")
    done = run_check(repo, "--since", first)
    assert done.returncode == 0, done.stderr
    assert "all 2 commits" in done.stdout


def test_a_side_branch_merged_in_is_checked_too(repo, git) -> None:
    first = commit(git, repo, f"feat: one\n\n{FULL}")
    git(repo, "switch", "-q", "-c", "side")
    bad = commit(git, repo, "feat: on side, no trailers")
    git(repo, "switch", "-q", "master")
    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    git(repo, "add", "b.txt")
    git(repo, "commit", "-q", "-m", f"feat: on master\n\n{FULL}")
    git(repo, "merge", "-q", "--no-ff", "-m", f"merge side\n\n{FULL}", "side")
    done = run_check(repo, "--since", first)
    assert done.returncode == 1
    assert bad[:7] in done.stdout


def test_a_non_ascii_subject_is_named_intact(repo, git) -> None:
    first = commit(git, repo, f"feat: one\n\n{FULL}")
    commit(git, repo, "feat: café résumé", "--no-verify")
    done = run_check(repo, "--since", first)
    assert done.returncode == 1
    assert "feat: café résumé" in done.stdout


def test_the_start_is_read_from_provenance_start(repo, git) -> None:
    commit(git, repo, "scaffold, before the hook")
    first = commit(git, repo, f"feat: one\n\n{FULL}")
    (repo / "PROVENANCE_START").write_text(first + "\n", encoding="utf-8")
    done = run_check(repo)
    assert done.returncode == 0, done.stderr
    assert "all 1 commits" in done.stdout


def test_a_placeholder_start_file_stops_with_a_plain_message(repo, git) -> None:
    commit(git, repo, f"feat: one\n\n{FULL}")
    placeholder = "REPLACE-WITH-THE-FIRST-HOOKED-COMMIT-SHA\n"
    (repo / "PROVENANCE_START").write_text(placeholder, encoding="utf-8")
    done = run_check(repo)
    assert done.returncode == 2
    assert "does not hold a commit sha yet" in done.stderr
    assert "--since" in done.stderr


def test_an_unknown_start_commit_stops_with_a_plain_message(repo, git) -> None:
    commit(git, repo, f"feat: one\n\n{FULL}")
    done = run_check(repo, "--since", "0123456789abcdef0123456789abcdef01234567")
    assert done.returncode == 2
    assert "was not found" in done.stderr
