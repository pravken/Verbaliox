"""
API keys of cloud language models.

Keys live in their own table (never in `settings`, which the UI reads in full) and are encrypted
with Windows DPAPI (CryptProtectData), so a copy of the database is useless on another computer or
under another Windows account. Elsewhere (tests, development on Linux/macOS) they are stored as is,
marked "plain:". The UI only ever gets the last four characters.
"""

import base64
import ctypes
import sys
from datetime import datetime
from typing import Dict, Optional

_ENTROPY = b"Verbaliox API key"
# Keys saved before the rename: read with the entropy of that time and saved again (rewrap_former)
_FORMER_ENTROPY = b"VerbaScribe API key"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes) -> _Blob:
    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))


def _dpapi(data: bytes, protect: bool, entropy_bytes: bytes = _ENTROPY) -> bytes:
    """CryptProtectData / CryptUnprotectData have the same argument list:
    (data in, description, entropy, reserved, prompt, flags, data out)."""
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    src, entropy, out = _blob(data), _blob(entropy_bytes), _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    if not fn(ctypes.byref(src), None, ctypes.byref(entropy), None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
        raise OSError("DPAPI failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def protect(text: str) -> str:
    if sys.platform == "win32":
        return "dpapi:" + base64.b64encode(_dpapi(text.encode("utf-8"), True)).decode("ascii")
    return "plain:" + text


def unprotect(stored: str) -> Optional[str]:
    try:
        if stored.startswith("dpapi:"):
            blob = base64.b64decode(stored[6:])
            try:
                return _dpapi(blob, False).decode("utf-8")
            except OSError:
                return _dpapi(blob, False, _FORMER_ENTROPY).decode("utf-8")
        if stored.startswith("plain:"):
            return stored[6:]
    except Exception:
        return None  # e.g. the database was copied from another Windows account
    return None


def _conn():
    from app.database import get_connection

    conn = get_connection()
    conn.execute("CREATE TABLE IF NOT EXISTS secrets (name TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
    return conn


def set_secret(name: str, value: str) -> None:
    from app.database import _db_lock

    with _db_lock:
        conn = _conn()
        conn.execute(
            "INSERT INTO secrets (name, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (name, protect(value), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        conn.close()


def get_secret(name: str) -> Optional[str]:
    from app.database import _db_lock

    with _db_lock:
        conn = _conn()
        row = conn.execute("SELECT value FROM secrets WHERE name = ?", (name,)).fetchone()
        conn.close()
    return unprotect(row[0]) if row else None


def rewrap_former() -> int:
    """Keys saved with the former entropy are saved again with the current one (called at start; a
    current key is left alone). Returns how many were saved again."""
    if sys.platform != "win32":
        return 0
    from app.database import _db_lock

    done = 0
    with _db_lock:
        conn = _conn()
        try:
            for name, stored in conn.execute("SELECT name, value FROM secrets").fetchall():
                if not stored.startswith("dpapi:"):
                    continue
                blob = base64.b64decode(stored[6:])
                try:
                    _dpapi(blob, False)
                    continue  # already current
                except OSError:
                    pass
                try:
                    value = _dpapi(blob, False, _FORMER_ENTROPY).decode("utf-8")
                except OSError:
                    continue  # another account's key: the UI says it cannot be read
                conn.execute("UPDATE secrets SET value = ? WHERE name = ?", (protect(value), name))
                done += 1
            conn.commit()
        finally:
            conn.close()
    return done


def delete_secret(name: str) -> None:
    from app.database import _db_lock

    with _db_lock:
        conn = _conn()
        conn.execute("DELETE FROM secrets WHERE name = ?", (name,))
        conn.commit()
        conn.close()


def hint(name: str) -> Dict[str, object]:
    """{"saved": bool, "last4": "…ab12", "readable": bool} for the UI; never the key itself."""
    from app.database import _db_lock

    with _db_lock:
        conn = _conn()
        row = conn.execute("SELECT value FROM secrets WHERE name = ?", (name,)).fetchone()
        conn.close()
    if not row:
        return {"saved": False, "last4": "", "readable": False}
    key = unprotect(row[0])
    return {"saved": True, "last4": ("…" + key[-4:]) if key and len(key) >= 8 else "", "readable": key is not None}
