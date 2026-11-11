#!/usr/bin/env bash
# install.sh: put one faultline site release live on the box, or undo the last one.
# Runs as root (sudo). scripts/deploy_site.py uploads it with the tars and calls it; nothing here
# is run by hand except --bootstrap (once) and --rollback.
#
#   install.sh --bootstrap   once: the faultline system user (no shell), the /srv/faultline tree,
#                            the staging folder (owned by the sudo caller), and uv if absent
#   install.sh <stamp>       install the release staged as site-<stamp>.tar.gz (and, when present,
#                            record-<stamp>.tar.gz) next to this script
#   install.sh --graded26    run the 26-clip set replay on the live release, no network, and write
#                            /srv/faultline/replays/graded26.json
#   install.sh --rollback    point current back at the release before it and restart
#
# Any failure after the switch puts the previous release back and restarts it.
# nginx is reloaded only after nginx -t passes; a failed test restores the old vhost.

set -euo pipefail

BASE=/srv/faultline
RELEASES=$BASE/releases
CURRENT=$BASE/current
WWW=$BASE/www
STAGING=/srv/deploy-staging/faultline
SITE=metahackathon.pitbot.gg
VHOST_AVAILABLE=/etc/nginx/sites-available/$SITE
VHOST_ENABLED=/etc/nginx/sites-enabled/$SITE
UNIT=faultline-site.service
UNIT_PATH=/etc/systemd/system/$UNIT
HEALTH=http://127.0.0.1:8711/api/health
KEEP_RELEASES=3
# ProtectHome=yes hides any Python under a home folder from the faultline user, so uv puts the
# Python it fetches here, and keeps its cache here too.
export UV_PYTHON_INSTALL_DIR=$BASE/python
export UV_CACHE_DIR=$BASE/uv-cache

