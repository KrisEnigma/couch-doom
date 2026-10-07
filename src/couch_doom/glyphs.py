"""Controller button and keycap glyphs.

Uses Kenney's Input Prompts (CC0, assets/prompts); falls back to vector drawing if an SVG is missing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pygame

from .draw import paint, rr_on

ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "prompts"
PROMPT_HEIGHT = 34
# Shoulders/triggers are wide; at full height they outweigh the face buttons.
PROMPT_HEIGHTS = {"LB": 27, "RB": 27, "LT": 31, "RT": 31}
PROMPT_TINT = (248, 240, 228)

_PAD_FILES = {
    "xbox": {
        "A": "xbox/xbox_button_color_a", "B": "xbox/xbox_button_color_b",
        "X": "xbox/xbox_button_color_x", "Y": "xbox/xbox_button_color_y",
        "LB": "xbox/xbox_lb", "RB": "xbox/xbox_rb", "LT": "xbox/xbox_lt", "RT": "xbox/xbox_rt",
        "START": "xbox/xbox_button_menu", "BACK": "xbox/xbox_button_view",
        "RS": "xbox/xbox_stick_r_vertical", "R3": "xbox/xbox_stick_r_press",
    },
    "playstation": {
        "A": "playstation/playstation_button_color_cross", "B": "playstation/playstation_button_color_circle",
        "X": "playstation/playstation_button_color_square", "Y": "playstation/playstation_button_color_triangle",
        "LB": "playstation/playstation_trigger_l1", "RB": "playstation/playstation_trigger_r1",
        "LT": "playstation/playstation_trigger_l2", "RT": "playstation/playstation_trigger_r2",
        "START": "playstation/playstation5_button_options", "BACK": "playstation/playstation5_button_create",
        "RS": "playstation/playstation_stick_r_vertical", "R3": "playstation/playstation_stick_r_press",
    },
    # SDL maps Nintendo pads by printed label, so "A" really is the A button here.
    "switch": {
        "A": "switch/switch_button_a", "B": "switch/switch_button_b",
        "X": "switch/switch_button_x", "Y": "switch/switch_button_y",
        "LB": "switch/switch_button_l", "RB": "switch/switch_button_r",
        "LT": "switch/switch_button_zl", "RT": "switch/switch_button_zr",
        "START": "switch/switch_button_plus", "BACK": "switch/switch_button_minus",
        "RS": "switch/switch_stick_r_vertical", "R3": "switch/switch_stick_r_press",
    },
}
_KEY_FILES = {
    "ENTER": "keyboard_mouse/keyboard_return",
    "ESC": "keyboard_mouse/keyboard_escape",
    "TAB": "keyboard_mouse/keyboard_tab",
    "/": "keyboard_mouse/keyboard_slash_forward",
    "LEFT": "keyboard_mouse/keyboard_arrow_left",
    "RIGHT": "keyboard_mouse/keyboard_arrow_right",
    "UP": "keyboard_mouse/keyboard_arrow_up",
    "DOWN": "keyboard_mouse/keyboard_arrow_down",
    "F2": "keyboard_mouse/keyboard_f2",
    "F3": "keyboard_mouse/keyboard_f3",
    "BKSP": "keyboard_mouse/keyboard_backspace_icon",
    "A-Z": "keyboard_mouse/keyboard_a",
}

BUTTON_NAMES = {
    "xbox": {"B": "B", "START": "Menu"},
    "playstation": {"B": "Circle", "START": "Options"},
    "switch": {"B": "B", "START": "+"},
}


def _load_prompt(path: Path, height: int) -> pygame.Surface:
    """Rasterize an SVG so its visible artwork (not its padded canvas) is exactly `height` px tall."""
    probe = pygame.image.load_sized_svg(str(path), (256, 256))
    ink = probe.get_bounding_rect()
    size = max(8, round(256 * height / max(1, ink.height)))
    img = pygame.image.load_sized_svg(str(path), (size, size))
    img = img.subsurface(img.get_bounding_rect()).copy()
    img.fill((*PROMPT_TINT, 255), special_flags=pygame.BLEND_RGBA_MULT)
    return img

PAD_BODY = (30, 24, 22)
PAD_LINE = (112, 100, 90)
PAD_LABEL = (226, 218, 204)
KEY_BODY = (62, 51, 46)
KEY_EDGE = (22, 17, 15)
KEY_LINE = (96, 83, 74)

FACE_COLORS = {
    "A": (112, 198, 100),
    "B": (234, 88, 66),
    "X": (88, 150, 232),
    "Y": (240, 194, 74),
}

FontGetter = Callable[..., pygame.font.Font]


def _blit_ink_centered(dest: pygame.Surface, text: pygame.Surface, cx: float, cy: float) -> None:
    """Center the visible pixels, not the font's line box (its ascent/descent padding is uneven)."""
    ink = text.get_bounding_rect()
    dest.blit(text, (round(cx - ink.centerx), round(cy - ink.centery)))


