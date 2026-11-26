"""Generate the Kindergarten Manager application icon (2026-11-26).

Original design, drawn programmatically (no external artwork, no downloads):

* a dark-teal rounded square tile (the app surface);
* a cream-white open book filling the lower half, with a subtle darker
  under-cover and a soft spine gap so the open shape stays readable at 16px;
* a golden two-leaf sprout rising from the spine, the growing-learner motif.

Outputs, all synthetic and reproducible from this script:

* ``app_icon_master.png``      1024x1024 master artwork
* ``app_icon_256.png``         256x256 PNG for docs/store listings
* ``app_icon.ico``             Windows ICO with 16/24/32/48/64/128/256

The script only writes the three files beside itself and never touches
business data.  Pillow (already a locked backend dependency) is required.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent

# Dark-teal tile, cream book, golden sprout.
TEAL = (16, 77, 82, 255)
TEAL_EDGE = (11, 60, 65, 255)
CREAM = (246, 239, 221, 255)
CREAM_SHADE = (216, 203, 171, 255)
GOLD = (240, 180, 48, 255)
GOLD_DEEP = (214, 156, 26, 255)

WORK = 2048  # supersampled working canvas
OUT_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _teardrop_leaf(draw, *, base, length, width, lean_deg, color):
    """One leaf as a smooth teardrop polygon growing from ``base``.

    ``lean_deg`` is measured from straight up; positive leans to the right.
    The sides bulge to ``width`` near the base and taper to a soft tip, so
    two mirrored leaves read as the classic V of a young sprout.
    """
    import math

    ax, ay = base
    theta = math.radians(lean_deg)
    ux, uy = math.sin(theta), -math.cos(theta)
    px, py = -uy, ux
    steps = 16
    left_side = []
    right_side = []
    for index in range(steps + 1):
        ratio = index / steps
        bulge = (width / 2) * math.sin(math.pi * min(1.0, 0.15 + ratio * 0.95))
        cx = ax + ux * (length * ratio)
        cy = ay + uy * (length * ratio)
        left_side.append((cx + px * bulge, cy + py * bulge))
        right_side.append((cx - px * bulge, cy - py * bulge))
    draw.polygon(left_side + right_side[::-1], fill=color)


def _book_polygon(spine_x, top, bottom, spread, flare):
    """Sampled open-book outline for one half (curved top and bottom edges)."""
    top_points = []
    bottom_points = []
    steps = 24
    for index in range(steps + 1):
        ratio = index / steps
        x = spine_x - spread * ratio
        # The page top sags slightly toward the spine and lifts outward.
        lift = int(flare * (1 - ratio) ** 0.6)
        top_points.append((x, top + lift))
        bottom_points.append((x, bottom + int(lift * 0.55)))
    return top_points + bottom_points[::-1]


def render():
    image = Image.new("RGBA", (WORK, WORK), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Rounded-square tile with a slightly darker edge so the silhouette
    # survives on a white taskbar.
    draw.rounded_rectangle(
        (0, 0, WORK - 1, WORK - 1), radius=430, fill=TEAL, width=8,
        outline=TEAL_EDGE,
    )

    # Open book: a darker under-cover extending mainly downward, two cream
    # pages with a gentle outward lift, and a narrow tile-colored spine slit.
    spine_x = WORK // 2
    top = 850
    bottom = 1600
    spread = 560
    flare = 46
    cover = _book_polygon(
        spine_x, top - 36, bottom + 60, spread + 44, flare + 4
    )
    draw.polygon(cover, fill=CREAM_SHADE)
    draw.polygon(
        [(spine_x + (spine_x - x), y) for x, y in cover],
        fill=CREAM_SHADE,
    )
    for sign in (-1, 1):
        page = _book_polygon(spine_x, top, bottom, spread, flare)
        draw.polygon(
            [(spine_x + sign * (x - spine_x), y) for x, y in page],
            fill=CREAM,
        )
    draw.rectangle((spine_x - 7, top - 10, spine_x + 7, bottom + 34), fill=TEAL)

    # Two-leaf sprout: the stem rises from the spine; two mirrored teardrop
    # leaves grow from the stem top and open in a clean V.
    stem_top = 585
    draw.line([(spine_x, top - 30), (spine_x, stem_top)], fill=GOLD_DEEP, width=58)
    draw.ellipse(
        (spine_x - 29, stem_top - 29, spine_x + 29, stem_top + 29),
        fill=GOLD_DEEP,
    )
    _teardrop_leaf(
        draw, base=(spine_x - 10, stem_top - 12), length=350, width=150,
        lean_deg=-34, color=GOLD,
    )
    _teardrop_leaf(
        draw, base=(spine_x + 10, stem_top - 12), length=350, width=150,
        lean_deg=34, color=GOLD,
    )
    return image


def main():
    rendered = render()
    master = rendered.resize((1024, 1024), Image.LANCZOS)
    master.save(HERE / "app_icon_master.png")

    frame_256 = master.resize((256, 256), Image.LANCZOS)
    frame_256.save(HERE / "app_icon_256.png")

    frames = [master.resize((size, size), Image.LANCZOS) for size in OUT_SIZES]
    # The saving base image must be the largest one: the plugin skips any
    # requested size larger than the base.
    master.save(
        HERE / "app_icon.ico",
        format="ICO",
        append_images=frames,
        sizes=[(size, size) for size in OUT_SIZES],
    )
    print(f"icon files written to {HERE}")


if __name__ == "__main__":
    main()
