from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

CORE_BACKUP_SUFFIXES = (
    "database.sql.gz",
    "files.tar",
    "private-files.tar",
    "site_config_backup.json",
)
APP_ARCHIVE_SUFFIX = "apps.tar.gz"
TIMESTAMP_RE = re.compile(r"^(\d{8}_\d{6})-(.+?)-(database\.sql\.gz|files\.tar|private-files\.tar|site_config_backup\.json|apps\.tar\.gz)$")
APP_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
DEFAULT_SETTINGS: dict[str, Any] = {
    "version": 3,
    "backup_mode": "scheduled",
    "one_time_completed_at": None,
    "one_time_timestamp": None,
    "schedule_enabled": True,
    "schedule": {
        "daily": {"enabled": True, "time": "02:00"},
        "weekly": {"enabled": False, "weekday": "Sun", "time": "02:00"},
        "monthly": {"enabled": False, "day": 1, "time": "02:00"},
    },
    "retention": {"auto_apply": False, "daily": 7, "weekly": 4, "monthly": 12},
    "storage": {"local_path": "", "require_mount": False, "previous_paths": []},
    "apps": {
        "archive_enabled": True,
        "auto_include_new_apps": True,
        "selected_apps": [],
        "excluded_apps": ["frappe", "erpnext"],
    },
}

_EXCLUDED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".cache", ".next", "coverage",
}
_EXCLUDED_FILES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "id_rsa", "id_ed25519", "credentials.json", "token.json",
    "service-account.json",
}
_EXCLUDED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".env"}


def read_settings(path: Path) -> dict[str, Any]:
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for key in ("schedule", "retention", "storage", "apps"):
                if isinstance(raw.get(key), dict):
                    settings[key].update(raw[key])
            if "schedule_enabled" in raw:
                settings["schedule_enabled"] = bool(raw["schedule_enabled"])
            if raw.get("backup_mode") in {"scheduled", "one_time"}:
                settings["backup_mode"] = raw["backup_mode"]
            for key in ("one_time_completed_at", "one_time_timestamp"):
                if key in raw:
                    settings[key] = raw[key]
            if "version" in raw:
                settings["version"] = raw["version"]
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError):
        raise RuntimeError(f"Invalid backup manager settings file: {path}")
    return settings