class Glyphs:
    def __init__(self, font: FontGetter, scale: float):
        self.font = font
        self.s = scale
        self.family = "xbox"
        self._cache: dict[tuple, pygame.Surface] = {}

    def _px(self, v: float) -> int:
        return max(1, int(round(v * self.s)))

    def get(self, spec: str) -> pygame.Surface:
        key = (self.family, spec)
        if key not in self._cache:
            self._cache[key] = self._from_asset(spec) or self._build(spec)
        return self._cache[key]

    def _from_asset(self, spec: str) -> pygame.Surface | None:
        rel = _KEY_FILES.get(spec[4:]) if spec.startswith("KEY:") else _PAD_FILES[self.family].get(spec)
        if not rel:
            return None
        path = ASSET_DIR / f"{rel}.svg"
        if not path.exists():
            return None
        try:
            return _load_prompt(path, self._px(PROMPT_HEIGHTS.get(spec, PROMPT_HEIGHT)))
        except (pygame.error, ValueError):
            return None

    def row(self, specs: tuple[str, ...]) -> pygame.Surface:
        key = ("row", self.family, specs)
        if key not in self._cache:
            parts = [self.get(s) for s in specs]
            gap = self._px(5)
            w = sum(p.get_width() for p in parts) + gap * (len(parts) - 1)
            h = max(p.get_height() for p in parts)
            surf = pygame.Surface((w, h), pygame.SRCALPHA)
            x = 0
            for p in parts:
                surf.blit(p, (x, (h - p.get_height()) // 2))
                x += p.get_width() + gap
            self._cache[key] = surf
        return self._cache[key]

    def _label(self, surf: pygame.Surface, text: str, size: float, color, cy: float | None = None) -> None:
        _blit_ink_centered(surf, self.font(size, bold=True).render(text, True, color), surf.get_width() / 2, surf.get_height() / 2 if cy is None else cy)

    def _build(self, spec: str) -> pygame.Surface:
        if spec in FACE_COLORS:
            return self._face(spec)
        if spec in ("LB", "RB"):
            return self._shoulder(spec)
        if spec in ("LT", "RT"):
            return self._trigger(spec)
        if spec == "START":
            return self._menu_button(self._start_icon)
        if spec == "BACK":
            return self._menu_button(self._back_icon)
        if spec.startswith("KEY:"):
            return self._keycap(spec[4:])
        if spec in ("RS", "R3"):
            return self._keycap(spec)
        raise ValueError(f"Unknown glyph {spec}")

    # ---- controller ----

    def _face(self, letter: str) -> pygame.Surface:
        d = self._px(34)
        color = FACE_COLORS[letter]
        ring = 2.4 * self.s

        def p(big, k):
            c = (d * k // 2, d * k // 2)
            pygame.draw.circle(big, color, c, d * k // 2)
            pygame.draw.circle(big, PAD_BODY, c, d * k // 2 - int(ring * k))

        surf = paint(d, d, p)
        self._label(surf, letter, 18, color)
        return surf

    def _shoulder(self, label: str) -> pygame.Surface:
        w, h = self._px(50), self._px(28)
        big_r, small_r = 14 * self.s, 6 * self.s
        radii = (big_r, small_r, small_r, small_r) if label == "LB" else (small_r, big_r, small_r, small_r)
        surf = self._outlined(w, h, radii)
        self._label(surf, label, 15, PAD_LABEL)
        return surf

    def _trigger(self, label: str) -> pygame.Surface:
        w, h = self._px(40), self._px(34)
        top, bottom = 15 * self.s, 6 * self.s
        surf = self._outlined(w, h, (top, top, bottom, bottom))
        self._label(surf, label, 15, PAD_LABEL, cy=h / 2 + 1.5 * self.s)
        return surf

    def _outlined(self, w: int, h: int, radii) -> pygame.Surface:
        line = 2 * self.s

        def p(big, k):
            full = pygame.Rect(0, 0, w * k, h * k)
            rr_on(big, full, PAD_LINE, tuple(r * k for r in radii))
            inset = int(line * k)
            rr_on(big, full.inflate(-2 * inset, -2 * inset), PAD_BODY, tuple(r * k - inset for r in radii))

        return paint(w, h, p)

    def _menu_button(self, icon) -> pygame.Surface:
        w, h = self._px(42), self._px(28)
        line = 2 * self.s

        def p(big, k):
            full = pygame.Rect(0, 0, w * k, h * k)
            r = h * k / 2
            rr_on(big, full, PAD_LINE, (r, r, r, r))
            inset = int(line * k)
            rr_on(big, full.inflate(-2 * inset, -2 * inset), PAD_BODY, (r - inset,) * 4)
            icon(big, k, w * k, h * k)

        return paint(w, h, p)

    def _start_icon(self, big, k, W, H):
        bar_w, bar_h, gap = 14 * self.s * k, 2.2 * self.s * k, 4 * self.s * k
        x = (W - bar_w) / 2
        y0 = H / 2 - gap - bar_h / 2
        for i in range(3):
            pygame.draw.rect(big, PAD_LABEL, (x, y0 + i * gap, bar_w, bar_h), border_radius=int(bar_h / 2))

    def _back_icon(self, big, k, W, H):
        size, off, line = 9 * self.s * k, 3.5 * self.s * k, max(1, int(2 * self.s * k))
        cx, cy = W / 2, H / 2
        pygame.draw.rect(big, PAD_LABEL, (cx - size / 2 - off / 2, cy - size / 2 - off / 2, size, size), line, border_radius=int(2 * self.s * k))
        pygame.draw.rect(big, PAD_LABEL, (cx - size / 2 + off / 2, cy - size / 2 + off / 2, size, size), border_radius=int(2 * self.s * k))

    # ---- keyboard ----

    def _keycap(self, name: str) -> pygame.Surface:
        h = self._px(32)
        edge = 3.5 * self.s
        arrows = {"LEFT": 180, "RIGHT": 0, "UP": 90, "DOWN": 270}
        font = self.font(14, bold=True)
        text_w = 0 if name in arrows else font.size(name)[0]
        w = max(h, text_w + self._px(22))
        radius = 6 * self.s

        def p(big, k):
            full = pygame.Rect(0, 0, w * k, h * k)
            rr_on(big, full, KEY_EDGE, (radius * k,) * 4)
            cap = pygame.Rect(0, 0, w * k, int((h - edge) * k))
            rr_on(big, cap, KEY_LINE, (radius * k,) * 4)
            inset = max(1, int(1.4 * self.s * k))
            rr_on(big, cap.inflate(-2 * inset, -2 * inset), KEY_BODY, ((radius - 1.4 * self.s) * k,) * 4)
            if name in arrows:
                self._arrow(big, k, cap.center, arrows[name])

        surf = paint(w, h, p)
        if name not in arrows:
            t = font.render(name, True, PAD_LABEL)
            _blit_ink_centered(surf, t, w / 2, (h - edge) / 2)
        return surf

    def _arrow(self, big, k, center, angle: int) -> None:
        size = 6.5 * self.s * k
        cx, cy = center
        pts = {
            0: [(cx + size, cy), (cx - size * 0.7, cy - size), (cx - size * 0.7, cy + size)],
            180: [(cx - size, cy), (cx + size * 0.7, cy - size), (cx + size * 0.7, cy + size)],
            90: [(cx, cy - size), (cx - size, cy + size * 0.7), (cx + size, cy + size * 0.7)],
            270: [(cx, cy + size), (cx - size, cy - size * 0.7), (cx + size, cy - size * 0.7)],
        }[angle]
        pygame.draw.polygon(big, PAD_LABEL, pts)
