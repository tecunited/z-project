import time
import logging
import threading
import subprocess

from ui.display.screens import (
    draw_home, draw_menu, draw_status,
    draw_setting, draw_confirm, draw_message, draw_test_capture,
    draw_installation_list, draw_installation_detail
)
from ui.display.hdmi import draw_logo_screen, draw_photo_screen
from ui.hardware.gpio import (
    setup as gpio_setup, cleanup as gpio_cleanup,
    wait_for_press, wait_for_release
)
from ui.display.init import get_device, clear
from consai.settings import load_settings, update_setting
from consai.db import get_last_capture, log_event
from consai.config import UNIT_ID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ── Menus ─────────────────────────────────────────────────────────────────────

MAIN_MENU   = ["Status", "Camera", "System", "Test Capture"]
CAMERA_MENU = [
    "Interval", "Resolution", "Quality",
    "Gain", "Shutter", "EV",
    "Sharpness", "Contrast", "Brightness",
    "AWB", "Metering", "Rotation",
    "Flip H", "Flip V", "HDR",
    "Back"
]
SYSTEM_MENU = [
    "Wi-Fi",
    "New Installation",
    "Installations",
    "Factory Reset",
    "USB Backup",
    "Delete Synced",
    "Delete All",
    "Reboot",
    "Back"
]

CAMERA_SETTINGS_DEF = {
    "Interval": {
        "key":    "capture_freq",
        "values": [1, 2, 5, 10, 15, 30, 60],
        "unit":   "min",
    },
    "Resolution": {
        "key":    "width",
        "values": [4656, 3840, 1920, 1280],
        "unit":   "px",
    },
    "Quality": {
        "key":    "quality",
        "values": [70, 80, 85, 90, 95],
        "unit":   "%",
    },
    "Gain": {
        "key":    "gain",
        "values": [1.0, 2.0, 4.0, 8.0, 12.0, 16.0],
        "unit":   "",
    },
    "Shutter": {
        "key":    "shutter",
        "values": [0, 5000, 10000, 20000, 33000, 50000, 100000],
        "unit":   "us",
    },
    "EV": {
        "key":    "ev",
        "values": [-4.0, -3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0],
        "unit":   "",
    },
    "Sharpness": {
        "key":    "sharpness",
        "values": [0.0, 0.5, 1.0, 2.0, 4.0, 8.0],
        "unit":   "",
    },
    "Contrast": {
        "key":    "contrast",
        "values": [0.5, 0.8, 1.0, 1.1, 1.2, 1.5, 2.0],
        "unit":   "",
    },
    "Brightness": {
        "key":    "brightness",
        "values": [-0.5, -0.3, -0.1, 0.0, 0.1, 0.3, 0.5],
        "unit":   "",
    },
    "AWB": {
        "key":    "awb",
        "values": ["auto", "sunlight", "cloudy", "tungsten", "fluorescent"],
        "unit":   "",
    },
    "Metering": {
        "key":    "metering",
        "values": ["centre", "spot", "average"],
        "unit":   "",
    },
    "Rotation": {
        "key":    "rotation",
        "values": [0, 90, 180, 270],
        "unit":   "deg",
    },
    "Flip H": {
        "key":    "hflip",
        "values": [False, True],
        "unit":   "",
    },
    "Flip V": {
        "key":    "vflip",
        "values": [False, True],
        "unit":   "",
    },
    "HDR": {
        "key":    "hdr",
        "values": [False, True],
        "unit":   "",
    },
}

# ── State ─────────────────────────────────────────────────────────────────────

class UIState:
    HOME         = "home"
    MAIN_MENU    = "main_menu"
    STATUS       = "status"
    CAMERA_MENU  = "camera_menu"
    SYSTEM_MENU  = "system_menu"
    TEST_CAPTURE = "test_capture"

state        = UIState.HOME
menu_index   = 0
camera_index = 0
system_index = 0
last_input   = time.time()
OLED_BLANKED = False

IDLE_TIMEOUT = 60

# ── Recording state ───────────────────────────────────────────────────────────

recording = True

