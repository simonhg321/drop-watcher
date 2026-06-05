#!/bin/bash
# sysadmin_backup.sh — full-box pre-reboot backup for ironman (instockornot.club)
#
# Run BEFORE `apt update && upgrade` + `init 6`. Captures everything that is NOT
# in a git repo: live SQLite DBs, Skipper code, secrets, service configs, Ghost
# content, and package state. One chmod-600 tarball + a sha256 manifest.
#
# Live DBs are snapshotted with SQLite's online `.backup` (NOT cp) so a WAL-mode
# DB being written mid-backup yields a consistent file, not a torn read.
#
# Usage (NOPASSWD stays off — run via sudo):
#     ! sudo bash /home/shg/drop-watcher/bin/sysadmin_backup.sh
#
# Output: /home/shg/backups/ironman-full_<ts>.tar.gz  (+ .sha256)
# HGR / Iron Man

# Best-effort by design: a missing source warns and continues — it never aborts
# the whole backup. We do NOT `set -e`. We DO catch unset vars + pipe failures.
set -uo pipefail

# --- preconditions --------------------------------------------------------
if [ "$EUID" -ne 0 ]; then
    echo "✗ Must run as root: ! sudo bash $0" >&2
    exit 1
fi

command -v sqlite3 >/dev/null 2>&1 || { echo "✗ sqlite3 not found — install it first" >&2; exit 1; }

OWNER="shg"
HOME_DIR="/home/${OWNER}"
BACKUP_DIR="${HOME_DIR}/backups"
TS="$(date +%Y%m%d-%H%M%S)"
STAGE="$(mktemp -d "/tmp/ironman-backup.${TS}.XXXX")"
TARBALL="${BACKUP_DIR}/ironman-full_${TS}.tar.gz"

WARNINGS=0
warn() { echo "  ⚠ $*" >&2; WARNINGS=$((WARNINGS + 1)); }
ok()   { echo "  ✓ $*"; }

# Clean up the staging dir on any exit (it holds secrets — don't leave it around).
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

mkdir -p "$BACKUP_DIR"
chmod 700 "$STAGE"

echo "=== ironman full backup — ${TS} ==="
echo "Staging: $STAGE"

# Copy a path into the staging tree, preserving its absolute layout under tree/.
# Best-effort: warns if the source is missing.
stage_path() {
    local src="$1"
    if [ ! -e "$src" ]; then warn "missing, skipped: $src"; return; fi
    local dest="${STAGE}/tree${src}"
    mkdir -p "$(dirname "$dest")"
    if cp -a "$src" "$dest" 2>/dev/null; then ok "staged $src"; else warn "failed to copy $src"; fi
}

# Online SQLite snapshot — consistent even under concurrent WAL writes.
backup_db() {
    local src="$1" name="$2"
    if [ ! -f "$src" ]; then warn "DB missing, skipped: $src"; return; fi
    local dest="${STAGE}/databases/${name}"
    mkdir -p "${STAGE}/databases"
    if sqlite3 "$src" ".backup '$dest'" 2>/dev/null; then
        local sz; sz="$(du -h "$dest" | cut -f1)"
        ok "DB snapshot $name ($sz)"
    else
        warn "sqlite .backup failed for $src — falling back to cp (may be inconsistent)"
        cp -a "$src" "$dest" 2>/dev/null && ok "DB cp fallback $name" || warn "cp also failed: $src"
    fi
}

# --- 1. live databases (online .backup) -----------------------------------
echo "[1/7] Databases (online snapshot)"
backup_db "/var/lib/skipper/skipper.db"            "skipper.db"
backup_db "/var/lib/drop-watcher/dropwatcher.db"   "dropwatcher.db"

# --- 2. application code --------------------------------------------------
echo "[2/7] Application code"
stage_path "/opt/skipper"

# --- 3. secrets -----------------------------------------------------------
echo "[3/7] Secrets"
stage_path "/var/lib/skipper/curator.secret"
stage_path "${HOME_DIR}/.vault"                       # anthropic/slack/curator tokens
stage_path "/var/lib/drop-watcher/nkd.secret"

# --- 4. Drop Watcher config -----------------------------------------------
echo "[4/7] Drop Watcher config"
stage_path "/etc/drop-watcher"                        # .env + sources.yaml + makers/settings

