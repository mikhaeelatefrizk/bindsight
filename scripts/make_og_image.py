# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generate docs/assets/og-image.png, the social-preview card.

Committed as a PNG because Open Graph consumers (Twitter/X, LinkedIn, Slack,
Mastodon) do not render SVG. This script is the reproducible source for that
PNG — regenerate with:

    python scripts/make_og_image.py

Requires Pillow, which arrives with the ``report`` extra via matplotlib.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
NAVY = (11, 83, 148)
NAVY_DARK = (8, 59, 107)
TEAL = (15, 157, 143)
WHITE = (255, 255, 255)

OUT = Path(__file__).resolve().parents[1] / "docs" / "assets" / "og-image.png"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load DejaVu at ``size``, falling back to Pillow's default."""
    import matplotlib

    base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(str(base / name), size)
    except OSError:  # pragma: no cover - environment without the bundled fonts
        return ImageFont.load_default()


def _background() -> Image.Image:
    """Vertical navy gradient canvas."""
    img = Image.new("RGB", (W, H), NAVY)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        draw.line(
            [(0, y), (W, y)],
            fill=tuple(int(NAVY[i] + (NAVY_DARK[i] - NAVY[i]) * t) for i in range(3)),
        )
    return img


def _mark(size: int) -> Image.Image:
    """Render the bindsight mark: open antigen ring with a docked binder."""
    scale = 4
    s = size * scale
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    pad = int(s * 0.10)
    width = int(s * 0.095)
    box = (pad, pad, s - pad, s - pad)
    # Gap spans 270..360 deg (upper right) — that is the targetable site.
    draw.arc(box, start=0, end=270, fill=WHITE, width=width)

    core = int(s * 0.10)
    cx = cy = s // 2
    draw.ellipse((cx - core, cy - core, cx + core, cy + core), fill=WHITE)

    # Binder capsule, docked radially into the open site at 45 degrees.
    cap_w, cap_h = int(s * 0.15), int(s * 0.32)
    cap = Image.new("RGBA", (cap_w, cap_h), (0, 0, 0, 0))
    ImageDraw.Draw(cap).rounded_rectangle((0, 0, cap_w - 1, cap_h - 1), cap_w // 2, fill=TEAL)
    cap = cap.rotate(-45, expand=True, resample=Image.BICUBIC)

    # Seat the capsule slightly inside the ring radius so it reads as docked
    # into the open site rather than floating beside it.
    radius = (s - 2 * pad) / 2 * 0.62
    bx = int(cx + radius * 0.707) - cap.width // 2
    by = int(cy - radius * 0.707) - cap.height // 2
    layer.alpha_composite(cap, (bx, by))

    return layer.resize((size, size), Image.LANCZOS)


def main() -> int:
    """Render the card and write it to docs/assets/og-image.png."""
    img = _background()
    draw = ImageDraw.Draw(img)

    img.paste(_mark(150), (80, 74), _mark(150))

    draw.text((256, 92), "bindsight", font=_font(84, bold=True), fill=WHITE)
    draw.text((258, 190), "Expression → Binder", font=_font(34), fill=(150, 200, 245))

    body = [
        "The first open-source pipeline that takes RNA-seq counts",
        "and outputs ranked de novo protein binder candidates —",
        "with full provenance back to the patient cohort.",
    ]
    for i, line in enumerate(body):
        draw.text((80, 290 + i * 46), line, font=_font(33), fill=(226, 238, 250))

    draw.line([(80, 456), (W - 80, 456)], fill=(255, 255, 255, 60), width=2)

    facts = [
        ("ERBB2", "rediscovered, rank 4"),
        ("0.84", "best ipTM, free GPU"),
        ("50%", "success @ ipTM 0.65"),
        ("AGPL-3.0", "open + citable"),
    ]
    for i, (value, label) in enumerate(facts):
        x = 80 + i * 268
        draw.text((x, 492), value, font=_font(42, bold=True), fill=WHITE)
        draw.text((x, 546), label, font=_font(21), fill=(160, 195, 232))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