def set_recording(enabled: bool):
    global recording
    recording = enabled
    if enabled:
        subprocess.run(["sudo", "systemctl", "start", "capture.timer"])
        log_event("ui", "Capture started via KEY1")
        logger.info("Capture STARTED")
    else:
        subprocess.run(["sudo", "systemctl", "stop", "capture.timer"])
        log_event("ui", "Capture stopped via KEY1")
        logger.info("Capture STOPPED")

def toggle_recording():
    set_recording(not recording)

# ── Heartbeat ─────────────────────────────────────────────────────────────────

heartbeat = False

def _heartbeat_thread():
    global heartbeat
    while True:
        heartbeat = True
        time.sleep(0.5)
        heartbeat = False
        time.sleep(0.5)

# ── OLED blank/wake ───────────────────────────────────────────────────────────

def blank_oled():
    global OLED_BLANKED
    if not OLED_BLANKED:
        clear()
        OLED_BLANKED = True
        logger.info("OLED blanked")

def wake_oled():
    global OLED_BLANKED
    OLED_BLANKED = False

# ── Home refresh thread ───────────────────────────────────────────────────────

_stop_refresh = threading.Event()

def _home_refresh():
    while not _stop_refresh.is_set():
        if state == UIState.HOME and not OLED_BLANKED:
            draw_home(recording=recording, heartbeat=heartbeat)
        time.sleep(3)

# ── HDMI refresh thread ───────────────────────────────────────────────────────

def _hdmi_refresh():
    while True:
        try:
            draw_logo_screen(recording=recording)
        except Exception as e:
            logger.error(f"HDMI refresh error: {e}")
        time.sleep(30)

# ── Setting editor ────────────────────────────────────────────────────────────

def edit_setting(name: str):
    global state, last_input
    if name not in CAMERA_SETTINGS_DEF:
        return

    defn     = CAMERA_SETTINGS_DEF[name]
    settings = load_settings()
    key      = defn["key"]
    values   = defn["values"]
    current  = settings.get(key, values[0])

    res_labels = {
        4656: "16MP 4656x3496",
        3840: "4K  3840x2160",
        1920: "FHD 1920x1080",
        1280: "HD  1280x720",
    }
    res_heights = {
        4656: 3496,
        3840: 2160,
        1920: 1080,
        1280: 720,
    }

    try:
        idx = values.index(current)
    except ValueError:
        idx = 0

    while True:
        if name == "Resolution":
            val_str = res_labels.get(values[idx], str(values[idx]))
        elif name in ("Flip H", "Flip V", "HDR"):
            val_str = "ON" if values[idx] else "OFF"
        elif name == "Shutter":
            val_str = "auto" if values[idx] == 0 else f"{values[idx]}us"
        else:
            val_str = f"{values[idx]} {defn['unit']}".strip()

        draw_setting(name, val_str)
        btn = None
        while btn is None:
            btn = wait_for_press()
            time.sleep(0.05)
        wait_for_release()

        last_input = time.time()

        if btn == "RIGHT":
            idx = (idx + 1) % len(values)
        elif btn == "UP":
            idx = (idx - 1) % len(values)
        elif btn == "DOWN":
            idx = (idx + 1) % len(values)
        elif btn in ("LEFT", "PRESS"):
            update_setting(key, values[idx])
            if name == "Resolution":
                update_setting("height", res_heights.get(values[idx], 3496))
                label = res_labels.get(values[idx], str(values[idx]))
            elif name in ("Flip H", "Flip V", "HDR"):
                label = "ON" if values[idx] else "OFF"
            elif name == "Shutter":
                label = "auto" if values[idx] == 0 else f"{values[idx]}us"
            else:
                label = str(values[idx])
            draw_message("Saved", f"{name}: {label}", duration=1.0)
            state = UIState.CAMERA_MENU
            return

# ── Test capture ──────────────────────────────────────────────────────────────

