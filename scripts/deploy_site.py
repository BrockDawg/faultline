"""Deploy the faultline live demo page to a box over ssh.

Standard library only; runs on Windows, Mac and Linux.

Run from the repo root:
    uv run python scripts/deploy_site.py --host <ssh alias> [--record] [--final] [--dry-run]
    uv run python scripts/deploy_site.py --host <ssh alias> --bootstrap [--dry-run]

Before anything leaves this machine it checks:
- the working tree is clean (`git status --porcelain` prints nothing);
- `scripts/site_sweep.py` passed on this exact bundle and page: `site/data/.sweep-<bundle sha>.ok`
  exists and its `page_sha256` equals the page as it is now, so a page edited after the sweep
  is refused;
- with `--final` only, HEAD is on GitHub (contained in a branch `git ls-remote origin` lists).
  Early deploys run before the push, so only the last one needs it.

Then it packs `site-<stamp>.tar.gz` (`git archive HEAD`, `www/` from `site/` with its built
`data/`, and a `COMMIT` file holding HEAD's sha for `/api/health`) and, with `--record`,
`record-<stamp>.tar.gz` (the three record roots and the racing folder). It uploads them with
`deploy/site/install.sh` to the box's staging folder by `scp`, runs `install.sh <stamp>` under
sudo, then `install.sh --graded26` (the 26-clip set replay on the box), and prints the rollback
line. `--dry-run` runs the read-only checks, prints every step, and runs nothing on the box.

ssh and scp are called with argument lists, never a shell string. The host has no default and no
address, user name or key path is written here: the ssh alias in your own ssh config holds them.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STAGING = "/srv/deploy-staging/faultline"
SITE_URL = "https://metahackathon.pitbot.gg/"

Runner = Callable[[Sequence[str]], None]


class Refused(Exception):
    """A preflight check failed: nothing is uploaded."""


# --- local reads -------------------------------------------------------------------------------


def git(repo: Path, *args: str) -> str:
    """Run a read-only git command in `repo` and return its stdout."""
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise Refused(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def load_sweep(repo: Path = REPO):  # noqa: ANN201 - a module object
    """Import `scripts/site_sweep.py`, whose hashes key the stamp. Missing means refused."""
    path = repo / "scripts" / "site_sweep.py"
    if not path.is_file():
        path = REPO / "scripts" / "site_sweep.py"
    if not path.is_file():
        raise Refused("scripts/site_sweep.py is missing: the sweep stamp cannot be checked")
    spec = importlib.util.spec_from_file_location("_site_sweep", path)
    if spec is None or spec.loader is None:
        raise Refused(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    # Registered before running it: its dataclasses look their module up in sys.modules.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


def sweep_check(bundle: Path, page: Path, sweep=None) -> str | None:  # noqa: ANN001
    """None when the sweep's stamp matches this bundle AND this page, else the reason."""
    sweep = sweep or load_sweep()
    stamp = sweep.stamp_path(bundle)
    if not stamp.is_file():
        return f"no {stamp.name}: the bundle changed or was never swept; run site_sweep.py"
    try:
        body = json.loads(stamp.read_text(encoding="utf-8"))
    except ValueError:
        return f"{stamp.name} is not JSON: run site_sweep.py again"
    page_now = sweep.tree_sha256(page, skip=bundle)
    if not isinstance(body, dict) or body.get("page_sha256") != page_now:
        return "the page changed after the sweep: run site_sweep.py again"
    return None


def head_on_github(repo: Path) -> bool:
    """True when HEAD is contained in some branch the `origin` remote lists right now."""
    head = git(repo, "rev-parse", "HEAD").strip()
    for line in git(repo, "ls-remote", "--heads", "origin").splitlines():
        sha = line.split("\t", 1)[0].strip()
        if sha == head:
            return True
        probe = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", head, sha],
            capture_output=True,
            check=False,
        )
        if probe.returncode == 0:
            return True
    return False


def preflight(repo: Path, page: Path, bundle: Path, final: bool) -> list[tuple[str, str | None]]:
    """Every check as (name, None when it passes or the reason it refuses)."""
    checks: list[tuple[str, str | None]] = []
    dirty = git(repo, "status", "--porcelain").rstrip()
    checks.append(("working tree clean", f"not clean:\n{dirty}" if dirty else None))

    if not bundle.is_dir():
        checks.append(("sweep passed on this bundle and page", f"no bundle at {bundle}"))
    else:
        checks.append(("sweep passed on this bundle and page", sweep_check(bundle, page)))

    if final:
        on = head_on_github(repo)
        why = None if on else "HEAD is not on GitHub: push first (or fetch, if pushed elsewhere)"
        checks.append(("HEAD on GitHub (--final)", why))
    return checks


# --- packing -----------------------------------------------------------------------------------


def _add_tree(tar: tarfile.TarFile, src: Path, arcname: str) -> None:
    """Add `src` under `arcname`, leaving out dotfiles (the sweep stamp among them)."""
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if any(part.startswith(".") for part in rel.parts) or not path.is_file():
            continue
        tar.add(path, arcname=f"{arcname}/{rel.as_posix()}", recursive=False)


def pack_site(repo: Path, page: Path, out: Path, commit: str) -> None:
    """`git archive HEAD`, plus www/ from the page folder, plus COMMIT."""
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", "HEAD"], capture_output=True, check=True
    ).stdout
    with tarfile.open(out, "w:gz") as tar:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as src:
            for member in src.getmembers():
                data = src.extractfile(member) if member.isfile() else None
                tar.addfile(member, data)
        _add_tree(tar, page, "www")
        body = (commit + "\n").encode("ascii")
        info = tarfile.TarInfo("COMMIT")
        info.size = len(body)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(body))


