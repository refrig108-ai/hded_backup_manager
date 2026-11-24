#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
BENCH_DIR = Path(__file__).resolve().parents[3]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def write_status(path: Path, status: str, message: str, **extra) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "message": message,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        **extra,
    }
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)
    os.chmod(path, 0o600)


def run(command: list[str], timeout: int = 3600) -> None:
    subprocess.run(command, cwd=BENCH_DIR, check=True, timeout=timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely restore an HDED database-only backup")
    parser.add_argument("--site", required=True)
    parser.add_argument("--backup-file", required=True)
    parser.add_argument("--status-file", required=True)
    args = parser.parse_args()

    site = args.site
    site_path = BENCH_DIR / "sites" / site
    backup_file = Path(args.backup_file)
    status_file = Path(args.status_file)
    bench = Path.home() / ".local" / "bin" / "bench"
    if not bench.is_file():
        bench = BENCH_DIR / "env" / "bin" / "bench"
    if not bench.is_file() or not site_path.is_dir():
        write_status(status_file, "failed", "لم يتم العثور على Bench أو الموقع المطلوب.")
        return 2

    expected_prefix = site.replace(".", "_")
    if (
        backup_file.is_symlink()
        or not backup_file.is_file()
        or backup_file.name != f"{backup_file.name.split('-', 1)[0]}-{expected_prefix}-database.sql.gz"
        or backup_file.parent.resolve() != backup_file.parent
    ):
        write_status(status_file, "failed", "ملف النسخة أو مساره غير صالح.")
        return 2

    try:
        with gzip.open(backup_file, "rb") as stream:
            while stream.read(1024 * 1024):
                pass
    except Exception as exc:
        write_status(status_file, "failed", f"ملف النسخة المضغوط تالف: {str(exc)[:200]}")
        return 2

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safety_dir = site_path / "private" / "restore_safety" / timestamp
    safety_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(safety_dir, 0o700)
    maintenance_enabled = False
    safety_file: Path | None = None
    restored = False

    try:
        write_status(status_file, "running", "تفعيل وضع الصيانة وإنشاء نسخة أمان من قاعدة البيانات الحالية.")
        run([str(bench), "--site", site, "set-maintenance-mode", "on"], timeout=120)
        maintenance_enabled = True

        with tempfile.TemporaryDirectory(prefix="hded-restore-config-") as conf_dir:
            conf_path = Path(conf_dir) / "site_config_backup.json"
            run([
                str(bench), "--site", site, "backup",
                "--backup-path", str(safety_dir),
                "--backup-path-conf", str(conf_path),
            ], timeout=2700)

        safety_files = sorted(
            safety_dir.glob(f"*-{expected_prefix}-database.sql.gz"),
            key=lambda item: item.stat().st_mtime_ns,
        )
        if not safety_files:
            raise RuntimeError("لم يتم إنشاء نسخة أمان من قاعدة البيانات الحالية.")
        safety_file = safety_files[-1]
        os.chmod(safety_file, 0o600)

        write_status(
            status_file, "running",
            "اكتملت نسخة الأمان. جارٍ استعادة قاعدة البيانات المختارة.",
            safety_backup=str(safety_file),
        )

        import frappe
        frappe.init(site=site, sites_path=str(BENCH_DIR / "sites"))
        frappe.connect()
        try:
            from frappe.database.db_manager import DbManager
            DbManager.restore_database(
                verbose=True,
                target=frappe.conf.db_name,
                source=str(backup_file),
                user=frappe.conf.db_user,
                password=frappe.conf.db_password,
            )
            restored = True
        finally:
            frappe.destroy()

        run([str(bench), "--site", site, "clear-cache"], timeout=180)
        run([str(bench), "--site", site, "clear-website-cache"], timeout=180)
        run([str(bench), "--site", site, "set-maintenance-mode", "off"], timeout=120)
        maintenance_enabled = False
        write_status(
            status_file, "success",
            "اكتملت استعادة قاعدة البيانات بنجاح. تم الاحتفاظ بنسخة الأمان السابقة.",
            safety_backup=str(safety_file),
            restored_from=str(backup_file),
        )
        return 0

    except Exception as exc:
        error = str(exc)[:500]
        if safety_file and safety_file.is_file():
            try:
                write_status(status_file, "running", "فشلت الاستعادة الأساسية. جارٍ إرجاع قاعدة البيانات من نسخة الأمان.")
                import frappe
                frappe.init(site=site, sites_path=str(BENCH_DIR / "sites"))
                frappe.connect()
                try:
                    from frappe.database.db_manager import DbManager
                    DbManager.restore_database(
                        verbose=True,
                        target=frappe.conf.db_name,
                        source=str(safety_file),
                        user=frappe.conf.db_user,
                        password=frappe.conf.db_password,
                    )
                finally:
                    frappe.destroy()
                run([str(bench), "--site", site, "clear-cache"], timeout=180)
                if maintenance_enabled:
                    run([str(bench), "--site", site, "set-maintenance-mode", "off"], timeout=120)
                    maintenance_enabled = False
                write_status(
                    status_file, "failed",
                    f"فشلت الاستعادة المطلوبة، لكن تمت إعادة قاعدة البيانات السابقة بنجاح. التفاصيل: {error}",
                    safety_backup=str(safety_file),
                )
                return 1
            except Exception as rollback_error:
                write_status(
                    status_file, "critical",
                    "فشلت الاستعادة وفشل الرجوع التلقائي. بقي وضع الصيانة مفعلاً لحماية الموقع. "
                    f"خطأ الاستعادة: {error} — خطأ الرجوع: {str(rollback_error)[:300]}",
                    safety_backup=str(safety_file),
                )
                return 3

        if maintenance_enabled:
            try:
                run([str(bench), "--site", site, "set-maintenance-mode", "off"], timeout=120)
            except Exception:
                pass
        write_status(status_file, "failed", f"لم تتم الاستعادة: {error}")
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Restore runner fatal error: {exc}", file=sys.stderr)
        raise SystemExit(1)
