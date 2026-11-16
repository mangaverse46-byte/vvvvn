import os
import sqlite3
from contextlib import contextmanager
from config import DB_PATH

os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER NOT NULL, manga_id TEXT NOT NULL, title TEXT NOT NULL,
            PRIMARY KEY(user_id, manga_id)
        );
        CREATE TABLE IF NOT EXISTS follows (
            user_id INTEGER NOT NULL, manga_id TEXT NOT NULL, title TEXT NOT NULL,
            PRIMARY KEY(user_id, manga_id)
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        ''')

def save_user(user):
    with db() as c:
        c.execute('INSERT INTO users(user_id,username,first_name) VALUES(?,?,?) '
                  'ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name',
                  (user.id, user.username or '', user.first_name or ''))

def toggle_item(table, user_id, manga_id, title):
    if table not in ('favorites', 'follows'):
        raise ValueError('invalid table')
    with db() as c:
        row = c.execute(f'SELECT 1 FROM {table} WHERE user_id=? AND manga_id=?', (user_id, manga_id)).fetchone()
        if row:
            c.execute(f'DELETE FROM {table} WHERE user_id=? AND manga_id=?', (user_id, manga_id))
            return False
        c.execute(f'INSERT INTO {table}(user_id,manga_id,title) VALUES(?,?,?)', (user_id, manga_id, title))
        return True

def get_items(table, user_id):
    if table not in ('favorites', 'follows'):
        raise ValueError('invalid table')
    with db() as c:
        return c.execute(f'SELECT manga_id,title FROM {table} WHERE user_id=? ORDER BY title', (user_id,)).fetchall()

def stats():
    with db() as c:
        return {"users": c.execute('SELECT COUNT(*) FROM users').fetchone()[0],
                "favorites": c.execute('SELECT COUNT(*) FROM favorites').fetchone()[0],
                "follows": c.execute('SELECT COUNT(*) FROM follows').fetchone()[0]}