def pack_record(record: Path, racing: Path, out: Path) -> None:
    """The record roots (shipped, graded, real) as record/, and the racing folder as racing/."""
    for name in ("shipped", "graded", "real"):
        if not (record / name).is_dir():
            raise Refused(f"no record root {record / name}")
    if not racing.is_dir():
        raise Refused(f"no racing folder {racing}")
    with tarfile.open(out, "w:gz") as tar:
        _add_tree(tar, record, "record")
        _add_tree(tar, racing, "racing")


# --- the plan ----------------------------------------------------------------------------------


def remote_steps(host: str, stamp: str, files: list[str], graded26: bool) -> list[list[str]]:
    """The ssh and scp argument lists, in order."""
    steps = [["scp", *files, f"{host}:{STAGING}/"]]
    steps.append(["ssh", host, "sudo", "bash", f"{STAGING}/install.sh", stamp])
    if graded26:
        steps.append(["ssh", host, "sudo", "bash", f"{STAGING}/install.sh", "--graded26"])
    return steps


def bootstrap_steps(host: str, install_sh: Path) -> list[list[str]]:
    remote = "/tmp/faultline-install.sh"
    return [
        ["scp", str(install_sh), f"{host}:{remote}"],
        ["ssh", host, "sudo", "bash", remote, "--bootstrap"],
        ["ssh", host, "rm", "-f", remote],
    ]


def rollback_line(host: str) -> str:
    return f"ssh {host} sudo bash /srv/faultline/current/deploy/site/install.sh --rollback"


def run_step(argv: Sequence[str]) -> None:
    print("+ " + " ".join(argv), flush=True)
    subprocess.run(list(argv), check=True)


def main(argv: Sequence[str] | None = None, runner: Runner = run_step) -> int:
    parser = argparse.ArgumentParser(description="Deploy the faultline live demo page.")
    parser.add_argument("--host", required=True, help="ssh alias of the box (no default)")
    parser.add_argument("--record", action="store_true", help="also ship record roots + racing")
    parser.add_argument("--final", action="store_true", help="refuse unless HEAD is on GitHub")
    parser.add_argument("--dry-run", action="store_true", help="check and print, run nothing")
    parser.add_argument("--bootstrap", action="store_true", help="first time: user + /srv tree")
    parser.add_argument("--no-graded26", action="store_true", help="skip the 26-clip replay")
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--page", type=Path, default=None, help="default <repo>/site")
    parser.add_argument("--record-src", type=Path, default=None, help="default data/site/record")
    parser.add_argument("--racing-src", type=Path, default=None, help="default data/site/racing")
    args = parser.parse_args(argv)

    host: str = args.host
    if not host or host.startswith("-"):
        parser.error("--host must be an ssh alias")
    repo: Path = args.repo.resolve()
    install_sh = repo / "deploy" / "site" / "install.sh"

    if args.bootstrap:
        steps = bootstrap_steps(host, install_sh)
        print(f"plan: bootstrap {host} (faultline user, /srv/faultline, staging, uv)")
        for step in steps:
            if args.dry_run:
                print("would run: " + " ".join(step))
            else:
                runner(step)
        return 0

    page: Path = (args.page or repo / "site").resolve()
    bundle = page / "data"
    record_src: Path = (args.record_src or repo / "data" / "site" / "record").resolve()
    racing_src: Path = (args.racing_src or repo / "data" / "site" / "racing").resolve()

    refused = False
    print(f"plan: deploy to {host}{' (dry run: nothing runs on the box)' if args.dry_run else ''}")
    try:
        checks = preflight(repo, page, bundle, args.final)
    except Refused as exc:
        checks = [("git", str(exc))]
    if not args.final:
        checks.append(("HEAD on GitHub", "not required without --final"))
    for name, why in checks:
        if why is None:
            print(f"  ok      {name}")
        elif name == "HEAD on GitHub":
            print(f"  skip    {name}: {why}")
        else:
            refused = True
            print(f"  REFUSE  {name}: {why}")
    if refused and not args.dry_run:
        print("refused: nothing was packed or uploaded.")
        return 1

    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    site_name = f"site-{stamp}.tar.gz"
    record_name = f"record-{stamp}.tar.gz"
    print(f"stamp: {stamp}")
    print(f"pack: {site_name} = git archive HEAD + www/ (from {page}) + COMMIT")
    if args.record:
        print(f"pack: {record_name} = record/ (from {record_src}) + racing/ (from {racing_src})")

    with tempfile.TemporaryDirectory(prefix="faultline-deploy-") as tmp:
        site_tar = Path(tmp) / site_name
        record_tar = Path(tmp) / record_name
        files = [str(install_sh), str(site_tar)] + ([str(record_tar)] if args.record else [])
        steps = remote_steps(host, stamp, files, graded26=not args.no_graded26)

        if args.dry_run:
            for step in steps:
                print("would run: " + " ".join(step))
            print("rollback: " + rollback_line(host))
            if refused:
                print("dry run: a real deploy would be refused by the checks above.")
                return 1
            return 0

        commit = git(repo, "rev-parse", "HEAD").strip()
        pack_site(repo, page, site_tar, commit)
        print(f"packed {site_name}: {site_tar.stat().st_size / 1e6:.1f} MB, commit {commit}")
        if args.record:
            pack_record(record_src, racing_src, record_tar)
            print(f"packed {record_name}: {record_tar.stat().st_size / 1e6:.1f} MB")
        for step in steps:
            runner(step)

    print(f"live: {SITE_URL}")
    print("rollback: " + rollback_line(host))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print(f"failed: {' '.join(map(str, exc.cmd))} exited {exc.returncode}", file=sys.stderr)
        sys.exit(1)
