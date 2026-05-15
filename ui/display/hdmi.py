import time
import logging
import struct
import fcntl
import array
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from consai.config import UNIT_ID
from consai.db import get_last_capture, get_pending_count
from consai.utils import get_cpu_temp, get_disk_free_mb
from consai.battery import get_battery_status

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

FB_DEV       = "/dev/fb0"
STRIP_H      = 50           # bottom status strip — fixed pixel height
LOGO_COLOR   = (255, 140, 0)
BG_COLOR     = (10, 10, 10)
STRIP_COLOR  = (24, 24, 24)
TEXT_COLOR   = (255, 255, 255)
DIM_COLOR    = (90, 90, 90)
REC_COLOR    = (220, 40, 40)

# ── Framebuffer detection ─────────────────────────────────────────────────────

def get_fb_info() -> tuple[int, int, int]:
    """
    Returns (width, height, bits_per_pixel) from the framebuffer.
    Falls back to safe defaults if detection fails.
    """
    try:
        FBIOGET_VSCREENINFO = 0x4600
        with open(FB_DEV, 'rb') as fb:
            info = array.array('B', [0] * 160)
            fcntl.ioctl(fb, FBIOGET_VSCREENINFO, info, True)
            w   = struct.unpack_from('I', info, 0)[0]
            h   = struct.unpack_from('I', info, 4)[0]
            bpp = struct.unpack_from('I', info, 24)[0]
            if w > 0 and h > 0 and bpp in (16, 24, 32):
                return w, h, bpp
    except Exception as e:
        logger.warning(f"FB detection failed: {e}")
    return 1024, 600, 16  # safe default

# ── Framebuffer writer ────────────────────────────────────────────────────────

def _to_rgb565(r: int, g: int, b: int) -> int:
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

def write_to_fb(image: Image.Image):
    """
    Write a PIL image to the framebuffer.
    Handles 16-bit RGB565, 24-bit RGB, and 32-bit RGBA automatically.
    Image is resized to match FB resolution exactly.
    """
    w, h, bpp = get_fb_info()
    img = image.resize((w, h), Image.LANCZOS).convert("RGB")
    pixels = img.load()

    if bpp == 16:
        buf = bytearray(w * h * 2)
        idx = 0
        for y in range(h):
            for x in range(w):
                r, g, b = pixels[x, y]
                c = _to_rgb565(r, g, b)
                buf[idx]     = c & 0xFF
                buf[idx + 1] = (c >> 8) & 0xFF
                idx += 2
    elif bpp == 24:
        buf = bytearray(w * h * 3)
        idx = 0
        for y in range(h):
            for x in range(w):
                r, g, b = pixels[x, y]
                buf[idx] = b; buf[idx+1] = g; buf[idx+2] = r
                idx += 3
    else:  # 32-bit BGRA
        img32 = image.resize((w, h), Image.LANCZOS).convert("RGBA")
        r, g, b, a = img32.split()
        bgra = Image.merge("RGBA", (b, g, r, a))
        buf = bgra.tobytes()

    try:
        with open(FB_DEV, 'wb') as fb:
            fb.write(buf)
    except Exception as e:
        logger.error(f"FB write failed: {e}")

# ── Fonts — scaled to FB height ───────────────────────────────────────────────

def _scale(base: int) -> int:
    """Scale font size relative to FB height."""
    _, h, _ = get_fb_info()
    return max(8, int(base * h / 600))

def _font(size: int) -> ImageFont:
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            _scale(size))
    except Exception:
        return ImageFont.load_default()

def _font_bold(size: int) -> ImageFont:
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            _scale(size))
    except Exception:
        return ImageFont.load_default()

# ── Letterbox helper ──────────────────────────────────────────────────────────

def _letterbox(photo: Image.Image, max_w: int, max_h: int) -> tuple[Image.Image, int, int]:
    """
    Fit photo into max_w x max_h preserving aspect ratio.
    Returns (resized_image, x_offset, y_offset) for centered placement.
    """
    pw, ph = photo.size
    scale  = min(max_w / pw, max_h / ph)
    nw     = int(pw * scale)
    nh     = int(ph * scale)
    resized = photo.resize((nw, nh), Image.LANCZOS)
    x = (max_w - nw) // 2
    y = (max_h - nh) // 2
    return resized, x, y

# ── Status strip ──────────────────────────────────────────────────────────────