def do_test_capture():
    draw_test_capture("Capturing...")
    try:
        from consai.capture import run
        run()
        last = get_last_capture()
        if last:
            draw_test_capture("Check HDMI")
            draw_photo_screen(
                last["filepath"],
                recording=recording,
                duration=10.0
            )
        draw_test_capture("Done!")
        time.sleep(1.5)
    except Exception as e:
        logger.error(f"Test capture error: {e}")
        draw_message("Error", str(e)[:20], duration=3.0)

# ── Reboot ────────────────────────────────────────────────────────────────────

def do_reboot():
    draw_confirm("Reboot now?")
    btn = None
    while btn is None:
        btn = wait_for_press()
        time.sleep(0.05)
    wait_for_release()
    if btn == "PRESS":
        draw_message("Rebooting", "Please wait...", duration=1.0)
        subprocess.run(["sudo", "reboot"])
    else:
        draw_message("Cancelled", "", duration=1.0)

# ── Force sync ────────────────────────────────────────────────────────────────

def do_force_sync():
    draw_message("Syncing...", "Starting sync", duration=0.5)
    try:
        subprocess.Popen(
            ["python3", "-m", "consai.sync"],
            cwd="/home/z001",
            env={"PYTHONPATH": "/home/z001", "PATH": "/usr/bin:/bin"}
        )
        draw_message("Sync", "Started OK", duration=2.0)
        log_event("ui", "Force sync triggered via KEY3")
    except Exception as e:
        draw_message("Sync Error", str(e)[:20], duration=2.0)

# ── USB Backup ────────────────────────────────────────────────────────────────

def do_usb_backup():
    from consai.usb import is_usb_present, backup_to_usb, is_mounted, unmount_usb

    if is_mounted():
        unmount_usb()

    if not is_usb_present():
        draw_message("No USB", "Plug in USB stick", duration=3.0)
        return

    draw_confirm("Backup to USB?")
    btn = None
    while btn is None:
        btn = wait_for_press()
        time.sleep(0.05)
    wait_for_release()

    if btn != "PRESS":
        draw_message("Cancelled", "", duration=1.0)
        return

    def progress(current, total, filename):
        from ui.display.screens import _font, _font_bold
        from ui.display.init import get_device
        from luma.core.render import canvas
        device = get_device()
        with canvas(device) as draw:
            draw.rectangle((0, 0, 127, 13), fill="white")
            draw.text((2, 1), f"Backup {int(current/total*100)}%",
                      font=_font_bold(10), fill="black")
            draw.text((2, 18), f"{current} / {total}",
                      font=_font(9), fill="white")
            draw.text((2, 30), filename[:20], font=_font(8), fill="white")
            bar_w = int((current / total) * 124)
            draw.rectangle((2, 44, 126, 54), outline="white")
            if bar_w > 0:
                draw.rectangle((2, 44, 2 + bar_w, 54), fill="white")

    draw_message("Backing up", "Please wait...", duration=0.5)
    result = backup_to_usb(progress_callback=progress)

    if "error" in result:
        draw_message("Error", result["error"][:20], duration=3.0)
    else:
        draw_message(
            "Backup Done",
            f"{result['copied']} new, {result['skipped']} skipped",
            duration=3.0
        )

# ── Delete synced ─────────────────────────────────────────────────────────────

def do_delete_synced():
    from consai.usb import delete_synced_photos

    draw_confirm("Delete synced?")
    btn = None
    while btn is None:
        btn = wait_for_press()
        time.sleep(0.05)
    wait_for_release()

    if btn != "PRESS":
        draw_message("Cancelled", "", duration=1.0)
        return

    draw_message("Deleting...", "Synced photos", duration=0.5)
    count = delete_synced_photos()
    draw_message("Done", f"{count} files deleted", duration=3.0)

# ── Delete all ────────────────────────────────────────────────────────────────

def do_delete_all():
    from consai.usb import delete_all_photos

    draw_confirm("Delete ALL photos?")
    btn = None
    while btn is None:
        btn = wait_for_press()
        time.sleep(0.05)
    wait_for_release()

    if btn != "PRESS":
        draw_message("Cancelled", "", duration=1.0)
        return

    draw_confirm("Are you sure?")
    btn = None
    while btn is None:
        btn = wait_for_press()
        time.sleep(0.05)
    wait_for_release()

    if btn != "PRESS":
        draw_message("Cancelled", "", duration=1.0)
        return

    draw_message("Deleting...", "All photos", duration=0.5)
    count = delete_all_photos()
    draw_message("Done", f"{count} files deleted", duration=3.0)

