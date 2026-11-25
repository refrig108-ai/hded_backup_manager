#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
BENCH_DIR = Path(__file__).resolve().parents[3]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from hded_backup_manager.backup_engine import (  # noqa: E402
    apply_retention,
    read_settings,
    write_settings,
    prepare_backup_directory,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="HDED ERPNext database-only backup runner")
    parser.add_argument("--site", required=True)
    args = parser.parse_args()

    bench = Path.home() / ".local" / "bin" / "bench"
    if not bench.is_file():
        bench = BENCH_DIR / "env" / "bin" / "bench"
    if not bench.is_file():
        print("ERROR: bench executable was not found", file=sys.stderr)
        return 2

    site_path = BENCH_DIR / "sites" / args.site
    private_dir = site_path / "private"
    settings_path = private_dir / "hded_backup_manager_settings.json"
    settings = read_settings(settings_path)
    backup_mode = settings.get("backup_mode", "scheduled")
    if backup_mode == "one_time" and settings.get("one_time_completed_at"):
        print("[HDED] The configured one-time backup has already completed; refusing another run.", file=sys.stderr)
        return 5

    storage = settings.get("storage", {})
    try:
        backup_dir = prepare_backup_directory(
            site_path=site_path,
            bench_dir=BENCH_DIR,
            local_path=storage.get("local_path", ""),
            require_mount=bool(storage.get("require_mount", False)),
            create=True,
        )
    except Exception as exc:
        print(f"ERROR: Invalid backup storage directory: {exc}", file=sys.stderr)
        return 4

    prefix = args.site.replace(".", "_")
    # Bench always creates a site_config_backup.json alongside the SQL dump.
    # Store that sensitive config file in a temporary private directory so the
    # selected destination receives exactly one file: database.sql.gz.
    with tempfile.TemporaryDirectory(prefix="hded-backup-config-") as temporary_config_dir:
        temporary_config = Path(temporary_config_dir) / "site_config_backup.json"
        command = [
            str(bench), "--site", args.site, "backup",
            "--backup-path", str(backup_dir),
            "--backup-path-conf", str(temporary_config),
        ]
        print(f"[HDED] Starting database-only backup in: {backup_dir}", flush=True)
        subprocess.run(command, cwd=BENCH_DIR, check=True)

    database_pattern = f"*-{prefix}-database.sql.gz"
    database_files = [
        path for path in backup_dir.glob(database_pattern)
        if path.is_file() and not path.is_symlink() and path.stat().st_size > 0
    ]
    if not database_files:
        print("ERROR: Bench backup completed but no database dump was found", file=sys.stderr)
        return 3

    database_path = max(database_files, key=lambda path: (path.stat().st_mtime_ns, path.name))
    timestamp = database_path.name.split("-", 1)[0]
    try:
        datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
    except ValueError:
        print("ERROR: Database backup filename has an invalid timestamp", file=sys.stderr)
        return 3

    print(
        f"[HDED] Database-only backup created: {database_path.name} "
        f"({database_path.stat().st_size} bytes)",
        flush=True,
    )

    pending_drive_timestamps: set[str] = set()

    # Cloud upload is deliberately isolated from local backup success: a
    # Google outage must never turn a valid local database backup into failure.
    try:
        import frappe

        frappe.init(site=args.site, sites_path=str(BENCH_DIR / "sites"))
        try:
            from hded_backup_manager.google_drive import pending_timestamps, process_backup_uploads

            cloud_result = process_backup_uploads(
                database_path,
                site_path=site_path,
            )
            pending_drive_timestamps = pending_timestamps(site_path)
            if cloud_result.get("enabled"):
                print(
                    "[HDED] Google Drive upload: "
                    f"uploaded={cloud_result.get('uploaded', 0)}, "
                    f"pending={cloud_result.get('pending', 0)}",
                    flush=True,
                )
                if cloud_result.get("last_error"):
                    print(
                        f"[HDED] Google Drive warning: {cloud_result['last_error']}",
                        file=sys.stderr,
                        flush=True,
                    )
            else:
                print("[HDED] Google Drive automatic upload is not enabled.", flush=True)
        finally:
            frappe.destroy()
    except Exception as exc:
        print(
            f"[HDED] Google Drive upload could not run; local backup is safe: {str(exc)[:400]}",
            file=sys.stderr,
            flush=True,
        )

    retention = settings.get("retention", {})
    if retention.get("auto_apply", False):
        print("[HDED] Applying configured database-backup retention policy", flush=True)
        result = apply_retention(
            backup_dir,
            prefix,
            retention,
            protected_timestamps=pending_drive_timestamps,
        )
        print(
            f"[HDED] Retention removed {result['deleted_count']} files; "
            f"incomplete backup sets preserved: {result['incomplete_preserved']}; "
            f"Drive-pending backups protected: {len(pending_drive_timestamps)}",
            flush=True,
        )

    if backup_mode == "one_time":
        # Re-read settings before marking completion to avoid overwriting a
        # concurrent settings save with stale values from startup.
        latest_settings = read_settings(settings_path)
        if latest_settings.get("backup_mode") == "one_time":
            latest_settings["one_time_completed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            latest_settings["one_time_timestamp"] = timestamp
            write_settings(settings_path, latest_settings)
            print("[HDED] One-time database backup marked as completed.", flush=True)

    print("[HDED] Database-only backup workflow completed successfully", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: Bench backup failed with exit code {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode or 1)
    except Exception as exc:
        print(f"ERROR: HDED database backup post-processing failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