def write_settings(path: Path, settings: dict[str, Any]) -> None:
    """Atomically save private backup-manager settings with owner-only permissions."""
    path = Path(path)
    if path.is_symlink() or path.resolve().parent != path.parent.resolve(strict=True):
        raise RuntimeError(f"Unsafe backup manager settings path: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=".hded-backup-settings-", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(settings, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
        os.chmod(path, 0o600)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _filesystem_type(path: Path) -> str:
    """Return the filesystem type that backs path, if findmnt is available."""
    try:
        result = subprocess.run(
            ["findmnt", "-n", "-o", "FSTYPE", "-T", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
        )
        return result.stdout.strip().lower()
    except (OSError, subprocess.SubprocessError):
        return ""


def _mount_target(path: Path) -> str:
    """Return the most specific mount target containing path."""
    try:
        result = subprocess.run(
            ["findmnt", "-n", "-o", "TARGET", "-T", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
        )
        target = result.stdout.strip()
        return target or "/"
    except (OSError, subprocess.SubprocessError):
        return "/"


def backup_directory_details(path: Path) -> dict[str, Any]:
    path = Path(path).resolve(strict=True)
    root_device = os.stat("/").st_dev
    path_device = os.stat(path).st_dev
    mount_target = _mount_target(path)
    filesystem_type = _filesystem_type(path)
    return {
        "path": str(path),
        "free_bytes": shutil.disk_usage(path).free,
        "mount_target": mount_target,
        "filesystem_type": filesystem_type,
        "is_separate_mount": (path_device != root_device and mount_target != "/") or filesystem_type == "vboxsf",
    }


def prepare_backup_directory(
    site_path: Path,
    bench_dir: Path,
    local_path: str | None = "",
    require_mount: bool = False,
    create: bool = True,
) -> Path:
    """
    Validate and prepare the directory used for complete Bench backups.
    An empty local_path preserves the historical <site>/private/backups location.
    Custom paths must be absolute and must not overlap the Bench directory.
    """
    site_path = Path(site_path).resolve(strict=True)
    bench_dir = Path(bench_dir).resolve(strict=True)
    default_path = site_path / "private" / "backups"
    raw = str(local_path or "").strip()
    is_default = not raw
    if raw:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise ValueError("اكتب مساراً مطلقاً يبدأ بعلامة /")
        candidate = Path(os.path.normpath(str(candidate)))
        if candidate == default_path:
            is_default = True
    else:
        candidate = default_path

    if candidate == Path("/"):
        raise ValueError("لا يمكن اختيار جذر النظام كمجلد للنسخ")
    if not is_default:
        home = Path.home().resolve()
        protected_targets = {
            Path("/"), Path("/home"), Path("/root"), Path("/mnt"), Path("/media"),
            Path("/var"), Path("/var/lib"), Path("/var/log"), Path("/var/cache"),
            Path("/var/tmp"), Path("/tmp"), Path("/run"), Path("/dev"), Path("/proc"),
            Path("/sys"), Path("/srv"), Path("/opt"), Path("/etc"), Path("/usr"),
            Path("/boot"), Path("/bin"), Path("/sbin"), Path("/lib"), Path("/lib64"),
        }
        if candidate in protected_targets:
            raise ValueError("لا تختر مجلد نظام أو جذر قرص؛ أنشئ مجلداً فرعياً مخصصاً للنسخ")
        if candidate == home or candidate in bench_dir.parents or bench_dir in candidate.parents:
            raise ValueError("اختر مجلداً مخصصاً خارج مجلد Bench ومجلد المنزل نفسه")

    # Refuse symlinks in the selected path or any existing parent.
    for component in (candidate, *candidate.parents):
        if component.is_symlink():
            raise ValueError(f"المسار يحتوي على رابط رمزي غير مسموح: {component}")

    existing = candidate
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if not existing.is_dir() or existing.is_symlink():
        raise ValueError("المجلد الأب للمسار المحدد غير صالح")
    if candidate.exists() and os.path.ismount(candidate) and _filesystem_type(candidate) != "vboxsf":
        raise ValueError("هذا هو جذر القرص المركّب. اختر مجلداً فرعياً داخله مثل /mnt/backup/hded")

    if require_mount:
        details = backup_directory_details(existing)
        if not details["is_separate_mount"]:
            raise ValueError(
                "تم اشتراط قرص منفصل، لكن المسار لا يقع حالياً على وحدة تخزين مركّبة منفصلة. "
                "تحقق من توصيل القرص وتركيبه ثم أعد الفحص."
            )

    if not candidate.exists():
        if not create:
            raise ValueError("مجلد النسخ المحدد غير موجود")
        candidate.mkdir(parents=True, mode=0o700, exist_ok=True)

    if candidate.is_symlink() or not candidate.is_dir():
        raise ValueError("مسار النسخ ليس مجلداً صالحاً")
    resolved = candidate.resolve(strict=True)
    if resolved != candidate:
        raise ValueError("لا يُسمح باستخدام مسار يحتوي على روابط رمزية")

    if not is_default:
        if resolved in bench_dir.parents or bench_dir in resolved.parents:
            raise ValueError("يجب أن يكون مجلد النسخ خارج مجلد Bench بالكامل")

    # Backups contain database and private files. Normal Linux folders are
    # made owner-only. VirtualBox vboxsf shares inherit access from mount
    # options and the vboxsf group, so do not chmod the host folder from the guest.
    filesystem_type = _filesystem_type(resolved)
    current_mode = os.stat(resolved).st_mode & 0o777
    if filesystem_type == "vboxsf":
        if current_mode & 0o007:
            raise ValueError(
                "مشاركة Windows تسمح بالوصول للمستخدمين الآخرين. "
                "أعد تركيبها بخيارات صلاحيات تمنع صلاحيات Other، ثم أعد الفحص."
            )
    else:
        try:
            os.chmod(resolved, 0o700)
        except OSError as exc:
            raise ValueError(f"تعذر تأمين صلاحيات مجلد النسخ (700): {exc}") from exc
        if (os.stat(resolved).st_mode & 0o077) != 0:
            raise ValueError("مجلد النسخ يجب ألا يكون متاحاً للمجموعة أو المستخدمين الآخرين")

    if not os.access(resolved, os.W_OK | os.X_OK):
        raise ValueError("المستخدم الذي يشغّل ERPNext لا يملك صلاحية الكتابة إلى هذا المجلد")

    fd, test_name = tempfile.mkstemp(prefix=".hded-backup-write-test-", dir=resolved)
    try:
        os.write(fd, b"HDED Backup Manager write test")
        os.fsync(fd)
    finally:
        os.close(fd)
        Path(test_name).unlink(missing_ok=True)

    return resolved


def discover_apps(bench_dir: Path) -> list[dict[str, Any]]:
    apps_dir = bench_dir / "apps"
    installed_file = bench_dir / "sites" / "apps.txt"
    installed = set()
    try:
        installed = {line.strip() for line in installed_file.read_text(encoding="utf-8").splitlines() if line.strip()}
    except OSError:
        pass

    found: list[dict[str, Any]] = []
    if not apps_dir.is_dir():
        return found

    for folder in sorted(apps_dir.iterdir(), key=lambda p: p.name.lower()):
        if not folder.is_dir() or folder.is_symlink() or not APP_NAME_RE.fullmatch(folder.name):
            continue
        package_dir = folder / folder.name
        if not package_dir.is_dir() or package_dir.is_symlink() or not (package_dir / "hooks.py").is_file():
            continue
        found.append({"name": folder.name, "installed": folder.name in installed})
    return found


def selected_app_names(bench_dir: Path, settings: dict[str, Any]) -> list[str]:
    discovered = {item["name"] for item in discover_apps(bench_dir)}
    app_settings = settings.get("apps", {})
    if app_settings.get("auto_include_new_apps", True):
        excluded = set(app_settings.get("excluded_apps") or [])
        selected = discovered - excluded
    else:
        selected = discovered.intersection(set(app_settings.get("selected_apps") or []))
    # Keep the manager source itself in the archive whenever it exists, so the
    # tool required to manage restoration is not accidentally excluded.
    if "hded_backup_manager" in discovered:
        selected.add("hded_backup_manager")
    return sorted(selected)


def _safe_tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    parts = PurePosixPath(info.name).parts
    if info.issym() or info.islnk() or not (info.isfile() or info.isdir()):
        return None
    if any(part in _EXCLUDED_DIRS for part in parts):
        return None
    base = parts[-1].lower() if parts else ""
    if base in _EXCLUDED_FILES or base.startswith(".env"):
        return None
    if Path(base).suffix.lower() in _EXCLUDED_SUFFIXES:
        return None
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _git_metadata(app_dir: Path) -> dict[str, Any]:
    if not (app_dir / ".git").exists():
        return {"branch": None, "commit": None, "modified": None}

    def git(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(app_dir), *args],
                check=True, capture_output=True, text=True, timeout=5,
                env={"PATH": "/usr/bin:/bin", "GIT_OPTIONAL_LOCKS": "0"},
            )
            return result.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            return None

    branch = git("branch", "--show-current")
    commit = git("rev-parse", "HEAD")
    modified = None
    try:
        result = subprocess.run(
            ["git", "-C", str(app_dir), "diff", "--quiet"],
            timeout=5, env={"PATH": "/usr/bin:/bin", "GIT_OPTIONAL_LOCKS": "0"},
        )
        modified = result.returncode != 0
    except (OSError, subprocess.SubprocessError):
        pass
    return {"branch": branch, "commit": commit, "modified": modified}


def create_apps_archive(bench_dir: Path, backup_dir: Path, site: str, timestamp: str, settings: dict[str, Any]) -> Path | None:
    app_settings = settings.get("apps", {})
    if not app_settings.get("archive_enabled", True):
        return None

    app_names = selected_app_names(bench_dir, settings)
    if not app_names:
        raise RuntimeError("No application source directories were selected for archiving")

    apps_root = bench_dir / "apps"
    installed_file = bench_dir / "sites" / "apps.txt"
    try:
        installed_names = [line.strip() for line in installed_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        installed_names = []

    manifest = {
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "site": site,
        "timestamp": timestamp,
        "auto_include_new_apps": bool(app_settings.get("auto_include_new_apps", True)),
        "applications": [],
    }
    for name in app_names:
        app_dir = apps_root / name
        manifest["applications"].append({
            "name": name,
            "installed_in_bench": name in installed_names,
            **_git_metadata(app_dir),
        })

    site_prefix = site.replace(".", "_")
    final_path = backup_dir / f"{timestamp}-{site_prefix}-{APP_ARCHIVE_SUFFIX}"
    fd, temp_name = tempfile.mkstemp(prefix=f".{timestamp}-apps-", suffix=".tmp", dir=backup_dir)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with tarfile.open(temp_path, mode="w:gz", compresslevel=6) as archive:
            for name in app_names:
                app_dir = apps_root / name
                if app_dir.is_symlink() or not app_dir.is_dir():
                    raise RuntimeError(f"Application directory is no longer safe: {name}")
                archive.add(app_dir, arcname=f"apps/{name}", recursive=True, filter=_safe_tar_filter)

            metadata_items = {
                "backup-metadata/apps-manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                "backup-metadata/apps.txt": ("\n".join(installed_names) + "\n").encode("utf-8"),
            }
            for arcname, content in metadata_items.items():
                info = tarfile.TarInfo(arcname)
                info.size = len(content)
                info.mode = 0o600
                archive.addfile(info, fileobj=__import__("io").BytesIO(content))

        os.chmod(temp_path, 0o600)
        os.replace(temp_path, final_path)
        os.chmod(final_path, 0o600)
        return final_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def list_backup_sets(backup_dir: Path, site_prefix: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Path]] = {}
    escaped_prefix = re.escape(site_prefix)
    pattern = re.compile(
        rf"^(\d{{8}}_\d{{6}})-{escaped_prefix}-(database\.sql\.gz|files\.tar|private-files\.tar|site_config_backup\.json|apps\.tar\.gz)$"
    )
    for path in backup_dir.iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        match = pattern.fullmatch(path.name)
        if match:
            timestamp, suffix = match.groups()
            grouped.setdefault(timestamp, {})[suffix] = path

    result = []
    required = set(CORE_BACKUP_SUFFIXES)
    for timestamp, files in grouped.items():
        try:
            created = datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
        except ValueError:
            continue
        total_size = sum(path.stat().st_size for path in files.values())
        result.append({
            "timestamp": timestamp,
            "created": created.strftime("%Y-%m-%d %H:%M:%S"),
            "date": created.date(),
            "complete": required.issubset(files),
            "apps_available": APP_ARCHIVE_SUFFIX in files,
            "files": files,
            "total_size": total_size,
        })
    return sorted(result, key=lambda row: row["timestamp"], reverse=True)


def retention_plan(backup_dir: Path, site_prefix: str, retention: dict[str, Any]) -> dict[str, Any]:
    sets = [row for row in list_backup_sets(backup_dir, site_prefix) if row["complete"]]
    keep: set[str] = set()

    daily_limit = int(retention.get("daily", 7))
    weekly_limit = int(retention.get("weekly", 4))
    monthly_limit = int(retention.get("monthly", 12))

    by_day: dict[date, str] = {}
    by_week: dict[tuple[int, int], str] = {}
    by_month: dict[tuple[int, int], str] = {}
    for row in sets:  # Already newest first, so first value in each bucket is retained.
        day = row["date"]
        by_day.setdefault(day, row["timestamp"])
        iso = day.isocalendar()
        by_week.setdefault((iso.year, iso.week), row["timestamp"])
        by_month.setdefault((day.year, day.month), row["timestamp"])

    keep.update(list(by_day.values())[:daily_limit])
    keep.update(list(by_week.values())[:weekly_limit])
    keep.update(list(by_month.values())[:monthly_limit])
    if sets and not keep:
        keep.add(sets[0]["timestamp"])

    delete_rows = [row for row in sets if row["timestamp"] not in keep]
    # Incomplete sets are intentionally preserved and are never retention candidates.
    incomplete_count = sum(1 for row in list_backup_sets(backup_dir, site_prefix) if not row["complete"])

    return {
        "keep": sorted(keep, reverse=True),
        "delete": [
            {
                "timestamp": row["timestamp"],
                "created": row["created"],
                "size": row["total_size"],
                "files": [path.name for path in row["files"].values()],
            }
            for row in delete_rows
        ],
        "incomplete_preserved": incomplete_count,
        "complete_count": len(sets),
    }


def apply_retention(backup_dir: Path, site_prefix: str, retention: dict[str, Any]) -> dict[str, Any]:
    plan = retention_plan(backup_dir, site_prefix, retention)
    root = backup_dir.resolve(strict=True)
    deleted: list[str] = []

    for row in plan["delete"]:
        timestamp = row["timestamp"]
        pattern = re.compile(
            rf"^{re.escape(timestamp)}-{re.escape(site_prefix)}-(database\.sql\.gz|files\.tar|private-files\.tar|site_config_backup\.json|apps\.tar\.gz)$"
        )
        candidates = [path for path in backup_dir.iterdir() if pattern.fullmatch(path.name)]
        # Refuse the whole set if any candidate is a symlink or resolves outside the backup directory.
        if any(path.is_symlink() or not path.is_file() or path.resolve(strict=True).parent != root for path in candidates):
            continue
        # Delete only complete sets; the plan contains only complete sets.
        for path in candidates:
            path.unlink()
            deleted.append(path.name)

    return {**plan, "deleted_files": deleted, "deleted_count": len(deleted)}
