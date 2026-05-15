import time
import logging
from luma.core.render import canvas
from PIL import ImageFont

from ui.display.init import get_device
from consai.db import get_last_capture, get_pending_count
from consai.utils import get_cpu_temp, get_disk_free_mb, get_memory_free_mb
from consai.config import UNIT_ID

logger = logging.getLogger(__name__)

# ── Font ──────────────────────────────────────────────────────────────────────

def _font(size=10):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()

def _font_bold(size=10):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except Exception:
        return ImageFont.load_default()

# ── Home screen ───────────────────────────────────────────────────────────────

def draw_home(recording: bool = True, heartbeat: bool = False):
    device  = get_device()
    now     = time.strftime("%H:%M")
    from consai.config import INSTALLATION_ID
    from consai.db import get_photo_count_for_installation
    count = get_photo_count_for_installation(INSTALLATION_ID)
    pending = get_pending_count()
    last = get_last_capture()
    temp = get_cpu_temp()
    disk = get_disk_free_mb()

    from consai.config import INSTALLATION_ID

    if last:
        last_time = last["captured_at"][11:16]
        last_id   = last["id"]
    else:
        last_time = "--:--"
        last_id   = 0

    p_up   = pending["pending_upload"]
    p_sync = pending["pending_sync"]
    if p_up == 0 and p_sync == 0:
        sync_str = "synced"
    elif p_up > 0:
        sync_str = f"{p_up} up"
    else:
        sync_str = f"{p_sync} sync"

    rec_str = "REC" if recording else "STP"
    hb_dot  = "*" if heartbeat else " "

    with canvas(device) as draw:
        # Header bar
        draw.rectangle((0, 0, 127, 13), fill="white")
        draw.text((2, 1),   UNIT_ID,  font=_font_bold(10), fill="black")
        draw.text((52, 1),  now,      font=_font_bold(10), fill="black")
        draw.text((98, 1),  rec_str,  font=_font(9),
                  fill="black" if recording else "white")
        draw.text((120, 1), hb_dot,   font=_font_bold(10), fill="black")

        # Installation ID row
        if INSTALLATION_ID == "0000":
            draw.text((2, 16), "LOCAL  sync off",
                      font=_font(9), fill="white")
        else:
            draw.text((2, 16), f"In:{INSTALLATION_ID}",
                      font=_font(9), fill="white")
            draw.text((60, 16), f"Ph:{count}",
                      font=_font(9), fill="white")

        # Last capture
        draw.text((2, 27), f"Last: {last_time} #{last_id}",
                  font=_font(9), fill="white")

        # Sync
        draw.text((2, 38), f"Sync: {sync_str}",
                  font=_font(9), fill="white")

        # Bottom strip
        draw.line((0, 50, 127, 50), fill="white")
        temp_str = f"{temp}C" if temp else "?C"
        disk_str = f"{disk // 1024}G" if disk > 0 else "?G"
        try:
            import subprocess as _sp
            r = _sp.run(["iwgetid", "-r"], capture_output=True, text=True)
            wifi_ssid = r.stdout.strip() or "NoWiFi"
        except Exception:
            wifi_ssid = "NoWiFi"

        draw.text((2, 53), f"{temp_str} {disk_str}",
                  font=_font(8), fill="white")
        draw.text((126, 53), wifi_ssid[:12],
                  font=_font(8), fill="white", anchor="ra")

# ── Menu screen ───────────────────────────────────────────────────────────────

def draw_menu(items: list, selected: int, title: str = "MENU"):
    device = get_device()
    with canvas(device) as draw:
        # Header
        draw.rectangle((0, 0, 127, 13), fill="white")
        draw.text((2, 1), title, font=_font_bold(10), fill="black")

        # Items — show max 4 at a time
        max_visible = 4
        start = max(0, selected - max_visible + 1)
        visible = items[start:start + max_visible]

        for i, item in enumerate(visible):
            y = 16 + i * 12
            actual_idx = start + i
            if actual_idx == selected:
                draw.rectangle((0, y - 1, 127, y + 10), fill="white")
                draw.text((8, y), f"> {item}", font=_font_bold(9), fill="black")
            else:
                draw.text((8, y), item, font=_font(9), fill="white")

# ── Status screen ─────────────────────────────────────────────────────────────

