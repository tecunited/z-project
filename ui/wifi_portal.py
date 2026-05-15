import logging
import threading
import time
from flask import Flask, request, redirect, render_template_string

logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── Shared state ──────────────────────────────────────────────────────────────

_networks     = []
_result       = {"ssid": None, "password": None, "submitted": False}
_server       = None

PORTAL_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Consai Wi-Fi Setup</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            background: #0a0a0a;
            color: #fff;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .card {
            background: #1a1a1a;
            border-radius: 16px;
            padding: 32px;
            width: 100%;
            max-width: 400px;
            border: 1px solid #333;
        }
        .logo {
            color: #ff8c00;
            font-size: 28px;
            font-weight: bold;
            margin-bottom: 8px;
        }
        .subtitle {
            color: #666;
            font-size: 14px;
            margin-bottom: 28px;
        }
        label {
            display: block;
            color: #999;
            font-size: 12px;
            margin-bottom: 6px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        select, input {
            width: 100%;
            padding: 12px 16px;
            background: #111;
            border: 1px solid #333;
            border-radius: 8px;
            color: #fff;
            font-size: 16px;
            margin-bottom: 20px;
            outline: none;
        }
        select:focus, input:focus {
            border-color: #ff8c00;
        }
        button {
            width: 100%;
            padding: 14px;
            background: #ff8c00;
            border: none;
            border-radius: 8px;
            color: #000;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
        }
        button:active { opacity: 0.8; }
        .unit {
            color: #444;
            font-size: 12px;
            margin-top: 20px;
            text-align: center;
        }
        .success {
            color: #4caf50;
            text-align: center;
            font-size: 18px;
            padding: 20px 0;
        }
    </style>
</head>
<body>
<div class="card">
    <div class="logo">CONSAI</div>
    <div class="subtitle">Wi-Fi Setup — Unit {{ unit_id }}</div>

    {% if submitted %}
    <div class="success">
        ✅ Connecting to {{ ssid }}...<br>
        <small style="color:#666">You can close this page</small>
    </div>
    {% else %}
    <form method="POST" action="/connect">
        <label>Select Network</label>
        <select name="ssid" required>
            {% for net in networks %}
            <option value="{{ net.ssid }}">
                {{ net.ssid }} ({{ net.signal }}%)
            </option>
            {% endfor %}
            <option value="__other__">Other (enter manually)</option>
        </select>

        <label>Network Name (if Other)</label>
        <input type="text" name="ssid_manual"
               placeholder="Leave blank if selected above">

        <label>Password</label>
        <input type="password" name="password"
               placeholder="Wi-Fi password" required>

        <button type="submit">Connect</button>
    </form>
    {% endif %}

    <div class="unit">consai.io</div>
</div>
</body>
</html>
"""

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
@app.route("/generate_204", methods=["GET"])   # Android captive portal
@app.route("/hotspot-detect.html", methods=["GET"])  # Apple captive portal
def index():
    from consai.config import UNIT_ID
    return render_template_string(
        PORTAL_HTML,
        networks=_networks,
        unit_id=UNIT_ID,
        submitted=False,
        ssid=None
    )

@app.route("/connect", methods=["POST"])
def connect():
    from consai.config import UNIT_ID
    ssid     = request.form.get("ssid", "")
    manual   = request.form.get("ssid_manual", "").strip()
    password = request.form.get("password", "")

    if ssid == "__other__" and manual:
        ssid = manual

    _result["ssid"]      = ssid
    _result["password"]  = password
    _result["submitted"] = True

    logger.info(f"Portal: connect request for {ssid}")

    return render_template_string(
        PORTAL_HTML,
        networks=_networks,
        unit_id=UNIT_ID,
        submitted=True,
        ssid=ssid
    )

# ── Server control ────────────────────────────────────────────────────────────

def start_portal(networks: list) -> threading.Thread:
    """Start the captive portal in a background thread."""
    global _networks, _result
    _networks = networks
    _result   = {"ssid": None, "password": None, "submitted": False}

    def _run():
        import logging as _log
        _log.getLogger("werkzeug").setLevel(_log.ERROR)
        app.run(host="0.0.0.0", port=80, debug=False, use_reloader=False)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    logger.info("Captive portal started on port 80")
    return t

def wait_for_submission(timeout: int = 120) -> dict | None:
    """Wait for user to submit the form. Returns result or None on timeout."""
    start = time.time()
    while time.time() - start < timeout:
        if _result["submitted"]:
            return _result
        time.sleep(0.5)
    return None

def stop_portal():
    """Stop the Flask server."""
    try:
        import requests as req
        req.get("http://localhost/shutdown", timeout=1)
    except Exception:
        pass