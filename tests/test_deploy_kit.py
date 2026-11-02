"""The deploy kit for the live demo page: the nginx vhost, the systemd unit, install.sh and
scripts/deploy_site.py. Text checks and in-process dry runs only: nothing here reaches a box,
and git is replaced by canned answers so no test reads or writes a real repository.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / "deploy" / "site"
VHOST = KIT / "metahackathon.pitbot.gg.conf"
UNIT = KIT / "faultline-site.service"
INSTALL = KIT / "install.sh"
DEPLOY = REPO / "scripts" / "deploy_site.py"
KIT_FILES = (VHOST, UNIT, INSTALL, DEPLOY)


def _load_deploy():
    spec = importlib.util.spec_from_file_location("deploy_site", DEPLOY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deploy_site = _load_deploy()
SWEEP = deploy_site.load_sweep()


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


# --- the vhost ---------------------------------------------------------------------------------


def test_vhost_exact_server_name() -> None:
    names = re.findall(r"^\s*server_name\s+([^;]+);", _strip_comments(_text(VHOST)), re.M)
    assert names and all(n.strip() == "metahackathon.pitbot.gg" for n in names)


def test_vhost_root_outside_league_tree() -> None:
    roots = re.findall(r"^\s*root\s+([^;]+);", _strip_comments(_text(VHOST)), re.M)
    assert roots == ["/srv/faultline/www"]
    assert not roots[0].startswith("/srv/www/brockweb/dev")


def test_vhost_includes_deny_snippet_before_other_regex_locations() -> None:
    body = _strip_comments(_text(VHOST))
    assert "include snippets/deny-backups.conf;" in body
    assert body.index("include snippets/deny-backups.conf;") < body.index("location ~*")


def test_vhost_api_proxy_unbuffered_and_limited() -> None:
    body = _strip_comments(_text(VHOST))
    api = re.search(r"location \^~ /api/ \{(.*?)\n    \}", body, re.S)
    assert api, "no ^~ /api/ location"
    block = api.group(1)
    assert "proxy_pass http://127.0.0.1:8711;" in block
    assert "proxy_buffering off;" in block
    assert "proxy_read_timeout 300s;" in block
    assert "limit_req zone=faultline burst=5 nodelay;" in block
    assert re.search(
        r"^limit_req_zone \$binary_remote_addr zone=faultline:\S+ rate=10r/m;", body, re.M
    )


def test_vhost_job_stream_is_not_rate_limited() -> None:
    body = _strip_comments(_text(VHOST))
    jobs = re.search(r"location \^~ /api/jobs/ \{(.*?)\n    \}", body, re.S)
    assert jobs, "no ^~ /api/jobs/ location"
    block = jobs.group(1)
    assert "proxy_pass http://127.0.0.1:8711;" in block
    assert "proxy_buffering off;" in block
    assert "proxy_read_timeout 300s;" in block
    assert "limit_req" not in block
    # The POSTs still go through the limited /api/ block.
    assert body.count("limit_req zone=faultline") == 1


def test_vhost_headers() -> None:
    body = _strip_comments(_text(VHOST))
    csp = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'"
    )
    assert f'add_header Content-Security-Policy "{csp}" always;' in body
    assert "Strict-Transport-Security" in body
    assert 'X-Content-Type-Options "nosniff"' in body
    assert 'Referrer-Policy "no-referrer"' in body
    # add_header inside a location would drop every server-level header for that location.
    assert body.count("add_header") == 4


def test_vhost_uses_wildcard_cert_and_redirects_http() -> None:
    body = _strip_comments(_text(VHOST))
    assert "ssl_certificate     /etc/letsencrypt/live/pitbot.gg/fullchain.pem;" in body
    assert "return 301 https://$host$request_uri;" in body
    assert re.search(r"^\s*listen 443 ssl;", body, re.M)
    assert re.search(r"^\s*listen 80;", body, re.M)


# --- the unit ----------------------------------------------------------------------------------


def _unit_keys() -> dict[str, list[str]]:
    keys: dict[str, list[str]] = {}
    for line in _text(UNIT).splitlines():
        if "=" in line and not line.lstrip().startswith(("#", "[")):
            k, v = line.split("=", 1)
            keys.setdefault(k.strip(), []).append(v.strip())
    return keys


def test_unit_has_no_network_and_no_environment_file() -> None:
    keys = _unit_keys()
    assert keys["IPAddressDeny"] == ["any"]
    assert keys["IPAddressAllow"] == ["localhost"]
    assert "EnvironmentFile" not in keys


def test_unit_sandbox_and_limits() -> None:
    keys = _unit_keys()
    expect = {
        "User": "faultline",
        "WorkingDirectory": "/srv/faultline/current",
        "MemoryMax": "1G",
        "CPUQuota": "150%",
        "Nice": "10",
        "TasksMax": "64",
        "ProtectSystem": "strict",
        "ProtectHome": "yes",
        "ReadOnlyPaths": "/srv/faultline",
        "PrivateTmp": "yes",
        "NoNewPrivileges": "yes",
        "Restart": "on-failure",
    }
    for key, value in expect.items():
        assert keys.get(key) == [value], key


def test_unit_execstart_is_the_worker_contract() -> None:
    assert _unit_keys()["ExecStart"] == [
        "/srv/faultline/current/.venv/bin/python -m faultline.adapters.video.serve "
        "--host 127.0.0.1 --port 8711 --roots /srv/faultline/record "
        "--bundle /srv/faultline/www/data --racing /srv/faultline/racing "
        "--replays /srv/faultline/replays"
    ]


# --- install.sh --------------------------------------------------------------------------------


def test_install_sets_python_dir_under_srv_faultline() -> None:
    m = re.search(r"^export UV_PYTHON_INSTALL_DIR=(\S+)$", _text(INSTALL), re.M)
    assert m
    value = m.group(1).replace("$BASE", "/srv/faultline")
    assert value.startswith("/srv/faultline/")
    assert _text(INSTALL).index("UV_PYTHON_INSTALL_DIR") < _text(INSTALL).index("sync --frozen")


def test_install_modes_and_guards() -> None:
    text = _text(INSTALL)
    for mode in ("--bootstrap) bootstrap", "--rollback) rollback", "--graded26) graded26"):
        assert mode in text
    assert "--shell /usr/sbin/nologin faultline" in text
    assert 'uv" sync --frozen --extra site' in text
    # nginx is reloaded only after nginx -t passes.
    assert text.index("if ! nginx -t") < text.index("systemctl reload nginx")
    # A failed go-live puts the previous release back.
    assert 'switch_current "$prev"' in text


def test_install_venv_python_is_managed_and_under_srv_faultline() -> None:
    text = _text(INSTALL)
    sync = next(line for line in text.splitlines() if "sync --frozen" in line)
    assert "--python-preference only-managed" in sync
    after = text[text.index(sync) :]
    assert 'readlink -f "$dest/.venv/bin/python"' in after
    assert '"$BASE"/*) ;;' in after
    # The check runs before the switch, so a bad venv never goes live.
    assert after.index('"$BASE"/*) ;;') < after.index('switch_current "$dest"')


def test_install_record_kept_until_live_and_restored_on_failure() -> None:
    text = _text(INSTALL)
    body = text[text.index("install_record() {") : text.index("restore_record() {")]
    assert 'mv "$BASE/$name" "$BASE/$name.old"' in body
    # The swap itself never deletes the previous copy (only a stale .old before moving).
    assert body.count('rm -rf "$BASE/$name.old"') == 1
    assert body.index('rm -rf "$BASE/$name.old"') < body.index('mv "$BASE/$name" "$BASE/$name.old"')
    restore = text[text.index("restore_record() {") : text.index("drop_record_backup() {")]
    assert 'mv "$BASE/$name.old" "$BASE/$name"' in restore
    release = text[text.index("install_release() {") : text.index("rollback() {")]
    assert release.index("trap restore_record EXIT") < release.index("install_record")
    failed = release[release.index('if ! check_live "$commit"') :]
    assert failed.index("restore_record") < failed.index('die "release')
    assert release.index('check_live "$commit"') < release.index("drop_record_backup")


def test_install_sh_parses() -> None:
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on this machine")
    done = subprocess.run([bash, "-n", str(INSTALL)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_install_graded26_runs_with_no_network() -> None:
    text = _text(INSTALL)
    run = text[text.index("systemd-run") : text.index('> "$out"')]
    assert "IPAddressDeny=any" in run
    assert "--uid=faultline" in run


# --- deploy_site.py ----------------------------------------------------------------------------


def _fake_repo(tmp_path: Path, *, swept: bool) -> Path:
    repo = tmp_path / "repo"
    (repo / "deploy" / "site").mkdir(parents=True)
    (repo / "deploy" / "site" / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    data = repo / "site" / "data"
    data.mkdir(parents=True)
    (repo / "site" / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
    (data / "index.json").write_text("{}\n", encoding="utf-8")
    if swept:
        SWEEP.write_stamp(data, repo / "site")
    return repo


@pytest.fixture
def no_git(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Canned git: a clean tree, HEAD `abc123`, and HEAD on GitHub only when told."""
    state: dict[str, object] = {"dirty": "", "on_github": False, "github_asked": 0}

    def fake_git(repo: Path, *args: str) -> str:
        if args[:1] == ("status",):
            return str(state["dirty"])
        if args[:2] == ("rev-parse", "HEAD"):
            return "abc123\n"
        raise AssertionError(f"unexpected git call {args}")

    def fake_on_github(repo: Path) -> bool:
        state["github_asked"] = int(state["github_asked"]) + 1  # type: ignore[arg-type]
        return bool(state["on_github"])

    monkeypatch.setattr(deploy_site, "git", fake_git)
    monkeypatch.setattr(deploy_site, "head_on_github", fake_on_github)

    def no_subprocess(*a: object, **k: object) -> None:
        raise AssertionError(f"subprocess called: {a}")

    monkeypatch.setattr(deploy_site.subprocess, "run", no_subprocess)
    return state