def draw_status():
    device = get_device()
    from consai.db import get_photo_count_for_installation
    from consai.config import INSTALLATION_ID
    count = get_photo_count_for_installation(INSTALLATION_ID)
    pending = get_pending_count()
    temp    = get_cpu_temp()
    disk    = get_disk_free_mb()
    mem     = get_memory_free_mb()

    with canvas(device) as draw:
        # Header
        draw.rectangle((0, 0, 127, 13), fill="white")
        draw.text((2, 1), "STATUS", font=_font_bold(10), fill="black")

        # Data rows — evenly spaced
        draw.text((2, 16), "Photos:", font=_font(9), fill="white")
        draw.text((60, 16), str(count), font=_font_bold(9), fill="white")

        draw.text((2, 27), "Upload:", font=_font(9), fill="white")
        draw.text((60, 27), str(pending["pending_upload"]), font=_font_bold(9), fill="white")

        draw.text((2, 38), "Sync:", font=_font(9), fill="white")
        draw.text((60, 38), str(pending["pending_sync"]), font=_font_bold(9), fill="white")

        # Divider
        draw.line((0, 50, 127, 50), fill="white")

        # Bottom stats — compact single line
        temp_str = f"{temp}C" if temp else "?C"
        disk_str = f"{disk // 1024}G" if disk > 0 else "?G"
        mem_str  = f"{mem}MB" if mem > 0 else "?MB"
        draw.text((2, 53), f"{temp_str}  {disk_str}  {mem_str}",
                  font=_font(8), fill="white")

# ── Camera setting screen ─────────────────────────────────────────────────────

def draw_setting(title: str, value: str, hint: str = "LEFT/RIGHT to change"):
    device = get_device()
    with canvas(device) as draw:
        draw.rectangle((0, 0, 127, 13), fill="white")
        draw.text((2, 1), title, font=_font_bold(10), fill="black")

        draw.text((2, 20), "Value:", font=_font(9), fill="white")
        draw.rectangle((0, 30, 127, 44), fill="white")
        draw.text((4, 31), str(value), font=_font_bold(10), fill="black")

        draw.text((2, 50), hint, font=_font(8), fill="white")

# ── Confirm screen ────────────────────────────────────────────────────────────

def draw_confirm(message: str, hint: str = "PRESS=Yes  LEFT=No"):
    device = get_device()
    with canvas(device) as draw:
        draw.rectangle((0, 0, 127, 13), fill="white")
        draw.text((2, 1), "CONFIRM", font=_font_bold(10), fill="black")
        draw.text((2, 18), message, font=_font(9), fill="white")
        draw.line((0, 51, 127, 51), fill="white")
        draw.text((2, 53), hint, font=_font(8), fill="white")

# ── Message screen ────────────────────────────────────────────────────────────

def draw_message(title: str, message: str, duration: float = 2.0):
    device = get_device()
    with canvas(device) as draw:
        draw.rectangle((0, 0, 127, 13), fill="white")
        draw.text((2, 1), title, font=_font_bold(10), fill="black")
        draw.text((2, 20), message, font=_font(9), fill="white")
    time.sleep(duration)

# ── Test capture screen ───────────────────────────────────────────────────────

def draw_test_capture(status: str = "Ready"):
    device = get_device()
    with canvas(device) as draw:
        draw.rectangle((0, 0, 127, 13), fill="white")
        draw.text((2, 1), "TEST CAPTURE", font=_font_bold(9), fill="black")
        draw.text((2, 20), status, font=_font(9), fill="white")
        draw.text((2, 50), "PRESS to capture", font=_font(8), fill="white")


# installation List -----------------

def draw_installation_list(installations: list, selected: int):
    """Show list of installations with status icons."""
    device = get_device()
    with canvas(device) as draw:
        draw.rectangle((0, 0, 127, 13), fill="white")
        draw.text((2, 1), "INSTALLATIONS", font=_font_bold(9), fill="black")

        max_visible = 4
        start = max(0, selected - max_visible + 1)
        visible = installations[start:start + max_visible]

        for i, inst in enumerate(visible):
            y = 16 + i * 12
            actual_idx = start + i

            # Status icon
            if inst["status"] == "active":
                icon = ">"
            elif inst["has_photos"] and not inst["backed_up"]:
                icon = "!"
            else:
                icon = " "

            label = f"{icon}{inst['id']} {inst['photo_count']}ph"

            if actual_idx == selected:
                draw.rectangle((0, y - 1, 127, y + 10), fill="white")
                draw.text((4, y), label, font=_font_bold(9), fill="black")
            else:
                draw.text((4, y), label, font=_font(9), fill="white")

def draw_installation_detail(inst: dict):
    """Show detail for one installation."""
    device = get_device()
    status = "ACTIVE" if inst["status"] == "active" else "ARCHIVED"
    with canvas(device) as draw:
        draw.rectangle((0, 0, 127, 13), fill="white")
        draw.text((2, 1), f"INSTALL {inst['id']}", font=_font_bold(9), fill="black")

        draw.text((2, 16), f"Status: {status}", font=_font(9), fill="white")
        draw.text((2, 27), f"Photos: {inst['photo_count']}", font=_font(9), fill="white")
        draw.text((2, 38), f"Size:   {inst['size_mb']}MB", font=_font(9), fill="white")

        backed = "YES" if inst["backed_up"] else "NO ⚠"
        draw.text((2, 49), f"Backed: {backed}", font=_font(9), fill="white")