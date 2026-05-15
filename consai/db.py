import sqlite3
import logging
from contextlib import contextmanager
from consai.config import DB_PATH

logger = logging.getLogger(__name__)

# ── Connection ────────────────────────────────────────────────────────────────

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ── Schema ────────────────────────────────────────────────────────────────────

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS photos (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                filename            TEXT NOT NULL UNIQUE,
                filepath            TEXT NOT NULL,
                backup_path         TEXT,
                pr_path             TEXT,
                th_path             TEXT,
                captured_at         TEXT NOT NULL,
                size_bytes          INTEGER,
                width               INTEGER,
                height              INTEGER,

                -- metadata
                unit_id             TEXT,
                installation_id     TEXT,
                camera_type         TEXT,
                lat                 REAL,
                lon                 REAL,
                location_name       TEXT,
                weather_temp        REAL,
                weather_desc        TEXT,
                weather_humidity    INTEGER,
                capture_freq        INTEGER,

                -- sync state
                uploaded            INTEGER DEFAULT 0,
                uploaded_pr         INTEGER DEFAULT 0,
                uploaded_th         INTEGER DEFAULT 0,
                upload_attempts     INTEGER DEFAULT 0,
                uploaded_at         TEXT,
                synced_to_api       INTEGER DEFAULT 0,
                api_attempts        INTEGER DEFAULT 0,
                synced_at           TEXT,
                error_msg           TEXT
            );

            CREATE TABLE IF NOT EXISTS system_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                event_time  TEXT NOT NULL DEFAULT (datetime('now')),
                level       TEXT NOT NULL,
                service     TEXT NOT NULL,
                message     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        migrate_db()
    logger.info(f"Database initialised at {DB_PATH}")

# ── Photos ────────────────────────────────────────────────────────────────────

def insert_photo(data: dict) -> int:
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    sql = f"INSERT OR IGNORE INTO photos ({cols}) VALUES ({placeholders})"
    with get_db() as conn:
        cur = conn.execute(sql, list(data.values()))
        return cur.lastrowid

def get_pending_uploads(limit: int = 10) -> list:
    from consai.config import INSTALLATION_ID
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM photos
            WHERE uploaded = 0 
            AND upload_attempts < 5
            AND installation_id = ?
            ORDER BY captured_at ASC
            LIMIT ?
        """, (INSTALLATION_ID, limit)).fetchall()
        return [dict(r) for r in rows]

def get_pending_api_sync(limit: int = 10) -> list:
    from consai.config import INSTALLATION_ID
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM photos
            WHERE uploaded = 1
              AND uploaded_pr = 1
              AND uploaded_th = 1
              AND synced_to_api = 0
              AND api_attempts < 5
              AND installation_id = ?
            ORDER BY captured_at ASC
            LIMIT ?
        """, (INSTALLATION_ID, limit)).fetchall()
        return [dict(r) for r in rows]

def get_pending_preview_generation(limit: int = 10) -> list:
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM photos
            WHERE pr_path IS NULL
            ORDER BY captured_at ASC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

def mark_uploaded(photo_id: int, error: str = None):
    with get_db() as conn:
        if error:
            conn.execute("""
                UPDATE photos
                SET upload_attempts = upload_attempts + 1,
                    error_msg = ?
                WHERE id = ?
            """, (error, photo_id))
        else:
            conn.execute("""
                UPDATE photos
                SET uploaded = 1,
                    uploaded_at = datetime('now'),
                    upload_attempts = upload_attempts + 1,
                    error_msg = NULL
                WHERE id = ?
            """, (photo_id,))

def mark_uploaded_pr(photo_id: int):
    with get_db() as conn:
        conn.execute(
            "UPDATE photos SET uploaded_pr = 1 WHERE id = ?",
            (photo_id,)
        )

def mark_uploaded_th(photo_id: int):
    with get_db() as conn:
        conn.execute(
            "UPDATE photos SET uploaded_th = 1 WHERE id = ?",
            (photo_id,)
        )

def mark_previews_generated(photo_id: int, pr_path: str, th_path: str):
    with get_db() as conn:
        conn.execute("""
            UPDATE photos SET pr_path = ?, th_path = ? WHERE id = ?
        """, (pr_path, th_path, photo_id))

def mark_synced(photo_id: int, error: str = None):
    with get_db() as conn:
        if error:
            conn.execute("""
                UPDATE photos
                SET api_attempts = api_attempts + 1,
                    error_msg = ?
                WHERE id = ?
            """, (error, photo_id))
        else:
            conn.execute("""
                UPDATE photos
                SET synced_to_api = 1,
                    synced_at = datetime('now'),
                    api_attempts = api_attempts + 1,
                    error_msg = NULL
                WHERE id = ?
            """, (photo_id,))

def get_photo_count() -> int:
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]

def get_last_capture() -> dict | None:
    with get_db() as conn:
        row = conn.execute("""
            SELECT * FROM photos ORDER BY captured_at DESC LIMIT 1
        """).fetchone()
        return dict(row) if row else None

def get_pending_count() -> dict:
    from consai.config import INSTALLATION_ID
    with get_db() as conn:
        r = conn.execute("""
            SELECT
                SUM(CASE WHEN uploaded = 0 THEN 1 ELSE 0 END) as pending_upload,
                SUM(CASE WHEN uploaded = 1 AND synced_to_api = 0 THEN 1 ELSE 0 END) as pending_sync
            FROM photos
            WHERE installation_id = ?
        """, (INSTALLATION_ID,)).fetchone()
        return {"pending_upload": r[0] or 0, "pending_sync": r[1] or 0}

# ── System events ─────────────────────────────────────────────────────────────

def log_event(service: str, message: str, level: str = "INFO"):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO system_events (level, service, message)
            VALUES (?, ?, ?)
        """, (level, service, message))

# ── Settings ──────────────────────────────────────────────────────────────────

def get_setting(key: str, default: str = None) -> str | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default

def set_setting(key: str, value: str):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
        """, (key, value))

def migrate_db():
    """Run any needed schema migrations."""
    with get_db() as conn:
        # Add installation_id column if missing
        try:
            conn.execute("ALTER TABLE photos ADD COLUMN installation_id TEXT")
            logger.info("Migration: added installation_id column")
        except Exception:
            pass  # Column already exists

        # Backfill installation_id from filename
        # filename format: UNITID_INSTALLID_TIMESTAMP.jpg
        conn.execute("""
            UPDATE photos
            SET installation_id = SUBSTR(filename, 6, 4)
            WHERE installation_id IS NULL
            AND LENGTH(filename) >= 10
        """)
        logger.info("Migration: backfilled installation_id from filenames")


def get_photo_count_for_installation(installation_id: str) -> int:
    with get_db() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM photos WHERE installation_id = ?",
            (installation_id,)
        ).fetchone()[0]
# ── Init on import ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    log_event("db", "Database initialised and ready")
    print(f"✅ DB ready at {DB_PATH}")
    print(f"   Photos: {get_photo_count()}")
    print(f"   Pending: {get_pending_count()}")

def migrate_db():
    """Run any needed schema migrations."""
    with get_db() as conn:
        # Add installation_id column if missing
        try:
            conn.execute("ALTER TABLE photos ADD COLUMN installation_id TEXT")
            logger.info("Migration: added installation_id column")
        except Exception:
            pass  # Column already exists

        # Backfill installation_id from filename
        conn.execute("""
            UPDATE photos
            SET installation_id = SUBSTR(filename, 6, 4)
            WHERE installation_id IS NULL
            AND LENGTH(filename) > 9
        """)
        logger.info("Migration: backfilled installation_id from filenames")