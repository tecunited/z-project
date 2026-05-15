import os
from pathlib import Path
from dotenv import load_dotenv

# ── Locate and load .env ──────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent  # /home/z001
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Missing required config: {key}")
    return val

def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default)

# Unit identity
UNIT_ID         = _require("UNIT_ID")
CAMERA_TYPE     = _get("CAMERA_TYPE", "z-project")
HOSTNAME        = os.uname().nodename

# Installation ID — read from unit_config DB first, fall back to .env
def _get_installation_id() -> str:
    try:
        import sqlite3 as _sqlite3
        db_path = BASE_DIR / "logs" / "unit_config.sqlite"
        if db_path.exists():
            conn = _sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT value FROM unit_config WHERE key = 'current_install'"
            ).fetchone()
            conn.close()
            if row and row[0]:
                return row[0]
    except Exception:
        pass
    return _get("INSTALLATION_ID", "0000")

INSTALLATION_ID = _get_installation_id()
# 0000 means unassigned to cloud project — capture works, sync blocked
COMMISSIONED    = INSTALLATION_ID != ""
SYNC_ENABLED    = INSTALLATION_ID != "0000" and INSTALLATION_ID != ""

# ── consai.app ────────────────────────────────────────────────────────────────
API_KEY         = _require("API_KEY")
API_BASE_URL    = _get("API_BASE_URL", "https://consai.app")

# ── Storage backend ───────────────────────────────────────────────────────────
STORAGE_BACKEND = _get("STORAGE_BACKEND", "gcs")  # gcs | r2 | s3

# GCS
GCS_BUCKET              = _get("GCS_BUCKET")
GCS_CREDENTIALS_PATH    = _get("GCS_CREDENTIALS_PATH")

# Cloudflare R2 (S3-compatible)
R2_ACCOUNT_ID           = _get("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID        = _get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY    = _get("R2_SECRET_ACCESS_KEY")
R2_BUCKET               = _get("R2_BUCKET")
R2_ENDPOINT             = _get("R2_ENDPOINT")  # set by provision.sh from account_id

# ── External APIs ─────────────────────────────────────────────────────────────
OPENWEATHER_API_KEY     = _get("OPENWEATHER_API_KEY")
IPINFO_TOKEN            = _get("IPINFO_TOKEN")

# ── Paths ─────────────────────────────────────────────────────────────────────
DB_PATH             = BASE_DIR / "logs" / f"{HOSTNAME}_db.sqlite"
CAMERA_SETTINGS     = BASE_DIR / "camera_settings.json"
PHOTO_DIR           = BASE_DIR / "photos"
PHOTO_BACKUP_DIR    = BASE_DIR / "photos_backup"

# ── Capture schedule ──────────────────────────────────────────────────────────
CAPTURE_FREQ_MIN    = int(_get("CAPTURE_FREQ", "1"))
SYNC_FREQ_MIN       = int(_get("SYNC_FREQ", "5"))

# ── Ensure critical dirs exist ────────────────────────────────────────────────
for _dir in [DB_PATH.parent, PHOTO_DIR, PHOTO_BACKUP_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)