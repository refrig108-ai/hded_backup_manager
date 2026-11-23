#!/usr/bin/env bash
set -euo pipefail

BENCH_DIR=""
SITE=""
BENCH_USER="${SUDO_USER:-}"
INITIAL_TIME="02:00"

usage() {
    echo "Usage:"
    echo "  sudo bash install_systemd.sh --bench-dir PATH --site SITE [--user USER] [--time HH:MM]"
}

while (($#)); do
    case "$1" in
        --bench-dir) BENCH_DIR="${2:?}"; shift 2 ;;
        --site) SITE="${2:?}"; shift 2 ;;
        --user) BENCH_USER="${2:?}"; shift 2 ;;
        --time) INITIAL_TIME="${2:?}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

[[ $EUID -eq 0 ]] || {
    echo "Run this installer using sudo." >&2
    exit 1
}

[[ -n "$BENCH_DIR" && -n "$SITE" && -n "$BENCH_USER" ]] || {
    usage
    exit 2
}

[[ "$SITE" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || {
    echo "Invalid site name." >&2
    exit 2
}

[[ "$INITIAL_TIME" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] || {
    echo "Invalid time. Use HH:MM." >&2
    exit 2
}

[[ "$BENCH_DIR" != *[[:space:]]* ]] || {
    echo "Bench path cannot contain whitespace." >&2
    exit 2
}

BENCH_DIR="$(realpath -e "$BENCH_DIR")"

APP_DIR="$BENCH_DIR/apps/hded_backup_manager"
SITE_DIR="$BENCH_DIR/sites/$SITE"
PYTHON="$BENCH_DIR/env/bin/python"
RUNNER="$APP_DIR/scripts/backup_runner.py"
CONTROL_SOURCE="$APP_DIR/scripts/hded-backup-control"

[[ -d "$SITE_DIR" ]] || {
    echo "Site directory not found: $SITE_DIR" >&2
    exit 1
}

[[ -f "$RUNNER" && -f "$CONTROL_SOURCE" ]] || {
    echo "Application installation files are missing." >&2
    exit 1
}

[[ -x "$PYTHON" ]] || {
    echo "Bench Python environment not found: $PYTHON" >&2
    exit 1
}

id "$BENCH_USER" >/dev/null 2>&1 || {
    echo "Linux user not found: $BENCH_USER" >&2
    exit 1
}

USER_HOME="$(getent passwd "$BENCH_USER" | cut -d: -f6)"
BENCH_GROUP="$(id -gn "$BENCH_USER")"

if [[ ! -x "$USER_HOME/.local/bin/bench" && ! -x "$BENCH_DIR/env/bin/bench" ]]; then
    echo "Bench executable was not found for $BENCH_USER." >&2
    exit 1
fi

CONTROL_BIN="/usr/local/sbin/hded-backup-control"
SERVICE_UNIT="/etc/systemd/system/hded-erp-backup.service"
TIMER_UNIT="/etc/systemd/system/hded-erp-backup.timer"
SUDOERS_FILE="/etc/sudoers.d/hded-backup-manager"

SERVICE_NAME="hded-erp-backup.service"
TIMER_NAME="hded-erp-backup.timer"

TIMER_WAS_ACTIVE="$(systemctl is-active "$TIMER_NAME" 2>/dev/null || true)"
TIMER_CREATED=0

backup_existing() {
    local file="$1"
    if [[ -f "$file" && ! -L "$file" ]]; then
        cp -a "$file" "$file.before-install-$(date +%Y%m%d-%H%M%S)"
    fi
}

echo "Installing HDED Backup Manager system integration..."
echo "Bench: $BENCH_DIR"
echo "Site: $SITE"
echo "User: $BENCH_USER"

install -d -o root -g root -m 0755 /usr/local/sbin

backup_existing "$CONTROL_BIN"
install -o root -g root -m 0750 "$CONTROL_SOURCE" "$CONTROL_BIN"

echo "Control utility installed."

if [[ -L "$SERVICE_UNIT" ]]; then
    echo "Refusing to replace a symbolic-link service unit." >&2
    exit 1
fi

backup_existing "$SERVICE_UNIT"

DOCKER_WANTS=""
DOCKER_AFTER=""

if systemctl cat docker.service >/dev/null 2>&1; then
    DOCKER_WANTS=" docker.service"
    DOCKER_AFTER=" docker.service"
fi

SERVICE_TMP="$(mktemp)"
trap 'rm -f "$SERVICE_TMP"' EXIT

cat > "$SERVICE_TMP" <<EOF
[Unit]
Description=HDED ERPNext Backup Service
Wants=network-online.target$DOCKER_WANTS
After=network-online.target$DOCKER_AFTER

[Service]
Type=oneshot
User=$BENCH_USER
Group=$BENCH_GROUP
WorkingDirectory=$BENCH_DIR
Environment=PATH=$USER_HOME/.local/bin:$BENCH_DIR/env/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
UMask=0077
ExecStart=$PYTHON $RUNNER --site $SITE

Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
TimeoutStartSec=45min

StandardOutput=journal
StandardError=journal
EOF

install -o root -g root -m 0644 "$SERVICE_TMP" "$SERVICE_UNIT"
rm -f "$SERVICE_TMP"
trap - EXIT

echo "Backup service installed."

if [[ -L "$TIMER_UNIT" ]]; then
    echo "Refusing to replace a symbolic-link timer unit." >&2
    exit 1
fi

if [[ ! -e "$TIMER_UNIT" ]]; then
    TIMER_TMP="$(mktemp)"
    trap 'rm -f "$TIMER_TMP"' EXIT

    cat > "$TIMER_TMP" <<EOF
[Unit]
Description=HDED ERP Backup Schedule

[Timer]
OnCalendar=*-*-* $INITIAL_TIME:00
Persistent=true
AccuracySec=1min
Unit=$SERVICE_NAME

[Install]
WantedBy=timers.target
EOF

    install -o root -g root -m 0644 "$TIMER_TMP" "$TIMER_UNIT"
    rm -f "$TIMER_TMP"
    trap - EXIT

    TIMER_CREATED=1
    echo "New timer created with initial time $INITIAL_TIME."
else
    echo "Existing timer preserved without changing its schedule."
fi

if [[ -L "$SUDOERS_FILE" ]]; then
    echo "Refusing to replace a symbolic-link sudoers file." >&2
    exit 1
fi

backup_existing "$SUDOERS_FILE"

SUDOERS_TMP="$(mktemp)"
trap 'rm -f "$SUDOERS_TMP"' EXIT

printf '%s ALL=(root) NOPASSWD: %s\n' \
    "$BENCH_USER" "$CONTROL_BIN" > "$SUDOERS_TMP"

chmod 0440 "$SUDOERS_TMP"
visudo -cf "$SUDOERS_TMP" >/dev/null

install -o root -g root -m 0440 "$SUDOERS_TMP" "$SUDOERS_FILE"
rm -f "$SUDOERS_TMP"
trap - EXIT

echo "Restricted sudo permission installed."

systemctl daemon-reload

if [[ "$TIMER_CREATED" == "1" ]]; then
    systemctl enable --now "$TIMER_NAME"
elif [[ "$TIMER_WAS_ACTIVE" == "active" ]] && ! systemctl is-active --quiet "$TIMER_NAME"; then
    systemctl start "$TIMER_NAME"
fi

echo
echo "HDED Backup Manager system integration completed."
echo "Existing timer configuration and enabled/disabled state were preserved."
echo

systemctl is-active "$TIMER_NAME" 2>/dev/null || true
systemctl list-timers "$TIMER_NAME" --all --no-pager
