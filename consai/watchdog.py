import time
import logging
import subprocess
from pathlib import Path
from consai.config import UNIT_ID
from consai.db import log_event, get_last_capture, get_pending_count
from consai.utils import get_system_health, is_online

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

CHECK_INTERVAL   = 60       # seconds between health checks
SERVICES         = [
    "capture.timer",
    "sync.timer",
    "oled-menu.service",
]

# ── Systemd helpers ───────────────────────────────────────────────────────────

def service_is_active(name: str) -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False

def restart_service(name: str) -> bool:
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", name],
            capture_output=True, text=True
        )
        success = result.returncode == 0
        if success:
            logger.info(f"Restarted {name}")
            log_event("watchdog", f"Restarted {name}")
        else:
            logger.error(f"Failed to restart {name}: {result.stderr}")
            log_event("watchdog", f"Failed to restart {name}", level="ERROR")
        return success
    except Exception as e:
        logger.error(f"restart_service error: {e}")
        return False

def get_service_status(name: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"

# ── Health check ──────────────────────────────────────────────────────────────

def run_health_check() -> dict:
    health = get_system_health()

    # Service states
    health["services"] = {
        name: get_service_status(name) for name in SERVICES
    }

    # Capture state
    last = get_last_capture()
    health["last_capture"]  = last["captured_at"] if last else None
    health["last_filename"] = last["filename"] if last else None

    # Queue state
    pending = get_pending_count()
    health["pending_upload"] = pending["pending_upload"]
    health["pending_sync"]   = pending["pending_sync"]

    return health

# ── OTA ───────────────────────────────────────────────────────────────────────

def check_ota() -> bool:
    """
    Placeholder for OTA update check.
    Will poll consai.app/api/units/{unit_id}/update when backend is ready.
    Returns True if an update was applied.
    """
    # TODO: implement when consai.app OTA endpoint is ready
    return False

def apply_update():
    """Pull latest code and restart services."""
    logger.info("Applying OTA update...")
    log_event("watchdog", "OTA update started")
    try:
        subprocess.run(
            ["git", "-C", "/home/z001", "pull", "--ff-only"],
            capture_output=True, text=True, check=True
        )
        for service in SERVICES:
            restart_service(service)
        log_event("watchdog", "OTA update complete")
        logger.info("OTA update complete")
    except subprocess.CalledProcessError as e:
        logger.error(f"OTA git pull failed: {e.stderr}")
        log_event("watchdog", f"OTA failed: {e.stderr}", level="ERROR")

# ── Main loop ─────────────────────────────────────────────────────────────────

def run():
    logger.info(f"Watchdog started — unit {UNIT_ID}")
    log_event("watchdog", "Watchdog started")

    while True:
        try:
            health = run_health_check()

            # Log health summary
            logger.info(
                f"Health — CPU: {health['cpu_temp']}°C | "
                f"Disk: {health['disk_free_mb']}MB free | "
                f"RAM: {health['memory_free_mb']}MB free | "
                f"Online: {health['online']} | "
                f"Pending: {health['pending_upload']} upload / "
                f"{health['pending_sync']} sync"
            )

            # Log service states
            for name, state in health["services"].items():
                if state not in ("active", "inactive"):
                    logger.warning(f"Service {name} is {state} — restarting")
                    restart_service(name)

            # OTA check (no-op until backend ready)
            if is_online():
                if check_ota():
                    apply_update()

            log_event("watchdog", f"Health OK — {health['cpu_temp']}°C "
                                  f"{health['disk_free_mb']}MB disk "
                                  f"{health['memory_free_mb']}MB RAM")

        except Exception as e:
            logger.error(f"Watchdog error: {e}")
            log_event("watchdog", f"Watchdog error: {e}", level="ERROR")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    run()