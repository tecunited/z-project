import json
import logging
from consai.config import CAMERA_SETTINGS

logger = logging.getLogger(__name__)

DEFAULTS = {
    # Resolution
    "width":        4656,
    "height":       3496,
    "quality":      90,
    "timeout_ms":   3000,

    # Orientation
    "rotation":     0,
    "hflip":        False,
    "vflip":        False,

    # Exposure
    "shutter":      0,        # 0 = auto, otherwise microseconds
    "gain":         8.0,      # ~ISO 800, fixed to prevent flicker
    "ev":           0.0,      # exposure compensation -4 to +4

    # Image
    "sharpness":    1.0,      # 0.0-16.0
    "contrast":     1.1,      # 0.0-32.0
    "brightness":   0.0,      # -1.0 to 1.0
    "awb":          "auto",
    "metering":     "centre",
    "hdr":          False,
}

def load_settings() -> dict:
    try:
        if CAMERA_SETTINGS.exists() and CAMERA_SETTINGS.stat().st_size > 10:
            with open(CAMERA_SETTINGS) as f:
                saved = json.load(f)
            return {**DEFAULTS, **saved}
    except Exception as e:
        logger.warning(f"Could not load camera settings: {e}")
    save_settings(DEFAULTS)
    return DEFAULTS.copy()

def save_settings(settings: dict):
    try:
        merged = {**DEFAULTS, **settings}
        with open(CAMERA_SETTINGS, "w") as f:
            json.dump(merged, f, indent=2)
        logger.info("Camera settings saved")
    except Exception as e:
        logger.error(f"Could not save camera settings: {e}")

def get_setting(key: str):
    return load_settings().get(key, DEFAULTS.get(key))

def update_setting(key: str, value):
    settings = load_settings()
    settings[key] = value
    save_settings(settings)

if __name__ == "__main__":
    print("📷 Camera settings:", load_settings())