from __future__ import annotations

import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from hashlib import pbkdf2_hmac, sha256
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("UPPER_CONTROL_DATA_DIR", BASE_DIR.parent / "data"))
DB_PATH = Path(os.environ.get("UPPER_CONTROL_DB", DATA_DIR / "upper_control.db"))

PBKDF2_ITERATIONS = 260_000
SESSION_TTL_HOURS = int(os.environ.get("UPPER_CONTROL_SESSION_TTL_HOURS", "12"))


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    derived = pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, expected = stored.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    derived = pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
    return hmac.compare_digest(derived.hex(), expected)


def hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'operator',
                disabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS device_tokens (
                device_id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_seen_at TEXT
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                intent TEXT NOT NULL,
                result TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS commands (
                command_id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                source TEXT NOT NULL,
                intent TEXT NOT NULL,
                params_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                delivered INTEGER NOT NULL DEFAULT 0,
                delivered_at TEXT,
                completed_at TEXT,
                message TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS media_events (
                media_id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            """
        )

        admin_user = os.environ.get("UPPER_CONTROL_ADMIN_USER", "admin")
        admin_password = os.environ.get("UPPER_CONTROL_ADMIN_PASSWORD", "admin123")
        row = conn.execute("SELECT id FROM users WHERE username = ?", (admin_user,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users(username, password_hash, role, created_at) VALUES (?, ?, 'admin', ?)",
                (admin_user, hash_password(admin_password), now_iso()),
            )

        device_id = os.environ.get("UPPER_DEVICE_ID", "digua_x5")
        device_token = os.environ.get("UPPER_DEVICE_TOKEN", "dev-device-token")
        row = conn.execute("SELECT device_id FROM device_tokens WHERE device_id = ?", (device_id,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO device_tokens(device_id, token_hash, created_at) VALUES (?, ?, ?)",
                (device_id, hash_token(device_token), now_iso()),
            )


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    created_at = datetime.now().astimezone()
    expires_at = created_at + timedelta(hours=SESSION_TTL_HOURS)
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (hash_token(token), user_id, created_at.isoformat(), expires_at.isoformat()),
        )
    return token


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, role, disabled FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None or row["disabled"]:
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso(), row["id"]))
        return {"id": row["id"], "username": row["username"], "role": row["role"]}


def get_user_by_session(token: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.role, u.disabled, s.expires_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (hash_token(token),),
        ).fetchone()
        if row is None or row["disabled"]:
            return None
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at < datetime.now().astimezone():
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
            return None
        return {"id": row["id"], "username": row["username"], "role": row["role"]}


def verify_device_token(device_id: str, token: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT token_hash FROM device_tokens WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        if row is None:
            return False
        ok = hmac.compare_digest(row["token_hash"], hash_token(token))
        if ok:
            conn.execute("UPDATE device_tokens SET last_seen_at = ? WHERE device_id = ?", (now_iso(), device_id))
        return ok


def append_log(source: str, intent: str, result: str, level: str, message: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO logs(timestamp, source, intent, result, level, message) VALUES (?, ?, ?, ?, ?, ?)",
            (now_iso(), source, intent, result, level, message),
        )


def get_logs(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT timestamp, source, intent, result, level, message FROM logs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def insert_command(command_id: str, device_id: str, source: str, intent: str, params: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO commands(command_id, device_id, source, intent, params_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (command_id, device_id, source, intent, json.dumps(params, ensure_ascii=False), now_iso()),
        )


def poll_pending_commands(device_id: str, limit: int = 20) -> list[dict[str, Any]]:
    delivered_at = now_iso()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT command_id, source, intent, params_json, created_at, delivered, delivered_at
            FROM commands
            WHERE device_id = ? AND delivered = 0 AND status = 'pending'
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (device_id, limit),
        ).fetchall()
        ids = [row["command_id"] for row in rows]
        if ids:
            conn.executemany(
                "UPDATE commands SET delivered = 1, delivered_at = ? WHERE command_id = ?",
                [(delivered_at, command_id) for command_id in ids],
            )
    commands = []
    for row in rows:
        commands.append(
            {
                "command_id": row["command_id"],
                "source": row["source"],
                "intent": row["intent"],
                "params": json.loads(row["params_json"] or "{}"),
                "created_at": row["created_at"],
                "delivered": True,
                "delivered_at": delivered_at,
            }
        )
    return commands


def complete_command(command_id: str, status: str, message: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE commands SET status = ?, message = ?, completed_at = ? WHERE command_id = ?",
            (status, message, now_iso(), command_id),
        )


def insert_media_event(media_id: str, device_id: str, payload: dict[str, Any], timestamp: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO media_events(media_id, device_id, payload_json, timestamp) VALUES (?, ?, ?, ?)",
            (media_id, device_id, json.dumps(payload, ensure_ascii=False), timestamp),
        )