# ── Wi-Fi setup ───────────────────────────────────────────────────────────────

def do_wifi_setup():
    from consai.wifi import (
        get_wifi_status, scan_networks, get_saved_networks,
        connect_to_network, read_password_from_keyboard
    )

    status = get_wifi_status()
    draw_message("Wi-Fi", f"{status['ssid'] or 'Not connected'}", duration=1.5)

    draw_message("Scanning...", "Please wait 5s", duration=0.5)
    networks = scan_networks()

    if not networks:
        draw_message("No Networks", "Try again", duration=3.0)
        return

    saved    = get_saved_networks()
    net_index = 0

    def draw_network_list():
        items = []
        for n in networks:
            prefix = "* " if n["ssid"] in saved else "  "
            items.append(f"{prefix}{n['ssid']}")
        items.append("  Cancel")
        draw_menu(items, net_index, "SELECT WIFI")

    draw_network_list()

    while True:
        btn = wait_for_press()
        time.sleep(0.05)
        if btn is None:
            continue
        wait_for_release()

        if btn == "UP":
            net_index = (net_index - 1) % (len(networks) + 1)
            draw_network_list()
        elif btn == "DOWN":
            net_index = (net_index + 1) % (len(networks) + 1)
            draw_network_list()
        elif btn in ("PRESS", "RIGHT"):
            if net_index == len(networks):
                draw_message("Cancelled", "", duration=1.0)
                return
            break
        elif btn == "LEFT":
            draw_message("Cancelled", "", duration=1.0)
            return

    selected_ssid = networks[net_index]["ssid"]
    password = None

    if selected_ssid in saved:
        draw_message("Connecting", selected_ssid[:16], duration=0)
        success = connect_to_network(selected_ssid, "")
    else:
        from ui.display.screens import _font, _font_bold
        from ui.display.init import get_device
        from luma.core.render import canvas

        def update_display(pwd):
            device = get_device()
            stars = "*" * len(pwd)
            with canvas(device) as draw:
                draw.rectangle((0, 0, 127, 13), fill="white")
                draw.text((2, 1), "Password:", font=_font_bold(10), fill="black")
                draw.text((2, 18), selected_ssid[:20], font=_font(9), fill="white")
                draw.rectangle((0, 32, 127, 46), fill="white")
                draw.text((4, 33), stars[-18:] if len(stars) > 18 else stars,
                          font=_font(10), fill="black")
                draw.text((2, 50), "Enter=OK  ESC=Cancel",
                          font=_font(8), fill="white")

        device = get_device()
        with canvas(device) as draw:
            draw.rectangle((0, 0, 127, 13), fill="white")
            draw.text((2, 1), "Password:", font=_font_bold(10), fill="black")
            draw.text((2, 18), selected_ssid[:20], font=_font(9), fill="white")
            draw.text((2, 35), "Type on USB keyboard", font=_font(8), fill="white")
            draw.text((2, 50), "Enter=OK  ESC=Cancel", font=_font(8), fill="white")

        password = read_password_from_keyboard(
            display_callback=update_display,
            cancel_callback=lambda: draw_message("Cancelled", "", duration=1.0)
        )

        if password is None:
            return

        draw_message("Connecting", selected_ssid[:16], duration=0)
        success = connect_to_network(selected_ssid, password)

    if success:
        time.sleep(3)
        new_status = get_wifi_status()
        draw_message(
            "Connected!",
            f"{new_status['ip'] or 'Getting IP...'}",
            duration=4.0
        )
    else:
        draw_message("Failed", "Check password", duration=4.0)

# ── New Installation ──────────────────────────────────────────────────────────

