#!/usr/bin/env python3
"""SIAP Analytics — Modul autentikasi (Flask-Login + SQLite)."""

import os
import sqlite3
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH   = os.path.join(_BASE_DIR, "instance", "siap_users.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

DEFAULT_USER = "admin"
DEFAULT_PASS = "siap2025"


# ── Model ────────────────────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, uid, username, role):
        self.id       = str(uid)
        self.username = username
        self.role     = role          # "admin" | "viewer"

    def is_admin(self):
        return self.role == "admin"


# ── DB helpers ────────────────────────────────────────────────────────────────

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    UNIQUE NOT NULL,
                password_hash TEXT    NOT NULL,
                role          TEXT    NOT NULL DEFAULT 'viewer',
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.commit()
    # Buat akun admin default jika belum ada
    if not _row_by_username(DEFAULT_USER):
        _create(DEFAULT_USER, DEFAULT_PASS, "admin")
        print(f"[AUTH] Akun admin dibuat  username: {DEFAULT_USER}  password: {DEFAULT_PASS}")
        print("[AUTH] Segera ganti password via halaman /admin setelah login pertama.")


# ── CRUD ─────────────────────────────────────────────────────────────────────

def _row_by_username(username):
    with _conn() as c:
        return c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()


def _create(username, password, role="viewer"):
    with _conn() as c:
        c.execute(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
            (username, generate_password_hash(password), role),
        )
        c.commit()


def get_user_by_id(uid):
    with _conn() as c:
        row = c.execute("SELECT id,username,role FROM users WHERE id=?", (uid,)).fetchone()
        return User(row["id"], row["username"], row["role"]) if row else None


def verify_user(username, password):
    row = _row_by_username(username)
    if row and check_password_hash(row["password_hash"], password):
        return User(row["id"], row["username"], row["role"])
    return None


def create_user(username, password, role="viewer"):
    if _row_by_username(username):
        raise ValueError(f"Username '{username}' sudah digunakan.")
    _create(username, password, role)


def delete_user(uid):
    with _conn() as c:
        c.execute("DELETE FROM users WHERE id=?", (uid,))
        c.commit()


def update_password(uid, new_password):
    with _conn() as c:
        c.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (generate_password_hash(new_password), uid),
        )
        c.commit()


def get_all_users():
    with _conn() as c:
        return [dict(r) for r in
                c.execute("SELECT id,username,role,created_at FROM users ORDER BY id").fetchall()]
