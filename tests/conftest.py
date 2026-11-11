"""Shared test fixtures: real git in temp repos, isolated from this machine's git config.

Every git call made through these fixtures runs with:
- GIT_CONFIG_GLOBAL pointing at an empty temp file, so a global commit.gpgsign,
  commit.template or core.hooksPath never leaks in;
- GIT_CONFIG_NOSYSTEM=1, so the system config (core.autocrlf=true on Windows) never leaks in;
- no inherited GIT_DIR, GIT_WORK_TREE or GIT_INDEX_FILE.

Use the `git` fixture to run git, and `make_repo` (or `repo`) for a fresh repo on `master`
with a local user.name and user.email.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_LEAKY_GIT_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES",
    "GIT_TEMPLATE_DIR",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_DATE",
)

GitRunner = Callable[..., subprocess.CompletedProcess[str]]


@pytest.fixture
def git_env(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate git from this machine's global and system config for the whole test."""
    home = tmp_path_factory.mktemp("git-home")
    empty_global = home / "gitconfig"
    empty_global.write_text("", encoding="utf-8")
    for name in _LEAKY_GIT_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_global))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")


def run_git(
    repo: Path, *args: str, check: bool = True, input: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run git in `repo`, text decoded as UTF-8; raise with git's own output when check fails."""
    done = subprocess.run(
        ["git", *args],
        cwd=repo,
        input=input,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=os.environ.copy(),
    )
    if check and done.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed ({done.returncode}) in {repo}\n"
            f"stdout: {done.stdout}\nstderr: {done.stderr}"
        )
    return done


@pytest.fixture
def git(git_env: None) -> GitRunner:
    """`git(repo, *args, check=True, input=None)` runs real git in the isolated environment."""
    return run_git


@pytest.fixture
def make_repo(git_env: None, tmp_path: Path) -> Callable[[str], Path]:
    """`make_repo(name)` makes `tmp_path/name` a fresh repo on `master` with a local user."""

    def _make(name: str = "repo") -> Path:
        path = tmp_path / name
        path.mkdir(parents=True)
        run_git(path, "init", "-q", "-b", "master")
        run_git(path, "config", "user.name", "Test Builder")
        run_git(path, "config", "user.email", "builder@example.com")
        return path

    return _make


@pytest.fixture
def repo(make_repo: Callable[[str], Path]) -> Path:
    """A fresh repo on `master` with a local user and no commits."""
    return make_repo("repo")
