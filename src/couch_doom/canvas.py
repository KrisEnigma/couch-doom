"""GPU stand-in for the window surface.

The UI is drawn as a pile of cached pygame surfaces. On a software window surface every frame re-blends all of
them on the CPU, which costs more than a 120 Hz frame at Retina and 4K sizes. A Canvas takes the same calls,
uploads each surface once as a texture, and lets the GPU do the blending, so a frame costs about the same at any
resolution and refresh rate.

It covers what ui.py does to the screen: blit, fill (plain and BLEND_MULT), clip, copy and the few pygame.draw
shapes, through rect(), lines() and line() below. A surface must not be drawn onto after its first blit to a
Canvas: its texture would go stale. The UI already builds a surface once and then only blits it.
"""
from __future__ import annotations

import weakref
from collections import OrderedDict

import pygame
from pygame._sdl2 import video

_ZERO, _ONE, _ONE_MINUS_SRC_ALPHA, _ADD = 1, 2, 6, 1  # SDL_BlendFactor / SDL_BlendOperation
_SHAPE_CACHE_SIZE = 256
# SDL's software renderer is slower than blitting to the window surface, so a machine without a GPU gets the
# surface instead. The dummy video driver only has the software renderer: smoke sets -1 to exercise the canvas.
ACCELERATED = 1
# Renderer failures raise pygame._sdl2.sdl2.error, a RuntimeError that is not a pygame.error.
ERRORS = (pygame.error, RuntimeError)


class Canvas:
    def __init__(self, window: pygame.Window):
        # convert() and convert_alpha() take their format from a window surface, and a window with a renderer has
        # none. A hidden 1x1 window lends its surface for that, and must outlive every convert. utility keeps it
        # out of the Windows and X11 taskbar.
        self.format_window = pygame.Window("CouchDoom", (1, 1), hidden=True, utility=True)
        self.format_window.get_surface()
        try:
            self.renderer = video.Renderer(window, accelerated=ACCELERATED, vsync=True)
        except ERRORS:
            self.format_window.destroy()
            raise
        self._textures: weakref.WeakKeyDictionary[pygame.Surface, video.Texture] = weakref.WeakKeyDictionary()
        self._shapes: OrderedDict[tuple, pygame.Surface] = OrderedDict()
        self._clip: pygame.Rect | None = None
        # Darkens what's under an alpha shape to (1 - alpha), keeping the colour for an ADD pass to fill in.
        self._cut = video.Renderer.compose_custom_blend_mode((_ZERO, _ONE_MINUS_SRC_ALPHA, _ADD), (_ZERO, _ONE, _ADD))
        self._clear()

    def close(self) -> None:
        """Free textures before the renderer, and the renderer before its window: SDL frees them with the window."""
        self._textures.clear()
        self._shapes.clear()
        self.renderer = None
        if self.format_window is not None:
            self.format_window.destroy()
            self.format_window = None

    # ---------- surface-like queries ----------

    def get_size(self) -> tuple[int, int]:
        return self.renderer.get_viewport().size

    def get_width(self) -> int:
        return self.get_size()[0]

    def get_height(self) -> int:
        return self.get_size()[1]

    def get_rect(self) -> pygame.Rect:
        return pygame.Rect((0, 0), self.get_size())

    def get_clip(self) -> pygame.Rect:
        return self._clip.copy() if self._clip else self.get_rect()

    def set_clip(self, rect) -> None:
        self._clip = pygame.Rect(rect).clip(self.get_rect()) if rect is not None else None

    def copy(self) -> pygame.Surface:
        """What has been drawn this frame, read back from the GPU. Slow: for one-off snapshots only."""
        return self.renderer.to_surface()

    # ---------- drawing ----------

    def texture(self, surface: pygame.Surface) -> video.Texture:
        tex = self._textures.get(surface)
        if tex is None:
            tex = self._textures[surface] = video.Texture.from_surface(self.renderer, surface)
        return tex

    def blit(self, source: pygame.Surface, dest, area=None, special_flags: int = 0) -> pygame.Rect:
        if special_flags:
            raise NotImplementedError("Canvas.blit has no special_flags; see blit_mix for the one blend it needs")
        bounds = source.get_rect()
        src = pygame.Rect(area).clip(bounds) if area is not None else bounds
        dst = pygame.Rect(int(dest[0]), int(dest[1]), src.w, src.h)
        shown = dst.clip(self.get_clip())
        if not shown.w or not shown.h:
            return pygame.Rect(dst.topleft, (0, 0))
        src = pygame.Rect(src.x + shown.x - dst.x, src.y + shown.y - dst.y, shown.w, shown.h)
        tex = self.texture(source)
        alpha = source.get_alpha()
        tex.alpha = 255 if alpha is None else alpha
        tex.blend_mode = pygame.BLENDMODE_BLEND
        tex.draw(srcrect=src, dstrect=shown)
        return shown

    def blit_scaled(self, source: pygame.Surface, area: pygame.Rect, dest: pygame.Rect, alpha: float = 1.0) -> None:
        """`area` of `source` stretched to `dest`, nearest-neighbour, inside the clip. The launch zoom uses it to scale
        on the GPU instead of rescaling a full-screen slice every frame."""
        clip = self.get_clip()
        shown = pygame.Rect(dest).clip(clip)
        if not shown.w or not shown.h or not area.w or not area.h:
            return
        kx, ky = area.w / dest.w, area.h / dest.h
        src = pygame.FRect(area.x + (shown.x - dest.x) * kx, area.y + (shown.y - dest.y) * ky, shown.w * kx, shown.h * ky)
        tex = self.texture(source)
        tex.alpha = max(0, min(255, round(255 * alpha)))
        tex.blend_mode = pygame.BLENDMODE_BLEND
        tex.draw(srcrect=src, dstrect=shown)

    def blit_mix(self, old: pygame.Surface, new: pygame.Surface, k: float, pos) -> None:
        """Two overlays that share one alpha shape, colours mixed `k` of the way to `new`, alpha left as is.

        Stacking them with alpha would thicken the shape mid-fade. Instead: darken what's below by the shape once,
        then add each overlay's colour weighted by its share.
        """
        dst = pygame.Rect((int(pos[0]), int(pos[1])), new.get_size())
        shown = dst.clip(self.get_clip())
        if not shown.w or not shown.h:
            return
        src = pygame.Rect(shown.x - dst.x, shown.y - dst.y, shown.w, shown.h)
        k = max(0.0, min(1.0, k))
        cut = self.texture(new)
        cut.blend_mode, cut.alpha = self._cut, 255
        cut.draw(srcrect=src, dstrect=shown)
        for surface, share in ((old, 1 - k), (new, k)):
            tex = self.texture(surface)
            tex.blend_mode, tex.alpha = pygame.BLENDMODE_ADD, round(255 * share)
            tex.draw(srcrect=src, dstrect=shown)

    def fill(self, color, rect=None, special_flags: int = 0) -> pygame.Rect:
        area = (pygame.Rect(rect) if rect is not None else self.get_rect()).clip(self.get_clip())
        if not area.w or not area.h:
            return area
        if special_flags == pygame.BLEND_MULT:
            mode = pygame.BLENDMODE_MOD
        elif not special_flags:
            mode = pygame.BLENDMODE_NONE
        else:
            raise NotImplementedError(f"Canvas.fill special_flags={special_flags}")
        self.renderer.draw_blend_mode = mode
        self.renderer.draw_color = (*pygame.Color(color)[:3], 255)
        self.renderer.fill_rect(area)
        return area

    def shape(self, key: tuple, size: tuple[int, int], paint) -> pygame.Surface:
        """A small transparent surface painted once by `paint(surface)` and kept by `key`, for pygame.draw shapes."""
        surf = self._shapes.get(key)
        if surf is None:
            surf = pygame.Surface((max(1, size[0]), max(1, size[1])), pygame.SRCALPHA)
            paint(surf)
            self._shapes[key] = surf
            while len(self._shapes) > _SHAPE_CACHE_SIZE:
                self._shapes.popitem(last=False)
        else:
            self._shapes.move_to_end(key)
        return surf

    def present(self) -> None:
        self.renderer.present()
        self._clear()

    def _clear(self) -> None:
        self.renderer.draw_blend_mode = pygame.BLENDMODE_NONE
        self.renderer.draw_color = (0, 0, 0, 255)
        self.renderer.clear()


