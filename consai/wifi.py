import subprocess
import logging
import time
import sys
import tty
import termios

logger = logging.getLogger(__name__)

# ── Current status ────────────────────────────────────────────────────────────

def get_current_ssid() -> str | None:
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
            capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            if line.startswith("yes:"):
                return line.split(":", 1)[1]
    except Exception as e:
        logger.error(f"SSID check failed: {e}")
    return None

def get_current_ip() -> str | None:
    try:
        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True, text=True
        )
        ips = result.stdout.strip().split()
        return ips[0] if ips else None
    except Exception:
        return None

def get_signal_strength() -> int | None:
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "ACTIVE,SIGNAL", "dev", "wifi"],
            capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            if line.startswith("yes:"):
                return int(line.split(":")[1])
    except Exception:
        return None

def get_wifi_status() -> dict:
    return {
        "ssid":   get_current_ssid(),
        "ip":     get_current_ip(),
        "signal": get_signal_strength(),
    }

# ── Scan ──────────────────────────────────────────────────────────────────────

def scan_networks() -> list:
    try:
        subprocess.run(
            ["sudo", "nmcli", "dev", "wifi", "rescan"],
            capture_output=True, timeout=10
        )
        time.sleep(4)  # increased from 2 to 4
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
            capture_output=True, text=True
        )
        networks = []
        seen = set()
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2:
                ssid = parts[0].strip()
                if ssid and ssid not in seen:
                    seen.add(ssid)
                    try:
                        signal = int(parts[1])
                    except Exception:
                        signal = 0
                    security = parts[2] if len(parts) > 2 else "WPA2"
                    networks.append({
                        "ssid":     ssid,
                        "signal":   signal,
                        "security": security,
                    })
        return sorted(networks, key=lambda x: x["signal"], reverse=True)
    except Exception as e:
        logger.error(f"Network scan failed: {e}")
        return []

# ── Connect ───────────────────────────────────────────────────────────────────