def _draw_strip(draw: ImageDraw.Draw, y: int, w: int, recording: bool = True):
    draw.rectangle((0, y, w, y + STRIP_H), fill=STRIP_COLOR)

    battery  = get_battery_status()
    temp     = get_cpu_temp()
    disk     = get_disk_free_mb()
    now      = time.strftime("%H:%M")
    try:
        from consai.config import INSTALLATION_ID
        from consai.db import get_photo_count_for_installation
        count = get_photo_count_for_installation(INSTALLATION_ID)
    except Exception:
        count = 0
    pending  = get_pending_count()

    # Battery
    if battery["available"]:
        bolt    = " ⚡" if battery["charging"] else ""
        bat_str = f"{battery['percent']}%{bolt}"
    else:
        bat_str = "--"

    # Sync
    try:
        pending = get_pending_count()
        p_up = pending["pending_upload"]
        p_sy = pending["pending_sync"]
        sync_str = "synced" if p_up == 0 and p_sy == 0 else f"↑{p_up}"
    except Exception:
        count = 0
        sync_str = "--"

    # Rec indicator
    rec_str = "● REC" if recording else "○ STP"
    rec_col = REC_COLOR if recording else DIM_COLOR

    temp_str = f"{temp}C" if temp else "--C"
    disk_str = f"{disk // 1024}GB" if disk > 0 else "--"

    fn = _font_bold(16)
    fs = _font(13)
    cy = y + STRIP_H // 2 - _scale(8)

    # Evenly space items across the strip
    items = [
        (UNIT_ID,               fn, LOGO_COLOR),
        (now,                   fn, TEXT_COLOR),
        (f"Photos {count}",     fs, TEXT_COLOR),
        (sync_str,              fs, TEXT_COLOR),
        (f"CPU {temp_str}",     fs, TEXT_COLOR),
        (f"Disk {disk_str}",    fs, TEXT_COLOR),
        (f"Batt {bat_str}",     fs, TEXT_COLOR),
    ]

    # Left side items — evenly spaced
    section_w = (w - 160) // len(items)
    for i, (text, font, color) in enumerate(items):
        draw.text((20 + i * section_w, cy), text, font=font, fill=color)

    # REC — pinned to right
    draw.text((w - 140, cy), rec_str, font=fn, fill=rec_col)

# ── Screens ───────────────────────────────────────────────────────────────────

def draw_logo_screen(recording: bool = True):
    """Default HDMI — branded Consai frame."""
    w, h, _ = get_fb_info()
    content_h = h - STRIP_H

    img  = Image.new("RGB", (w, h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Logo
    draw.text(
        (w // 2, content_h // 2 - _scale(50)),
        "CONSAI",
        font=_font_bold(80),
        fill=LOGO_COLOR,
        anchor="mm"
    )

    # Tagline
    draw.text(
        (w // 2, content_h // 2 + _scale(20)),
        "Every frame. Every day.",
        font=_font(22),
        fill=DIM_COLOR,
        anchor="mm"
    )

    # Unit ID below tagline
    draw.text(
        (w // 2, content_h // 2 + _scale(50)),
        f"Unit {UNIT_ID}",
        font=_font(18),
        fill=DIM_COLOR,
        anchor="mm"
    )

    # Hint
    draw.text(
        (w // 2, content_h - _scale(30)),
        "KEY2 — test capture    KEY1 — start/stop",
        font=_font(14),
        fill=DIM_COLOR,
        anchor="mm"
    )

    # Divider above strip
    draw.line((0, content_h, w, content_h), fill=LOGO_COLOR, width=2)

    _draw_strip(draw, content_h, w, recording=recording)
    write_to_fb(img)


def draw_photo_screen(photo_path: str, recording: bool = True,
                      duration: float = 10.0):
    """
    Show a captured photo letterboxed fullscreen with status strip.
    Returns to logo screen after duration seconds.
    """
    w, h, _ = get_fb_info()
    content_h = h - STRIP_H

    img  = Image.new("RGB", (w, h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Load and letterbox the photo
    try:
        photo = Image.open(photo_path).convert("RGB")
        resized, px, py = _letterbox(photo, w, content_h)
        img.paste(resized, (px, py))
        logger.info(f"Photo displayed: {photo_path} → {resized.size} at ({px},{py})")
    except Exception as e:
        logger.error(f"Photo load failed: {e}")
        draw.text((w // 2, content_h // 2), "Photo load failed",
                  font=_font(20), fill=TEXT_COLOR, anchor="mm")

    # Filename + timestamp overlay bar
    last = get_last_capture()
    if last:
        bar_h = _scale(22)
        draw.rectangle((0, content_h - bar_h, w, content_h),
                        fill=(0, 0, 0))
        draw.text(
            (10, content_h - bar_h + 2),
            f"{last['filename']}   {last['captured_at']}   "
            f"{last['size_bytes'] // 1024}KB   "
            f"{last['width']}x{last['height']}",
            font=_font(12),
            fill=DIM_COLOR
        )

    # Orange border around photo area
    draw.rectangle((px - 2, py - 2,
                    px + resized.width + 2,
                    py + resized.height + 2),
                   outline=LOGO_COLOR, width=2)

    # Divider
    draw.line((0, content_h, w, content_h), fill=LOGO_COLOR, width=2)

    _draw_strip(draw, content_h, w, recording=recording)
    write_to_fb(img)

    time.sleep(duration)
    draw_logo_screen(recording=recording)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    w, h, bpp = get_fb_info()
    print(f"Framebuffer: {w}x{h} {bpp}bpp")
    print("Drawing logo screen — check HDMI...")
    draw_logo_screen(recording=True)
    time.sleep(10)

    # Test with last photo if available
    from consai.db import get_last_capture
    last = get_last_capture()
    if last:
        print(f"Showing photo: {last['filename']}")
        draw_photo_screen(last["filepath"], recording=True, duration=10)
    print("Done")