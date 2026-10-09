"""Draw Steam library art for a "non-Steam game" shortcut (or to upload to SteamGridDB) from the app icon's motif.

Writes packaging/steam/: capsule.png (600x900), wide.png (920x430), hero.png (1920x620, no logo: Steam lays the
logo over it), logo.png (transparent wordmark) and icon.png (the app icon).
Run: python packaging/generate_steam_art.py   (needs Pillow)
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from generate_icon import CHARCOAL, CREAM, DEMON, HELLFIRE, couch, render as render_icon

HERE = Path(__file__).resolve().parent
FONT = HERE.parent / "src" / "couch_doom" / "assets" / "fonts" / "Barlow-Bold.ttf"
SS = 2  # drawn at twice the size, then scaled down for clean edges


def glow(size: tuple[int, int], box: tuple[float, float, float, float], color, blur: float) -> Image.Image:
    g = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse(box, fill=color)
    return g.filter(ImageFilter.GaussianBlur(blur))


def scene(w: int, h: int, cx: float, base: float, couch_w: float) -> Image.Image:
    """Charcoal with the icon's hellfire pooled under a couch standing on `base`."""
    img = Image.new("RGBA", (w, h), CHARCOAL)
    for scale, color, blur in ((1.0, HELLFIRE[0], 0.14), (0.62, HELLFIRE[1], 0.08), (0.32, HELLFIRE[2], 0.045)):
        rx, ry = couch_w * 0.95 * scale, couch_w * 0.34 * scale
        img.alpha_composite(glow((w, h), (cx - rx, base - ry * 0.55, cx + rx, base + ry * 1.45), color, couch_w * blur))
    couch(ImageDraw.Draw(img), cx, base, couch_w)
    return img


def wordmark(height: int, stacked: bool = False) -> Image.Image:
    """COUCH DOOM in the app's header style: cream Barlow Bold over a short red bar."""
    font = ImageFont.truetype(str(FONT), height)
    lines = ["COUCH", "DOOM"] if stacked else ["COUCH DOOM"]
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    boxes = [probe.textbbox((0, 0), line, font=font) for line in lines]
    gap = int(height * 0.08)
    text_w = max(b[2] - b[0] for b in boxes)
    text_h = sum(b[3] - b[1] for b in boxes) + gap * (len(lines) - 1)
    bar_h, bar_gap = max(4, int(height * 0.09)), int(height * 0.16)
    img = Image.new("RGBA", (text_w, text_h + bar_gap + bar_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 0
    for line, b in zip(lines, boxes):
        d.text((-b[0], y - b[1]), line, font=font, fill=CREAM)
        y += b[3] - b[1] + gap
    d.rectangle((0, text_h + bar_gap, int(text_w * 0.42), text_h + bar_gap + bar_h), fill=DEMON)
    return img


def shadowed(mark: Image.Image, radius: float) -> Image.Image:
    pad = int(radius * 3)
    out = Image.new("RGBA", (mark.width + 2 * pad, mark.height + 2 * pad), (0, 0, 0, 0))
    shadow = Image.new("RGBA", mark.size, (0, 0, 0, 200))
    shadow.putalpha(mark.getchannel("A").point(lambda a: a * 200 // 255))
    out.alpha_composite(shadow, (pad, pad + int(radius * 0.6)))
    out = out.filter(ImageFilter.GaussianBlur(radius))
    out.alpha_composite(mark, (pad, pad))
    return out


def place(img: Image.Image, mark: Image.Image, x: float, y: float) -> None:
    img.alpha_composite(mark, (int(x), int(y)))


def finish(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    return img.resize(size, Image.LANCZOS)


def capsule() -> Image.Image:
    w, h = 600 * SS, 900 * SS
    img = scene(w, h, w / 2, h * 0.86, w * 0.78)
    mark = shadowed(wordmark(int(h * 0.15), stacked=True), h * 0.01)
    place(img, mark, (w - mark.width) / 2, h * 0.08)
    return finish(img, (600, 900))


def wide() -> Image.Image:
    w, h = 920 * SS, 430 * SS
    img = scene(w, h, w * 0.73, h * 0.80, w * 0.40)
    mark = shadowed(wordmark(int(h * 0.20), stacked=True), h * 0.012)
    place(img, mark, w * 0.06, (h - mark.height) / 2)
    return finish(img, (920, 430))


def hero() -> Image.Image:
    w, h = 1920 * SS, 620 * SS
    return finish(scene(w, h, w * 0.70, h * 0.84, w * 0.27), (1920, 620))


def logo() -> Image.Image:
    mark = wordmark(220 * SS)
    return mark.resize((mark.width // SS, mark.height // SS), Image.LANCZOS)


def main() -> None:
    out = HERE / "steam"
    out.mkdir(exist_ok=True)
    for name, image in (("capsule", capsule()), ("wide", wide()), ("hero", hero()), ("logo", logo()),
                        ("icon", render_icon().resize((256, 256), Image.LANCZOS))):
        path = out / f"{name}.png"
        image.save(path, optimize=True)
        print(path, image.size)


if __name__ == "__main__":
    main()
