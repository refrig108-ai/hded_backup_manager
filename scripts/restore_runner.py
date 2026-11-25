#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
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


def restore_database_dump(site: str, dump_file: Path) -> None:
    """Replace all site tables/views before importing a full SQL dump."""
    import frappe

    frappe.init(site=site, sites_path=str(BENCH_DIR / "sites"))
    try:
        frappe.connect()
        rows = frappe.db.sql("SHOW FULL TABLES")
        objects = []
        for row in rows:
            if len(row) < 2:
                continue
            name = str(row[0]).replace("`", "``")
            kind = str(row[1]).upper()
            objects.append((name, kind))

        # Drop views first because they can depend on base tables.
        for name, kind in objects:
            if "VIEW" in kind:
                frappe.db.sql(f"DROP VIEW IF EXISTS `{name}`")

        frappe.db.sql("SET FOREIGN_KEY_CHECKS=0")
        try:
            for name, kind in objects:
                if "VIEW" not in kind:
                    frappe.db.sql(f"DROP TABLE IF EXISTS `{name}`")
        finally:
            frappe.db.sql("SET FOREIGN_KEY_CHECKS=1")

        from frappe.database.db_manager import DbManager

        DbManager.restore_database(
            verbose=True,
            target=frappe.conf.db_name,
            source=str(dump_file),
            user=frappe.conf.db_user,
            password=frappe.conf.db_password,
        )
    finally:
        frappe.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely restore an HDED database-only backup")
    parser.add_argument("--site", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--backup-file")
    source.add_argument("--drive-file-id")
    parser.add_argument("--status-file", required=True)
    args = parser.parse_args()

    # Resolve a possibly relative status path before changing the working
    # directory; the API may pass it relative to the bench root.
    status_path = Path(args.status_file)
    if not status_path.is_absolute():
        status_path = (Path.cwd() / status_path).resolve()
    args.status_file = str(status_path)

    # Frappe's file logger resolves "../logs" and "<site>/logs" relative
    # to the process working directory. Its expected working directory is
    # the bench "sites" directory, not the bench root.
    sites_dir = BENCH_DIR / "sites"
    if not sites_dir.is_dir():
        raise RuntimeError(f"Bench sites directory does not exist: {sites_dir}")
    os.chdir(sites_dir)
    (BENCH_DIR / "logs").mkdir(parents=True, exist_ok=True)

    site = args.site
    site_path = BENCH_DIR / "sites" / site
    if not site_path.is_dir():
        write_status(Path(args.status_file), "failed", "لم يتم العثور على مجلد الموقع المطلوب.")
        return 2
    (site_path / "logs").mkdir(parents=True, exist_ok=True)
    backup_file: Path
    staged_drive_file = False
    if args.drive_file_id:
        try:
            import frappe

            frappe.init(site=site, sites_path=str(BENCH_DIR / "sites"))
            try:
                from hded_backup_manager.google_drive import download_drive_backup, list_drive_backups

                remote = next(
                    (item for item in list_drive_backups() if item.get("file_id") == args.drive_file_id),
                    None,
                )
                if not remote:
                    raise RuntimeError("الملف غير موجود داخل مجلد HDED المصرح به في Google Drive.")
                drive_name = str(remote.get("name") or "")
                if not re.fullmatch(r"\d{8}_\d{6}-[A-Za-z0-9_]+-database\.sql\.gz", drive_name):
                    raise RuntimeError("اسم ملف النسخة السحابية غير صالح.")
                staging_dir = site_path / "private" / "drive_restore_staging"
                staging_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
                if staging_dir.is_symlink() or staging_dir.resolve(strict=True) != staging_dir:
                    raise RuntimeError("مجلد الاستعادة المؤقت من Google Drive غير آمن.")
                os.chmod(staging_dir, 0o700)
                backup_file = staging_dir / drive_name
                write_status(
                    Path(args.status_file),
                    "running",
                    "جارٍ تنزيل نسخة قاعدة البيانات من Google Drive والتحقق من بصمتها.",
                    source=drive_name,
                    source_type="google_drive",
                )
                download_drive_backup(args.drive_file_id, backup_file)
                staged_drive_file = True
            finally:
                frappe.destroy()
        except Exception as exc:
            write_status(Path(args.status_file), "failed", f"تعذر تنزيل نسخة Google Drive: {str(exc)[:400]}")
            return 2
    else:
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

    import frappe
    frappe.init(site=site, sites_path=str(BENCH_DIR / "sites"))
    try:
        from frappe.installer import is_downgrade, is_partial, validate_database_sql
        if is_partial(str(backup_file)):
            raise RuntimeError("Partial database backups cannot restore a full site.")
        if is_downgrade(str(backup_file), verbose=True):
            raise RuntimeError("Backup is from a newer Frappe version; restore was stopped.")
        validate_database_sql(str(backup_file), _raise=True)
    finally:
        frappe.destroy()

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

        restore_database_dump(site, backup_file)
        restored = True

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
        if staged_drive_file:
            backup_file.unlink(missing_ok=True)
        return 0

    except Exception as exc:
        error = str(exc)[:500]
        if safety_file and safety_file.is_file():
            try:
                write_status(status_file, "running", "فشلت الاستعادة الأساسية. جارٍ إرجاع قاعدة البيانات من نسخة الأمان.")
                restore_database_dump(site, safety_file)
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
