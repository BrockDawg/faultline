"""The provenance commit-msg hook and its installer, driven through real git in temp repos."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from conftest import REPO_ROOT, GitRunner

HOOK_SOURCE = REPO_ROOT / ".githooks" / "commit-msg"
INSTALLER = REPO_ROOT / "scripts" / "install_hooks.py"
BUILT_ON = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}$")
DEFAULT_BUILT_WITH = "claude-opus-5-5 via Claude Code"


# --- helpers -------------------------------------------------------------------------------


def copy_hook(repo: Path) -> None:
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HOOK_SOURCE, hooks / "commit-msg")


def set_defaults(git: GitRunner, repo: Path) -> None:
    git(repo, "config", "faultline.builtWith", DEFAULT_BUILT_WITH)
    git(repo, "config", "faultline.metaModels", "none")


def commit(
    git: GitRunner, repo: Path, message: str, name: str = "a.txt", *extra: str
) -> subprocess.CompletedProcess[str]:
    path = repo / name
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(old + "x\n", encoding="utf-8")
    git(repo, "add", name)
    return git(repo, "commit", "-q", *extra, "-m", message, check=False)


def body(git: GitRunner, repo: Path, rev: str = "HEAD") -> str:
    return git(repo, "log", "-1", "--format=%B", rev).stdout.rstrip("\n")


def trailers(git: GitRunner, repo: Path, rev: str = "HEAD") -> list[tuple[str, str]]:
    out = git(repo, "log", "-1", "--format=%(trailers:only,unfold)", rev).stdout
    pairs = []
    for line in out.splitlines():
        if line.strip():
            key, _, value = line.partition(":")
            pairs.append((key.strip(), value.strip()))
    return pairs


def assert_stamped(git: GitRunner, repo: Path, rev: str = "HEAD") -> None:
    pairs = trailers(git, repo, rev)
    keys = [k for k, _ in pairs]
    assert keys[-3:] == ["Built-With", "Meta-Models", "Built-On"], pairs
    assert dict(pairs)["Built-With"] == DEFAULT_BUILT_WITH
    assert dict(pairs)["Meta-Models"] == "none"
    assert BUILT_ON.match(dict(pairs)["Built-On"])


def hooked_repo(make_repo: Callable[[str], Path], git: GitRunner, name: str = "repo") -> Path:
    repo = make_repo(name)
    copy_hook(repo)
    set_defaults(git, repo)
    return repo


def diverged(git: GitRunner, repo: Path) -> None:
    """master and side each gain one commit past a shared base."""
    assert commit(git, repo, "base").returncode == 0
    git(repo, "branch", "side")
    assert commit(git, repo, "on master", "m.txt").returncode == 0
    git(repo, "switch", "-q", "side")
    assert commit(git, repo, "on side", "s.txt").returncode == 0
    git(repo, "switch", "-q", "master")


# --- the hook file itself --------------------------------------------------------------------


def test_hook_file_is_lf_only_and_carries_the_marker() -> None:
    data = HOOK_SOURCE.read_bytes()
    assert b"\r" not in data
    assert data.startswith(b"#!/bin/sh\n")
    assert b"# faultline provenance hook\n" in data


# --- commits ---------------------------------------------------------------------------------


def test_message_with_all_three_trailers_is_committed_unchanged(make_repo, git) -> None:
    repo = make_repo("repo")
    copy_hook(repo)
    message = (
        "feat: add a thing\n\nBuilt-With: Brock (by hand)\nMeta-Models: llama-4\n"
        "Built-On: 2026-10-26T12:40:05-0500"
    )
    assert commit(git, repo, message).returncode == 0
    assert body(git, repo) == message


def test_message_without_trailers_is_stamped_from_config_in_order(make_repo, git) -> None:
    repo = hooked_repo(make_repo, git)
    assert commit(git, repo, "feat: a plain message").returncode == 0
    lines = body(git, repo).splitlines()
    assert lines[0] == "feat: a plain message"
    assert lines[-3] == f"Built-With: {DEFAULT_BUILT_WITH}"
    assert lines[-2] == "Meta-Models: none"
    assert lines[-1].startswith("Built-On: ")


def test_message_without_trailers_and_no_config_is_refused_naming_built_with(
    make_repo, git
) -> None:
    repo = make_repo("repo")
    copy_hook(repo)
    done = commit(git, repo, "feat: no trailers")
    assert done.returncode != 0
    assert '"Built-With:"' in done.stderr
    assert "git config faultline.builtWith" in done.stderr
    assert git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0


def test_missing_meta_models_with_no_config_is_refused_naming_meta_models(make_repo, git) -> None:
    repo = make_repo("repo")
    copy_hook(repo)
    done = commit(git, repo, "feat: x\n\nBuilt-With: Brock (by hand)")
    assert done.returncode != 0
    assert '"Meta-Models:"' in done.stderr


def test_built_on_value_is_local_date_time_with_offset(make_repo, git) -> None:
    repo = hooked_repo(make_repo, git)
    assert commit(git, repo, "feat: stamp me").returncode == 0
    assert BUILT_ON.match(dict(trailers(git, repo))["Built-On"])


def test_explicit_hand_written_built_with_is_kept_over_config(make_repo, git) -> None:
    repo = hooked_repo(make_repo, git)
    assert commit(git, repo, "docs: by hand\n\nBuilt-With: Brock (by hand)").returncode == 0
    pairs = trailers(git, repo)
    assert [v for k, v in pairs if k == "Built-With"] == ["Brock (by hand)"]
    assert [k for k, _ in pairs] == ["Built-With", "Meta-Models", "Built-On"]


def test_blank_built_with_is_refused_as_empty(make_repo, git) -> None:
    repo = hooked_repo(make_repo, git)
    done = commit(git, repo, "feat: x\n\nBuilt-With:\nMeta-Models: none")
    assert done.returncode != 0
    assert 'the "Built-With:" trailer is empty' in done.stderr


def test_lowercase_built_with_counts_as_present_and_is_not_duplicated(make_repo, git) -> None:
    repo = hooked_repo(make_repo, git)
    assert commit(git, repo, "feat: x\n\nbuilt-with: x").returncode == 0
    pairs = trailers(git, repo)
    assert [(k, v) for k, v in pairs if k.lower() == "built-with"] == [("built-with", "x")]


def test_other_trailers_are_left_as_they_are(make_repo, git) -> None:
    repo = hooked_repo(make_repo, git)
    co = "Co-Authored-By: Claude <noreply@anthropic.com>"
    assert commit(git, repo, f"feat: x\n\n{co}").returncode == 0
    lines = body(git, repo).splitlines()
    assert lines[2] == co
    assert_stamped(git, repo)


def test_plain_message_commit_is_stamped(make_repo, git) -> None:
    repo = hooked_repo(make_repo, git)
    done = commit(git, repo, "chore: keep local notes out of the repo", ".gitignore")
    assert done.returncode == 0, done.stderr
    assert body(git, repo).splitlines()[0] == "chore: keep local notes out of the repo"
    assert_stamped(git, repo)


# --- merges ----------------------------------------------------------------------------------


def test_merge_commit_with_message_is_stamped_not_refused(make_repo, git) -> None:
    repo = hooked_repo(make_repo, git)
    diverged(git, repo)
    done = git(repo, "merge", "--no-ff", "-m", "merge: x", "side", check=False)
    assert done.returncode == 0, done.stderr
    assert body(git, repo).splitlines()[0] == "merge: x"
    assert len(git(repo, "log", "-1", "--format=%P").stdout.split()) == 2
    assert_stamped(git, repo)


def test_merge_commit_with_no_edit_is_stamped_not_refused(make_repo, git) -> None:
    repo = hooked_repo(make_repo, git)
    diverged(git, repo)
    done = git(repo, "merge", "--no-edit", "side", check=False)
    assert done.returncode == 0, done.stderr
    assert len(git(repo, "log", "-1", "--format=%P").stdout.split()) == 2
    assert_stamped(git, repo)


def test_merge_from_detached_worktree_inside_git_folder_is_stamped(make_repo, git) -> None:
    repo = hooked_repo(make_repo, git)
    diverged(git, repo)
    scratch = repo / ".git" / "fold-test" / "wt"
    git(repo, "worktree", "add", "-q", "--detach", str(scratch), "side")
    done = git(scratch, "merge", "--no-edit", "-m", "merge local master with side", "master")
    assert done.returncode == 0, done.stderr
    assert body(git, scratch).splitlines()[0] == "merge local master with side"
    assert_stamped(git, scratch)
    git(repo, "worktree", "remove", "--force", str(scratch))


# --- the installer ---------------------------------------------------------------------------


def clone_tooling(repo: Path) -> None:
    (repo / ".githooks").mkdir()
    (repo / "scripts").mkdir()
    shutil.copyfile(HOOK_SOURCE, repo / ".githooks" / "commit-msg")
    shutil.copyfile(INSTALLER, repo / "scripts" / "install_hooks.py")


def run_installer(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/install_hooks.py"],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def snapshot(git: GitRunner, repo: Path) -> tuple[bytes | None, str]:
    hook = repo / ".git" / "hooks" / "commit-msg"
    data = hook.read_bytes() if hook.exists() else None
    config = git(repo, "config", "--local", "--list").stdout
    return data, config


def test_installer_cold_start_installs_hook_and_sets_both_defaults(make_repo, git) -> None:
    repo = make_repo("repo")
    clone_tooling(repo)
    done = run_installer(repo)
    assert done.returncode == 0, done.stderr
    assert (repo / ".git" / "hooks" / "commit-msg").read_bytes() == HOOK_SOURCE.read_bytes()
    assert git(repo, "config", "--get", "faultline.builtWith").stdout.strip() == DEFAULT_BUILT_WITH
    assert git(repo, "config", "--get", "faultline.metaModels").stdout.strip() == "none"
    assert git(repo, "config", "--get", "core.hooksPath", check=False).returncode != 0
    assert commit(git, repo, "feat: first").returncode == 0
    assert_stamped(git, repo)


def test_installer_second_run_changes_nothing(make_repo, git) -> None:
    repo = make_repo("repo")
    clone_tooling(repo)
    assert run_installer(repo).returncode == 0
    before = snapshot(git, repo)
    again = run_installer(repo)
    assert again.returncode == 0, again.stderr
    assert snapshot(git, repo) == before
    assert "already installed" in again.stdout


def test_installer_refuses_a_different_hook_without_the_marker(make_repo, git) -> None:
    repo = make_repo("repo")
    clone_tooling(repo)
    hook = repo / ".git" / "hooks" / "commit-msg"
    hook.parent.mkdir(parents=True, exist_ok=True)
    foreign = b"#!/bin/sh\r\n# someone else's hook\r\nexit 0\r\n"
    hook.write_bytes(foreign)
    done = run_installer(repo)
    assert done.returncode == 1
    assert "different commit-msg hook" in done.stderr
    assert hook.read_bytes() == foreign
    assert git(repo, "config", "--get", "faultline.builtWith", check=False).returncode != 0


def test_installer_keeps_an_existing_built_with_value(make_repo, git) -> None:
    repo = make_repo("repo")
    clone_tooling(repo)
    git(repo, "config", "faultline.builtWith", "Brock (by hand)")
    assert run_installer(repo).returncode == 0
    assert run_installer(repo).returncode == 0
    assert git(repo, "config", "--get", "faultline.builtWith").stdout.strip() == "Brock (by hand)"
    assert git(repo, "config", "--get", "faultline.metaModels").stdout.strip() == "none"


def test_installer_refuses_when_core_hooks_path_is_set_and_writes_nothing(make_repo, git) -> None:
    repo = make_repo("repo")
    clone_tooling(repo)
    elsewhere = repo.parent / "global-hooks"
    git(repo, "config", "--global", "core.hooksPath", str(elsewhere))
    before = snapshot(git, repo)
    done = run_installer(repo)
    assert done.returncode == 1
    assert "core.hooksPath" in done.stderr
    assert str(elsewhere) in done.stderr
    assert snapshot(git, repo) == before
    assert not elsewhere.exists()


def test_installer_hook_stamps_a_commit_inside_a_linked_worktree(make_repo, git) -> None:
    repo = make_repo("repo")
    clone_tooling(repo)
    assert run_installer(repo).returncode == 0
    assert commit(git, repo, "feat: base").returncode == 0
    linked = repo.parent / "repo--task"
    git(repo, "worktree", "add", "-q", "-b", "task", str(linked))
    assert not (linked / ".git").is_dir()
    assert (repo / ".git" / "hooks" / "commit-msg").is_file()
    done = commit(git, linked, "feat: in the worktree", "w.txt")
    assert done.returncode == 0, done.stderr
    assert_stamped(git, linked)


def test_installer_run_from_a_linked_worktree_installs_into_the_common_hooks(
    make_repo, git
) -> None:
    repo = make_repo("repo")
    clone_tooling(repo)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "--no-verify", "-m", "tooling")
    linked = repo.parent / "repo--task"
    git(repo, "worktree", "add", "-q", "-b", "task", str(linked))
    done = run_installer(linked)
    assert done.returncode == 0, done.stderr
    assert (repo / ".git" / "hooks" / "commit-msg").read_bytes() == HOOK_SOURCE.read_bytes()
