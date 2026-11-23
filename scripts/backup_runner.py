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

    command = [str(bench), "--site", args.site, "backup", "--with-files"]
    print("[HDED] Starting official Bench backup", flush=True)
    subprocess.run(command, cwd=BENCH_DIR, check=True)

    site_path = BENCH_DIR / "sites" / args.site
    private_dir = site_path / "private"
    backup_dir = private_dir / "backups"
    settings_path = private_dir / "hded_backup_manager_settings.json"
    if backup_dir.is_symlink() or not backup_dir.is_dir():
        print("ERROR: Backup directory is missing or is a symbolic link", file=sys.stderr)
        return 4
    if backup_dir.resolve(strict=True).parent != private_dir.resolve(strict=True):
        print("ERROR: Backup directory resolves outside the site's private directory", file=sys.stderr)
        return 4
    settings = read_settings(settings_path)

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
