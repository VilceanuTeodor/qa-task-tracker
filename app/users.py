"""User accounts, password hashing and login sessions."""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Literal, get_args

from app.db import get_conn
from app.errors import ValidationError

Role = Literal["user", "admin"]
ROLES = get_args(Role)

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
PASSWORD_MIN = 8
PASSWORD_MAX = 128
PBKDF2_ITERATIONS = 600_000
SESSION_LIFETIME = timedelta(days=7)


class UserNotFound(Exception):
    def __init__(self, user_id):
        super().__init__(f"User {user_id} not found")


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    _, iterations, salt_hex, digest_hex = stored.split("$")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
    return hmac.compare_digest(digest.hex(), digest_hex)


def _public(row):
    """The user fields that are safe to hand out (never the password hash)."""
    return {"id": row["id"], "username": row["username"], "role": row["role"], "created_at": row["created_at"]}


def _check_password(password):
    if len(password) < PASSWORD_MIN:
        raise ValidationError(f"Password must be at least {PASSWORD_MIN} characters")
    if len(password) > PASSWORD_MAX:
        raise ValidationError(f"Password must be at most {PASSWORD_MAX} characters")


def _check_role(role):
    if role not in ROLES:
        raise ValidationError(f"Role must be one of: {', '.join(ROLES)}")


def create_user(username, password, role="user"):
    username = (username or "").strip()
    password = password or ""
    if not USERNAME_PATTERN.match(username):
        raise ValidationError("Username must be 3-30 characters using letters, digits, '.', '_' or '-'")
    _check_password(password)
    _check_role(role)
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                (username, hash_password(password), role, _fmt(datetime.now())),
            )
            row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    except sqlite3.IntegrityError:
        raise ValidationError("That username is already taken")
    return _public(row)


def authenticate(username, password):
    """Return the user if the credentials are right, else None."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip(),)).fetchone()
    if row is None or not verify_password(password or "", row["password_hash"]):
        return None
    return _public(row)


def get_user(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise UserNotFound(user_id)
    return _public(row)


def find_user(username):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip(),)).fetchone()
    return _public(row) if row else None


def list_users():
    with get_conn() as conn:
        return [_public(row) for row in conn.execute("SELECT * FROM users ORDER BY username")]


def set_role(user_id, role, acting_user_id):
    _check_role(role)
    # Admins can't demote themselves, so there is always at least one admin left.
    if user_id == acting_user_id:
        raise ValidationError("You can't change your own role")
    get_user(user_id)
    with get_conn() as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    return get_user(user_id)


def delete_user(user_id, acting_user_id):
    if user_id == acting_user_id:
        raise ValidationError("You can't delete your own account")
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        if cur.rowcount == 0:
            raise UserNotFound(user_id)


def _token_hash(token):
    # Only a hash of each token is stored, so a leaked database can't be used to log in.
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id):
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_fmt(now),))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (_token_hash(token), user_id, _fmt(now), _fmt(now + SESSION_LIFETIME)),
        )
    return token


def user_for_token(token):
    if not token:
        return None
    with get_conn() as conn:
        row = conn.execute(
            """SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id
               WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
            (_token_hash(token), _fmt(datetime.now())),
        ).fetchone()
    return _public(row) if row else None


def delete_session(token):
    if token:
        with get_conn() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def ensure_admin():
    """Create the admin account on first run. Returns (username, password) if a password had to be generated.

    ADMIN_USERNAME (default "admin") picks the account; if ADMIN_PASSWORD is set,
    the admin's password is reset to it on every startup.
    """
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD")
    existing = find_user(username)
    if existing is None:
        generated = None if password else secrets.token_urlsafe(12)
        create_user(username, password or generated, role="admin")
        return (username, generated) if generated else None
    with get_conn() as conn:
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (existing["id"],))
        if password:
            _check_password(password)
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), existing["id"]))
    return None
