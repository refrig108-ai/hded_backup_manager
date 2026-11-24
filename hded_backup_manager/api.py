from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

import frappe
from frappe import _

from hded_backup_manager.backup_engine import (
    CORE_BACKUP_SUFFIXES,
    APP_ARCHIVE_SUFFIX,
    apply_retention,
    discover_apps,
    list_backup_sets,
    read_settings,
    retention_plan,
    prepare_backup_directory,
    backup_directory_details,
)

CONTROL_BIN = "/usr/local/sbin/hded-backup-control"
BACKUP_SUFFIXES = {
    "database": "database.sql.gz",
    "public": "files.tar",
    "private": "private-files.tar",
    "config": "site_config_backup.json",
    "apps": APP_ARCHIVE_SUFFIX,
}
TIMESTAMP_RE = re.compile(r"^\d{8}_\d{6}$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
WEEKDAYS = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


def _require_manager():
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("غير مصرح لك باستخدام مدير النسخ الاحتياطي"), frappe.PermissionError)


def _bench_dir() -> Path:
    # frappe.get_app_path("frappe") points to <bench>/apps/frappe/frappe.
    return Path(frappe.get_app_path("frappe")).resolve().parents[2]


def _backup_dir(settings: dict | None = None) -> Path:
    settings = settings if settings is not None else _get_settings()
    storage = settings.get("storage", {})
    try:
        return prepare_backup_directory(
            site_path=Path(frappe.get_site_path()),
            bench_dir=_bench_dir(),
            local_path=storage.get("local_path", ""),
            require_mount=bool(storage.get("require_mount", False)),
            create=True,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        frappe.throw(_("تعذر الوصول إلى مجلد النسخ الاحتياطي: {0}").format(str(exc)[:300]))


def _backup_dirs(
    settings: dict | None = None,
    allow_unavailable_active: bool = False,
) -> dict[str, Path | None]:
    settings = settings if settings is not None else _get_settings()
    result: dict[str, Path | None] = {}
    try:
        result["active"] = _backup_dir(settings)
    except Exception:
        if not allow_unavailable_active:
            raise
        result["active"] = None

    storage = settings.get("storage", {})
    previous_paths = storage.get("previous_paths") or []
    if not isinstance(previous_paths, list):
        previous_paths = []
    default_path = Path(frappe.get_site_path("private", "backups"))
    if default_path.exists() and not default_path.is_symlink():
        previous_paths = [*previous_paths, str(default_path)]

    active_value = str(storage.get("local_path") or "").strip()
    active_raw = Path(active_value).expanduser() if active_value else default_path
    active_raw = Path(os.path.normpath(str(active_raw)))
    seen: set[str] = set()
    index = 0
    for raw in previous_paths:
        if not isinstance(raw, str) or not raw.strip():
            continue
        candidate = Path(os.path.normpath(str(Path(raw).expanduser())))
        if not candidate.is_absolute() or candidate == active_raw or not candidate.exists():
            continue
        if any(component.is_symlink() for component in (candidate, *candidate.parents)):
            continue
        try:
            resolved = candidate.resolve(strict=True)
            if resolved != candidate or not resolved.is_dir():
                continue
            if resolved != default_path and (resolved in _bench_dir().parents or _bench_dir() in resolved.parents):
                continue
        except OSError:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        index += 1
        result[f"previous_{index}"] = resolved
    return result


def _settings_path() -> Path:
    private_root = Path(frappe.get_site_path("private")).resolve(strict=True)
    path = private_root / "hded_backup_manager_settings.json"
    if path.is_symlink() or path.resolve().parent != private_root:
        frappe.throw(_("ملف إعدادات مدير النسخ الاحتياطي غير صالح"))
    return path


def _get_settings() -> dict:
    try:
        return read_settings(_settings_path())
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        frappe.log_error(title="HDED Backup Manager Settings", message=str(exc))
        frappe.throw(_("تعذر قراءة إعدادات مدير النسخ الاحتياطي"))


def _save_settings(settings: dict) -> None:
    path = _settings_path()
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
    except OSError as exc:
        temp.unlink(missing_ok=True)
        frappe.throw(_("تعذر حفظ إعدادات النسخ الاحتياطي: {0}").format(str(exc)[:200]))


def _site_prefix() -> str:
    return frappe.local.site.replace(".", "_")


def _expected_files(timestamp: str, storage: str = "active") -> dict[str, Path]:
    if not TIMESTAMP_RE.fullmatch(timestamp or ""):
        frappe.throw(_("معرّف النسخة الاحتياطية غير صالح"))
    folders = _backup_dirs(allow_unavailable_active=(storage != "active"))
    if storage not in folders or folders[storage] is None:
        frappe.throw(_("مجلد تخزين النسخة غير معروف أو غير متاح حالياً"))
    folder = folders[storage]
    prefix = f"{timestamp}-{_site_prefix()}"
    return {kind: folder / f"{prefix}-{suffix}" for kind, suffix in BACKUP_SUFFIXES.items()}


def _run_control(*args: str, timeout: int = 25) -> str:
    if not Path(CONTROL_BIN).is_file():
        frappe.throw(_("برنامج التحكم غير مثبت. أعد تشغيل ملف تحديث التطبيق."))
    try:
        proc = subprocess.run(
            ["sudo", "-n", CONTROL_BIN, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
        )
    except subprocess.TimeoutExpired:
        frappe.throw(_("انتهت مهلة الاتصال بخدمة النسخ الاحتياطي"))
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        frappe.throw(_("تعذر تنفيذ أمر النسخ الاحتياطي: {0}").format(detail[:500] or proc.returncode))
    return (proc.stdout or "").strip()


def _system_status() -> dict:
    output = _run_control("status")
    values = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return {
        "timer_active": values.get("TIMER_ACTIVE", "unknown") == "active",
        "service_active": values.get("SERVICE_ACTIVE", "unknown") in ("active", "activating"),
        "service_result": values.get("SERVICE_RESULT", "unknown"),
        "next_run": values.get("NEXT_RUN", "غير متاح"),
        "last_trigger": values.get("LAST_TRIGGER", "غير متاح"),
    }


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"



_STORAGE_HIDDEN_ROOTS = {
    "/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc",
    "/root", "/run", "/sbin", "/sys", "/tmp", "/usr", "/var", "/opt",
}


def _mounted_storage_locations() -> list[dict]:
    """List mounted local block-device filesystems for the server-side folder picker."""
    command = [
        "lsblk", "--json", "--paths",
        "--output", "NAME,TYPE,TRAN,RM,SIZE,FSTYPE,LABEL,MOUNTPOINTS",
    ]
    try:
        proc = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=10,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
        )
        payload = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        frappe.throw(_("تعذر قراءة وحدات التخزين المركّبة على الخادم: {0}").format(str(exc)[:250]))

    root_device = os.stat("/").st_dev
    seen: set[str] = set()
    locations: list[dict] = []

    def visit(node: dict) -> None:
        mountpoints = node.get("mountpoints")
        if not isinstance(mountpoints, list):
            mountpoint = node.get("mountpoint")
            mountpoints = [mountpoint] if mountpoint else []

        for raw_mount in mountpoints:
            if not isinstance(raw_mount, str) or not raw_mount.startswith("/"):
                continue
            candidate = Path(os.path.normpath(raw_mount))
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            is_run_media_mount = Path("/run/media") == candidate or Path("/run/media") in candidate.parents
            if candidate != Path("/"):
                if not is_run_media_mount and any(candidate == Path(root) or Path(root) in candidate.parents for root in _STORAGE_HIDDEN_ROOTS):
                    continue
            try:
                resolved = candidate.resolve(strict=True)
                if resolved != candidate or not resolved.is_dir():
                    continue
                key = str(resolved)
                if key in seen:
                    continue
                stat_result = os.stat(resolved)
                free_bytes = shutil.disk_usage(resolved).free
            except OSError:
                continue

            seen.add(key)
            transport = str(node.get("tran") or "").lower()
            removable_raw = node.get("rm")
            removable = removable_raw is True or str(removable_raw).lower() in {"1", "true", "yes"}
            is_external = transport == "usb" or removable or is_run_media_mount
            if resolved == Path("/"):
                kind_label = "قرص النظام"
            elif is_external:
                kind_label = "قرص خارجي"
            else:
                kind_label = "قرص داخلي أو وحدة تخزين"

            label = str(node.get("label") or node.get("name") or resolved.name or "وحدة تخزين")
            locations.append({
                "path": str(resolved),
                "label": label,
                "kind_label": kind_label,
                "device": str(node.get("path") or node.get("name") or ""),
                "transport": transport or "غير محدد",
                "removable": removable,
                "size": str(node.get("size") or "غير معروف"),
                "filesystem": str(node.get("fstype") or "غير معروف"),
                "free_bytes": free_bytes,
                "is_separate_mount": stat_result.st_dev != root_device,
            })

        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child)

    for device in payload.get("blockdevices") or []:
        if isinstance(device, dict):
            visit(device)

    # VirtualBox shared folders expose Windows host directories through the
    # vboxsf filesystem. They are not block devices, so lsblk cannot list them.
    try:
        shared_proc = subprocess.run(
            ["findmnt", "--json", "--types", "vboxsf", "--output", "SOURCE,TARGET,FSTYPE,OPTIONS"],
            check=False, capture_output=True, text=True, timeout=8,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
        )
        if shared_proc.returncode == 0 and shared_proc.stdout.strip():
            shared_payload = json.loads(shared_proc.stdout)
            for shared in shared_payload.get("filesystems") or []:
                raw_target = shared.get("target")
                if not isinstance(raw_target, str) or not raw_target.startswith("/"):
                    continue
                target = Path(os.path.normpath(raw_target))
                # A VirtualBox host share is expected below /media/sf_* or a
                # user-selected mount point. It is deliberately exempt from
                # the general /media and /mnt system-folder exclusions.
                if target.is_symlink() or not target.is_dir():
                    continue
                try:
                    resolved = target.resolve(strict=True)
                    if resolved != target or not resolved.is_dir():
                        continue
                    key = str(resolved)
                    if key in seen:
                        continue
                    free_bytes = shutil.disk_usage(resolved).free
                    stat_result = os.stat(resolved)
                except OSError:
                    continue

                seen.add(key)
                source = str(shared.get("source") or "VirtualBox Shared Folder")
                share_name = source.rsplit("[", 1)[0].strip() or source
                options = str(shared.get("options") or "")
                read_only = "ro" in {part.strip() for part in options.split(",")}
                locations.append({
                    "path": str(resolved),
                    "label": share_name,
                    "kind_label": "مجلد Windows مشترك عبر VirtualBox",
                    "device": source,
                    "transport": "virtualbox",
                    "removable": False,
                    "size": "مجلد مشترك",
                    "filesystem": "vboxsf",
                    "free_bytes": free_bytes,
                    "is_separate_mount": True,
                    "read_only": read_only,
                })
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        # A guest without VirtualBox Guest Additions simply has no vboxsf entry.
        pass

    return sorted(locations, key=lambda item: (item["path"] != "/", item["path"].casefold()))


