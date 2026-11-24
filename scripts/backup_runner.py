#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
BENCH_DIR = Path(__file__).resolve().parents[3]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from hded_backup_manager.backup_engine import (  # noqa: E402
    apply_retention,
    create_apps_archive,
    read_settings,
    write_settings,
    prepare_backup_directory,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="HDED ERPNext backup runner")
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

    command = [
        str(bench), "--site", args.site, "backup", "--with-files",
        "--backup-path", str(backup_dir),
    ]
    print(f"[HDED] Starting official Bench backup in: {backup_dir}", flush=True)
    subprocess.run(command, cwd=BENCH_DIR, check=True)

    prefix = args.site.replace(".", "_")
    config_files = sorted(backup_dir.glob(f"*-{prefix}-site_config_backup.json"))
    if not config_files:
        print("ERROR: Bench backup completed but no site config backup was found", file=sys.stderr)
        return 3
    timestamp = config_files[-1].name.split("-", 1)[0]

    if settings.get("apps", {}).get("archive_enabled", True):
        print("[HDED] Archiving selected application source directories", flush=True)
        archive = create_apps_archive(BENCH_DIR, backup_dir, args.site, timestamp, settings)
        print(f"[HDED] Application archive created: {archive.name} ({archive.stat().st_size} bytes)", flush=True)

    retention = settings.get("retention", {})
    if retention.get("auto_apply", False):
        print("[HDED] Applying configured retention policy", flush=True)
        result = apply_retention(backup_dir, prefix, retention)
        print(f"[HDED] Retention removed {result['deleted_count']} files; incomplete sets preserved: {result['incomplete_preserved']}", flush=True)

    if backup_mode == "one_time":
        settings["one_time_completed_at"] = __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds")
        settings["one_time_timestamp"] = timestamp
        write_settings(settings_path, settings)
        print("[HDED] One-time backup marked as completed; future automatic or manual reruns are blocked.", flush=True)

    print("[HDED] Backup workflow completed successfully", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: Bench backup failed with exit code {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode or 1)
    except Exception as exc:
        print(f"ERROR: HDED backup post-processing failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
