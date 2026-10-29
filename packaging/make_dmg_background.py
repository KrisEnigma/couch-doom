"""Render the 2x Finder background used by the macOS drag-to-Applications DMG."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "packaging" / "dmg-background.png"
FONT_DIR = ROOT / "src" / "couch_doom" / "assets" / "fonts"
SCALE = 1  # Finder treats the background's pixel dimensions as its logical size.
WIDTH, HEIGHT = 640, 360

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
    # A restrained charcoal-to-hellfire wash sized to the Finder window.
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
    draw.rounded_rectangle((22, 22, WIDTH - 22, HEIGHT - 22), radius=22, outline=(246, 235, 216, 25), width=2)
    draw.line((46, 58, 46, 116), fill=RED + (255,), width=4)

    draw = ImageDraw.Draw(image, "RGBA")
    draw.text((76, 54), "COUCHDOOM", font=font("Barlow-Bold.ttf", 29), fill=CREAM + (255,))
    draw.text((79, 94), "MADE BY KRISENIGMA", font=font("JetBrainsMono-Regular.ttf", 9), fill=MUTED + (255,))

    tag = "macOS  /  INSTALLER"
    tag_font = font("JetBrainsMono-Regular.ttf", 9)
    tag_box = draw.textbbox((0, 0), tag, font=tag_font)
    tag_width = tag_box[2] - tag_box[0]
    tag_height = tag_box[3] - tag_box[1]
    pad_x = 11
    pill_right = WIDTH - 48
    pill_left = pill_right - tag_width - 2 * pad_x
    pill_top, pill_bottom = 50, 78
    draw.rounded_rectangle((pill_left, pill_top, pill_right, pill_bottom), radius=14, fill=(224, 51, 39, 27), outline=(224, 51, 39, 120), width=2)
    draw.text((pill_left + pad_x, pill_top + (pill_bottom - pill_top - tag_height) // 2 - tag_box[1]), tag, font=tag_font, fill=(255, 174, 148, 255))

    # The arrow stays in the empty channel between the app and Applications icons.
    center_text(draw, "DRAG TO INSTALL", (320, 164), font("Barlow-Bold.ttf", 14), CREAM + (255,))
    ay = 201
    draw.line((229, ay, 411, ay), fill=(224, 51, 39, 230), width=3)
    draw.polygon(((411, ay), (397, ay - 7), (397, ay + 7)), fill=RED + (255,))
    # Small terminal-like ticks link the arrow to the two Finder icon positions.
    for x in (196, 444):
        draw.line((x, 190, x, 211), fill=(246, 235, 216, 70), width=2)

    # Finder draws icon names in dark text; these warm label beds keep them readable on the charcoal artwork.
    label_y = 274
    label_width, label_height = 112, 20
    for center_x in (156, 484):
        left = center_x - label_width // 2
        top = label_y - label_height // 2
        draw.rounded_rectangle((left, top, left + label_width, top + label_height), radius=10,
                               fill=(246, 235, 216, 235), outline=(197, 177, 150, 130), width=1)

    draw.text((51, 321), "macOS 10.15+  /  HELP + LICENSE INCLUDED", font=font("JetBrainsMono-Regular.ttf", 7), fill=MUTED + (235,))
    image.save(OUTPUT, optimize=True)
    print(OUTPUT)


if __name__ == "__main__":
    main()