@frappe.whitelist()
def get_storage_locations():
    """Return mounted internal/external volumes visible to the ERPNext server."""
    _require_manager()
    locations = _mounted_storage_locations()
    return {"locations": locations}


@frappe.whitelist()
def browse_storage_directory(mount_path: str, path: str | None = None):
    """List safe child directories strictly within one currently mounted volume."""
    _require_manager()
    locations = _mounted_storage_locations()
    mount = next((item for item in locations if item["path"] == str(mount_path or "")), None)
    if not mount:
        frappe.throw(_("وحدة التخزين المحددة لم تعد متاحة أو لم تعد مركّبة"))

    root = Path(mount["path"])
    requested_raw = str(path or mount["path"]).strip()
    requested = Path(os.path.normpath(requested_raw))
    if not requested.is_absolute():
        frappe.throw(_("مسار المجلد غير صالح"))

    try:
        # Reject symlinks in the requested path before resolving it.
        for component in (requested, *requested.parents):
            if component.is_symlink():
                frappe.throw(_("لا يمكن استعراض مسار يحتوي على رابط رمزي"))
            if component == root:
                break
        current = requested.resolve(strict=True)
        resolved_root = root.resolve(strict=True)
        if current != resolved_root and resolved_root not in current.parents:
            frappe.throw(_("لا يمكن الخروج من وحدة التخزين المحددة"))
        if not current.is_dir():
            frappe.throw(_("المسار المحدد ليس مجلداً"))
        root_device = os.stat(resolved_root).st_dev
        is_virtualbox_share = mount.get("filesystem") == "vboxsf"
        if not is_virtualbox_share and os.stat(current).st_dev != root_device:
            frappe.throw(_("لا يمكن الانتقال عبر وحدة تخزين أخرى من داخل هذا المسار"))
        free_bytes = shutil.disk_usage(current).free
    except FileNotFoundError:
        frappe.throw(_("المجلد غير موجود حالياً"))
    except PermissionError:
        frappe.throw(_("لا توجد صلاحية لاستعراض هذا المجلد"))
    except OSError as exc:
        frappe.throw(_("تعذر استعراض المجلد: {0}").format(str(exc)[:200]))

    directories = []
    try:
        children = sorted(current.iterdir(), key=lambda item: item.name.casefold())
        for child in children:
            if child.is_symlink() or not child.is_dir():
                continue
            if current == Path("/"):
                if child.name in {root_name.lstrip("/") for root_name in _STORAGE_HIDDEN_ROOTS}:
                    continue
            if not is_virtualbox_share:
                try:
                    if os.stat(child).st_dev != root_device:
                        continue
                except OSError:
                    continue
            directories.append({"name": child.name, "path": str(child)})
            if len(directories) >= 200:
                break
    except PermissionError:
        frappe.throw(_("لا توجد صلاحية لقراءة محتويات هذا المجلد"))

    parent = str(current.parent) if current != resolved_root and resolved_root in current.parents else None
    if current == Path("/"):
        parent = None
    bench_dir = _bench_dir()
    default_backup = Path(frappe.get_site_path("private", "backups")).resolve(strict=False)
    protected_exact = {
        Path("/"), Path("/home"), Path("/mnt"), Path("/media"),
        Path("/var"), Path("/var/lib"), Path("/var/log"), Path("/var/cache"),
        Path("/tmp"), Path("/run"), Path("/dev"), Path("/proc"), Path("/sys"),
        Path("/etc"), Path("/usr"), Path("/opt"), Path("/boot"), Path("/root"),
    }
    overlaps_bench = (current in bench_dir.parents or bench_dir in current.parents) and current != default_backup
    can_write = os.access(current, os.W_OK | os.X_OK)
    can_select = (
        current != Path("/")
        and current not in protected_exact
        and current != Path.home().resolve()
        and (is_virtualbox_share or not os.path.ismount(current))
        and not overlaps_bench
        and can_write
        and not bool(mount.get("read_only", False))
    )
    return {
        "mount_path": str(resolved_root),
        "mount_label": mount["label"],
        "mount_kind": mount["kind_label"],
        "mount_filesystem": mount.get("filesystem"),
        "mount_read_only": bool(mount.get("read_only", False)),
        "current_path": str(current),
        "parent_path": parent,
        "can_select": can_select,
        "free_bytes": free_bytes,
        "directories": directories,
    }