def do_new_installation():
    from consai.installation import (
        get_current_installation_id, get_install_counter,
        start_new_installation, init_unit_config
    )
    from consai.db import get_photo_count, get_pending_count
    from consai.usb import is_usb_present

    init_unit_config()
    current = get_current_installation_id()
    count   = get_photo_count()
    pending = get_pending_count()

    draw_message(
        f"Install: {current}",
        f"{count} photos / {pending['pending_upload']} not synced",
        duration=2.0
    )

    if count > 0:
        if is_usb_present():
            draw_confirm(f"Backup {count} photos?")
            btn = None
            while btn is None:
                btn = wait_for_press()
                time.sleep(0.05)
            wait_for_release()
            if btn == "PRESS":
                do_usb_backup()
        else:
            draw_message("No USB", "Photos will be archived", duration=2.0)

    draw_confirm("Start new install?")
    btn = None
    while btn is None:
        btn = wait_for_press()
        time.sleep(0.05)
    wait_for_release()

    if btn != "PRESS":
        draw_message("Cancelled", "", duration=1.0)
        return

    def progress(msg):
        draw_message("Please wait", msg, duration=0)

    new_id = start_new_installation(progress_callback=progress)

    draw_message("New Install!", f"ID: {new_id}", duration=3.0)

    subprocess.run(["sudo", "systemctl", "restart",
                    "capture.timer", "sync.timer", "watchdog.service"])

# ── Installations browser ─────────────────────────────────────────────────────

def do_installations():
    from consai.installation import (
        get_installation_list, backup_archive_to_usb,
        delete_archive_photos, init_unit_config
    )
    from consai.usb import is_usb_present

    init_unit_config()
    installations = get_installation_list()

    if not installations:
        draw_message("No Data", "No installations yet", duration=2.0)
        return

    idx = 0
    draw_installation_list(installations, idx)

    while True:
        btn = wait_for_press()
        time.sleep(0.05)
        if btn is None:
            continue
        wait_for_release()

        if btn == "UP":
            idx = (idx - 1) % len(installations)
            draw_installation_list(installations, idx)
        elif btn == "DOWN":
            idx = (idx + 1) % len(installations)
            draw_installation_list(installations, idx)
        elif btn == "LEFT":
            return
        elif btn in ("PRESS", "RIGHT"):
            inst = installations[idx]
            draw_installation_detail(inst)

            btn2 = None
            while btn2 is None:
                btn2 = wait_for_press()
                time.sleep(0.05)
            wait_for_release()

            if btn2 == "LEFT":
                draw_installation_list(installations, idx)
                continue

            if inst["status"] == "archived" and inst["has_photos"]:
                draw_confirm("Backup to USB?")
                btn3 = None
                while btn3 is None:
                    btn3 = wait_for_press()
                    time.sleep(0.05)
                wait_for_release()

                if btn3 == "PRESS":
                    if not is_usb_present():
                        draw_message("No USB", "Plug in USB stick", duration=3.0)
                    else:
                        def progress(cur, tot, fname):
                            draw_message(
                                f"Backup {int(cur/tot*100)}%",
                                f"{cur}/{tot}", duration=0
                            )
                        result = backup_archive_to_usb(
                            inst["id"], progress_callback=progress
                        )
                        draw_message(
                            "Done",
                            f"{result.get('copied', 0)} copied",
                            duration=2.0
                        )

                        draw_confirm("Delete photos now?")
                        btn4 = None
                        while btn4 is None:
                            btn4 = wait_for_press()
                            time.sleep(0.05)
                        wait_for_release()

                        if btn4 == "PRESS":
                            deleted = delete_archive_photos(inst["id"])
                            draw_message("Deleted", f"{deleted} files", duration=2.0)
                            installations = get_installation_list()

            draw_installation_list(installations, idx)

# ── Factory Reset ─────────────────────────────────────────────────────────────

