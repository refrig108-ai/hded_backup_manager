from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests
import frappe
from frappe.utils.password import decrypt, encrypt

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
CALLBACK_PATH = "/api/method/hded_backup_manager.api.google_drive_oauth_callback"
CONFIG_NAME = "hded_backup_manager_google_drive.json"
FOLDER_MIME = "application/vnd.google-apps.folder"
BACKUP_RE = re.compile(r"^\d{8}_\d{6}-[A-Za-z0-9_]+-database\.sql\.gz$")
CHUNK_SIZE = 8 * 1024 * 1024
MAX_RETRIES = 5


def _site_private(site_path: Path | None = None) -> Path:
    root = Path(site_path) if site_path else Path(frappe.get_site_path())
    private = root / "private"
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    if private.is_symlink() or not private.is_dir():
        raise RuntimeError("مجلد private للموقع غير صالح")
    try:
        os.chmod(private, 0o700)
    except OSError:
        pass
    return private.resolve(strict=True)


def _config_path(site_path: Path | None = None) -> Path:
    private = _site_private(site_path)
    path = private / CONFIG_NAME
    if path.is_symlink() or path.resolve().parent != private:
        raise RuntimeError("مسار إعدادات Google Drive غير آمن")
    return path


def _defaults() -> dict:
    return {
        "version": 1,
        "client_id": "",
        "client_secret_enc": "",
        "refresh_token_enc": "",
        "redirect_uri": "",
        "folder_name": "HDED ERP Backups",
        "folder_id": "",
        "auto_upload": False,
        "oauth_state_hash": "",
        "oauth_state_expires": 0,
        "pending_uploads": [],
        "uploads": {},
        "last_upload": None,
        "last_error": "",
        "connected_at": None,
    }


def _read_raw(site_path: Path | None = None) -> dict:
    path = _config_path(site_path)
    config = _defaults()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            config.update(data)
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"تعذر قراءة إعدادات Google Drive: {exc}") from exc
    if not isinstance(config.get("pending_uploads"), list):
        config["pending_uploads"] = []
    if not isinstance(config.get("uploads"), dict):
        config["uploads"] = {}
    return config