def _apps_for_ui(settings: dict) -> list[dict]:
    app_settings = settings.get("apps", {})
    known = discover_apps(_bench_dir())
    excluded = set(app_settings.get("excluded_apps") or [])
    selected = set(app_settings.get("selected_apps") or [])
    output = []
    for app in known:
        name = app["name"]
        is_selected = name not in excluded if app_settings.get("auto_include_new_apps", True) else name in selected
        output.append({**app, "selected": is_selected})
    return output


def _email_connections_for_ui() -> dict[str, dict | None]:
    """Return non-secret metadata for active outgoing Email Account records."""
    result: dict[str, dict | None] = {"gmail": None, "outlook": None, "yahoo": None}
    try:
        rows = frappe.get_all(
            "Email Account",
            filters={"enable_outgoing": 1},
            fields=["name", "email_id", "service"],
            order_by="modified desc",
            limit_page_length=100,
        )
    except Exception:
        # Email status is a convenience for this dashboard; it must not make
        # backup status unavailable if an Email Account schema is customized.
        frappe.log_error(title="HDED Backup Manager Email Status", message=frappe.get_traceback())
        return result

    for row in rows:
        service = (row.get("service") or "").strip().lower()
        email_id = (row.get("email_id") or "").strip()
        domain = email_id.rsplit("@", 1)[-1].lower() if "@" in email_id else ""

        if service == "gmail" or domain in {"gmail.com", "googlemail.com"}:
            provider = "gmail"
        elif service == "outlook.com" or domain in {"outlook.com", "hotmail.com", "live.com", "msn.com"}:
            provider = "outlook"
        elif service == "yahoo mail" or domain.endswith("yahoo.com"):
            provider = "yahoo"
        else:
            continue

        if result[provider] is None and email_id:
            result[provider] = {"email_id": email_id, "account_name": row.get("name")}

    return result