def do_factory_reset():
    from consai.installation import (
        get_reset_summary, factory_reset, init_unit_config
    )
    from consai.wifi import read_password_from_keyboard

    init_unit_config()
    summary = get_reset_summary()

    draw_message(
        "FACTORY RESET",
        f"{summary['installations']} installs "
        f"{summary['total_photos']} photos",
        duration=3.0
    )

    if summary["not_backed_up"] > 0:
        draw_message(
            f"⚠ WARNING",
            f"{summary['not_backed_up']} installs not backed up",
            duration=3.0
        )

    draw_confirm("DELETE EVERYTHING?")
    btn = None
    while btn is None:
        btn = wait_for_press()
        time.sleep(0.05)
    wait_for_release()

    if btn != "PRESS":
        draw_message("Cancelled", "", duration=1.0)
        return

    from ui.display.screens import _font, _font_bold
    from ui.display.init import get_device
    from luma.core.render import canvas

    device = get_device()
    with canvas(device) as draw:
        draw.rectangle((0, 0, 127, 13), fill="white")
        draw.text((2, 1), "TYPE: RESET", font=_font_bold(9), fill="black")
        draw.text((2, 18), "on USB keyboard", font=_font(9), fill="white")
        draw.text((2, 35), "to confirm", font=_font(9), fill="white")
        draw.text((2, 50), "ESC to cancel", font=_font(8), fill="white")

    confirmed_text = read_password_from_keyboard()

    if confirmed_text != "RESET":
        draw_message("Cancelled", "Wrong input", duration=2.0)
        return

    def progress(msg):
        draw_message("Resetting...", msg, duration=0)

    success = factory_reset(progress_callback=progress)

    if success:
        draw_message("Reset Done", "Rebooting...", duration=2.0)
        subprocess.run(["sudo", "reboot"])
    else:
        draw_message("Error", "Reset failed", duration=3.0)

# ── Main loop ─────────────────────────────────────────────────────────────────

