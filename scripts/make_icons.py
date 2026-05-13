"""Generate all icon assets for MonomePyBridge from a single programmatic design.

Usage (from repo root):

    python scripts/make_icons.py

Outputs into monomepybridge/resources/:
    icon_16.png   icon_32.png   icon_48.png   icon_64.png
    icon_128.png  icon_256.png  icon_512.png  icon_1024.png
    icon.ico      (Windows — multi-size ICO: 16 / 32 / 48 / 64 / 128 / 256)
    icon.icns     (macOS  — PNG-compressed ICNS: all sizes)

Design: dark navy rounded-square background with a 4×4 monome button grid.
The outer ring of buttons is lit in amber; the inner 2×2 quad stays dim,
giving a clean "hollow-square" silhouette that reads well from 16 → 1024 px.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw

RESOURCES = Path(__file__).resolve().parent.parent / "monomepybridge" / "resources"

# ── Colour palette ─────────────────────────────────────────────────────
BG        = ( 14,  14,  30, 255)   # very dark navy
BTN_LIT   = (240, 160,  28, 255)   # amber — lit button
BTN_GLOW  = (255, 210,  80, 255)   # lighter amber for top-left highlight
BTN_DIM   = ( 38,  38,  60, 255)   # deep indigo-gray — unlit button
BTN_DSHADOW = (160,  80,   0, 255)  # shadow below lit button
BTN_SSHADOW = ( 18,  18,  36, 255)  # shadow below dim button

# 4×4 grid: outer ring lit, inner 2×2 dim  →  hollow square silhouette
_LIT = frozenset([
    (0,0),(0,1),(0,2),(0,3),
    (1,0),               (1,3),
    (2,0),               (2,3),
    (3,0),(3,1),(3,2),(3,3),
])


def _render(size: int) -> Image.Image:
    """Render the icon at ``size × size`` pixels, fully RGBA."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── background rounded rectangle ──────────────────────────────────
    pad = max(1, round(size * 0.04))
    bg_r = round(size * 0.20)
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=bg_r,
        fill=BG,
    )

    # ── 4×4 button grid ───────────────────────────────────────────────
    cols = rows = 4
    grid_pad   = round(size * 0.115)   # margin between bg edge and grid
    gap        = round(size * 0.032)   # gap between buttons
    available  = size - 2 * grid_pad - (cols - 1) * gap
    cell       = available / cols
    btn_r      = max(2, round(cell * 0.20))

    for row in range(rows):
        for col in range(cols):
            x0 = grid_pad + col * (cell + gap)
            y0 = grid_pad + row * (cell + gap)
            x1 = x0 + cell
            y1 = y0 + cell

            lit = (row, col) in _LIT

            # --- shadow (offset 2px bottom-right) ----------------------
            shadow_off = max(1, round(size * 0.004))
            shadow_col = BTN_DSHADOW if lit else BTN_SSHADOW
            draw.rounded_rectangle(
                [x0 + shadow_off, y0 + shadow_off,
                 x1 + shadow_off, y1 + shadow_off],
                radius=btn_r,
                fill=shadow_col,
            )

            # --- main button face --------------------------------------
            base_col = BTN_LIT if lit else BTN_DIM
            draw.rounded_rectangle(
                [x0, y0, x1, y1],
                radius=btn_r,
                fill=base_col,
            )

            # --- top-left highlight (only visible at >= 32 px) --------
            if size >= 32 and lit:
                hl_h = max(2, round(cell * 0.22))
                hl_w = round(cell * 0.60)
                hl_r = max(1, btn_r // 2)
                draw.rounded_rectangle(
                    [x0 + 2, y0 + 2,
                     x0 + 2 + hl_w, y0 + 2 + hl_h],
                    radius=hl_r,
                    fill=BTN_GLOW,
                )

    return img


# ── ICNS writer (pure Python, macOS PNG-compressed ICNS) ───────────────
_ICNS_MAP = {
     16: b"icp4",
     32: b"icp5",
     64: b"icp6",
    128: b"ic07",
    256: b"ic08",
    512: b"ic09",
   1024: b"ic10",
}


def _build_icns(images: dict[int, Image.Image]) -> bytes:
    entries: list[bytes] = []
    for size, ostype in _ICNS_MAP.items():
        img = images.get(size)
        if img is None:
            continue
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png = buf.getvalue()
        entry_len = 8 + len(png)
        entries.append(ostype + struct.pack(">I", entry_len) + png)
    body = b"".join(entries)
    return b"icns" + struct.pack(">I", 8 + len(body)) + body


# ── main ───────────────────────────────────────────────────────────────
def main() -> None:
    RESOURCES.mkdir(parents=True, exist_ok=True)

    sizes = [16, 32, 48, 64, 128, 256, 512, 1024]
    images: dict[int, Image.Image] = {}

    for s in sizes:
        img = _render(s)
        out = RESOURCES / f"icon_{s}.png"
        img.save(out, format="PNG")
        images[s] = img
        print(f"  {out.name}  ({s}×{s})")

    # Windows ICO — embed 16 / 32 / 48 / 64 / 128 / 256
    ico_sizes = [16, 32, 48, 64, 128, 256]
    ico_imgs = [images[s].convert("RGBA") for s in ico_sizes]
    ico_path = RESOURCES / "icon.ico"
    ico_imgs[0].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in ico_sizes],
        append_images=ico_imgs[1:],
    )
    print(f"  {ico_path.name}  (ICO, {ico_sizes})")

    # macOS ICNS
    icns_path = RESOURCES / "icon.icns"
    icns_path.write_bytes(_build_icns(images))
    print(f"  {icns_path.name}  (ICNS)")

    print(f"\nAll icons written to:\n  {RESOURCES}")


if __name__ == "__main__":
    main()
