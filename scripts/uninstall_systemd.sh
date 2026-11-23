#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || {
    echo "Run this script using sudo." >&2
    exit 1
}

echo "Removing HDED Backup Manager system integration..."

systemctl disable --now hded-erp-backup.timer 2>/dev/null || true
systemctl stop hded-erp-backup.service 2>/dev/null || true

rm -f /etc/systemd/system/hded-erp-backup.timer
rm -f /etc/systemd/system/hded-erp-backup.service
rm -f /etc/sudoers.d/hded-backup-manager
rm -f /usr/local/sbin/hded-backup-control

systemctl daemon-reload
systemctl reset-failed hded-erp-backup.service 2>/dev/null || true

echo
echo "System integration removed."
echo "Application files, site settings and existing backup files were NOT deleted."
