"""Email+password auth for the area picker: sqlite3 user storage, PBKDF2
password hashing, cookie-backed sessions, and a fixed-invite-code gate for
registration (no self-service invite generation -- codes are configured by
whoever runs the server).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2]
ROOT = SCRIPTS.parent
AUTH_DB_FILE = Path(os.environ.get("VC_AREA_PICKER_AUTH_DB") or (ROOT / "Config" / "auth.db"))
INVITE_CODES_FILE = ROOT / "Config" / "auth_invite_codes.json"

SESSION_COOKIE_NAME = "vc_session"
SESSION_TTL = timedelta(days=30)
DEV_LOGIN_EMAIL = "dev@worldbuilder.local"
_PBKDF2_ITERATIONS = 200_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        AUTH_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(AUTH_DB_FILE), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        _conn = conn
    return _conn


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS).hex()


def _read_invite_codes() -> list[str]:
    env_value = os.environ.get("VC_AREA_PICKER_INVITE_CODES")
    if env_value is not None:
        return [c.strip() for c in env_value.split(",") if c.strip()]
    try:
        if INVITE_CODES_FILE.exists():
            data = json.loads(INVITE_CODES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(c).strip() for c in data if str(c).strip()]
    except Exception:
        pass
    return []


def ensure_invite_codes_file() -> None:
    """Create a starter invite-codes file with one random code on first run, so
    a fresh checkout has something to register with without hand-editing JSON.
    Only called from the real server entrypoint (see server.main()), never on
    import, so importing this module (e.g. from tests) never touches disk."""
    if INVITE_CODES_FILE.exists() or os.environ.get("VC_AREA_PICKER_INVITE_CODES") is not None:
        return
    try:
        INVITE_CODES_FILE.parent.mkdir(parents=True, exist_ok=True)
        code = secrets.token_hex(4).upper()
        INVITE_CODES_FILE.write_text(json.dumps([code], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[area_picker] 已生成邀请码配置 {INVITE_CODES_FILE}\n[area_picker] 初始邀请码: {code}")
    except Exception as exc:
        print(f"[area_picker] 邀请码配置生成失败: {exc}")


def validate_invite_code(code: str) -> bool:
    code = str(code or "").strip()
    if not code:
        return False
    return code in _read_invite_codes()


def register(email: str, password: str, invite_code: str) -> dict:
    email = str(email or "").strip().lower()
    password = str(password or "")
    if not _EMAIL_RE.match(email):
        return {"ok": False, "message": "邮箱格式不正确"}
    if len(password) < 8:
        return {"ok": False, "message": "密码至少需要 8 位"}
    if not validate_invite_code(invite_code):
        return {"ok": False, "message": "邀请码无效"}
    conn = _get_conn()
    with _lock:
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            return {"ok": False, "message": "该邮箱已注册"}
        salt = secrets.token_bytes(16)
        password_hash = _hash_password(password, salt)
        conn.execute(
            "INSERT INTO users (email, password_hash, password_salt, created_at) VALUES (?, ?, ?, ?)",
            (email, password_hash, salt.hex(), _now().isoformat()),
        )
        conn.commit()
    return {"ok": True, "message": "注册成功"}


def _create_session(user_id: int) -> str:
    conn = _get_conn()
    token = secrets.token_urlsafe(32)
    now = _now()
    with _lock:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now.isoformat(), (now + SESSION_TTL).isoformat()),
        )
        conn.commit()
    return token


def login(email: str, password: str) -> dict:
    email = str(email or "").strip().lower()
    password = str(password or "")
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, password_hash, password_salt FROM users WHERE email = ?", (email,)
    ).fetchone()
    if not row:
        return {"ok": False, "message": "邮箱或密码错误"}
    user_id, password_hash, salt_hex = row
    candidate = _hash_password(password, bytes.fromhex(salt_hex))
    if not hmac.compare_digest(candidate, password_hash):
        return {"ok": False, "message": "邮箱或密码错误"}
    token = _create_session(user_id)
    return {"ok": True, "message": "登录成功", "token": token, "email": email}


def dev_login() -> dict:
    """Create or reuse the local development user and return a session."""
    conn = _get_conn()
    email = DEV_LOGIN_EMAIL
    with _lock:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            user_id = row[0]
        else:
            salt = secrets.token_bytes(16)
            password_hash = _hash_password(secrets.token_urlsafe(32), salt)
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, password_salt, created_at) VALUES (?, ?, ?, ?)",
                (email, password_hash, salt.hex(), _now().isoformat()),
            )
            conn.commit()
            user_id = cur.lastrowid
    token = _create_session(user_id)
    return {"ok": True, "message": "登录成功", "token": token, "email": email}


def logout(token: str) -> None:
    if not token:
        return
    conn = _get_conn()
    with _lock:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()


def user_for_token(token: str) -> dict | None:
    if not token:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT users.id, users.email, sessions.expires_at FROM sessions "
        "JOIN users ON users.id = sessions.user_id WHERE sessions.token = ?",
        (token,),
    ).fetchone()
    if not row:
        return None
    user_id, email, expires_at = row
    if datetime.fromisoformat(expires_at) < _now():
        with _lock:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
        return None
    return {"id": user_id, "email": email}