def connect_to_network(ssid: str, password: str) -> bool:
    try:
        # Find saved connection name by SSID
        result = subprocess.run(
            ["nmcli", "-t", "-f", "TYPE,NAME", "con", "show"],
            capture_output=True, text=True
        )
        saved_con_name = None
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[0] == "802-11-wireless":
                con_name = parts[1]
                r2 = subprocess.run(
                    ["nmcli", "-t", "-f", "802-11-wireless.ssid",
                     "con", "show", con_name],
                    capture_output=True, text=True
                )
                for l in r2.stdout.splitlines():
                    if "802-11-wireless.ssid:" in l:
                        saved_ssid = l.split(":", 1)[1].strip()
                        if saved_ssid == ssid:
                            saved_con_name = con_name
                            break
            if saved_con_name:
                break

        if saved_con_name:
            result = subprocess.run(
                ["sudo", "nmcli", "con", "up", "id", saved_con_name],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                logger.info(f"Connected via saved profile: {saved_con_name}")
                return True
            logger.warning(f"Saved profile failed, trying fresh: {result.stderr}")

        # No saved profile or failed — try with password
        if password:
            result = subprocess.run(
                ["sudo", "nmcli", "dev", "wifi", "connect", ssid,
                 "password", password],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                logger.info(f"Connected to: {ssid}")
                return True
            else:
                logger.error(f"Connection failed: {result.stderr}")
                return False

        logger.error(f"No saved profile and no password for: {ssid}")
        return False
    except subprocess.TimeoutExpired:
        logger.error("Connection timed out")
        return False
    except Exception as e:
        logger.error(f"Connection error: {e}")
        return False

# ── Keyboard password input ───────────────────────────────────────────────────

def read_password_from_keyboard(
    display_callback=None,
    cancel_callback=None
) -> str | None:
    """
    Read password from USB keyboard by reading /dev/input directly.
    Works even without a TTY (under systemd).
    """
    import struct
    import glob

    # Find USB keyboard input device
    keyboard_dev = None
    for dev in glob.glob("/dev/input/by-id/*kbd*") + \
                glob.glob("/dev/input/by-id/*keyboard*"):
        keyboard_dev = dev
        break

    if not keyboard_dev:
        # Fallback — try event devices
        for dev in glob.glob("/dev/input/event*"):
            keyboard_dev = dev
            break

    if not keyboard_dev:
        logger.error("No keyboard device found")
        return None

    logger.info(f"Reading keyboard from: {keyboard_dev}")

    # Key code to character mapping (US layout)
    KEYMAP = {
        2: ('1','!'), 3: ('2','@'), 4: ('3','#'), 5: ('4','$'),
        6: ('5','%'), 7: ('6','^'), 8: ('7','&'), 9: ('8','*'),
        10: ('9','('), 11: ('0',')'), 12: ('-','_'), 13: ('=','+'),
        16: ('q','Q'), 17: ('w','W'), 18: ('e','E'), 19: ('r','R'),
        20: ('t','T'), 21: ('y','Y'), 22: ('u','U'), 23: ('i','I'),
        24: ('o','O'), 25: ('p','P'), 26: ('[','{'), 27: (']','}'),
        30: ('a','A'), 31: ('s','S'), 32: ('d','D'), 33: ('f','F'),
        34: ('g','G'), 35: ('h','H'), 36: ('j','J'), 37: ('k','K'),
        38: ('l','L'), 39: (';',':'), 40: ("'",'"'), 41: ('`','~'),
        43: ('\\','|'), 44: ('z','Z'), 45: ('x','X'), 46: ('c','C'),
        47: ('v','V'), 48: ('b','B'), 49: ('n','N'), 50: ('m','M'),
        51: (',','<'), 52: ('.','>'), 53: ('/','?'), 57: (' ',' '),
    }

    KEY_ENTER     = 28
    KEY_BACKSPACE = 14
    KEY_ESC       = 1
    KEY_LEFTSHIFT = 42
    KEY_RIGHTSHIFT = 54
    KEY_CAPSLOCK  = 58

    password  = []
    shift     = False
    caps      = False

    # Input event struct on 64-bit ARM:
    # timeval: sec (8 bytes) + usec (8 bytes) + type (2) + code (2) + value (4) = 24 bytes
    EVENT_SIZE = 24
    EVENT_FORMAT = "qqHHI"

    try:
        with open(keyboard_dev, "rb") as f:
            if display_callback:
                display_callback("")
            while True:
                data = f.read(EVENT_SIZE)
                if len(data) < EVENT_SIZE:
                    continue

                _, _, etype, code, value = struct.unpack(EVENT_FORMAT, data)

                # Only process key press (value=1) and repeat (value=2)
                if etype != 1:
                    continue

                # Track shift state
                if code in (KEY_LEFTSHIFT, KEY_RIGHTSHIFT):
                    shift = value in (1, 2)
                    continue

                # Only on key down
                if value != 1:
                    continue

                if code == KEY_ESC:
                    if cancel_callback:
                        cancel_callback()
                    return None

                elif code == KEY_ENTER:
                    break

                elif code == KEY_BACKSPACE:
                    if password:
                        password.pop()
                    if display_callback:
                        display_callback("".join(password))

                elif code == KEY_CAPSLOCK:
                    caps = not caps

                elif code in KEYMAP:
                    use_upper = shift ^ caps
                    char = KEYMAP[code][1 if use_upper else 0]
                    password.append(char)
                    if display_callback:
                        display_callback("".join(password))

    except Exception as e:
        logger.error(f"Keyboard read error: {e}")
        return None

    return "".join(password)

def get_saved_networks() -> set:
    """Return set of SSIDs that have saved connections."""
    try:
        # Get wifi connection names
        result = subprocess.run(
            ["nmcli", "-t", "-f", "TYPE,NAME", "con", "show"],
            capture_output=True, text=True
        )
        saved = set()
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[0] == "802-11-wireless":
                con_name = parts[1]
                # Get the SSID for this connection
                r2 = subprocess.run(
                    ["nmcli", "-t", "-f", "802-11-wireless.ssid",
                     "con", "show", con_name],
                    capture_output=True, text=True
                )
                for l in r2.stdout.splitlines():
                    if "802-11-wireless.ssid:" in l:
                        ssid = l.split(":", 1)[1].strip()
                        if ssid:
                            saved.add(ssid)
        return saved
    except Exception as e:
        logger.error(f"Saved networks check failed: {e}")
        return set()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    status = get_wifi_status()
    print(f"SSID:   {status['ssid']}")
    print(f"IP:     {status['ip']}")
    print(f"Signal: {status['signal']}%")
    print(f"\nAvailable networks:")
    for n in scan_networks():
        print(f"  {n['ssid']} ({n['signal']}%) {n['security']}")