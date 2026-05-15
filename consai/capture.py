import logging
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

from consai.config import (
    UNIT_ID, INSTALLATION_ID, CAMERA_TYPE,
    CAPTURE_FREQ_MIN, PHOTO_DIR, PHOTO_BACKUP_DIR, CAMERA_SETTINGS
)
from consai.db import insert_photo, log_event
from consai.utils import now_iso, now_filename, get_location, get_file_size
from consai.weather import get_weather
from consai.settings import load_settings

logger = logging.getLogger(__name__)

# ── Lock ──────────────────────────────────────────────────────────────────────

LOCK_FILE = Path("/tmp/consai_capture.lock")

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

# ── Camera command ────────────────────────────────────────────────────────────

def build_libcamera_cmd(output_path: str, settings: dict) -> list:
    cmd = [
        "rpicam-still",
        "--output",    output_path,
        "--width",     str(settings.get("width",  4656)),
        "--height",    str(settings.get("height", 3496)),
        "--quality",   str(settings.get("quality", 90)),
        "--timeout",   str(settings.get("timeout_ms", 3000)),
        "--nopreview",
    ]

    # Orientation
    rotation = settings.get("rotation", 0)
    if rotation:
        cmd += ["--rotation", str(rotation)]

    if settings.get("hflip", False):
        cmd += ["--hflip"]

    if settings.get("vflip", False):
        cmd += ["--vflip"]

    # Exposure
    shutter = settings.get("shutter", 0)
    if shutter and shutter > 0:
        cmd += ["--shutter", str(int(shutter))]

    gain = settings.get("gain", 0)
    if gain and gain > 0:
        cmd += ["--gain", str(gain)]

    ev = settings.get("ev", 0.0)
    if ev != 0.0:
        cmd += ["--ev", str(ev)]

    # Image quality
    sharpness = settings.get("sharpness")
    if sharpness is not None:
        cmd += ["--sharpness", str(sharpness)]

    contrast = settings.get("contrast")
    if contrast is not None:
        cmd += ["--contrast", str(contrast)]

    brightness = settings.get("brightness")
    if brightness is not None:
        cmd += ["--brightness", str(brightness)]

    # AWB and metering
    awb = settings.get("awb", "auto")
    cmd += ["--awb", awb]

    metering = settings.get("metering", "centre")
    cmd += ["--metering", metering]

    # HDR
    if settings.get("hdr", False):
        cmd += ["--hdr"]

    return cmd

def capture_photo(output_path: Path, settings: dict) -> bool:
    cmd = build_libcamera_cmd(str(output_path), settings)
    logger.info(f"Capturing: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd, timeout=30, capture_output=True, text=True
        )
        if result.returncode != 0:
            logger.error(f"rpicam-still error: {result.stderr}")
            return False
        if not output_path.exists() or output_path.stat().st_size == 0:
            logger.error("Capture produced empty or missing file")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("rpicam-still timed out")
        return False
    except FileNotFoundError:
        logger.error("rpicam-still not found")
        return False

# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    if _is_running():
        logger.warning("Capture already running — skipping")
        return
    _acquire_lock()
    try:
        _capture()
    finally:
        _release_lock()

def _capture():
    settings  = load_settings()
    timestamp = now_filename()
    filename  = f"{UNIT_ID}_{INSTALLATION_ID}_{timestamp}.jpg"

    photo_path  = PHOTO_DIR / filename
    backup_path = PHOTO_BACKUP_DIR / filename

    logger.info(f"Starting capture → {filename}")
    success = capture_photo(photo_path, settings)

    if not success:
        log_event("capture", f"Capture failed for {filename}", level="ERROR")
        return

    # Backup
    try:
        shutil.copy2(photo_path, backup_path)
    except Exception as e:
        logger.warning(f"Backup copy failed: {e}")

    # Metadata
    location = get_location()
    weather  = get_weather(location["lat"], location["lon"])

    try:
        from PIL import Image
        with Image.open(photo_path) as img:
            width, height = img.size
    except Exception:
        width, height = None, None

    record = {
        "installation_id":  INSTALLATION_ID,
        "filename":         filename,
        "filepath":         str(photo_path),
        "backup_path":      str(backup_path),
        "captured_at":      now_iso(),
        "size_bytes":       get_file_size(str(photo_path)),
        "width":            width,
        "height":           height,
        "unit_id":          UNIT_ID,
        "camera_type":      CAMERA_TYPE,
        "lat":              location["lat"],
        "lon":              location["lon"],
        "location_name":    location["location_name"],
        "capture_freq":     CAPTURE_FREQ_MIN,
        **weather,
    }

    photo_id = insert_photo(record)
    log_event("capture", f"Captured {filename} → id={photo_id}")
    logger.info(f"✅ Captured {filename} ({record['size_bytes']} bytes) id={photo_id}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()