def run():
    global state, menu_index, camera_index, system_index
    global last_input, OLED_BLANKED

    gpio_setup()

    # Initialize unit config
    from consai.installation import init_unit_config
    init_unit_config()

    _stop_refresh.clear()
    threading.Thread(target=_heartbeat_thread, daemon=True).start()
    threading.Thread(target=_home_refresh, daemon=True).start()
    threading.Thread(target=_hdmi_refresh, daemon=True).start()

    logger.info(f"OLED UI started — unit {UNIT_ID}")
    draw_logo_screen(recording=recording)
    draw_home(recording=recording, heartbeat=False)

    try:
        while True:
            btn = wait_for_press()
            time.sleep(0.05)

            # ── Idle timeout → blank OLED ──────────────────────────────
            if btn is None:
                if not OLED_BLANKED and \
                   time.time() - last_input > IDLE_TIMEOUT:
                    blank_oled()
                continue

            # ── Any press wakes OLED ───────────────────────────────────
            if OLED_BLANKED:
                wake_oled()
                last_input = time.time()
                draw_home(recording=recording, heartbeat=heartbeat)
                continue

            last_input = time.time()

            # ── KEY shortcuts ──────────────────────────────────────────
            if btn == "KEY1":
                toggle_recording()
                draw_message(
                    "Recording",
                    "STARTED ●" if recording else "STOPPED ○",
                    duration=1.5
                )
                draw_logo_screen(recording=recording)
                state = UIState.HOME
                continue

            if btn == "KEY2":
                do_test_capture()
                state = UIState.HOME
                continue

            if btn == "KEY3":
                do_force_sync()
                continue

            # ── HOME ───────────────────────────────────────────────────
            if state == UIState.HOME:
                if btn in ("PRESS", "RIGHT"):
                    state = UIState.MAIN_MENU
                    menu_index = 0
                    draw_menu(MAIN_MENU, menu_index, "MENU")

            # ── MAIN MENU ──────────────────────────────────────────────
            elif state == UIState.MAIN_MENU:
                if btn == "UP":
                    menu_index = (menu_index - 1) % len(MAIN_MENU)
                    draw_menu(MAIN_MENU, menu_index, "MENU")
                elif btn == "DOWN":
                    menu_index = (menu_index + 1) % len(MAIN_MENU)
                    draw_menu(MAIN_MENU, menu_index, "MENU")
                elif btn in ("PRESS", "RIGHT"):
                    selected = MAIN_MENU[menu_index]
                    if selected == "Status":
                        state = UIState.STATUS
                        draw_status()
                    elif selected == "Camera":
                        state = UIState.CAMERA_MENU
                        camera_index = 0
                        draw_menu(CAMERA_MENU, camera_index, "CAMERA")
                    elif selected == "System":
                        state = UIState.SYSTEM_MENU
                        system_index = 0
                        draw_menu(SYSTEM_MENU, system_index, "SYSTEM")
                    elif selected == "Test Capture":
                        do_test_capture()
                        state = UIState.HOME
                elif btn == "LEFT":
                    state = UIState.HOME
                    draw_home(recording=recording, heartbeat=heartbeat)

            # ── STATUS ─────────────────────────────────────────────────
            elif state == UIState.STATUS:
                if btn in ("LEFT", "PRESS"):
                    state = UIState.MAIN_MENU
                    draw_menu(MAIN_MENU, menu_index, "MENU")

            # ── CAMERA MENU ────────────────────────────────────────────
            elif state == UIState.CAMERA_MENU:
                if btn == "UP":
                    camera_index = (camera_index - 1) % len(CAMERA_MENU)
                    draw_menu(CAMERA_MENU, camera_index, "CAMERA")
                elif btn == "DOWN":
                    camera_index = (camera_index + 1) % len(CAMERA_MENU)
                    draw_menu(CAMERA_MENU, camera_index, "CAMERA")
                elif btn in ("PRESS", "RIGHT"):
                    selected = CAMERA_MENU[camera_index]
                    if selected == "Back":
                        state = UIState.MAIN_MENU
                        draw_menu(MAIN_MENU, menu_index, "MENU")
                    else:
                        edit_setting(selected)
                        draw_menu(CAMERA_MENU, camera_index, "CAMERA")
                elif btn == "LEFT":
                    state = UIState.MAIN_MENU
                    draw_menu(MAIN_MENU, menu_index, "MENU")

            # ── SYSTEM MENU ────────────────────────────────────────────
            elif state == UIState.SYSTEM_MENU:
                if btn == "UP":
                    system_index = (system_index - 1) % len(SYSTEM_MENU)
                    draw_menu(SYSTEM_MENU, system_index, "SYSTEM")
                elif btn == "DOWN":
                    system_index = (system_index + 1) % len(SYSTEM_MENU)
                    draw_menu(SYSTEM_MENU, system_index, "SYSTEM")
                elif btn in ("PRESS", "RIGHT"):
                    selected = SYSTEM_MENU[system_index]
                    if selected == "Wi-Fi":
                        do_wifi_setup()
                        draw_menu(SYSTEM_MENU, system_index, "SYSTEM")
                    elif selected == "New Installation":
                        do_new_installation()
                        draw_menu(SYSTEM_MENU, system_index, "SYSTEM")
                    elif selected == "Installations":
                        do_installations()
                        draw_menu(SYSTEM_MENU, system_index, "SYSTEM")
                    elif selected == "Factory Reset":
                        do_factory_reset()
                        draw_menu(SYSTEM_MENU, system_index, "SYSTEM")
                    elif selected == "USB Backup":
                        do_usb_backup()
                        draw_menu(SYSTEM_MENU, system_index, "SYSTEM")
                    elif selected == "Delete Synced":
                        do_delete_synced()
                        draw_menu(SYSTEM_MENU, system_index, "SYSTEM")
                    elif selected == "Delete All":
                        do_delete_all()
                        draw_menu(SYSTEM_MENU, system_index, "SYSTEM")
                    elif selected == "Reboot":
                        do_reboot()
                        state = UIState.HOME
                    elif selected == "Back":
                        state = UIState.MAIN_MENU
                        draw_menu(MAIN_MENU, menu_index, "MENU")
                elif btn == "LEFT":
                    state = UIState.MAIN_MENU
                    draw_menu(MAIN_MENU, menu_index, "MENU")

    except KeyboardInterrupt:
        pass
    finally:
        _stop_refresh.set()
        gpio_cleanup()
        logger.info("OLED UI stopped")


if __name__ == "__main__":
    run()