# --- 5. service / system configs ------------------------------------------
echo "[5/7] Service configs"
stage_path "/etc/apache2"
stage_path "/etc/supervisor"
stage_path "/etc/cron.d"
# Custom unit files only (real files in /etc/systemd/system, not the symlink farm).
mkdir -p "${STAGE}/tree/etc/systemd/system"
found_units=0
for unit in /etc/systemd/system/*.service; do
    [ -f "$unit" ] || continue
    cp -a "$unit" "${STAGE}/tree/etc/systemd/system/" 2>/dev/null && found_units=$((found_units + 1))
done
[ "$found_units" -gt 0 ] && ok "staged ${found_units} custom .service unit(s)" || warn "no custom .service units found"

# Crontabs — both the spool files and a rendered `crontab -l` per user.
stage_path "/var/spool/cron/crontabs"
mkdir -p "${STAGE}/crontabs"
for u in "$OWNER" root; do
    crontab -l -u "$u" > "${STAGE}/crontabs/${u}.crontab" 2>/dev/null \
        && ok "crontab -l for ${u}" || warn "no crontab for ${u}"
done

# --- 6. Ghost content (best-effort) ---------------------------------------
echo "[6/7] Ghost (best-effort)"
stage_path "/var/www/ghost/content"
stage_path "/var/www/ghost/config.production.json"
stage_path "/var/www/html"                            # Apache DocumentRoot (Drop Watcher static)

# --- 7. package / system state --------------------------------------------
echo "[7/7] Package & system state"
mkdir -p "${STAGE}/system-state"
dpkg --get-selections          > "${STAGE}/system-state/dpkg-selections.txt"   2>/dev/null && ok "dpkg --get-selections"   || warn "dpkg --get-selections failed"
apt-mark showmanual            > "${STAGE}/system-state/apt-manual.txt"        2>/dev/null && ok "apt-mark showmanual"     || warn "apt-mark showmanual failed"
uname -a                       > "${STAGE}/system-state/uname.txt"             2>/dev/null
dpkg -l 'linux-image*'         > "${STAGE}/system-state/kernels.txt"           2>/dev/null
{ ip addr; echo; ip route; }   > "${STAGE}/system-state/network.txt"           2>/dev/null
systemctl list-unit-files --state=enabled > "${STAGE}/system-state/enabled-units.txt" 2>/dev/null
df -h                          > "${STAGE}/system-state/disk.txt"              2>/dev/null
ok "system state recorded"

# --- manifest + tarball ---------------------------------------------------
echo "Building manifest…"
( cd "$STAGE" && find . -type f ! -name MANIFEST.sha256 -print0 \
    | sort -z | xargs -0 sha256sum > MANIFEST.sha256 ) \
    && ok "MANIFEST.sha256 ($(wc -l < "${STAGE}/MANIFEST.sha256") files)" \
    || warn "manifest generation failed"

echo "Creating tarball…"
if tar -czf "$TARBALL" -C "$STAGE" . 2>/dev/null; then
    chmod 600 "$TARBALL"
    sha256sum "$TARBALL" | awk '{print $1}' > "${TARBALL}.sha256"
    chmod 600 "${TARBALL}.sha256"
    chown "${OWNER}:${OWNER}" "$TARBALL" "${TARBALL}.sha256" 2>/dev/null
    SIZE="$(du -h "$TARBALL" | cut -f1)"
    ok "tarball: $TARBALL ($SIZE)"
else
    echo "✗ tar failed — backup NOT created" >&2
    exit 1
fi

# Retain the last 7 full backups.
cd "$BACKUP_DIR" && ls -t ironman-full_*.tar.gz 2>/dev/null | tail -n +8 | while read -r old; do
    rm -f "$old" "${old}.sha256"
done
ok "pruned to last 7 backups"

echo "=== Done — ${WARNINGS} warning(s) ==="
echo "Verify:  sha256sum -c <(echo \"\$(cat ${TARBALL}.sha256)  ${TARBALL}\")"
echo "Inspect: tar -tzf ${TARBALL} | head"
echo "Pull:    scp '${OWNER}@instockornot.club:${TARBALL}*' ~/ironman-backups/"
[ "$WARNINGS" -eq 0 ] || echo "  (review warnings above — some sources were missing or unreadable)"
exit 0