def _dashboard_backups(settings: dict | None = None) -> list[dict]:
    result = []
    suffix_map = {
        "database": "database.sql.gz",
        "public": "files.tar",
        "private": "private-files.tar",
        "apps": APP_ARCHIVE_SUFFIX,
    }
    for storage, directory in _backup_dirs(settings, allow_unavailable_active=True).items():
        if directory is None or not directory.is_dir():
            continue
        for row in list_backup_sets(directory, _site_prefix()):
            timestamp = row["timestamp"]
            files = {
                key: f"{timestamp}-{_site_prefix()}-{suffix}"
                for key, suffix in suffix_map.items()
                if suffix in row["files"]
            }
            result.append({
                "timestamp": timestamp,
                "storage": storage,
                "storage_label": "المجلد المحدد" if storage == "active" else "مجلد سابق",
                "created": row["created"],
                "complete": row["complete"],
                "file_count": len(row["files"]),
                "file_total": 1 if set(row["files"]) == {"database.sql.gz"} else (5 if row["apps_available"] else 4),
                "apps_available": row["apps_available"],
                "total_size": row["total_size"],
                "size_label": _format_size(row["total_size"]),
                "files": files,
            })
    return sorted(result, key=lambda item: (item["timestamp"], item["storage"] == "active"), reverse=True)


