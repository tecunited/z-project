import logging
import requests
from pathlib import Path

from consai.config import (
    API_KEY, API_BASE_URL, UNIT_ID,
    INSTALLATION_ID, COMMISSIONED, CAMERA_TYPE
)
from consai.db import (
    get_pending_uploads, get_pending_api_sync,
    mark_uploaded, mark_uploaded_pr, mark_uploaded_th,
    mark_previews_generated, mark_synced, log_event
)
from consai.image_utils import generate_preview_and_thumbnail
from consai.storage import get_backend

logger = logging.getLogger(__name__)

# ── Lock ──────────────────────────────────────────────────────────────────────

LOCK_FILE = Path("/tmp/consai_sync.lock")

def _is_running() -> bool:
    if LOCK_FILE.exists():
        pid = LOCK_FILE.read_text().strip()
        if Path(f"/proc/{pid}").exists():
            return True
        LOCK_FILE.unlink(missing_ok=True)
    return False

def _acquire_lock():
    import os
    LOCK_FILE.write_text(str(os.getpid()))

def _release_lock():
    LOCK_FILE.unlink(missing_ok=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_path(photo: dict) -> Path:
    """Return existing photo path — primary or backup."""
    p = Path(photo["filepath"])
    if p.exists():
        return p
    b = Path(photo["backup_path"])
    if b.exists():
        return b
    raise FileNotFoundError(f"Photo missing: {photo['filepath']}")

# ── API sync ──────────────────────────────────────────────────────────────────

def sync_to_api(photo: dict) -> bool:
    """Post photo metadata to consai.app."""
    backend = get_backend()

    # Build storage URLs using installation_id as bucket path
    base_name = Path(photo["filename"]).stem
    hq_url = backend.get_url(f"{INSTALLATION_ID}/{photo['filename']}")
    pr_url = backend.get_url(f"{INSTALLATION_ID}/{base_name}_pr.jpg")
    th_url = backend.get_url(f"{INSTALLATION_ID}/{base_name}_th.jpg")

    payload = {
        "unit_id":          UNIT_ID,
        "installation_id":  INSTALLATION_ID,
        "camera_type":      CAMERA_TYPE,
        "filename":         photo["filename"],
        "captured_at":      photo["captured_at"],
        "storage_url":      hq_url,
        "preview_url":      pr_url,
        "thumbnail_url":    th_url,
        "size_bytes":       photo["size_bytes"],
        "width":            photo["width"],
        "height":           photo["height"],
        "lat":              photo["lat"],
        "lon":              photo["lon"],
        "location_name":    photo["location_name"],
        "weather_temp":     photo["weather_temp"],
        "weather_desc":     photo["weather_desc"],
        "weather_humidity": photo["weather_humidity"],
        "capture_freq":     photo["capture_freq"],
    }

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "X-Unit-ID":          UNIT_ID,
        "X-Installation-ID":  INSTALLATION_ID,
        "X-Camera-Type":      CAMERA_TYPE,
        "Content-Type":       "application/json",
    }

    try:
        r = requests.post(
            f"{API_BASE_URL}/api/photos",
            json=payload,
            headers=headers,
            timeout=15,
        )
        r.raise_for_status()
        return True
    except requests.exceptions.Timeout:
        logger.warning(f"API timeout: {photo['filename']}")
        return False
    except requests.exceptions.HTTPError as e:
        logger.warning(f"API error {photo['filename']}: {e}")
        return False
    except Exception as e:
        logger.warning(f"API failed {photo['filename']}: {e}")
        return False

# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    if _is_running():
        logger.warning("Sync already running — skipping")
        return
    _acquire_lock()
    try:
        _sync()
    finally:
        _release_lock()

def _sync():
    # ── Sync enabled check ─────────────────────────────────────────────
    from consai.config import SYNC_ENABLED
    if not SYNC_ENABLED:
        logger.warning(
            "Sync disabled — INSTALLATION_ID=0000. "
            "Start a new installation to enable cloud sync."
        )
        log_event("sync", "Sync skipped — no installation assigned", level="WARNING")
        return

    backend = get_backend()

    # ── Step 1: Upload pending photos to storage ───────────────────────
    pending = get_pending_uploads(limit=10)
    logger.info(f"Pending uploads: {len(pending)}")

    for photo in pending:
        try:
            hq_path = _resolve_path(photo)
            base    = hq_path.stem
            pr_path = hq_path.parent / f"{base}_pr.jpg"
            th_path = hq_path.parent / f"{base}_th.jpg"

            # Generate previews if needed
            if not pr_path.exists() or not th_path.exists():
                pr_path, th_path = generate_preview_and_thumbnail(hq_path)
                mark_previews_generated(photo["id"], str(pr_path), str(th_path))
                logger.info(f"Generated previews for {photo['filename']}")

            # Upload HQ — stored under installation_id/
            backend.upload(hq_path, f"{INSTALLATION_ID}/{photo['filename']}")
            mark_uploaded(photo["id"])
            logger.info(f"✅ HQ uploaded: {photo['filename']}")

            # Upload PR
            backend.upload(pr_path, f"{INSTALLATION_ID}/{pr_path.name}")
            mark_uploaded_pr(photo["id"])
            logger.info(f"✅ PR uploaded: {pr_path.name}")

            # Upload TH
            backend.upload(th_path, f"{INSTALLATION_ID}/{th_path.name}")
            mark_uploaded_th(photo["id"])
            logger.info(f"✅ TH uploaded: {th_path.name}")

            log_event("sync", f"Uploaded {photo['filename']} + PR + TH")

        except Exception as e:
            mark_uploaded(photo["id"], error=str(e))
            logger.error(f"❌ Upload failed {photo['filename']}: {e}")

    # ── Step 2: Sync uploaded photos to API ───────────────────────────
    pending_api = get_pending_api_sync(limit=10)
    logger.info(f"Pending API sync: {len(pending_api)}")

    for photo in pending_api:
        success = sync_to_api(photo)
        if success:
            mark_synced(photo["id"])
            log_event("sync", f"API synced: {photo['filename']}")
            logger.info(f"✅ API synced: {photo['filename']}")
        else:
            mark_synced(photo["id"], error="API sync failed")
            logger.error(f"❌ API sync failed: {photo['filename']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()