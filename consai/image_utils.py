import logging
from pathlib import Path
from PIL import Image

logger = logging.getLogger(__name__)


def generate_preview_and_thumbnail(hq_path: Path) -> tuple[Path, Path]:
    """
    Generate _pr (half resolution) and _th (1/5 resolution) from HQ.
    Returns (pr_path, th_path).
    Raises on failure.
    """
    base = hq_path.stem          # e.g. master-z_20260506_114610
    pr_path = hq_path.parent / f"{base}_pr.jpg"
    th_path = hq_path.parent / f"{base}_th.jpg"

    with Image.open(hq_path) as img:
        w, h = img.size

        # Preview — half resolution
        pr = img.copy()
        pr.thumbnail((w // 2, h // 2), Image.LANCZOS)
        pr.save(pr_path, "JPEG", quality=85)
        logger.info(f"Preview: {pr_path.name} ({pr.size[0]}x{pr.size[1]})")

        # Thumbnail — 1/5 resolution
        th = img.copy()
        th.thumbnail((w // 5, h // 5), Image.LANCZOS)
        th.save(th_path, "JPEG", quality=75)
        logger.info(f"Thumbnail: {th_path.name} ({th.size[0]}x{th.size[1]})")

    return pr_path, th_path


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("Usage: python3 -m consai.image_utils <path_to_hq.jpg>")
        sys.exit(1)
    hq = Path(sys.argv[1])
    pr, th = generate_preview_and_thumbnail(hq)
    print(f"✅ PR: {pr} ({pr.stat().st_size} bytes)")
    print(f"✅ TH: {th} ({th.stat().st_size} bytes)")