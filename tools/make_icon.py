"""Renders the app icon from the logo's silhouette: assets/brand/dragon-v-mask.png (the dragon-V, white =
the mark) painted in the «Туман» colours: a graphite mark on light grey, a soft rounded square.

Writes assets/brand/icon-<size>.rgba.z for each size of assets/icon.ico: the raw RGBA pixels, zlib-packed.
build_exe.py wraps them into the icon with its own PNG writer (app/tray.py reads only that form), so the
build needs no Pillow. Run this once when the logo or its colours change (needs Pillow):

    python tools/make_icon.py
"""
import zlib
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "assets" / "brand"
SIZES = [256, 64, 48, 32, 16]  # build_exe.py build_ico

BG = ((0xEE, 0xF1, 0xF5), (0xD9, 0xDE, 0xE6))      # top, bottom
MARK = ((0x3A, 0x41, 0x4C), (0x20, 0x25, 0x2D))    # top left, bottom right
FRAME = (0, 0, 0, 22)


def _mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _vertical(n, top, bottom):
    g = Image.new("RGB", (1, n))
    for y in range(n):
        g.putpixel((0, y), _mix(top, bottom, y / max(1, n - 1)))
    return g.resize((n, n))


def _diagonal(n, a, b):
    small = Image.new("RGB", (64, 64))
    for y in range(64):
        for x in range(64):
            small.putpixel((x, y), _mix(a, b, (x * .45 + y * .55) / 63))
    return small.resize((n, n), Image.BICUBIC)


def render(size: int) -> Image.Image:
    """One size, drawn at 1024 px and scaled down. Up to 32 px the mark fills more of the square: its head
    and horns must still read on the taskbar and in the tray."""
    n = 1024
    mask_src = Image.open(BRAND / "dragon-v-mask.png").convert("L")
    side = int(n * (0.80 if size <= 32 else 0.70))
    k = side / max(mask_src.size)
    m = mask_src.resize((round(mask_src.width * k), round(mask_src.height * k)), Image.LANCZOS)
    mask = Image.new("L", (n, n), 0)
    mask.paste(m, ((n - m.width) // 2 + n // 100, (n - m.height) // 2))
    art = Image.composite(_diagonal(n, *MARK), _vertical(n, *BG), mask)
    shape = Image.new("L", (n, n), 0)
    ImageDraw.Draw(shape).rounded_rectangle((0, 0, n - 1, n - 1), int(n * .22), fill=255)
    icon = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    icon.paste(art, (0, 0), shape)
    ImageDraw.Draw(icon).rounded_rectangle((1, 1, n - 2, n - 2), int(n * .22), outline=FRAME, width=3)
    return icon.resize((size, size), Image.LANCZOS)


def main() -> None:
    for s in SIZES:
        (BRAND / f"icon-{s}.rgba.z").write_bytes(zlib.compress(render(s).tobytes(), 9))
        print(f"[OK] icon {s}x{s}")


if __name__ == "__main__":
    main()