def _write(config: dict, site_path: Path | None = None) -> None:
    path = _config_path(site_path)
    temp = path.with_name(path.name + f".{secrets.token_hex(6)}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        temp.unlink(missing_ok=True)


def _secret(config: dict, field: str) -> str:
    value = config.get(field) or ""
    if not value:
        return ""
    try:
        return decrypt(value, key=f"HDED Backup Manager Google Drive {field}")
    except Exception as exc:
        raise RuntimeError("تعذر فك تشفير بيانات Google Drive. تحقق من encryption_key في site_config.json.") from exc


def _put_secret(config: dict, field: str, value: str) -> None:
    config[field] = encrypt(value) if value else ""


def _valid_redirect_uri(value: str) -> bool:
    try:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            return False
        host = parsed.hostname.lower()
        if host in {"localhost", "127.0.0.1", "::1"} or "." not in host:
            return False
        if host.endswith((".local", ".localhost", ".erp", ".internal")):
            return False
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return False
        if parsed.path != CALLBACK_PATH:
            return False
        if parsed.port not in (None, 443):
            return False
        return True
    except ValueError:
        return False


def save_oauth_settings(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    folder_name: str = "HDED ERP Backups",
    auto_upload: bool = False,
) -> dict:
    config = _read_raw()
    client_id = str(client_id or "").strip()
    client_secret = str(client_secret or "").strip()
    redirect_uri = str(redirect_uri or "").strip()
    folder_name = str(folder_name or "HDED ERP Backups").strip()

    if not client_id or not client_id.endswith(".apps.googleusercontent.com"):
        raise ValueError("Client ID غير صالح. استخدم OAuth Client ID من Google Cloud.")
    if client_secret:
        _put_secret(config, "client_secret_enc", client_secret)
    elif not config.get("client_secret_enc"):
        raise ValueError("أدخل Client Secret أول مرة.")
    if not _valid_redirect_uri(redirect_uri):
        raise ValueError(
            "عنوان إعادة التوجيه يجب أن يكون HTTPS وبنطاق صالح، وينتهي بالمسار "
            + CALLBACK_PATH
        )
    if not folder_name or len(folder_name) > 100:
        raise ValueError("اسم مجلد Google Drive يجب أن يكون بين حرف واحد و100 حرف.")

    old_client_id = str(config.get("client_id") or "")
    if old_client_id and old_client_id != client_id:
        # Refresh tokens belong to the OAuth client that issued them. A client change
        # therefore requires a fresh authorization and a new app-owned Drive folder.
        config["refresh_token_enc"] = ""
        config["folder_id"] = ""
        config["connected_at"] = None
    config["client_id"] = client_id
    config["redirect_uri"] = redirect_uri
    config["folder_name"] = folder_name
    config["auto_upload"] = bool(auto_upload)
    _write(config)
    return public_status()


def public_status() -> dict:
    config = _read_raw()
    connected = bool(config.get("refresh_token_enc"))
    pending = config.get("pending_uploads") or []
    return {
        "configured": bool(config.get("client_id") and config.get("client_secret_enc") and config.get("redirect_uri")),
        "client_id": config.get("client_id") or "",
        "connected": connected,
        "auto_upload": bool(config.get("auto_upload")),
        "folder_name": config.get("folder_name") or "HDED ERP Backups",
        "redirect_uri": config.get("redirect_uri") or "",
        "callback_path": CALLBACK_PATH,
        "pending_count": len(pending),
        "last_upload": config.get("last_upload"),
        "last_error": str(config.get("last_error") or "")[:500],
        "connected_at": config.get("connected_at"),
        "uploaded_count": len(config.get("uploads") or {}),
    }


def begin_oauth() -> str:
    config = _read_raw()
    if not config.get("client_id") or not config.get("client_secret_enc"):
        raise ValueError("احفظ Client ID وClient Secret أولاً.")
    if not _valid_redirect_uri(str(config.get("redirect_uri") or "")):
        raise ValueError("عنوان إعادة التوجيه غير صالح. استخدم HTTPS بنطاق صالح.")
    state = secrets.token_urlsafe(32)
    config["oauth_state_hash"] = hashlib.sha256(state.encode("utf-8")).hexdigest()
    config["oauth_state_expires"] = int(time.time()) + 600
    _write(config)
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": DRIVE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return AUTH_URL + "?" + urlencode(params)


def complete_oauth(code: str, state: str) -> None:
    config = _read_raw()
    expected = str(config.get("oauth_state_hash") or "")
    supplied = hashlib.sha256(str(state or "").encode("utf-8")).hexdigest()
    if not expected or not secrets.compare_digest(expected, supplied):
        raise ValueError("طلب OAuth غير صالح أو سبق استخدامه.")
    if int(config.get("oauth_state_expires") or 0) < int(time.time()):
        config["oauth_state_hash"] = ""
        config["oauth_state_expires"] = 0
        _write(config)
        raise ValueError("انتهت صلاحية طلب ربط Google Drive. أعد المحاولة.")
    config["oauth_state_hash"] = ""
    config["oauth_state_expires"] = 0
    _write(config)

    client_secret = _secret(config, "client_secret_enc")
    response = requests.post(
        TOKEN_URL,
        data={
            "code": str(code),
            "client_id": config["client_id"],
            "client_secret": client_secret,
            "redirect_uri": config["redirect_uri"],
            "grant_type": "authorization_code",
        },
        timeout=(15, 60),
    )
    if response.status_code != 200:
        raise RuntimeError(f"فشل تبادل رمز Google OAuth (HTTP {response.status_code}).")
    tokens = response.json()
    refresh_token = str(tokens.get("refresh_token") or "")
    if not refresh_token:
        refresh_token = _secret(config, "refresh_token_enc")
    if not refresh_token:
        raise RuntimeError("لم يرسل Google Refresh Token. أعد الربط مع الموافقة على الوصول الدائم.")
    _put_secret(config, "refresh_token_enc", refresh_token)
    config["connected_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    config["last_error"] = ""
    _write(config)
    ensure_drive_folder()


def _access_token() -> str:
    config = _read_raw()
    refresh_token = _secret(config, "refresh_token_enc")
    if not config.get("client_id") or not refresh_token:
        raise RuntimeError("حساب Google Drive غير مربوط.")
    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": config["client_id"],
            "client_secret": _secret(config, "client_secret_enc"),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=(15, 60),
    )
    if response.status_code != 200:
        if response.status_code in (400, 401):
            config["last_error"] = "انتهى تفويض Google أو أُلغي. أعد ربط الحساب."
            _write(config)
        raise RuntimeError(f"تعذر تجديد تفويض Google Drive (HTTP {response.status_code}).")
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("لم يرجع Google Access Token صالحاً.")
    return str(token)


def _headers(token: str | None = None) -> dict:
    return {"Authorization": "Bearer " + (token or _access_token())}


def _drive_json(method: str, url: str, **kwargs) -> dict:
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.update(_headers())
    response = requests.request(method, url, headers=headers, timeout=(20, 120), **kwargs)
    if response.status_code >= 400:
        detail = ""
        try:
            detail = response.json().get("error", {}).get("message", "")
        except Exception:
            pass
        raise RuntimeError(f"Google Drive API رفض الطلب (HTTP {response.status_code}): {detail[:250]}")
    if not response.content:
        return {}
    return response.json()


def ensure_drive_folder() -> str:
    config = _read_raw()
    folder_id = str(config.get("folder_id") or "")
    if folder_id:
        try:
            folder = _drive_json(
                "GET",
                f"{DRIVE_API}/files/{folder_id}",
                params={"fields": "id,name,mimeType,trashed"},
            )
            if folder.get("id") == folder_id and folder.get("mimeType") == FOLDER_MIME and not folder.get("trashed"):
                return folder_id
        except Exception:
            config["folder_id"] = ""

    folder = _drive_json(
        "POST",
        f"{DRIVE_API}/files",
        params={"fields": "id,name,mimeType"},
        json={"name": config.get("folder_name") or "HDED ERP Backups", "mimeType": FOLDER_MIME},
    )
    folder_id = str(folder.get("id") or "")
    if not folder_id:
        raise RuntimeError("لم يُرجع Google معرّف مجلد النسخ الاحتياطي.")
    config["folder_id"] = folder_id
    config["last_error"] = ""
    _write(config)
    return folder_id


def test_connection() -> dict:
    folder_id = ensure_drive_folder()
    folder = _drive_json(
        "GET",
        f"{DRIVE_API}/files/{folder_id}",
        params={"fields": "id,name,webViewLink"},
    )
    return {
        "ok": True,
        "folder_id": folder_id,
        "folder_name": folder.get("name") or "",
        "web_view_link": folder.get("webViewLink") or "",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _find_existing(name: str, folder_id: str) -> dict | None:
    escaped_name = name.replace("\\", "\\\\").replace("'", "\\'")
    payload = _drive_json(
        "GET",
        f"{DRIVE_API}/files",
        params={
            "q": f"name = '{escaped_name}' and '{folder_id}' in parents and trashed = false",
            "pageSize": 10,
            "orderBy": "createdTime desc",
            "fields": "files(id,name,size,webViewLink,createdTime,appProperties)",
        },
    )
    rows = payload.get("files") or []
    return rows[0] if rows else None


def _resumable_upload(path: Path, folder_id: str, token: str, digest: str) -> dict:
    size = path.stat().st_size
    metadata = {
        "name": path.name,
        "mimeType": "application/gzip",
        "parents": [folder_id],
        "description": "HDED ERPNext database-only backup",
        "appProperties": {"sha256": digest, "backupType": "database-only"},
    }
    response = requests.post(
        f"{DRIVE_UPLOAD_API}/files",
        params={"uploadType": "resumable", "fields": "id,name,size,webViewLink,createdTime"},
        headers={
            **_headers(token),
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "application/gzip",
            "X-Upload-Content-Length": str(size),
        },
        json=metadata,
        timeout=(20, 120),
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"تعذر بدء رفع Google Drive (HTTP {response.status_code}).")
    session_uri = response.headers.get("Location")
    if not session_uri:
        raise RuntimeError("لم يُرجع Google عنوان جلسة الرفع القابلة للاستئناف.")
    parsed_session = urlparse(session_uri)
    if parsed_session.scheme != "https" or parsed_session.hostname not in {"www.googleapis.com", "upload.googleapis.com"}:
        raise RuntimeError("أعاد Google عنوان جلسة رفع غير موثوق؛ أُوقف الرفع لحماية النسخة.")

    offset = 0
    completed = None
    no_progress_count = 0
    with path.open("rb") as stream:
        while offset < size:
            stream.seek(offset)
            chunk = stream.read(min(CHUNK_SIZE, size - offset))
            if not chunk:
                raise RuntimeError("انتهى ملف النسخة قبل اكتمال الرفع.")
            start = offset
            end = start + len(chunk) - 1
            headers = {
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Content-Type": "application/gzip",
            }
            advanced = False
            for attempt in range(MAX_RETRIES):
                try:
                    uploaded = requests.put(session_uri, data=chunk, headers=headers, timeout=(30, 300))
                except requests.RequestException:
                    if attempt + 1 >= MAX_RETRIES:
                        raise
                    time.sleep(min(2 ** attempt, 16))
                    probe = requests.put(
                        session_uri,
                        data=b"",
                        headers={"Content-Length": "0", "Content-Range": f"bytes */{size}"},
                        timeout=(20, 60),
                    )
                    if probe.status_code in (200, 201):
                        completed = probe.json()
                        break
                    if probe.status_code == 308:
                        received = probe.headers.get("Range", "")
                        new_offset = int(received.rsplit("-", 1)[1]) + 1 if received else 0
                        if new_offset > offset and new_offset <= size:
                            offset = new_offset
                            advanced = True
                            break
                        no_progress_count += 1
                        if no_progress_count >= 3:
                            raise RuntimeError("لم يتقدم رفع Google Drive بعد عدة محاولات؛ ستتم إعادة المحاولة في تشغيل النسخ التالي.")
                        continue
                    if probe.status_code == 404:
                        raise RuntimeError("انتهت صلاحية جلسة الرفع. أعد محاولة الرفع.")
                    continue
                if uploaded.status_code in (200, 201):
                    completed = uploaded.json()
                    break
                if uploaded.status_code == 308:
                    received = uploaded.headers.get("Range", "")
                    new_offset = int(received.rsplit("-", 1)[1]) + 1 if received else 0
                    if new_offset > offset and new_offset <= size:
                        offset = new_offset
                        advanced = True
                        break
                    no_progress_count += 1
                    if no_progress_count >= 3:
                        raise RuntimeError("لم يتقدم رفع Google Drive بعد عدة محاولات؛ ستتم إعادة المحاولة في تشغيل النسخ التالي.")
                    continue
                if uploaded.status_code >= 500 and attempt + 1 < MAX_RETRIES:
                    time.sleep(min(2 ** attempt, 16))
                    continue
                raise RuntimeError(f"توقف رفع Google Drive (HTTP {uploaded.status_code}).")
            if completed:
                break
            if offset == start and not advanced:
                raise RuntimeError("تعذر استكمال رفع Google Drive بعد عدة محاولات.")
            if offset > size:
                raise RuntimeError("أبلغ Google عن موضع رفع غير صالح.")
    if not completed:
        raise RuntimeError("لم يكتمل رفع ملف النسخة إلى Google Drive.")
    return completed


def upload_file(path: str | Path, site_path: Path | None = None) -> dict:
    backup = Path(path)
    if backup.is_symlink() or not backup.is_file() or not BACKUP_RE.fullmatch(backup.name):
        raise ValueError("ملف النسخة المحدد ليس نسخة قاعدة بيانات HDED صالحة.")
    backup = backup.resolve(strict=True)
    size = backup.stat().st_size
    if size <= 0:
        raise ValueError("ملف النسخة فارغ.")
    config = _read_raw(site_path)
    folder_id = ensure_drive_folder()
    digest = _sha256(backup)
    existing = _find_existing(backup.name, folder_id)
    if existing:
        properties = existing.get("appProperties") or {}
        if properties.get("sha256") == digest and int(existing.get("size") or 0) == size:
            result = existing
        else:
            raise RuntimeError("يوجد ملف بالاسم نفسه في Google Drive لا يمكن تأكيد تطابق بصمته؛ لم تتم الكتابة فوقه.")
    else:
        result = _resumable_upload(backup, folder_id, _access_token(), digest)
    uploaded = {
        "file_id": result.get("id"),
        "name": result.get("name") or backup.name,
        "size": int(result.get("size") or size),
        "web_view_link": result.get("webViewLink") or "",
        "sha256": digest,
        "uploaded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    config["uploads"][backup.name] = uploaded
    config["last_upload"] = uploaded
    config["last_error"] = ""
    pending = [item for item in config.get("pending_uploads", []) if item.get("name") != backup.name]
    config["pending_uploads"] = pending
    _write(config, site_path)
    return uploaded


def pending_timestamps(site_path: Path | None = None) -> set[str]:
    config = _read_raw(site_path)
    result = set()
    for item in config.get("pending_uploads", []):
        name = str(item.get("name") or "")
        match = re.match(r"^(\d{8}_\d{6})-", name)
        if match:
            result.add(match.group(1))
    return result


def process_backup_uploads(current_file: str | Path, site_path: Path | None = None) -> dict:
    config = _read_raw(site_path)
    if not config.get("auto_upload") or not config.get("refresh_token_enc"):
        return {"enabled": False, "uploaded": 0, "pending": len(config.get("pending_uploads", []))}
    current = Path(current_file).resolve(strict=True)
    queue = list(config.get("pending_uploads") or [])
    if not any(item.get("name") == current.name for item in queue):
        queue.append({"name": current.name, "path": str(current)})
    config["pending_uploads"] = queue[-200:]
    _write(config, site_path)

    uploaded_count = 0
    for item in list(config["pending_uploads"]):
        candidate = Path(str(item.get("path") or ""))
        if candidate.is_symlink() or not candidate.is_file() or not BACKUP_RE.fullmatch(candidate.name):
            config = _read_raw(site_path)
            config["last_error"] = f"ملف النسخة المعلّق غير متاح: {item.get('name', '')}"
            config["pending_uploads"] = [row for row in config.get("pending_uploads", []) if row.get("name") != item.get("name")]
            _write(config, site_path)
            continue
        try:
            upload_file(candidate, site_path)
            uploaded_count += 1
            config = _read_raw(site_path)
        except Exception as exc:
            config = _read_raw(site_path)
            config["last_error"] = str(exc)[:500]
            _write(config, site_path)
            break
    final = _read_raw(site_path)
    return {
        "enabled": True,
        "uploaded": uploaded_count,
        "pending": len(final.get("pending_uploads", [])),
        "last_error": str(final.get("last_error") or "")[:500],
    }


def list_drive_backups(site_prefix: str | None = None) -> list[dict]:
    config = _read_raw()
    if not config.get("refresh_token_enc"):
        raise RuntimeError("اربط حساب Google Drive أولاً.")
    folder_id = ensure_drive_folder()
    rows: list[dict] = []
    page_token = None
    for _ in range(5):
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "pageSize": 100,
            "orderBy": "createdTime desc",
            "fields": "nextPageToken,files(id,name,size,mimeType,createdTime,webViewLink,appProperties)",
        }
        if page_token:
            params["pageToken"] = page_token
        payload = _drive_json("GET", f"{DRIVE_API}/files", params=params)
        for item in payload.get("files") or []:
            name = str(item.get("name") or "")
            if not BACKUP_RE.fullmatch(name):
                continue
            if site_prefix and not name.endswith(f"-{site_prefix}-database.sql.gz"):
                continue
            rows.append({
                "file_id": item.get("id"),
                "name": name,
                "size": int(item.get("size") or 0),
                "created_time": item.get("createdTime"),
                "web_view_link": item.get("webViewLink") or "",
                "sha256": (item.get("appProperties") or {}).get("sha256", ""),
            })
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return rows


def download_drive_backup(file_id: str, destination: Path) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", str(file_id or "")):
        raise ValueError("معرّف نسخة Google Drive غير صالح.")
    config = _read_raw()
    folder_id = ensure_drive_folder()
    metadata = _drive_json(
        "GET",
        f"{DRIVE_API}/files/{file_id}",
        params={"fields": "id,name,size,mimeType,parents,trashed,appProperties"},
    )
    name = str(metadata.get("name") or "")
    if (
        metadata.get("id") != file_id
        or metadata.get("trashed")
        or folder_id not in (metadata.get("parents") or [])
        or not BACKUP_RE.fullmatch(name)
        or metadata.get("mimeType") == FOLDER_MIME
    ):
        raise ValueError("الملف المحدد ليس نسخة قاعدة بيانات تابعة لمجلد HDED على Google Drive.")
    expected_size = int(metadata.get("size") or 0)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.parent.is_symlink() or destination.parent.resolve() != destination.parent:
        raise ValueError("مجلد التنزيل المؤقت غير آمن.")
    response = requests.get(
        f"{DRIVE_API}/files/{file_id}",
        params={"alt": "media"},
        headers=_headers(),
        stream=True,
        timeout=(30, 300),
    )
    if response.status_code != 200:
        raise RuntimeError(f"تعذر تنزيل نسخة Google Drive (HTTP {response.status_code}).")
    digest = hashlib.sha256()
    written = 0
    temp = destination.with_name(destination.name + ".part")
    try:
        with temp.open("wb") as stream:
            os.chmod(temp, 0o600)
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                stream.write(chunk)
                digest.update(chunk)
                written += len(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if expected_size and written != expected_size:
            raise RuntimeError("حجم الملف بعد التنزيل لا يطابق الحجم المسجل في Google Drive.")
        if written <= 0:
            raise RuntimeError("الملف الذي تم تنزيله فارغ.")
        os.replace(temp, destination)
        os.chmod(destination, 0o600)
    except Exception:
        temp.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    properties = metadata.get("appProperties") or {}
    expected_hash = str(properties.get("sha256") or "")
    if expected_hash and not secrets.compare_digest(expected_hash, digest.hexdigest()):
        destination.unlink(missing_ok=True)
        raise RuntimeError("فشل فحص بصمة النسخة بعد تنزيلها من Google Drive.")
    return {"name": name, "size": written, "sha256": digest.hexdigest(), "file_id": file_id}



def disconnect() -> None:
    config = _read_raw()
    config["refresh_token_enc"] = ""
    config["folder_id"] = ""
    config["connected_at"] = None
    config["auto_upload"] = False
    config["last_error"] = ""
    config["pending_uploads"] = []
    _write(config)


def retry_pending_uploads(site_path: Path | None = None) -> dict:
    config = _read_raw(site_path)
    if not config.get("refresh_token_enc"):
        raise RuntimeError("حساب Google Drive غير مربوط.")
    queue = list(config.get("pending_uploads") or [])
    completed = 0
    for item in queue:
        path = Path(str(item.get("path") or ""))
        if path.is_symlink() or not path.is_file() or not BACKUP_RE.fullmatch(path.name):
            config = _read_raw(site_path)
            config["pending_uploads"] = [row for row in config.get("pending_uploads", []) if row.get("name") != item.get("name")]
            config["last_error"] = f"ملف النسخة المعلق غير متاح: {item.get('name', '')}"
            _write(config, site_path)
            continue
        try:
            upload_file(path, site_path)
            completed += 1
        except Exception as exc:
            config = _read_raw(site_path)
            config["last_error"] = str(exc)[:500]
            _write(config, site_path)
            break
    final = _read_raw(site_path)
    return {
        "uploaded": completed,
        "pending": len(final.get("pending_uploads") or []),
        "last_error": str(final.get("last_error") or "")[:500],
    }
