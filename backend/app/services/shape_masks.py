"""
Shape mask generator for watermark cropping.
Generates grayscale mask PNGs (white = visible, black = transparent)
that are alphamerge-d onto the watermark image in ffmpeg.
"""
import math
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

MASK_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "masks"
MASK_SIZE = 512  # all masks are square at this resolution; ffmpeg scales to target

VALID_SHAPES = {"none", "circle", "rounded", "star", "sun"}


def _draw_circle(draw: ImageDraw.ImageDraw, size: int) -> None:
    draw.ellipse((0, 0, size - 1, size - 1), fill=255)


def _draw_rounded(draw: ImageDraw.ImageDraw, size: int) -> None:
    radius = size // 6
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)


def _draw_star(draw: ImageDraw.ImageDraw, size: int) -> None:
    """5-point star."""
    cx = cy = size / 2
    outer_r = size / 2 * 0.98
    inner_r = outer_r * 0.4
    points = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        r = outer_r if i % 2 == 0 else inner_r
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(points, fill=255)


def _draw_sun(draw: ImageDraw.ImageDraw, size: int) -> None:
    """Sun: central disc + 12 triangular rays."""
    cx = cy = size / 2
    ray_outer = size / 2 * 0.98
    ray_inner = ray_outer * 0.55
    rays = 12
    points = []
    for i in range(rays * 2):
        angle = -math.pi / 2 + i * math.pi / rays
        r = ray_outer if i % 2 == 0 else ray_inner
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(points, fill=255)
    # Add solid central disc to soften the inner notches
    disc_r = ray_inner * 0.95
    draw.ellipse(
        (cx - disc_r, cy - disc_r, cx + disc_r, cy + disc_r),
        fill=255,
    )


_DRAWERS = {
    "circle": _draw_circle,
    "rounded": _draw_rounded,
    "star": _draw_star,
    "sun": _draw_sun,
}


def get_mask_path(shape: str) -> Optional[str]:
    """Return path to a cached mask PNG for the given shape, generating if missing.
    Returns None for shape='none' or unknown shapes."""
    if shape == "none" or shape not in _DRAWERS:
        return None
    MASK_DIR.mkdir(parents=True, exist_ok=True)
    target = MASK_DIR / f"{shape}_{MASK_SIZE}.png"
    if not target.exists():
        img = Image.new("L", (MASK_SIZE, MASK_SIZE), 0)
        draw = ImageDraw.Draw(img)
        _DRAWERS[shape](draw, MASK_SIZE)
        img.save(target, "PNG")
    return str(target)