@frappe.whitelist()
def get_dashboard():
    _require_manager()
    settings = _get_settings()
    storage_error = None
    try:
        directories = _backup_dirs(settings)
    except Exception as exc:
        storage_error = str(exc)[:300]
        directories = _backup_dirs(settings, allow_unavailable_active=True)
    directory = directories.get("active")
    configured_path = str(settings.get("storage", {}).get("local_path") or "").strip()
    if directory is None:
        directory = Path(configured_path).expanduser() if configured_path else Path(frappe.get_site_path("private", "backups"))
    backups = _dashboard_backups(settings)
    status = _system_status()
    storage_info = backup_directory_details(directory) if directories.get("active") is not None else None
    previous_directories = [str(path) for key, path in directories.items() if key.startswith("previous_") and path is not None]
    total_bytes = sum(item["total_size"] for item in backups)
    return {
        "status": status,
        "settings": settings,
        "apps": _apps_for_ui(settings),
        "email_connections": _email_connections_for_ui(),
        "summary": {
            "backup_count": len(backups),
            "complete_count": sum(1 for item in backups if item["complete"]),
            "total_size": _format_size(total_bytes),
            "latest": backups[0]["created"] if backups else "لا توجد نسخ بعد",
            "directory": str(directory),
            "previous_directory": previous_directories[0] if previous_directories else None,
            "previous_directories": previous_directories,
            "storage_error": storage_error,
            "free_space": _format_size(storage_info["free_bytes"]) if storage_info else "غير متاحة",
            "mount_target": storage_info["mount_target"] if storage_info else None,
            "is_separate_mount": storage_info["is_separate_mount"] if storage_info else False,
        },
        "backups": backups[:100],
    }


@frappe.whitelist(methods=["POST"])
def test_backup_path(path: str | None = None, require_mount: bool = False):
    _require_manager()
    raw_path = str(path or "").strip()
    must_be_mounted = require_mount if isinstance(require_mount, bool) else str(require_mount).strip().lower() in {"1", "true", "yes", "on"}
    if must_be_mounted and not raw_path:
        frappe.throw(_("أدخل مسار القرص الخارجي أولاً"))
    try:
        checked = prepare_backup_directory(
            site_path=Path(frappe.get_site_path()),
            bench_dir=_bench_dir(),
            local_path=raw_path,
            require_mount=must_be_mounted,
            create=True,
        )
        details = backup_directory_details(checked)
    except (OSError, ValueError, RuntimeError) as exc:
        frappe.throw(_("فشل فحص مجلد النسخ: {0}").format(str(exc)[:300]))
    return {
        "ok": True,
        "path": str(checked),
        "free_space": _format_size(details["free_bytes"]),
        "mount_target": details["mount_target"],
        "is_separate_mount": details["is_separate_mount"],
        "message": "المجلد صالح والكتابة إليه ناجحة",
    }


@frappe.whitelist(methods=["POST"])
def start_backup():
    _require_manager()
    settings = _get_settings()
    if settings.get("backup_mode") == "one_time" and settings.get("one_time_completed_at"):
        frappe.throw(_("تم تنفيذ النسخة المحددة لمرة واحدة بالفعل. غيّر نمط النسخ إلى النسخ الدوري ثم احفظ، أو أعد اختيار نمط النسخة الواحدة لبدء عملية جديدة."))
    _run_control("start", timeout=20)
    return {"message": "تم إرسال طلب إنشاء النسخة الاحتياطية إلى خدمة النظام"}