def test_dry_run_prints_plan_and_runs_nothing(
    tmp_path: Path, no_git: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _fake_repo(tmp_path, swept=True)
    ran: list[list[str]] = []
    code = deploy_site.main(
        ["--host", "fakehost", "--record", "--dry-run", "--repo", str(repo)],
        runner=lambda argv: ran.append(list(argv)),
    )
    out = capsys.readouterr().out
    assert code == 0
    assert ran == []
    assert "would run: scp" in out
    assert "fakehost:/srv/deploy-staging/faultline/" in out
    assert re.search(r"would run: ssh fakehost sudo bash \S+install.sh \d{8}T\d{6}Z", out)
    assert "--graded26" in out
    assert "rollback: ssh fakehost sudo bash /srv/faultline/current/deploy/site/install.sh" in out
    assert not list(tmp_path.rglob("*.tar.gz"))


def test_without_final_github_not_required(
    tmp_path: Path, no_git: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _fake_repo(tmp_path, swept=True)
    code = deploy_site.main(["--host", "fakehost", "--dry-run", "--repo", str(repo)], runner=print)
    assert code == 0
    assert no_git["github_asked"] == 0
    assert "REFUSE" not in capsys.readouterr().out


def test_final_requires_head_on_github(
    tmp_path: Path, no_git: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _fake_repo(tmp_path, swept=True)
    ran: list[list[str]] = []
    code = deploy_site.main(
        ["--host", "fakehost", "--final", "--repo", str(repo)], runner=lambda a: ran.append(a)
    )
    assert code == 1 and ran == []
    assert "REFUSE  HEAD on GitHub (--final)" in capsys.readouterr().out

    no_git["on_github"] = True
    code = deploy_site.main(
        ["--host", "fakehost", "--final", "--dry-run", "--repo", str(repo)], runner=print
    )
    assert code == 0
    assert no_git["github_asked"] == 2


def test_refuses_dirty_tree(
    tmp_path: Path, no_git: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _fake_repo(tmp_path, swept=True)
    no_git["dirty"] = " M src/x.py\n"
    ran: list[list[str]] = []
    assert deploy_site.main(["--host", "h", "--repo", str(repo)], runner=ran.append) == 1
    assert ran == []
    assert "REFUSE  working tree clean" in capsys.readouterr().out


def test_refuses_unswept_or_changed_bundle(
    tmp_path: Path, no_git: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _fake_repo(tmp_path, swept=False)
    ran: list[list[str]] = []
    assert deploy_site.main(["--host", "h", "--repo", str(repo)], runner=ran.append) == 1
    assert "REFUSE  sweep passed on this bundle" in capsys.readouterr().out

    repo2 = _fake_repo(tmp_path / "b", swept=True)
    (repo2 / "site" / "data" / "index.json").write_text('{"changed": 1}\n', encoding="utf-8")
    assert deploy_site.main(["--host", "h", "--repo", str(repo2)], runner=ran.append) == 1
    assert ran == []


def test_refuses_page_edited_after_sweep(
    tmp_path: Path, no_git: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _fake_repo(tmp_path, swept=True)
    ran: list[list[str]] = []
    assert deploy_site.main(["--host", "h", "--dry-run", "--repo", str(repo)], runner=print) == 0
    capsys.readouterr()
    (repo / "site" / "index.html").write_text("<!doctype html><p>edited</p>\n", encoding="utf-8")
    assert deploy_site.main(["--host", "h", "--repo", str(repo)], runner=ran.append) == 1
    assert ran == []
    assert "the page changed after the sweep" in capsys.readouterr().out


def test_refuses_stamp_without_page_hash(
    tmp_path: Path, no_git: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _fake_repo(tmp_path, swept=True)
    stamp = SWEEP.stamp_path(repo / "site" / "data")
    stamp.write_text("ok\n", encoding="utf-8")
    assert deploy_site.main(["--host", "h", "--repo", str(repo)], runner=print) == 1
    assert "REFUSE  sweep passed" in capsys.readouterr().out


def test_host_is_required() -> None:
    with pytest.raises(SystemExit):
        deploy_site.main(["--dry-run"])


def test_ssh_and_scp_are_argument_lists() -> None:
    steps = deploy_site.remote_steps("h", "20261102T000000Z", ["a", "b"], graded26=True)
    assert all(isinstance(s, list) and s[0] in ("ssh", "scp") for s in steps)
    assert "shell=True" not in _text(DEPLOY)


def test_deploy_site_is_stdlib_only() -> None:
    imports = re.findall(r"^(?:from|import) (\w+)", _text(DEPLOY), re.M)
    allowed = {
        "__future__", "argparse", "collections", "datetime", "importlib", "io", "json",
        "pathlib", "subprocess", "sys", "tarfile", "tempfile",
    }  # fmt: skip
    assert set(imports) <= allowed, set(imports) - allowed


# --- no real box named anywhere ----------------------------------------------------------------


@pytest.mark.parametrize("path", KIT_FILES, ids=lambda p: p.name)
def test_no_address_user_or_key_path(path: Path) -> None:
    text = _text(path)
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text.replace("127.0.0.1", "")), "an IP"
    assert not re.search(r"\b\w+@[\w.-]+\.\w+\b", text), "a user@host"
    assert "ubun" + "tu" not in text.lower()
    assert not re.search(r"(?i)\bid_(rsa|ed25519|ecdsa)\b|\.ssh/", text), "a key path"
    # The box's ssh alias, spelled in two pieces so this test does not hold it either.
    assert not re.search(r"" + "brock" + "dev" + r"", text.lower()), "the box alias"
