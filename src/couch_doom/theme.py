"""Per-preset colour theme taken from the title art's dominant vivid hue, like media players tint to album art."""
from __future__ import annotations

import colorsys
from dataclasses import dataclass

import pygame

Color = tuple[int, int, int]
HUE_STEPS = 36  # 10-degree buckets: neighbours share a theme (and its cached background)


@dataclass(frozen=True)
class Theme:
    key: int  # hue bucket, -1 for the house theme
    label: Color  # section labels, byline, toasts
    accent: Color  # brand stripe, underlines, launch wipe
    bar: tuple[Color, Color]  # selection ramp, left to right
    bg_top: Color
    bg_bottom: Color


HOUSE = Theme(-1, (236, 170, 64), (222, 56, 30), ((132, 32, 18), (90, 24, 15)), (24, 19, 17), (50, 17, 12))
HOUSE_HUE = 8 / 360
HOUSE_RANGE = 22 / 360  # reds and oranges stay on the house theme and its gold labels


def _hls(h: float, l: float, s: float) -> Color:
    return tuple(int(c * 255) for c in colorsys.hls_to_rgb(h, l, s))


def for_hue(bucket: int) -> Theme:
    h = (bucket + 0.5) / HUE_STEPS
    # Same lightness/saturation ladder as the house colours, so contrast and legibility carry over.
    return Theme(
        bucket,
        label=_hls(h, 0.62, 0.78),
        accent=_hls(h, 0.50, 0.75),
        bar=(_hls(h, 0.30, 0.62), _hls(h, 0.21, 0.58)),
        bg_top=_hls(h, 0.08, 0.17),
        bg_bottom=_hls(h, 0.12, 0.60),
    )


def from_art(surface: pygame.Surface) -> Theme:
    small = pygame.transform.smoothscale(surface, (48, 36))
    bins = [0.0] * HUE_STEPS
    for y in range(36):
        for x in range(48):
            r, g, b, _ = small.get_at((x, y))
            h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            weight = s * (1 - abs(2 * l - 1))  # vivid mid-tones count; greys, black and white don't
            if weight >= 0.12:
                bins[int(h * HUE_STEPS) % HUE_STEPS] += weight
    bucket = max(range(HUE_STEPS), key=lambda i: bins[i])
    if bins[bucket] < 3:  # mostly grey or dark art
        return HOUSE
    hue = (bucket + 0.5) / HUE_STEPS
    if min(abs(hue - HOUSE_HUE), 1 - abs(hue - HOUSE_HUE)) <= HOUSE_RANGE:
        return HOUSE
    return for_hue(bucket)
