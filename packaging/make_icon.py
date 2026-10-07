"""Regenerate couch-doom.ico (needs Pillow): python packaging/make_icon.py"""
import io
import os
from pathlib import Path

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame
from PIL import Image

RED, DEEP, GOLD, INK = (222, 56, 30), (90, 24, 15), (236, 170, 64), (246, 236, 222)
FONT = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "bahnschrift.ttf"


def render(size: int) -> pygame.Surface:
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    radius = size // 5
    for y in range(size):
        t = y / max(1, size - 1)
        row = [round(RED[i] + (DEEP[i] - RED[i]) * t) for i in range(3)]
        pygame.draw.line(surf, row, (0, y), (size, y))
    mask = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    font = pygame.font.Font(str(FONT), int(size * 0.62))
    font.bold = True
    text = font.render("CD", True, INK)
    ink = text.get_bounding_rect()
    surf.blit(text, (size // 2 - ink.centerx, int(size * 0.44) - ink.centery))
    bar_w, bar_h = int(size * 0.46), max(1, size // 14)
    pygame.draw.rect(surf, GOLD, (size // 2 - bar_w // 2, int(size * 0.76), bar_w, bar_h))
    return surf


def main() -> None:
    pygame.font.init()
    big = render(256)
    buf = io.BytesIO()
    pygame.image.save(big, buf, "icon.png")
    buf.seek(0)
    out = Path(__file__).with_name("couch-doom.ico")
    Image.open(buf).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    pygame.image.save(big, str(out.with_suffix(".png")))
    print(out)


if __name__ == "__main__":
    main()
