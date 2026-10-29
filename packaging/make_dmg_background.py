"""Render the 2x Finder background used by the macOS drag-to-Applications DMG."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "packaging" / "dmg-background.png"
ICON = ROOT / "packaging" / "couch-doom.png"
FONT_DIR = ROOT / "src" / "couch_doom" / "assets" / "fonts"
SCALE = 2
WIDTH, HEIGHT = 800 * SCALE, 450 * SCALE

INK = (19, 19, 21)
CREAM = (246, 235, 216)
TAN = (197, 177, 150)
RED = (224, 51, 39)
MUTED = (176, 163, 150)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_DIR / name, size * SCALE)


def center_text(draw: ImageDraw.ImageDraw, text: str, center: tuple[int, int], face: ImageFont.FreeTypeFont, fill: tuple[int, int, int]) -> None:
    box = draw.textbbox((0, 0), text, font=face)
    draw.text((center[0] - (box[2] - box[0]) // 2, center[1] - (box[3] - box[1]) // 2 - box[1]), text, font=face, fill=fill)


def main() -> None:
    # A restrained charcoal-to-hellfire wash, rendered at 2x for Retina Finder windows.
    image = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        ember = max(0.0, (t - 0.46) / 0.54) ** 1.7
        for x in range(WIDTH):
            side_fade = max(0.0, 1.0 - abs(x / (WIDTH - 1) - 0.5) * 1.8)
            glow = ember * side_fade
            pixels[x, y] = tuple(round(INK[i] * (1 - glow * 0.55) + (93, 24, 18)[i] * glow * 0.55) for i in range(3))

    draw = ImageDraw.Draw(image, "RGBA")
    # Fine CRT-like line work and corner registration marks keep the field textured but quiet.
    for y in range(HEIGHT):
        if y % (4 * SCALE) == 0:
            draw.line((0, y, WIDTH, y), fill=(255, 230, 210, 5), width=1)
    draw.rounded_rectangle((28, 28, WIDTH - 28, HEIGHT - 28), radius=28, outline=(246, 235, 216, 25), width=2)
    draw.line((58, 72, 58, 145), fill=RED + (255,), width=5)

    mark = Image.open(ICON).convert("RGBA")
    mark.thumbnail((82 * SCALE, 82 * SCALE), Image.Resampling.LANCZOS)
    image.alpha_composite(mark, (82 * SCALE, 62 * SCALE)) if image.mode == "RGBA" else image.paste(mark, (82 * SCALE, 62 * SCALE), mark)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text((178 * SCALE, 70 * SCALE), "COUCHDOOM", font=font("Barlow-Bold.ttf", 34), fill=CREAM + (255,))
    draw.text((181 * SCALE, 118 * SCALE), "MADE BY KRISENIGMA", font=font("JetBrainsMono-Regular.ttf", 10), fill=MUTED + (255,))

    tag = "macOS  /  INSTALLER"
    tag_font = font("JetBrainsMono-Regular.ttf", 9)
    tag_box = draw.textbbox((0, 0), tag, font=tag_font)
    tag_width = tag_box[2] - tag_box[0]
    tag_height = tag_box[3] - tag_box[1]
    pad_x, pad_y = 14 * SCALE, 9 * SCALE
    pill_right = WIDTH - 64 * SCALE
    pill_left = pill_right - tag_width - 2 * pad_x
    pill_top, pill_bottom = 78 * SCALE, 110 * SCALE
    draw.rounded_rectangle((pill_left, pill_top, pill_right, pill_bottom), radius=16 * SCALE, fill=(224, 51, 39, 27), outline=(224, 51, 39, 120), width=2)
    draw.text((pill_left + pad_x, pill_top + (pill_bottom - pill_top - tag_height) // 2 - tag_box[1]), tag, font=tag_font, fill=(255, 174, 148, 255))

    # The arrow stays in the empty channel between the app and Applications icons.
    center_text(draw, "DRAG TO INSTALL", (400 * SCALE, 206 * SCALE), font("Barlow-Bold.ttf", 17), CREAM + (255,))
    ay = 251 * SCALE
    draw.line((286 * SCALE, ay, 514 * SCALE, ay), fill=(224, 51, 39, 230), width=4 * SCALE)
    draw.polygon(((514 * SCALE, ay), (496 * SCALE, ay - 9 * SCALE), (496 * SCALE, ay + 9 * SCALE)), fill=RED + (255,))
    # Small terminal-like ticks link the arrow to the two Finder icon positions.
    for x in (245, 555):
        draw.line((x * SCALE, 238 * SCALE, x * SCALE, 264 * SCALE), fill=(246, 235, 216, 70), width=2)

    draw.text((64 * SCALE, 401 * SCALE), "macOS 10.15+  /  HELP + LICENSE INCLUDED", font=font("JetBrainsMono-Regular.ttf", 8), fill=MUTED + (235,))
    image.save(OUTPUT, optimize=True)
    print(OUTPUT)


if __name__ == "__main__":
    main()
