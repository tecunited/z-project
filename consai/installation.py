import sqlite3
import shutil
import logging
from pathlib import Path
from datetime import datetime

from consai.config import BASE_DIR, UNIT_ID

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────

UNIT_CONFIG_DB   = BASE_DIR / "logs" / "unit_config.sqlite"
ACTIVE_DB_DIR    = BASE_DIR / "logs" / "active"
ARCHIVE_DB_DIR   = BASE_DIR / "logs" / "archive"
PHOTOS_DIR       = BASE_DIR / "photos"
PHOTOS_BACKUP    = BASE_DIR / "photos_backup"
PHOTOS_ARCHIVE   = BASE_DIR / "photos_archive"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _folder_size_mb(path: Path) -> float:
    try:
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return round(total / 1024 / 1024, 1)
    except Exception:
        return 0.0

def _count_photos_in_folder(path: Path) -> int:
    try:
        return len(list(path.glob("*.jpg")))
    except Exception:
        return 0

# ── Unit config DB ────────────────────────────────────────────────────────────

def _get_config_db():
    UNIT_CONFIG_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(UNIT_CONFIG_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS unit_config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

def get_config(key: str, default: str = None) -> str | None:
    conn = _get_config_db()
    try:
        row = conn.execute(
            "SELECT value FROM unit_config WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default
    finally:
        conn.close()

def set_config(key: str, value: str):
    conn = _get_config_db()
    try:
        conn.execute("""
            INSERT INTO unit_config (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        conn.commit()
    finally:
        conn.close()

# ── Installation management ───────────────────────────────────────────────────

def get_current_installation_id() -> str:
    return get_config("current_install", "0000")

def get_install_counter() -> int:
    return int(get_config("install_counter", "0"))

def get_unit_id() -> str:
    return get_config("unit_id", UNIT_ID)

def init_unit_config():
    """Initialize unit config on first run."""
    if not get_config("unit_id"):
        set_config("unit_id", UNIT_ID)
    if not get_config("install_counter"):
        set_config("install_counter", "0")
    if not get_config("current_install"):
        set_config("current_install", "0000")
    if not get_config("provisioned_at"):
        set_config("provisioned_at", datetime.now().isoformat())
    logger.info(f"Unit config initialized — unit {UNIT_ID}")

# ── Installation list ─────────────────────────────────────────────────────────

def get_installation_list() -> list:
    installations = []
    current = get_current_installation_id()

    # Active installation
    from consai.db import get_pending_count, get_photo_count_for_installation
    db_count = get_photo_count_for_installation(current)
    size_mb  = _folder_size_mb(PHOTOS_DIR)
    pending  = get_pending_count()
    installations.append({
        "id":          current,
        "status":      "active",
        "photo_count": db_count,
        "pending":     pending["pending_upload"],
        "size_mb":     size_mb,
        "has_photos":  db_count > 0,
        "backed_up":   False,
    })

    # Archived installations from current DB
    try:
        import sqlite3 as _sq
        from consai.config import DB_PATH
        conn = _sq.connect(DB_PATH)
        rows = conn.execute("""
            SELECT installation_id, COUNT(*)
            FROM photos
            WHERE installation_id != ?
            GROUP BY installation_id
            ORDER BY installation_id ASC
        """, (current,)).fetchall()
        conn.close()

        for install_id, count in rows:
            archive_photos = PHOTOS_ARCHIVE / install_id
            size_mb   = _folder_size_mb(archive_photos)
            has_files = _count_photos_in_folder(archive_photos) > 0
            installations.append({
                "id":          install_id,
                "status":      "archived",
                "photo_count": count,
                "pending":     0,
                "size_mb":     size_mb,
                "has_photos":  has_files,
                "backed_up":   not has_files,
            })
    except Exception as e:
        logger.error(f"Error reading archived installations: {e}")

    # Check archive DBs — each may contain multiple installation IDs
    ARCHIVE_DB_DIR.mkdir(parents=True, exist_ok=True)
    for db_file in sorted(ARCHIVE_DB_DIR.glob(f"{UNIT_ID}_*_db.sqlite")):
        try:
            import sqlite3 as _sq
            conn = _sq.connect(db_file)
            rows = conn.execute("""
                SELECT installation_id, COUNT(*)
                FROM photos
                GROUP BY installation_id
                ORDER BY installation_id ASC
            """).fetchall()
            conn.close()

            for install_id, count in rows:
                if any(i["id"] == install_id for i in installations):
                    continue
                archive_photos = PHOTOS_ARCHIVE / install_id
                has_files = _count_photos_in_folder(archive_photos) > 0
                installations.append({
                    "id": install_id,
                    "status": "archived",
                    "photo_count": count,
                    "pending": 0,
                    "size_mb": _folder_size_mb(archive_photos),
                    "has_photos": has_files,
                    "backed_up": not has_files,
                })
        except Exception as e:
            logger.error(f"Error reading archive DB {db_file}: {e}")

    return installations

# ── New installation ──────────────────────────────────────────────────────────

def start_new_installation(progress_callback=None) -> str:
    """Archive current installation and start a new one."""
    current = get_current_installation_id()
    counter = get_install_counter()

    # Archive current DB
    if progress_callback:
        progress_callback("Archiving DB...")
    _archive_current_db(current)

    # Archive current photos
    if progress_callback:
        progress_callback("Archiving photos...")
    _archive_current_photos(current)

    # Increment counter and set new ID
    new_counter = counter + 1
    new_id = f"{new_counter:04d}"
    set_config("install_counter", str(new_counter))
    set_config("current_install", new_id)

    # Update .env
    if progress_callback:
        progress_callback("Updating config...")
    _update_env_installation_id(new_id)

    # Create fresh DB
    if progress_callback:
        progress_callback("Creating fresh DB...")
    _create_fresh_db(new_id)

    logger.info(f"New installation started: {new_id}")
    return new_id

def _archive_current_db(install_id: str):
    """Move current active DB to archive."""
    from consai.config import DB_PATH
    ARCHIVE_DB_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DB_DIR / f"{UNIT_ID}_{install_id}_db.sqlite"
    if DB_PATH.exists():
        shutil.move(str(DB_PATH), str(archive_path))
        logger.info(f"DB archived: {archive_path}")

def _archive_current_photos(install_id: str):
    """Move current photos to archive folder. Never deletes without archiving."""
    dest = PHOTOS_ARCHIVE / install_id
    dest.mkdir(parents=True, exist_ok=True)

    moved = 0
    for src in list(PHOTOS_DIR.glob("*.jpg")):
        dst = dest / src.name
        shutil.move(str(src), str(dst))
        moved += 1

    for src in list(PHOTOS_BACKUP.glob("*.jpg")):
        dst = dest / src.name
        if not dst.exists():
            shutil.move(str(src), str(dst))
        else:
            src.unlink()

    logger.info(f"Archived {moved} photos to {dest}")

def _update_env_installation_id(new_id: str):
    """Update INSTALLATION_ID in .env file."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    content = env_path.read_text()
    lines = content.splitlines()
    new_lines = []
    found = False
    for line in lines:
        if line.startswith("INSTALLATION_ID="):
            new_lines.append(f"INSTALLATION_ID={new_id}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"INSTALLATION_ID={new_id}")
    env_path.write_text("\n".join(new_lines) + "\n")
    logger.info(f"Updated .env INSTALLATION_ID={new_id}")

def _create_fresh_db(install_id: str):
    """Initialize a fresh SQLite DB for the new installation."""
    from consai.db import init_db
    init_db()
    # Verify it worked
    from consai.db import get_photo_count_for_installation
    get_photo_count_for_installation(install_id)
    logger.info(f"Fresh DB created and verified for installation {install_id}")

# ── Backup archive photos to USB ──────────────────────────────────────────────

def backup_archive_to_usb(install_id: str, progress_callback=None) -> dict:
    """Backup archived photos for a specific installation to USB."""
    from consai.usb import mount_usb, unmount_usb, get_usb_free_mb, MOUNT_POINT
    import subprocess

    archive_path = PHOTOS_ARCHIVE / install_id
    if not archive_path.exists():
        return {"error": f"No archive found for {install_id}"}

    if not mount_usb():
        return {"error": "Could not mount USB"}

    dest_name = f"{UNIT_ID}_{install_id}"
    dest = MOUNT_POINT / dest_name
    subprocess.run(["sudo", "mkdir", "-p", str(dest)], capture_output=True)

    files   = sorted(archive_path.glob("*.jpg"))
    total   = len(files)
    copied  = 0
    skipped = 0

    for i, src in enumerate(files):
        if progress_callback:
            progress_callback(i + 1, total, src.name)
        if get_usb_free_mb() < 50:
            break
        dst = dest / src.name
        if dst.exists():
            skipped += 1
            continue
        result = subprocess.run(
            ["sudo", "cp", str(src), str(dst)],
            capture_output=True
        )
        if result.returncode == 0:
            copied += 1

    unmount_usb()
    return {"copied": copied, "skipped": skipped, "total": total}

def delete_archive_photos(install_id: str) -> int:
    """Delete archived photos for an installation."""
    archive_path = PHOTOS_ARCHIVE / install_id
    deleted = 0
    if archive_path.exists():
        for f in archive_path.glob("*.jpg"):
            f.unlink()
            deleted += 1
    logger.info(f"Deleted {deleted} archived photos for {install_id}")
    return deleted

# ── Factory reset ─────────────────────────────────────────────────────────────

def factory_reset(progress_callback=None) -> bool:
    """Full wipe. Keeps unit_config.sqlite permanently."""
    try:
        current = get_current_installation_id()

        if progress_callback:
            progress_callback("Archiving current...")
        _archive_current_db(current)
        _archive_current_photos(current)

        if progress_callback:
            progress_callback("Wiping archives...")
        if PHOTOS_ARCHIVE.exists():
            shutil.rmtree(PHOTOS_ARCHIVE)
        PHOTOS_ARCHIVE.mkdir(parents=True, exist_ok=True)

        for folder in [PHOTOS_DIR, PHOTOS_BACKUP]:
            for f in folder.glob("*.jpg"):
                f.unlink()

        if progress_callback:
            progress_callback("Wiping databases...")
        from consai.config import DB_PATH
        if DB_PATH.exists():
            DB_PATH.unlink()
        if ARCHIVE_DB_DIR.exists():
            shutil.rmtree(ARCHIVE_DB_DIR)
        ARCHIVE_DB_DIR.mkdir(parents=True, exist_ok=True)

        set_config("current_install", "0000")
        _update_env_installation_id("0000")

        if progress_callback:
            progress_callback("Done")

        logger.info("Factory reset complete")
        return True

    except Exception as e:
        logger.error(f"Factory reset failed: {e}")
        return False

# ── Summary for warnings ──────────────────────────────────────────────────────

def get_reset_summary() -> dict:
    """Return summary for factory reset warning screen."""
    installations = get_installation_list()
    total_photos  = sum(i["photo_count"] for i in installations)
    not_backed_up = sum(
        1 for i in installations
        if i["has_photos"] and not i["backed_up"]
    )
    total_size_mb = sum(i["size_mb"] for i in installations)
    return {
        "installations":  len(installations),
        "total_photos":   total_photos,
        "not_backed_up":  not_backed_up,
        "total_size_mb":  total_size_mb,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_unit_config()
    print(f"Unit ID:      {get_unit_id()}")
    print(f"Install ID:   {get_current_installation_id()}")
    print(f"Counter:      {get_install_counter()}")
    print(f"Installations: {get_installation_list()}")