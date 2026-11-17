import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
  joined_at REAL NOT NULL, last_seen REAL NOT NULL, is_banned INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, added_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS favorites (
  user_id INTEGER NOT NULL, source_id TEXT NOT NULL, manga_id TEXT NOT NULL,
  title TEXT NOT NULL, manga_url TEXT NOT NULL, cover_url TEXT,
  notifications INTEGER NOT NULL DEFAULT 1, added_at REAL NOT NULL,
  PRIMARY KEY(user_id, source_id, manga_id)
);
CREATE TABLE IF NOT EXISTS vip_users (
  user_id INTEGER PRIMARY KEY, plan TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
  user_id INTEGER NOT NULL, day TEXT NOT NULL, single_downloads INTEGER NOT NULL DEFAULT 0,
  merge_chapters INTEGER NOT NULL DEFAULT 0, bonus_single INTEGER NOT NULL DEFAULT 0,
  bonus_merge INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id, day)
);
CREATE TABLE IF NOT EXISTS referrals (
  referred_id INTEGER PRIMARY KEY, inviter_id INTEGER NOT NULL, created_at REAL NOT NULL,
  rewarded INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS complaints (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
  body TEXT NOT NULL, created_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS download_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
  source_id TEXT, manga_title TEXT, chapter_title TEXT, created_at REAL NOT NULL
);
"""

class Database:
    def __init__(self, path: str):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self.session() as db:
            db.executescript(SCHEMA)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        return db

    @contextmanager
    def session(self):
        db = self.connect()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def touch_user(self, user):
        now = time.time()
        with self._lock, self.connect() as db:
            db.execute("""INSERT INTO users(user_id,username,first_name,joined_at,last_seen)
                VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username, first_name=excluded.first_name,last_seen=excluded.last_seen""",
                (user.id, user.username, user.first_name or "", now, now))

    def is_banned(self, user_id: int) -> bool:
        with self.session() as db:
            row = db.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,)).fetchone()
            return bool(row and row["is_banned"])

    def set_banned(self, user_id: int, banned: bool):
        with self._lock, self.connect() as db:
            db.execute("UPDATE users SET is_banned=? WHERE user_id=?", (int(banned), user_id))

    def add_favorite(self, user_id, source_id, manga):
        with self._lock, self.connect() as db:
            cur = db.execute("""INSERT OR IGNORE INTO favorites
                (user_id,source_id,manga_id,title,manga_url,cover_url,added_at)
                VALUES(?,?,?,?,?,?,?)""",
                (user_id, source_id, str(manga["id"]), manga["title"], manga["url"], manga.get("cover_url"), time.time()))
            return cur.rowcount > 0

    def favorites(self, user_id):
        with self.session() as db:
            return [dict(x) for x in db.execute(
                "SELECT * FROM favorites WHERE user_id=? ORDER BY added_at DESC", (user_id,))]

    def remove_favorite(self, user_id, source_id, manga_id):
        with self._lock, self.connect() as db:
            cur = db.execute("DELETE FROM favorites WHERE user_id=? AND source_id=? AND manga_id=?",
                             (user_id, source_id, str(manga_id)))
            return cur.rowcount > 0

    def stats(self):
        with self.session() as db:
            return {
                "users": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "favorites": db.execute("SELECT COUNT(*) FROM favorites").fetchone()[0],
                "downloads": db.execute("SELECT COUNT(*) FROM download_logs").fetchone()[0],
                "complaints": db.execute("SELECT COUNT(*) FROM complaints WHERE status='open'").fetchone()[0],
            }
