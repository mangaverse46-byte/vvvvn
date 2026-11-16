import os
import sqlite3
from pathlib import Path

class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init(self):
        with self.connect() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP, downloads INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS favorites(
                user_id INTEGER NOT NULL, source_id TEXT NOT NULL, manga_url TEXT NOT NULL,
                title TEXT, PRIMARY KEY(user_id, source_id, manga_url)
            );
            CREATE TABLE IF NOT EXISTS follows(
                user_id INTEGER NOT NULL, source_id TEXT NOT NULL, manga_url TEXT NOT NULL,
                title TEXT, PRIMARY KEY(user_id, source_id, manga_url)
            );
            """)

    def touch_user(self, user):
        with self.connect() as con:
            con.execute("INSERT INTO users(user_id,username,first_name) VALUES(?,?,?) "
                        "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name",
                        (user.id, user.username or "", user.first_name or ""))

    def add_download(self, user_id):
        with self.connect() as con:
            con.execute("UPDATE users SET downloads=downloads+1 WHERE user_id=?", (user_id,))

    def stats(self):
        with self.connect() as con:
            return con.execute("SELECT COUNT(*) users, COALESCE(SUM(downloads),0) downloads FROM users").fetchone()

    def toggle(self, table, user_id, source, url, title):
        if table not in ("favorites", "follows"):
            raise ValueError("invalid table")
        with self.connect() as con:
            exists = con.execute(f"SELECT 1 FROM {table} WHERE user_id=? AND source_id=? AND manga_url=?",
                                 (user_id, source, url)).fetchone()
            if exists:
                con.execute(f"DELETE FROM {table} WHERE user_id=? AND source_id=? AND manga_url=?",
                            (user_id, source, url))
                return False
            con.execute(f"INSERT OR IGNORE INTO {table}(user_id,source_id,manga_url,title) VALUES(?,?,?,?)",
                        (user_id, source, url, title))
            return True

    def list_items(self, table, user_id):
        if table not in ("favorites", "follows"):
            raise ValueError("invalid table")
        with self.connect() as con:
            return con.execute(f"SELECT * FROM {table} WHERE user_id=? ORDER BY rowid DESC", (user_id,)).fetchall()
