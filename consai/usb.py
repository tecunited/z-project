import os
import subprocess
import logging
from pathlib import Path
from datetime import datetime

from consai.config import UNIT_ID, INSTALLATION_ID
from consai.db import log_event

logger = logging.getLogger(__name__)

MOUNT_POINT = Path("/mnt/usb")

# ── Detection ─────────────────────────────────────────────────────────────────

def find_usb_device() -> str | None:
    """Return device path of first USB storage partition, or None."""
    try:
        result = subprocess.run(
            ["lsblk", "-o", "NAME,TRAN,FSTYPE", "-rn"],
            capture_output=True, text=True
        )
        usb_disks = set()
        partitions = []

        for line in result.stdout.splitlines():
            parts = line.split()
            if not parts:
                continue
            name = parts[0]

            # Detect USB disk
            if len(parts) == 2 and parts[1] == "usb":
                usb_disks.add(name)

            # Detect partition with filesystem
            elif len(parts) == 2 and parts[1] in ("vfat", "exfat", "ntfs", "ext4"):
                partitions.append(name)
            elif len(parts) == 3 and parts[2] in ("vfat", "exfat", "ntfs", "ext4"):
                partitions.append(name)

        # Match partition to USB disk by name prefix
        for part in partitions:
            parent = part.rstrip("0123456789")
            if parent in usb_disks:
                return f"/dev/{part}"

    except Exception as e:
        logger.error(f"USB detection failed: {e}")
    return None

def is_usb_present() -> bool:
    return find_usb_device() is not None

# ── Mount / unmount ───────────────────────────────────────────────────────────

def is_mounted() -> bool:
    try:
        result = subprocess.run(
            ["mountpoint", "-q", str(MOUNT_POINT)],
            capture_output=True
        )
        return result.returncode == 0
    except Exception:
        return False

def mount_usb() -> bool:
    # Always unmount first for clean mount
    if is_mounted():
        unmount_usb()

    device = find_usb_device()
    if not device:
        logger.warning("No USB device found")
        return False
    try:
        MOUNT_POINT.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["sudo", "mount", device, str(MOUNT_POINT)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            logger.error(f"Mount failed: {result.stderr}")
            return False
        logger.info(f"USB mounted: {device} → {MOUNT_POINT}")
        return True
    except Exception as e:
        logger.error(f"Mount error: {e}")
        return False

def unmount_usb() -> bool:
    try:
        subprocess.run(
            ["sudo", "umount", str(MOUNT_POINT)],
            capture_output=True, text=True
        )
        logger.info("USB unmounted safely")
        return True
    except Exception as e:
        logger.error(f"Unmount error: {e}")
        return False

def get_usb_free_mb() -> int:
    try:
        st = os.statvfs(MOUNT_POINT)
        return int(st.f_bavail * st.f_frsize / 1024 / 1024)
    except Exception:
        return -1

# ── Backup ────────────────────────────────────────────────────────────────────

def backup_to_usb(progress_callback=None, hq_only: bool = False) -> dict:
    """
    Copy photos to USB stick.
    Uses fixed folder name per unit/installation — skips already copied files.
    Safe to run multiple times — acts as incremental backup.
    """
    from consai.config import PHOTO_DIR

    if not mount_usb():
        return {"error": "Could not mount USB"}

    # Fixed folder — same name every time, new files get added, existing skipped
    dest_name = f"{UNIT_ID}_{INSTALLATION_ID}"
    dest = MOUNT_POINT / dest_name

    mk = subprocess.run(
        ["sudo", "mkdir", "-p", str(dest)],
        capture_output=True, text=True
    )
    if mk.returncode != 0:
        unmount_usb()
        return {"error": f"Could not create folder: {mk.stderr.strip()}"}

    # Gather files
    all_files = sorted(PHOTO_DIR.glob("*.jpg"))
    if hq_only:
        files = [f for f in all_files
                 if not f.stem.endswith("_pr")
                 and not f.stem.endswith("_th")]
    else:
        files = all_files

    total   = len(files)
    copied  = 0
    skipped = 0
    errors  = 0

    usb_free = get_usb_free_mb()
    logger.info(f"USB backup: {total} files → {dest} ({usb_free}MB free)")

    for i, src in enumerate(files):
        if progress_callback:
            progress_callback(i + 1, total, src.name)

        # Stop if USB almost full
        if get_usb_free_mb() < 50:
            logger.warning("USB almost full — stopping backup")
            break

        dst = dest / src.name

        # Skip if already backed up
        if dst.exists():
            skipped += 1
            continue

        # Copy
        cp = subprocess.run(
            ["sudo", "cp", str(src), str(dst)],
            capture_output=True, text=True
        )
        if cp.returncode == 0:
            copied += 1
            logger.debug(f"Copied: {src.name}")
        else:
            logger.error(f"Copy failed {src.name}: {cp.stderr.strip()}")
            errors += 1

    log_event("usb", f"Backup: {copied} copied, {skipped} skipped, {errors} errors")
    unmount_usb()

    return {
        "copied":  copied,
        "skipped": skipped,
        "errors":  errors,
        "total":   total,
        "dest":    str(dest),
    }

# ── Delete ────────────────────────────────────────────────────────────────────

def delete_synced_photos() -> int:
    """Delete photos that have been successfully uploaded. Returns count."""
    from consai.db import get_db
    from consai.config import PHOTO_DIR, PHOTO_BACKUP_DIR

    deleted = 0
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, filepath, backup_path, pr_path, th_path
            FROM photos
            WHERE uploaded = 1 AND synced_to_api = 1
        """).fetchall()

    for row in rows:
        for path_key in ["filepath", "backup_path", "pr_path", "th_path"]:
            p = row[path_key]
            if p and Path(p).exists():
                try:
                    Path(p).unlink()
                    deleted += 1
                except Exception as e:
                    logger.error(f"Delete failed {p}: {e}")

    log_event("usb", f"Deleted {deleted} synced photo files")
    return deleted

def delete_all_photos() -> int:
    """Delete ALL photos and reset DB. Returns count."""
    from consai.config import PHOTO_DIR, PHOTO_BACKUP_DIR
    from consai.db import get_db

    deleted = 0
    for folder in [PHOTO_DIR, PHOTO_BACKUP_DIR]:
        for f in folder.glob("*.jpg"):
            try:
                f.unlink()
                deleted += 1
            except Exception as e:
                logger.error(f"Delete failed {f}: {e}")

    # Clear photos table
    with get_db() as conn:
        conn.execute("DELETE FROM photos")
        conn.execute("DELETE FROM system_events")

    log_event("usb", f"Full delete: {deleted} files removed, DB cleared")
    return deleted


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"USB present: {is_usb_present()}")
    print(f"Device: {find_usb_device()}")
    print(f"Mounted: {is_mounted()}")