def _validate_storage_settings(storage_raw: dict, current_storage: dict | None = None) -> dict:
    if not isinstance(storage_raw, dict):
        frappe.throw(_("إعدادات التخزين المحلي غير صحيحة"))

    current_storage = current_storage if isinstance(current_storage, dict) else {}
    local_path = str(storage_raw.get("local_path") or "").strip()
    require_mount_raw = storage_raw.get("require_mount", False)
    require_mount = require_mount_raw if isinstance(require_mount_raw, bool) else str(require_mount_raw).strip().lower() in {"1", "true", "yes", "on"}
    if require_mount and not local_path:
        frappe.throw(_("لا يمكن اشتراط قرص منفصل مع ترك مسار التخزين الافتراضي"))
    try:
        checked_path = prepare_backup_directory(
            site_path=Path(frappe.get_site_path()),
            bench_dir=_bench_dir(),
            local_path=local_path,
            require_mount=require_mount,
            create=True,
        )
        if local_path:
            local_path = str(checked_path)
    except (OSError, ValueError, RuntimeError) as exc:
        frappe.throw(_("مسار تخزين النسخ غير صالح: {0}").format(str(exc)[:300]))

    history = current_storage.get("previous_paths") or []
    if not isinstance(history, list):
        history = []
    old_raw = str(current_storage.get("local_path") or "").strip()
    old_active = Path(old_raw).expanduser() if old_raw else Path(frappe.get_site_path("private", "backups"))
    old_active = Path(os.path.normpath(str(old_active)))
    if old_active != checked_path:
        history = [str(old_active), *history]

    new_path_string = str(checked_path)
    previous_paths = []
    for old_path in history:
        if not isinstance(old_path, str) or not old_path.strip():
            continue
        normalized = str(Path(os.path.normpath(str(Path(old_path).expanduser()))))
        if normalized != new_path_string and normalized not in previous_paths:
            previous_paths.append(normalized)

    return {
        "local_path": local_path,
        "require_mount": require_mount,
        "previous_paths": previous_paths[:20],
    }


def _validate_settings(raw: dict) -> dict:
    current = _get_settings()
    if not isinstance(raw, dict):
        frappe.throw(_("صيغة الإعدادات غير صحيحة"))

    backup_mode = str(raw.get("backup_mode", current.get("backup_mode", "scheduled"))).strip()
    if backup_mode not in {"scheduled", "one_time"}:
        frappe.throw(_("نمط النسخ الاحتياطي غير صالح"))

    current_storage = current.get("storage", {})
    storage_raw = raw.get("storage") or current_storage or {}
    storage = _validate_storage_settings(storage_raw, current_storage)

    schedule_enabled = bool(raw.get("schedule_enabled", current.get("schedule_enabled", True)))
    if backup_mode == "one_time":
        schedule_enabled = False
    schedule_raw = raw.get("schedule") or {}
    schedule = {}
    for key in ("daily", "weekly", "monthly"):
        item = schedule_raw.get(key) or current["schedule"][key]
        enabled = bool(item.get("enabled", False))
        time_value = str(item.get("time", "02:00")).strip()
        if not TIME_RE.fullmatch(time_value):
            frappe.throw(_("وقت {0} غير صالح. استخدم HH:MM").format(key))
        schedule[key] = {"enabled": enabled, "time": time_value}

    weekday = str((schedule_raw.get("weekly") or {}).get("weekday", current["schedule"]["weekly"]["weekday"]))
    if weekday not in WEEKDAYS:
        frappe.throw(_("يوم الأسبوع غير صالح"))
    schedule["weekly"]["weekday"] = weekday

    try:
        month_day = int((schedule_raw.get("monthly") or {}).get("day", current["schedule"]["monthly"]["day"]))
    except (TypeError, ValueError):
        frappe.throw(_("يوم الشهر غير صالح"))
    if not 1 <= month_day <= 28:
        frappe.throw(_("يوم الشهر يجب أن يكون بين 1 و28 لضمان التنفيذ كل شهر"))
    schedule["monthly"]["day"] = month_day

    if schedule_enabled and not any(item["enabled"] for item in schedule.values()):
        frappe.throw(_("فعّل موعداً واحداً على الأقل أو أوقف الجدولة التلقائية"))

    if backup_mode == "one_time" and current.get("backup_mode", "scheduled") == "one_time":
        one_time_completed_at = current.get("one_time_completed_at")
        one_time_timestamp = current.get("one_time_timestamp")
    else:
        one_time_completed_at = None
        one_time_timestamp = None


    retention_raw = raw.get("retention") or {}
    retention = {"auto_apply": bool(retention_raw.get("auto_apply", False))}
    for key, default in (("daily", 7), ("weekly", 4), ("monthly", 12)):
        try:
            value = int(retention_raw.get(key, current["retention"].get(key, default)))
        except (TypeError, ValueError):
            frappe.throw(_("قيمة الاحتفاظ غير صحيحة: {0}").format(key))
        if not 1 <= value <= 365:
            frappe.throw(_("قيمة الاحتفاظ يجب أن تكون بين 1 و365: {0}").format(key))
        retention[key] = value

    apps_raw = raw.get("apps") or {}
    discovered = {item["name"] for item in discover_apps(_bench_dir())}
    selected_raw = apps_raw.get("selected_apps", current["apps"].get("selected_apps", []))
    if not isinstance(selected_raw, list) or any(not isinstance(name, str) for name in selected_raw):
        frappe.throw(_("قائمة التطبيقات المحددة غير صحيحة"))
    selected = sorted(set(selected_raw))
    unknown = set(selected) - discovered
    if unknown:
        frappe.throw(_("توجد تطبيقات غير معروفة: {0}").format(", ".join(sorted(unknown))))
    auto_include = bool(apps_raw.get("auto_include_new_apps", current["apps"].get("auto_include_new_apps", True)))
    excluded = sorted(discovered - set(selected)) if auto_include else []
    if "hded_backup_manager" in discovered:
        selected = sorted(set(selected) | {"hded_backup_manager"})
        excluded = [name for name in excluded if name != "hded_backup_manager"]
    apps = {
        "archive_enabled": bool(apps_raw.get("archive_enabled", True)),
        "auto_include_new_apps": auto_include,
        "selected_apps": selected,
        "excluded_apps": excluded,
    }

    return {
        "version": 3,
        "backup_mode": backup_mode,
        "one_time_completed_at": one_time_completed_at,
        "one_time_timestamp": one_time_timestamp,
        "schedule_enabled": schedule_enabled,
        "schedule": schedule,
        "retention": retention,
        "storage": storage,
        "apps": apps,
    }


