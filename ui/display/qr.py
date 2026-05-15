import logging
import subprocess
import tempfile
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

def generate_qr_image(data: str, size: int = 300) -> Image.Image | None:
    """Generate a QR code image using qrencode."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name

        subprocess.run(
            ["qrencode", "-o", tmp_path, "-s", "8",
             "-m", "2", "--level=M", data],
            check=True, capture_output=True
        )
        img = Image.open(tmp_path).convert("RGB")
        img = img.resize((size, size), Image.NEAREST)
        Path(tmp_path).unlink(missing_ok=True)
        return img
    except Exception as e:
        logger.error(f"QR generation failed: {e}")
        return None

def draw_wifi_setup_screen(
    hotspot_ssid: str,
    hotspot_password: str,
    portal_url: str,
    unit_id: str
):
    """Draw Wi-Fi setup screen on HDMI with QR code."""
    from ui.display.hdmi import get_fb_info, write_to_fb, STRIP_H, BG_COLOR, LOGO_COLOR, DIM_COLOR, TEXT_COLOR, _font, _font_bold, _draw_strip

    w, h, _ = get_fb_info()
    content_h = h - STRIP_H

    img  = Image.new("RGB", (w, h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Title
    draw.text(
        (w // 2, 40),
        "Wi-Fi Setup",
        font=_font_bold(28),
        fill=LOGO_COLOR,
        anchor="mm"
    )

    # Instructions
    draw.text(
        (w // 2, 80),
        "1. Scan QR code to join setup network",
        font=_font(16),
        fill=TEXT_COLOR,
        anchor="mm"
    )
    draw.text(
        (w // 2, 105),
        "2. Open browser and enter your Wi-Fi details",
        font=_font(16),
        fill=TEXT_COLOR,
        anchor="mm"
    )

    # QR code — encode the hotspot join info
    qr_data = f"WIFI:T:WPA;S:{hotspot_ssid};P:{hotspot_password};;"
    qr_img  = generate_qr_image(qr_data, size=280)

    if qr_img:
        qr_x = w // 2 - 140
        qr_y = 130
        # White background for QR
        draw.rectangle(
            (qr_x - 10, qr_y - 10, qr_x + 290, qr_y + 290),
            fill="white"
        )
        img.paste(qr_img, (qr_x, qr_y))

    # Hotspot details
    draw.text(
        (w // 2, 440),
        f"Network: {hotspot_ssid}",
        font=_font_bold(18),
        fill=TEXT_COLOR,
        anchor="mm"
    )
    draw.text(
        (w // 2, 468),
        f"Password: {hotspot_password}",
        font=_font(16),
        fill=DIM_COLOR,
        anchor="mm"
    )
    draw.text(
        (w // 2, 496),
        f"Then open: {portal_url}",
        font=_font(16),
        fill=LOGO_COLOR,
        anchor="mm"
    )

    # Divider
    draw.line((0, content_h, w, content_h), fill=LOGO_COLOR, width=2)

    _draw_strip(draw, content_h, w, recording=True)
    write_to_fb(img)