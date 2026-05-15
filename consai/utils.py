import os
import socket
import logging
import requests
from datetime import datetime
from consai.config import IPINFO_TOKEN, UNIT_ID, CAMERA_TYPE

logger = logging.getLogger(__name__)

# ── Time ──────────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def now_filename() -> str:
    """Timestamp safe for use in filenames."""
    return datetime.now().strftime("%Y%m%d%H%M%S")

# ── Network ───────────────────────────────────────────────────────────────────

def is_online(timeout: int = 5) -> bool:
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
            ("8.8.8.8", 53)
        )
        return True
    except OSError:
        return False

def get_location() -> dict:
    """Get lat/lon and location name from IP. Returns defaults if offline."""
    defaults = {
        "lat": 25.2854,
        "lon": 51.5310,
        "location_name": "Doha, QA"
    }
    try:
        url = "https://ipinfo.io/json"
        if IPINFO_TOKEN:
            url += f"?token={IPINFO_TOKEN}"
        r = requests.get(url, timeout=5)
        data = r.json()
        lat, lon = data.get("loc", "25.2854,51.5310").split(",")
        return {
            "lat": float(lat),
            "lon": float(lon),
            "location_name": f"{data.get('city', '')}, {data.get('country', '')}"
        }
    except Exception as e:
        logger.warning(f"Location lookup failed: {e}")
        return defaults

# ── System ────────────────────────────────────────────────────────────────────

def get_cpu_temp() -> float | None:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read().strip()) / 1000, 1)
    except Exception:
        return None

def get_disk_free_mb() -> int:
    try:
        st = os.statvfs("/home")
        return int((st.f_bavail * st.f_frsize) / 1024 / 1024)
    except Exception:
        return -1

def get_memory_free_mb() -> int:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable"):
                    return int(line.split()[1]) // 1024
    except Exception:
        return -1

def get_system_health() -> dict:
    return {
        "unit_id":        UNIT_ID,
        "camera_type":    CAMERA_TYPE,
        "cpu_temp":       get_cpu_temp(),
        "disk_free_mb":   get_disk_free_mb(),
        "memory_free_mb": get_memory_free_mb(),
        "online":         is_online(),
        "timestamp":      now_iso()
    }

# ── Photo helpers ─────────────────────────────────────────────────────────────

def build_photo_filename(prefix: str = "photo") -> str:
    return f"{prefix}_{now_filename()}.jpg"

def get_file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return 0

if __name__ == "__main__":
    print("🌐 Online:", is_online())
    print("📍 Location:", get_location())
    print("🌡  Health:", get_system_health())