say() { printf 'install.sh: %s\n' "$*"; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root: sudo bash $0 $*"

find_uv() {
    if command -v uv >/dev/null 2>&1; then command -v uv; return; fi
    for p in /usr/local/bin/uv /root/.local/bin/uv; do
        if [ -x "$p" ]; then echo "$p"; return; fi
    done
    return 1
}

bootstrap() {
    if ! id faultline >/dev/null 2>&1; then
        useradd --system --user-group --no-create-home --home-dir /nonexistent \
            --shell /usr/sbin/nologin faultline
        say "created system user faultline (no shell)"
    fi
    install -d -m 0755 -o root -g root "$BASE" "$RELEASES" "$WWW" "$BASE/replays" \
        "$UV_PYTHON_INSTALL_DIR" "$UV_CACHE_DIR"
    # The record roots and the racing folder: readable by the worker only, never by nginx.
    install -d -m 0750 -o root -g faultline "$BASE/record" "$BASE/racing"
    local owner=${SUDO_USER:-root}
    install -d -m 0755 -o root -g root /srv/deploy-staging
    install -d -m 0755 -o "$owner" "$STAGING"
    if ! find_uv >/dev/null; then
        say "uv not found: installing it to /usr/local/bin"
        curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL=/usr/local/bin sh
    fi
    say "bootstrap done: $BASE, $STAGING (owner $owner), uv at $(find_uv)"
}

# Copy a release's www/ into place in one rename, so nginx never serves half a page.
publish_www() {
    local src=$1
    rm -rf "$WWW.new"
    cp -a "$src/www" "$WWW.new"
    chown -R root:root "$WWW.new"
    find "$WWW.new" -type d -exec chmod 0755 {} +
    find "$WWW.new" -type f -exec chmod 0644 {} +
    rm -rf "$WWW.old"
    if [ -d "$WWW" ]; then mv "$WWW" "$WWW.old"; fi
    mv "$WWW.new" "$WWW"
    rm -rf "$WWW.old"
}

switch_current() {
    ln -sfn "$1" "$CURRENT.new"
    mv -T "$CURRENT.new" "$CURRENT"
}

# Wait for the worker, then check the page through this box's own nginx (not through DNS).
check_live() {
    local want_commit=$1 body="" i
    for i in $(seq 1 30); do
        if body=$(curl -fsS --max-time 5 "$HEALTH" 2>/dev/null); then break; fi
        body=""
        sleep 1
    done
    [ -n "$body" ] || { say "health: no answer from $HEALTH"; return 1; }
    if ! printf '%s' "$body" | "$CURRENT/.venv/bin/python" -c '
import json, sys
h = json.load(sys.stdin)
want = sys.argv[1]
ok = h.get("ok") is True and (not want or h.get("commit") == want)
sys.exit(0 if ok else 1)
' "$want_commit"; then
        say "health: unexpected answer: $body"
        return 1
    fi
    if ! curl -fsS --max-time 10 -o /dev/null --resolve "$SITE:443:127.0.0.1" "https://$SITE/"; then
        say "page: https://$SITE/ did not answer 200 from this box"
        return 1
    fi
    say "live: health ok, commit ${want_commit:-?}, page 200"
}

install_vhost() {
    local src=$1/deploy/site/$SITE.conf backup=""
    if [ -f "$VHOST_AVAILABLE" ] && cmp -s "$src" "$VHOST_AVAILABLE"; then
        ln -sfn "$VHOST_AVAILABLE" "$VHOST_ENABLED"
        return 0
    fi
    if [ -f "$VHOST_AVAILABLE" ]; then
        backup=$(mktemp)
        cp -a "$VHOST_AVAILABLE" "$backup"
    fi
    install -m 0644 "$src" "$VHOST_AVAILABLE"
    ln -sfn "$VHOST_AVAILABLE" "$VHOST_ENABLED"
    if ! nginx -t; then
        if [ -n "$backup" ]; then
            cp -a "$backup" "$VHOST_AVAILABLE"
        else
            rm -f "$VHOST_ENABLED" "$VHOST_AVAILABLE"
        fi
        die "nginx -t failed: the old vhost is back and nginx was not reloaded"
    fi
    systemctl reload nginx
    say "vhost installed and nginx reloaded"
}

install_unit() {
    local src=$1/deploy/site/$UNIT
    if [ -f "$UNIT_PATH" ] && cmp -s "$src" "$UNIT_PATH"; then return 0; fi
    install -m 0644 "$src" "$UNIT_PATH"
    systemctl daemon-reload
    systemctl enable "$UNIT" >/dev/null
    say "unit installed"
}

# Swap in the record roots and the racing folder from a staged record tar. The previous copies stay
# as <name>.old until the new release answers: restore_record puts them back, drop_record_backup
# deletes them once the release is live.
RECORD_SWAPPED=0
install_record() {
    local tarball=$1 tmp name
    tmp=$(mktemp -d "$BASE/record-unpack.XXXXXX")
    tar -xzf "$tarball" -C "$tmp" --no-same-owner
    for name in record racing; do
        [ -d "$tmp/$name" ] || { rm -rf "$tmp"; die "record tar has no $name/"; }
    done
    RECORD_SWAPPED=1
    for name in record racing; do
        chown -R root:faultline "$tmp/$name"
        find "$tmp/$name" -type d -exec chmod 0750 {} +
        find "$tmp/$name" -type f -exec chmod 0640 {} +
        rm -rf "$BASE/$name.old"
        if [ -d "$BASE/$name" ]; then mv "$BASE/$name" "$BASE/$name.old"; fi
        mv "$tmp/$name" "$BASE/$name"
    done
    rm -rf "$tmp"
    say "record roots and racing folder installed (previous copies kept until the release is live)"
}

restore_record() {
    [ "$RECORD_SWAPPED" -eq 1 ] || return 0
    local name
    for name in record racing; do
        if [ -d "$BASE/$name.old" ]; then
            rm -rf "${BASE:?}/$name"
            mv "$BASE/$name.old" "$BASE/$name"
        fi
    done
    RECORD_SWAPPED=0
    say "previous record roots and racing folder put back"
}

drop_record_backup() {
    rm -rf "$BASE/record.old" "$BASE/racing.old"
    RECORD_SWAPPED=0
}

prune_releases() {
    local live
    live=$(readlink -f "$CURRENT")
    ls -1 "$RELEASES" | sort | head -n -"$KEEP_RELEASES" | while read -r old; do
        [ "$RELEASES/$old" = "$live" ] || rm -rf "${RELEASES:?}/$old"
    done
}

install_release() {
    local stamp=$1
    [[ "$stamp" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || die "bad stamp: $stamp (want YYYYMMDDTHHMMSSZ)"
    id faultline >/dev/null 2>&1 || die "no faultline user: run install.sh --bootstrap first"
    local here uv dest prev="" commit
    here=$(cd "$(dirname "$0")" && pwd)
    uv=$(find_uv) || die "uv not found: run install.sh --bootstrap first"
    local site_tar=$here/site-$stamp.tar.gz record_tar=$here/record-$stamp.tar.gz
    [ -f "$site_tar" ] || die "missing $site_tar"
    dest=$RELEASES/$stamp
    [ -e "$dest" ] && die "release $stamp already exists"

    # 1. Unpack and build the venv. Nothing live has changed yet.
    install -d -m 0755 "$dest"
    tar -xzf "$site_tar" -C "$dest" --no-same-owner
    [ -d "$dest/www" ] || die "site tar has no www/"
    commit=$(tr -d '[:space:]' < "$dest/COMMIT" 2>/dev/null || true)
    # only-managed: a system or home-folder Python is never picked, so the venv's Python sits under
    # UV_PYTHON_INSTALL_DIR, which the unit can read with ProtectHome=yes.
    (cd "$dest" && "$uv" sync --frozen --extra site --no-dev --python-preference only-managed)
    local venv_py
    venv_py=$(readlink -f "$dest/.venv/bin/python")
    case "$venv_py" in
        "$BASE"/*) ;;
        *) die "the venv's Python is $venv_py, outside $BASE: the worker could not run it" ;;
    esac
    chown -R root:root "$dest"
    chmod -R go-w,a+rX "$dest"

    # 2. The vhost (nginx -t gates the reload) and the unit.
    install_vhost "$dest"
    install_unit "$dest"
    # Any exit before the release is confirmed live puts the previous record copies back.
    trap restore_record EXIT
    if [ -f "$record_tar" ]; then install_record "$record_tar"; fi

    # 3. Switch. From here a failure puts the previous release back.
    if [ -L "$CURRENT" ]; then prev=$(readlink -f "$CURRENT"); fi
    publish_www "$dest"
    switch_current "$dest"
    systemctl restart "$UNIT"
    if ! check_live "$commit"; then
        restore_record
        if [ -n "$prev" ] && [ -d "$prev" ]; then
            say "failed: putting $(basename "$prev") back"
            publish_www "$prev"
            switch_current "$prev"
            systemctl restart "$UNIT"
            check_live "" || say "the previous release did not answer either"
        else
            say "failed, and there is no previous release: stopping the worker"
            systemctl stop "$UNIT" || true
        fi
        die "release $stamp did not go live"
    fi

    drop_record_backup
    rm -f "$site_tar" "$record_tar"
    prune_releases
    say "release $stamp is live"
}

rollback() {
    [ -L "$CURRENT" ] || die "no current release"
    local live prev="" r
    live=$(basename "$(readlink -f "$CURRENT")")
    for r in $(ls -1 "$RELEASES" | sort); do
        [ "$r" = "$live" ] && break
        prev=$r
    done
    [ -n "$prev" ] || die "no release before $live to roll back to"
    publish_www "$RELEASES/$prev"
    switch_current "$RELEASES/$prev"
    install_vhost "$RELEASES/$prev"
    install_unit "$RELEASES/$prev"
    systemctl restart "$UNIT"
    check_live "$(tr -d '[:space:]' < "$RELEASES/$prev/COMMIT" 2>/dev/null || true)" \
        || die "rolled back to $prev but it did not answer"
    say "rolled back from $live to $prev"
}

# The 26-clip set replay, under the worker's own limits and with no network, as the faultline user.
graded26() {
    [ -L "$CURRENT" ] || die "no current release"
    local py=$CURRENT/.venv/bin/python out start end
    local root=$BASE/record/graded
    [ -f "$root/preds.jsonl" ] || die "missing $root/preds.jsonl (deploy with --record first)"
    out=$(mktemp)
    start=$(date +%s.%N)
    systemd-run --wait --pipe --collect --quiet --uid=faultline --gid=faultline \
        --working-directory="$CURRENT" \
        -p MemoryMax=1G -p CPUQuota=150% -p Nice=10 -p TasksMax=64 \
        -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes -p NoNewPrivileges=yes \
        -p IPAddressDeny=any -p IPAddressAllow=localhost \
        -E PYTHONDONTWRITEBYTECODE=1 \
        "$py" -m faultline.adapters.video.replay_one --record "$root" --all "$root/preds.jsonl" \
        > "$out" || { rm -f "$out"; die "the 26-clip replay failed; graded26.json left as it was"; }
    end=$(date +%s.%N)
    "$py" - "$out" "$start" "$end" "$CURRENT/COMMIT" "$BASE/replays/graded26.json" <<'PY'
import datetime
import json
import os
import sys
from pathlib import Path

out, start, end, commit_file, dest = sys.argv[1:6]
result = None
for raw in Path(out).read_text(encoding="utf-8").splitlines():
    try:
        obj = json.loads(raw)
    except ValueError:
        continue
    if isinstance(obj, dict) and obj.get("set_sha256"):
        result = obj
if result is None:
    sys.exit("install.sh: the replay printed no set hash; graded26.json left as it was")
commit = Path(commit_file).read_text(encoding="utf-8").strip() if os.path.exists(commit_file) else ""
doc = {
    "time": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "seconds": round(float(end) - float(start), 1),
    "set_sha256": result["set_sha256"],
    "commit": commit,
    "network": "none",
    "result": result,
}
tmp = dest + ".tmp"
Path(tmp).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(tmp, 0o644)
os.replace(tmp, dest)
print(f"install.sh: graded26.json written, set {doc['set_sha256']}, {doc['seconds']} s")
PY
    rm -f "$out"
}

case "${1:-}" in
    --bootstrap) bootstrap ;;
    --rollback) rollback ;;
    --graded26) graded26 ;;
    "" | -h | --help) sed -n '2,15p' "$0" ;;
    -*) die "unknown option: $1" ;;
    *) install_release "$1" ;;
esac