@frappe.whitelist(methods=["POST"])
def save_storage_settings(storage_json: str):
    """Save only the local backup destination without changing systemd schedules."""
    _require_manager()
    try:
        storage_raw = json.loads(storage_json or "{}")
    except json.JSONDecodeError:
        frappe.throw(_("تعذر قراءة بيانات مسار التخزين"))
    if not isinstance(storage_raw, dict):
        frappe.throw(_("صيغة إعدادات مسار التخزين غير صحيحة"))

    settings = _get_settings()
    settings["storage"] = _validate_storage_settings(storage_raw, settings.get("storage", {}))
    settings["version"] = 3
    _save_settings(settings)
    return {
        "message": "تم حفظ مسار التخزين فقط. لم يتم تعديل جدول النسخ أو سياسة الاحتفاظ أو إعدادات التطبيقات."
    }


@frappe.whitelist(methods=["POST"])
def save_settings(settings_json: str):
    _require_manager()
    try:
        raw = json.loads(settings_json or "{}")
    except json.JSONDecodeError:
        frappe.throw(_("تعذر قراءة بيانات الإعدادات"))
    settings = _validate_settings(raw)
    schedule = settings["schedule"]
    _run_control(
        "set-schedule",
        "1" if schedule["daily"]["enabled"] else "0",
        schedule["daily"]["time"],
        "1" if schedule["weekly"]["enabled"] else "0",
        schedule["weekly"]["weekday"],
        schedule["weekly"]["time"],
        "1" if schedule["monthly"]["enabled"] else "0",
        str(schedule["monthly"]["day"]),
        schedule["monthly"]["time"],
    )
    _run_control("enable" if settings["schedule_enabled"] else "disable")
    _save_settings(settings)
    return {"message": "تم حفظ إعدادات الجدولة والاحتفاظ والتطبيقات"}


def _settings_from_request(settings_json: str | None) -> dict:
    if not settings_json:
        return _get_settings()
    try:
        raw = json.loads(settings_json)
    except json.JSONDecodeError:
        frappe.throw(_("تعذر قراءة بيانات الإعدادات"))
    return _validate_settings(raw)


@frappe.whitelist()
def preview_retention(settings_json: str | None = None):
    _require_manager()
    settings = _settings_from_request(settings_json)
    directory = _backup_dir(settings)
    plan = retention_plan(directory, _site_prefix(), settings["retention"])
    return {
        "directory": str(directory),
        "keep_count": len(plan["keep"]),
        "delete_count": len(plan["delete"]),
        "incomplete_preserved": plan["incomplete_preserved"],
        "complete_count": plan["complete_count"],
        "delete": [
            {**row, "size_label": _format_size(row["size"])}
            for row in plan["delete"]
        ],
    }