# pygame.draw only takes real surfaces; these send the same shapes to either target.

def rect(target, color, area, width: int = 0, border_radius: int = 0) -> None:
    if not isinstance(target, Canvas):
        pygame.draw.rect(target, color, area, width, border_radius=border_radius)
        return
    area = pygame.Rect(area)
    if not width and not border_radius:
        target.fill(color, area)
        return
    key = ("rect", area.size, tuple(pygame.Color(color)), width, border_radius)
    surf = target.shape(key, area.size, lambda s: pygame.draw.rect(s, color, s.get_rect(), width, border_radius=border_radius))
    target.blit(surf, area.topleft)


def lines(target, color, closed: bool, points, width: int = 1) -> None:
    if not isinstance(target, Canvas):
        pygame.draw.lines(target, color, closed, points, width)
        return
    pad = width
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    left, top = int(min(xs)) - pad, int(min(ys)) - pad
    size = (int(max(xs)) - left + pad + 1, int(max(ys)) - top + pad + 1)
    rel = tuple((p[0] - left, p[1] - top) for p in points)
    key = ("lines", rel, tuple(pygame.Color(color)), closed, width)
    surf = target.shape(key, size, lambda s: pygame.draw.lines(s, color, closed, rel, width))
    target.blit(surf, (left, top))


def line(target, color, start, end, width: int = 1) -> None:
    if not isinstance(target, Canvas):
        pygame.draw.line(target, color, start, end, width)
        return
    lines(target, color, False, [start, end], width)
