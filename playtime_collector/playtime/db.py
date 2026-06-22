"""SQLite storage.

The schema is multi-platform and multi-account from the start, so the same
store can later hold push-based platforms next to PS3. Playtime is kept as
rows in `sessions`; totals are computed on read. At most one session per
(platform, account) is open at a time.
"""
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config

lock = threading.Lock()
conn = None


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    global conn
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            platform    TEXT NOT NULL,
            account     TEXT NOT NULL,
            title_id    TEXT NOT NULL,
            title       TEXT,
            started_at  TEXT NOT NULL,
            ended_at    TEXT NOT NULL,
            seconds     INTEGER NOT NULL DEFAULT 0,
            is_open     INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_open ON sessions (platform, account, is_open);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS trophies (
            platform        TEXT NOT NULL,
            account         TEXT NOT NULL,
            npcommid        TEXT NOT NULL,
            title           TEXT,
            earned_json     TEXT NOT NULL,
            total_json      TEXT NOT NULL,
            earned_count    INTEGER NOT NULL,
            total_count     INTEGER NOT NULL,
            last_earned_at  TEXT,
            updated_at      TEXT NOT NULL,
            PRIMARY KEY (platform, account, npcommid)
        );
        CREATE TABLE IF NOT EXISTS trophy_items (
            platform   TEXT NOT NULL,
            account    TEXT NOT NULL,
            npcommid   TEXT NOT NULL,
            trophy_id  INTEGER NOT NULL,
            name       TEXT,
            detail     TEXT,
            grade      TEXT NOT NULL,
            hidden     INTEGER NOT NULL,
            unlocked   INTEGER NOT NULL,
            earned_at  TEXT,
            PRIMARY KEY (platform, account, npcommid, trophy_id)
        );
        """
    )
    conn.commit()
    set_meta_if_absent("tracked_since", now_iso())


def set_meta(key, value):
    with lock:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


def set_meta_if_absent(key, value):
    with lock:
        conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", (key, value))
        conn.commit()


def get_meta(key):
    with lock:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def get_open_session(platform):
    """The single in-progress session for a platform (only one game runs at a time)."""
    with lock:
        return conn.execute(
            "SELECT * FROM sessions WHERE platform = ? AND is_open = 1 "
            "ORDER BY id DESC LIMIT 1",
            (platform,),
        ).fetchone()


def close_open_sessions(platform):
    with lock:
        conn.execute(
            "UPDATE sessions SET is_open = 0 WHERE platform = ? AND is_open = 1",
            (platform,),
        )
        conn.commit()


def open_session(platform, account, title_id, title, seconds, when):
    with lock:
        conn.execute(
            "UPDATE sessions SET is_open = 0 WHERE platform = ? AND is_open = 1",
            (platform,),
        )
        conn.execute(
            "INSERT INTO sessions "
            "(platform, account, title_id, title, started_at, ended_at, seconds, is_open) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (platform, account, title_id, title, when, when, max(seconds, 0)),
        )
        conn.commit()


def update_open_session(session_id, seconds, title, when):
    with lock:
        conn.execute(
            "UPDATE sessions SET seconds = ?, title = COALESCE(?, title), ended_at = ? "
            "WHERE id = ?",
            (max(seconds, 0), title, when, session_id),
        )
        conn.commit()


def insert_closed_session(platform, account, title_id, title, seconds, when):
    """Used by /ingest for push-based platforms."""
    with lock:
        conn.execute(
            "INSERT INTO sessions "
            "(platform, account, title_id, title, started_at, ended_at, seconds, is_open) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (platform, account, title_id, title, when, when, max(seconds, 0)),
        )
        conn.commit()


def time_filter(platform, frm, to):
    """Build a WHERE clause filtering by platform and the session start time.

    `frm`/`to` are ISO timestamps or dates (YYYY-MM-DD). Because timestamps are
    stored as UTC ISO strings, lexicographic comparison gives the right window:
    `started_at >= frm AND started_at < to` (to is exclusive).
    """
    conditions = []
    params = []
    if platform:
        conditions.append("platform = ?")
        params.append(platform)
    if frm:
        conditions.append("started_at >= ?")
        params.append(frm)
    if to:
        conditions.append("started_at < ?")
        params.append(to)
    clause = ("WHERE " + " AND ".join(conditions) + " ") if conditions else ""
    return clause, params


def totals(platform=None, frm=None, to=None):
    clause, params = time_filter(platform, frm, to)
    sql = (
        "SELECT platform, account, title_id, "
        "MAX(title) AS title, "
        "SUM(seconds) AS total_seconds, "
        "COUNT(*) AS sessions, "
        "MIN(started_at) AS first_played, "
        "MAX(ended_at) AS last_played "
        "FROM sessions " + clause +
        "GROUP BY platform, account, title_id ORDER BY total_seconds DESC"
    )
    with lock:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def summary(platform=None, frm=None, to=None):
    clause, params = time_filter(platform, frm, to)
    with lock:
        row = conn.execute(
            "SELECT COALESCE(SUM(seconds), 0) AS seconds, COUNT(*) AS sessions "
            "FROM sessions " + clause,
            params,
        ).fetchone()
        playing = conn.execute(
            "SELECT COUNT(*) AS playing FROM sessions WHERE is_open = 1"
            + (" AND platform = ?" if platform else ""),
            (platform,) if platform else (),
        ).fetchone()
    return {
        "seconds_total": row["seconds"],
        "sessions_total": row["sessions"],
        "playing_count": playing["playing"],
    }


def open_sessions(platform=None):
    """Sessions currently in progress (independent of any time range)."""
    where = "WHERE is_open = 1" + (" AND platform = ?" if platform else "")
    params = (platform,) if platform else ()
    with lock:
        rows = conn.execute(
            "SELECT platform, account, title_id, title, "
            "seconds AS total_seconds, 1 AS sessions, "
            "started_at AS first_played, ended_at AS last_played "
            "FROM sessions " + where,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_trophies(platform, account, summary):
    import json
    with lock:
        conn.execute(
            "INSERT INTO trophies (platform, account, npcommid, title, earned_json, "
            "total_json, earned_count, total_count, last_earned_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(platform, account, npcommid) DO UPDATE SET "
            "title=excluded.title, earned_json=excluded.earned_json, "
            "total_json=excluded.total_json, earned_count=excluded.earned_count, "
            "total_count=excluded.total_count, last_earned_at=excluded.last_earned_at, "
            "updated_at=excluded.updated_at",
            (
                platform, account, summary["npcommid"], summary["title"],
                json.dumps(summary["earned"]), json.dumps(summary["total"]),
                summary["earnedCount"], summary["totalCount"],
                summary["lastEarnedAt"], now_iso(),
            ),
        )
        conn.commit()


def query_trophies(platform=None, account=None):
    import json
    where = []
    params = []
    if platform:
        where.append("platform = ?")
        params.append(platform)
    if account:
        where.append("account = ?")
        params.append(account)
    clause = ("WHERE " + " AND ".join(where) + " ") if where else ""
    with lock:
        rows = conn.execute(
            "SELECT * FROM trophies " + clause + "ORDER BY earned_count DESC", params
        ).fetchall()
    result = []
    for row in rows:
        result.append({
            "platform": row["platform"],
            "account": row["account"],
            "npcommid": row["npcommid"],
            "title": row["title"],
            "earned": json.loads(row["earned_json"]),
            "total": json.loads(row["total_json"]),
            "earnedCount": row["earned_count"],
            "totalCount": row["total_count"],
            "lastEarnedAt": row["last_earned_at"],
            "updatedAt": row["updated_at"],
        })
    return result


def upsert_trophy_items(platform, account, npcommid, items):
    with lock:
        conn.execute(
            "DELETE FROM trophy_items WHERE platform=? AND account=? AND npcommid=?",
            (platform, account, npcommid),
        )
        conn.executemany(
            "INSERT INTO trophy_items "
            "(platform, account, npcommid, trophy_id, name, detail, grade, hidden, unlocked, earned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (platform, account, npcommid, it["id"], it["name"], it["detail"],
                 it["grade"], int(it["hidden"]), int(it["unlocked"]), it["earnedAt"])
                for it in items
            ],
        )
        conn.commit()


def query_trophy_items(platform, account, npcommid):
    with lock:
        rows = conn.execute(
            "SELECT * FROM trophy_items WHERE platform=? AND account=? AND npcommid=? "
            "ORDER BY trophy_id",
            (platform, account, npcommid),
        ).fetchall()
    return [
        {
            "id": r["trophy_id"],
            "name": r["name"],
            "detail": r["detail"],
            "grade": r["grade"],
            "hidden": bool(r["hidden"]),
            "unlocked": bool(r["unlocked"]),
            "earnedAt": r["earned_at"],
        }
        for r in rows
    ]


def delete_sessions(account):
    with lock:
        cur = conn.execute("DELETE FROM sessions WHERE account = ?", (account,))
        conn.commit()
        return cur.rowcount


def list_sessions(platform=None, frm=None, to=None, limit=500):
    """Raw session rows for arbitrary downstream aggregation."""
    clause, params = time_filter(platform, frm, to)
    with lock:
        rows = conn.execute(
            "SELECT platform, account, title_id, title, started_at, ended_at, "
            "seconds, is_open FROM sessions " + clause +
            "ORDER BY started_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
    return [dict(row) for row in rows]
