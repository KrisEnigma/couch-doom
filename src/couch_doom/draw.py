"""Anti-aliased shapes via supersampling; pygame's own rounded rects and circles are jagged."""
from __future__ import annotations

from functools import lru_cache
from typing import Callable

import pygame

SS = 4

Color = tuple[int, ...]
Radii = tuple[float, float, float, float]  # top-left, top-right, bottom-left, bottom-right


def rr_on(big: pygame.Surface, rect: pygame.Rect, color: Color, radii: Radii) -> None:
    """Rounded rect in supersampled space."""
    tl, tr, bl, br = (max(0, int(r)) for r in radii)
    pygame.draw.rect(
        big,
        color,
        rect,
        border_radius=max(tl, tr, bl, br, 1),
        border_top_left_radius=tl,
        border_top_right_radius=tr,
        border_bottom_left_radius=bl,
        border_bottom_right_radius=br,
    )


def paint(w: int, h: int, painter: Callable[[pygame.Surface, int], None]) -> pygame.Surface:
    """Run painter(big_surface, SS) on a supersampled canvas and downsample it."""
    w, h = max(1, w), max(1, h)
    big = pygame.Surface((w * SS, h * SS), pygame.SRCALPHA)
    painter(big, SS)
    return pygame.transform.smoothscale(big, (w, h))


@lru_cache(maxsize=512)
def rounded_rect(
    w: int,
    h: int,
    radius: float,
    fill: Color,
    border: Color | None = None,
    border_w: float = 0,
    radii: Radii | None = None,
) -> pygame.Surface:
    corners = radii or (radius, radius, radius, radius)

    def p(big: pygame.Surface, k: int) -> None:
        full = pygame.Rect(0, 0, w * k, h * k)
        if border and border_w:
            rr_on(big, full, border, tuple(c * k for c in corners))
            inset = max(1, int(border_w * k))
            rr_on(big, full.inflate(-2 * inset, -2 * inset), fill, tuple(c * k - inset for c in corners))
        else:
            rr_on(big, full, fill, tuple(c * k for c in corners))

    return paint(w, h, p)


@lru_cache(maxsize=128)
def disc(d: int, fill: Color, ring: Color | None = None, ring_w: float = 0) -> pygame.Surface:
    def p(big: pygame.Surface, k: int) -> None:
        c = (d * k // 2, d * k // 2)
        if ring and ring_w:
            pygame.draw.circle(big, ring, c, d * k // 2)
            pygame.draw.circle(big, fill, c, d * k // 2 - max(1, int(ring_w * k)))
        else:
            pygame.draw.circle(big, fill, c, d * k // 2)

    return paint(d, d, p)


def horizontal_ramp(w: int, h: int, left: Color, right: Color, curve: float = 1.0) -> pygame.Surface:
    """RGBA gradient from left to right; colors may carry alpha."""
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    for x in range(w):
        t = (x / max(1, w - 1)) ** curve
        c = tuple(int(a + (b - a) * t) for a, b in zip(left, right))
        pygame.draw.line(surf, c, (x, 0), (x, h))
    return surf
