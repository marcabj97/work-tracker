"""
database.py — All SQLite read/write operations for the Work Tracker.
"""

import sqlite3

DB_PATH = "work_tracker.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables if they don't exist. Safe to run multiple times."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,
            title       TEXT NOT NULL,
            description TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id   TEXT UNIQUE NOT NULL,
            subject      TEXT,
            sender       TEXT,
            received_at  TEXT,
            body_preview TEXT,
            fetched_at   TEXT DEFAULT (datetime('now'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS teams_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id  TEXT UNIQUE NOT NULL,
            chat_name   TEXT,
            sender      TEXT,
            content     TEXT,
            sent_at     TEXT,
            fetched_at  TEXT DEFAULT (datetime('now'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS browser_activity (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            url              TEXT,
            title            TEXT,
            visit_time       TEXT,
            domain           TEXT,
            duration_minutes REAL DEFAULT 0,
            duration_display TEXT DEFAULT '',
            is_meeting       INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Daily notes — one per day, free text scratchpad
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            date       TEXT UNIQUE NOT NULL,
            content    TEXT DEFAULT '',
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.commit()

    # Migrate existing browser_activity table if is_meeting column is missing
    try:
        cursor.execute("ALTER TABLE browser_activity ADD COLUMN is_meeting INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass  # Column already exists

    conn.close()
    print("Database ready.")


# ─── TASKS ────────────────────────────────────────────────────────────────────

def add_task(date, title, description=""):
    conn = get_connection()
    conn.execute("INSERT INTO tasks (date, title, description) VALUES (?, ?, ?)", (date, title, description))
    conn.commit()
    conn.close()


def delete_task(task_id):
    conn = get_connection()
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()


def get_tasks_for_date(date):
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, title, description, created_at FROM tasks WHERE date = ? ORDER BY created_at", (date,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── BROWSER ACTIVITY ─────────────────────────────────────────────────────────

def save_browser_activity(visits):
    conn = get_connection()
    for visit in visits:
        conn.execute("""
            INSERT INTO browser_activity
              (url, title, visit_time, domain, duration_minutes, duration_display, is_meeting)
            VALUES (:url, :title, :visit_time, :domain, :duration_minutes, :duration_display, :is_meeting)
        """, visit)
    conn.commit()
    conn.close()


def save_emails(emails):
    conn = get_connection()
    for email in emails:
        conn.execute("""
            INSERT OR IGNORE INTO emails (message_id, subject, sender, received_at, body_preview)
            VALUES (:message_id, :subject, :sender, :received_at, :body_preview)
        """, email)
    conn.commit()
    conn.close()


def save_teams_messages(messages):
    conn = get_connection()
    for msg in messages:
        conn.execute("""
            INSERT OR IGNORE INTO teams_messages (message_id, chat_name, sender, content, sent_at)
            VALUES (:message_id, :chat_name, :sender, :content, :sent_at)
        """, msg)
    conn.commit()
    conn.close()


def clear_browser_activity_for_date(date):
    conn = get_connection()
    conn.execute("DELETE FROM browser_activity WHERE visit_time LIKE ?", (f"{date}%",))
    conn.commit()
    conn.close()


# ─── TIMELINE ─────────────────────────────────────────────────────────────────

def get_day_timeline(date):
    conn = get_connection()
    events = []

    for row in conn.execute(
        "SELECT id, title, description, created_at FROM tasks WHERE date = ? ORDER BY created_at", (date,)
    ):
        events.append({
            "type": "task", "time": row["created_at"],
            "title": row["title"], "detail": row["description"] or "", "id": row["id"]
        })

    for row in conn.execute(
        "SELECT title, url, visit_time, domain, duration_minutes, duration_display, is_meeting "
        "FROM browser_activity WHERE visit_time LIKE ? ORDER BY visit_time", (f"{date}%",)
    ):
        events.append({
            "type": "browser", "time": row["visit_time"],
            "title": row["title"] or row["url"], "detail": row["url"],
            "domain": row["domain"] or "",
            "duration_minutes": row["duration_minutes"] or 0,
            "duration_display": row["duration_display"] or "",
            "is_meeting": bool(row["is_meeting"]),
            "id": None
        })

    conn.close()
    events.sort(key=lambda e: e["time"] or "")
    return events


# ─── MEETINGS ─────────────────────────────────────────────────────────────────

def get_meetings_for_date(date):
    """Return browser visits flagged as meetings for a given date."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT title, url, visit_time, duration_display FROM browser_activity "
        "WHERE visit_time LIKE ? AND is_meeting = 1 ORDER BY visit_time",
        (f"{date}%",)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── DAILY NOTES ──────────────────────────────────────────────────────────────

def get_note(date):
    """Get the daily note for a date. Returns empty string if none."""
    conn = get_connection()
    row = conn.execute("SELECT content FROM daily_notes WHERE date = ?", (date,)).fetchone()
    conn.close()
    return row["content"] if row else ""


def save_note(date, content):
    """Save or update the daily note for a date."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO daily_notes (date, content, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(date) DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at
    """, (date, content))
    conn.commit()
    conn.close()


# ─── SEARCH ───────────────────────────────────────────────────────────────────

def search(query):
    """
    Search tasks, browser history titles, and daily notes for a query string.
    Returns a list of result dicts sorted by date descending.
    Each dict has: date, type, title, detail
    """
    q = f"%{query}%"
    conn = get_connection()
    results = []

    # Search tasks
    for row in conn.execute(
        "SELECT date, title, description FROM tasks WHERE title LIKE ? OR description LIKE ? ORDER BY date DESC",
        (q, q)
    ):
        results.append({
            "date": row["date"], "type": "task",
            "title": row["title"], "detail": row["description"] or ""
        })

    # Search browser history
    for row in conn.execute(
        "SELECT DATE(visit_time) as date, title, url FROM browser_activity "
        "WHERE title LIKE ? OR url LIKE ? GROUP BY title, DATE(visit_time) ORDER BY date DESC",
        (q, q)
    ):
        results.append({
            "date": row["date"], "type": "browser",
            "title": row["title"] or row["url"], "detail": row["url"]
        })

    # Search daily notes
    for row in conn.execute(
        "SELECT date, content FROM daily_notes WHERE content LIKE ? ORDER BY date DESC", (q,)
    ):
        results.append({
            "date": row["date"], "type": "note",
            "title": f"Note on {row['date']}",
            "detail": row["content"][:200]
        })

    conn.close()
    results.sort(key=lambda r: r["date"] or "", reverse=True)
    return results


# ─── SETTINGS ─────────────────────────────────────────────────────────────────

def get_setting(key, default=None):
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


# ─── DOMAIN SUMMARY ───────────────────────────────────────────────────────────

def get_domain_summary(date):
    conn = get_connection()
    rows = conn.execute("""
        SELECT domain, SUM(duration_minutes) as total_minutes, COUNT(*) as visit_count
        FROM browser_activity WHERE visit_time LIKE ?
        GROUP BY domain ORDER BY total_minutes DESC
    """, (f"{date}%",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
