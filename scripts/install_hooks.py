"""Install the faultline provenance hook into this clone and set its trailer defaults.

Run from the repo root:  uv run python scripts/install_hooks.py

What it does, one printed line per action, and nothing on a second run:
- refuses if git's core.hooksPath is set at any scope (the hook would land in that folder);
- copies .githooks/commit-msg into the shared hooks folder (<git common dir>/hooks), so every
  linked worktree uses it too; core.hooksPath is never set;
- refuses if a different commit-msg hook without the faultline marker is already there;
- sets faultline.builtWith and faultline.metaModels only when they are unset, so values you
  set yourself survive a re-run.

Standard library only.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

MARKER = b"# faultline provenance hook"
DEFAULTS = (
    ("faultline.builtWith", "claude-opus-5-5 via Claude Code"),
    ("faultline.metaModels", "none"),
)


class InstallError(Exception):
    """A plain-words reason the installer stopped without changing anything."""


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def _repo_root(start: Path) -> Path:
    done = _git(start, "rev-parse", "--show-toplevel")
    if done.returncode != 0:
        raise InstallError(f"{start} is not inside a git repository.")
    return Path(done.stdout.strip())


def _hooks_dir(root: Path) -> Path:
    done = _git(root, "rev-parse", "--git-common-dir")
    if done.returncode != 0:
        raise InstallError(f"git could not name the git folder for {root}.")
    common = Path(done.stdout.strip())
    if not common.is_absolute():
        common = root / common
    return common.resolve() / "hooks"


def install(start: Path) -> list[str]:
    """Install into the repo holding `start`; return the action lines. Raise InstallError."""
    root = _repo_root(start)

    hooks_path = _git(root, "config", "--get", "core.hooksPath")
    if hooks_path.returncode == 0 and hooks_path.stdout.strip():
        raise InstallError(
            f"git's core.hooksPath is set to '{hooks_path.stdout.strip()}', so git does not read "
            "this clone's own hooks folder. Nothing was changed. Unset it, or copy "
            ".githooks/commit-msg into that folder yourself."
        )

    source = root / ".githooks" / "commit-msg"
    if not source.is_file():
        raise InstallError(f"{source} is missing. Nothing was changed.")
    hook_bytes = source.read_bytes().replace(b"\r\n", b"\n")

    target = _hooks_dir(root) / "commit-msg"
    actions: list[str] = []

    if target.exists():
        existing = target.read_bytes()
        if existing == hook_bytes:
            actions.append(f"hook already installed: {target}")
        elif MARKER not in existing:
            raise InstallError(
                f"{target} already holds a different commit-msg hook that is not the faultline "
                "provenance hook. Nothing was changed. Move it aside, then run this again."
            )
        else:
            target.write_bytes(hook_bytes)
            actions.append(f"hook updated: {target}")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(hook_bytes)
        actions.append(f"hook installed: {target}")

    mode = target.stat().st_mode
    wanted = mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    if wanted != mode:
        os.chmod(target, wanted)

    for key, default in DEFAULTS:
        current = _git(root, "config", "--get", key)
        if current.returncode == 0 and current.stdout.strip():
            actions.append(f'kept {key} = "{current.stdout.strip()}"')
            continue
        done = _git(root, "config", "--local", key, default)
        if done.returncode != 0:
            raise InstallError(f"git could not set {key}: {done.stderr.strip()}")
        actions.append(f'set {key} = "{default}"')

    return actions


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    try:
        actions = install(Path.cwd())
    except InstallError as err:
        print(f"install_hooks: {err}", file=sys.stderr)
        return 1
    for line in actions:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
