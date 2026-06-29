import sqlite3
import json
import os
import sys

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
DB_PATH = os.path.join(BASE_DIR, "data", "sessions.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS history (
                session_id INTEGER PRIMARY KEY,
                history_json TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL,
                code TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
    finally:
        conn.close()

def load_sessions():
    conn = get_connection()
    try:
        rows = conn.execute('SELECT * FROM sessions ORDER BY created_at').fetchall()
        sessions = []
        for row in rows:
            msgs = conn.execute(
                'SELECT sender, content FROM messages WHERE session_id = ? ORDER BY timestamp',
                (row['id'],)
            ).fetchall()
            hist_row = conn.execute(
                'SELECT history_json FROM history WHERE session_id = ?',
                (row['id'],)
            ).fetchone()
            history = json.loads(hist_row['history_json']) if hist_row else []
            session = {
                "id": row['id'],
                "name": row['name'],
                "messages": [{"sender": m['sender'], "text": m['content']} for m in msgs],
                "history": history
            }
            sessions.append(session)
        return sessions
    finally:
        conn.close()

def save_session(session):
    conn = get_connection()
    try:
        if 'id' in session and session['id'] is not None:
            conn.execute('UPDATE sessions SET name = ? WHERE id = ?', (session['name'], session['id']))
        else:
            cur = conn.execute('INSERT INTO sessions (name) VALUES (?)', (session['name'],))
            session['id'] = cur.lastrowid
        conn.execute('DELETE FROM messages WHERE session_id = ?', (session['id'],))
        conn.execute('DELETE FROM history WHERE session_id = ?', (session['id'],))
        for msg in session['messages']:
            conn.execute(
                'INSERT INTO messages (session_id, sender, content) VALUES (?, ?, ?)',
                (session['id'], msg['sender'], msg['text'])
            )
        conn.execute(
            'INSERT INTO history (session_id, history_json) VALUES (?, ?)',
            (session['id'], json.dumps(session['history']))
        )
        conn.commit()
    finally:
        conn.close()
    return session['id']

def delete_session(session_id):
    conn = get_connection()
    try:
        conn.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
        conn.commit()
    finally:
        conn.close()

init_db()