import os
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(os.environ.get("ADS_COACH_DB", Path(__file__).resolve().parent.parent / "data" / "coach.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS values_ (
    user TEXT NOT NULL, exp_id TEXT NOT NULL, cp_id TEXT NOT NULL,
    value REAL NOT NULL, ts REAL NOT NULL,
    PRIMARY KEY (user, exp_id, cp_id)
);
CREATE TABLE IF NOT EXISTS params (
    user TEXT NOT NULL, exp_id TEXT NOT NULL, key TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (user, exp_id, key)
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT NOT NULL, exp_id TEXT, symptom TEXT NOT NULL,
    cause TEXT, ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS steps (
    user TEXT NOT NULL, exp_id TEXT NOT NULL, step_idx INTEGER NOT NULL,
    done INTEGER NOT NULL, ts REAL NOT NULL,
    PRIMARY KEY (user, exp_id, step_idx)
);
CREATE TABLE IF NOT EXISTS exp_start (
    user TEXT NOT NULL, exp_id TEXT NOT NULL, ts REAL NOT NULL,
    PRIMARY KEY (user, exp_id)
);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def save_value(conn, user, exp_id, cp_id, value):
    conn.execute(
        "INSERT INTO values_ VALUES (?,?,?,?,?) "
        "ON CONFLICT(user, exp_id, cp_id) DO UPDATE SET value=excluded.value, ts=excluded.ts",
        (user, exp_id, cp_id, float(value), time.time()),
    )
    conn.commit()


def load_values(conn, user, exp_id) -> dict:
    rows = conn.execute("SELECT cp_id, value FROM values_ WHERE user=? AND exp_id=?", (user, exp_id))
    return dict(rows.fetchall())


def save_param(conn, user, exp_id, key, value):
    conn.execute(
        "INSERT INTO params VALUES (?,?,?,?) "
        "ON CONFLICT(user, exp_id, key) DO UPDATE SET value=excluded.value",
        (user, exp_id, key, float(value)),
    )
    conn.commit()


def load_params(conn, user, exp_id) -> dict:
    rows = conn.execute("SELECT key, value FROM params WHERE user=? AND exp_id=?", (user, exp_id))
    return dict(rows.fetchall())


def add_report(conn, user, exp_id, symptom, cause):
    conn.execute(
        "INSERT INTO reports (user, exp_id, symptom, cause, ts) VALUES (?,?,?,?,?)",
        (user, exp_id, symptom, cause, time.time()),
    )
    conn.commit()


def list_reports(conn) -> list:
    return conn.execute(
        "SELECT user, exp_id, symptom, cause, ts FROM reports ORDER BY ts DESC"
    ).fetchall()


def progress_overview(conn) -> list:
    return conn.execute(
        "SELECT user, exp_id, SUM(cp), MAX(ts) FROM ("
        "  SELECT user, exp_id, 1 AS cp, ts FROM values_"
        "  UNION ALL"
        "  SELECT user, exp_id, 0 AS cp, ts FROM steps WHERE done=1"
        ") GROUP BY user, exp_id ORDER BY user"
    ).fetchall()


def save_step(conn, user, exp_id, step_idx, done):
    conn.execute(
        "INSERT INTO steps VALUES (?,?,?,?,?) "
        "ON CONFLICT(user, exp_id, step_idx) DO UPDATE SET done=excluded.done, ts=excluded.ts",
        (user, exp_id, int(step_idx), 1 if done else 0, time.time()),
    )
    conn.commit()


def load_steps(conn, user, exp_id) -> dict:
    rows = conn.execute(
        "SELECT step_idx, done FROM steps WHERE user=? AND exp_id=?", (user, exp_id)
    )
    return {idx: bool(done) for idx, done in rows}


def step_counts(conn, user) -> dict:
    rows = conn.execute(
        "SELECT exp_id, COUNT(*) FROM steps WHERE user=? AND done=1 GROUP BY exp_id", (user,)
    )
    return dict(rows)


def get_or_create_start(conn, user, exp_id) -> float:
    row = conn.execute(
        "SELECT ts FROM exp_start WHERE user=? AND exp_id=?", (user, exp_id)
    ).fetchone()
    if row:
        return float(row[0])
    ts = time.time()
    conn.execute("INSERT INTO exp_start VALUES (?,?,?)", (user, exp_id, ts))
    conn.commit()
    return ts


def reset_experiment(conn, user, exp_id):
    """清空该实验的步骤进度并把自动检测起点重置为现在。"""
    conn.execute("DELETE FROM steps WHERE user=? AND exp_id=?", (user, exp_id))
    conn.execute(
        "INSERT INTO exp_start VALUES (?,?,?) "
        "ON CONFLICT(user, exp_id) DO UPDATE SET ts=excluded.ts",
        (user, exp_id, time.time()),
    )
    conn.commit()


def repair_exp02_final_step(conn, user):
    """Reset the legacy false positive once, retaining its previous value."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS exp02_step5_repair ("
        "user TEXT PRIMARY KEY, previous_done INTEGER, previous_ts REAL)"
    )
    if conn.execute("SELECT 1 FROM exp02_step5_repair WHERE user=?", (user,)).fetchone():
        return False
    row = conn.execute(
        "SELECT done, ts FROM steps WHERE user=? AND exp_id=? AND step_idx=4",
        (user, "exp02_transmission_line"),
    ).fetchone()
    conn.execute("INSERT INTO exp02_step5_repair VALUES (?,?,?)", (user, *(row or (None, None))))
    conn.execute(
        "DELETE FROM steps WHERE user=? AND exp_id=? AND step_idx=4",
        (user, "exp02_transmission_line"),
    )
    conn.commit()
    return True


def set_detection_start(conn, user, exp_id, ts):
    conn.execute(
        "INSERT INTO exp_start VALUES (?,?,?) "
        "ON CONFLICT(user, exp_id) DO UPDATE SET ts=excluded.ts",
        (user, exp_id, float(ts)),
    )
    conn.commit()