@frappe.whitelist(methods=["POST"])
def apply_retention_now(settings_json: str | None = None, expected_timestamps: str | None = None):
    _require_manager()
    settings = _settings_from_request(settings_json)
    plan = retention_plan(_backup_dir(settings), _site_prefix(), settings["retention"])
    if not plan["delete"]:
        return {"message": "لا توجد نسخ مكتملة زائدة للحذف", "deleted_count": 0}
    try:
        expected = set(json.loads(expected_timestamps or "[]"))
    except (json.JSONDecodeError, TypeError):
        frappe.throw(_("لم يتم تمرير قائمة النسخ التي تمت معاينتها"))
    current = {row["timestamp"] for row in plan["delete"]}
    if expected != current:
        frappe.throw(_("تغيرت قائمة النسخ المرشحة للحذف منذ المعاينة. أعد المعاينة قبل الحذف."))
    result = apply_retention(_backup_dir(settings), _site_prefix(), settings["retention"])
    return {
        "message": "اكتمل تطبيق سياسة الاحتفاظ. لم تُحذف النسخ غير المكتملة.",
        "deleted_count": result["deleted_count"],
        "incomplete_preserved": result["incomplete_preserved"],
    }


@frappe.whitelist()
def verify_backup(timestamp: str, storage: str = "active"):
    _require_manager()
    paths = _expected_files(timestamp, storage)
    backup_dir = _backup_dirs(allow_unavailable_active=(storage != "active"))[storage]
    core_kinds = ("database",)
    missing = [kind for kind in core_kinds if not paths[kind].is_file() or paths[kind].is_symlink()]
    if missing:
        return {"ok": False, "message": "النسخة غير مكتملة", "missing": missing, "checks": []}

    checks = []
    try:
        with gzip.open(paths["database"], "rb") as stream:
            while stream.read(1024 * 1024):
                pass
        checks.append({"name": "قاعدة البيانات المضغوطة", "ok": True})

        folder_mode = os.stat(backup_dir).st_mode & 0o777
        is_vboxsf = backup_directory_details(backup_dir).get("filesystem_type") == "vboxsf"
        forbidden_bits = 0o007 if is_vboxsf else 0o077
        safe_modes = all((os.stat(paths[kind]).st_mode & forbidden_bits) == 0 for kind in core_kinds)
        checks.append({"name": "صلاحيات حماية الملفات", "ok": safe_modes and (folder_mode & forbidden_bits) == 0})
        all_ok = all(check["ok"] for check in checks if not check.get("optional"))
        return {
            "ok": all_ok,
            "message": "اجتاز فحص الملفات" if all_ok else "فشل فحص سلامة النسخة أو صلاحياتها",
            "checks": checks,
        }
    except Exception as exc:
        frappe.log_error(title="HDED Backup Verification Failed", message=frappe.get_traceback())
        return {"ok": False, "message": f"فشل فحص النسخة: {str(exc)[:250]}", "checks": checks}


@frappe.whitelist()
def download_backup(filename: str, storage: str = "active"):
    _require_manager()
    allowed_suffixes = (
        "-" + BACKUP_SUFFIXES["database"],
        "-" + BACKUP_SUFFIXES["public"],
        "-" + BACKUP_SUFFIXES["private"],
        "-" + BACKUP_SUFFIXES["apps"],
    )
    if not isinstance(filename, str) or not any(filename.endswith(suffix) for suffix in allowed_suffixes):
        frappe.throw(_("هذا الملف غير متاح للتنزيل من المتصفح"))
    timestamp = filename.split("-", 1)[0]
    paths = _expected_files(timestamp, storage)
    backup_dir = _backup_dirs(allow_unavailable_active=(storage != "active"))[storage]
    allowed_paths = {path.name: path for kind, path in paths.items() if kind != "config"}
    path = allowed_paths.get(filename)
    if not path or path.is_symlink() or not path.is_file() or path.resolve().parent != backup_dir:
        frappe.throw(_("ملف النسخة الاحتياطية غير موجود أو غير صالح"))
    if path.stat().st_size > 256 * 1024 * 1024:
        frappe.throw(_("حجم الملف يتجاوز حد التنزيل المباشر من المتصفح (256 ميجابايت). استخدم وجهة التخزين الخارجية عند تفعيلها."))
    frappe.local.response.filename = path.name
    frappe.local.response.filecontent = path.read_bytes()
    frappe.local.response.type = "download"
