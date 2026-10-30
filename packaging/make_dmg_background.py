"""Render the background for the compact macOS drag-to-Applications DMG."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "packaging" / "dmg-background.png"
FONT_DIR = ROOT / "src" / "couch_doom" / "assets" / "fonts"
SCALE = 1
ART_WIDTH, ART_HEIGHT = 640, 304
WIDTH, HEIGHT = 1200, 800

INK = (19, 19, 21)
CREAM = (246, 235, 216)
RED = (224, 51, 39)
MUTED = (176, 163, 150)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_DIR / name, size * SCALE)


def center_text(draw: ImageDraw.ImageDraw, text: str, center: tuple[int, int], face: ImageFont.FreeTypeFont, fill: tuple[int, int, int]) -> None:
    box = draw.textbbox((0, 0), text, font=face)
    draw.text((center[0] - (box[2] - box[0]) // 2, center[1] - (box[3] - box[1]) // 2 - box[1]), text, font=face, fill=fill)


def main() -> None:
    # Extend the dark field beyond the fixed artwork so larger Finder windows don't expose white.
    image = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()
    for y in range(HEIGHT):
        t = min(y / (ART_HEIGHT - 1), 1.0)
        ember = max(0.0, (t - 0.46) / 0.54) ** 1.7
        for x in range(WIDTH):
            side_fade = max(0.0, 1.0 - abs(x / (ART_WIDTH - 1) - 0.5) * 1.8)
            glow = ember * side_fade
            pixels[x, y] = tuple(round(INK[i] * (1 - glow * 0.55) + (93, 24, 18)[i] * glow * 0.55) for i in range(3))

    draw = ImageDraw.Draw(image, "RGBA")
    # Keep the brand and installer instructions on a simple, consistent grid.
    draw.line((28, 36, 28, 94), fill=RED + (255,), width=4)
    draw.text((48, 36), "COUCHDOOM", font=font("Barlow-Bold.ttf", 29), fill=CREAM + (255,))
    draw.text((50, 76), "MADE BY KRISENIGMA", font=font("JetBrainsMono-Regular.ttf", 9), fill=MUTED + (255,))

    # The arrow stays in the empty channel between the app and Applications icons.
    center_text(draw, "DRAG TO INSTALL", (320, 146), font("Barlow-Bold.ttf", 14), CREAM + (255,))
    ay = 183
    draw.line((229, ay, 411, ay), fill=(224, 51, 39, 230), width=3)
    draw.polygon(((411, ay), (397, ay - 7), (397, ay + 7)), fill=RED + (255,))

    # Finder draws icon names in dark text; these warm label beds keep them readable on the charcoal artwork.
    # Finder's label baseline sits above the icon center; align the plates to the name text.
    label_y = 248
    label_width, label_height = 112, 20
    for center_x in (160, 480):
        left = center_x - label_width // 2
        top = label_y - label_height // 2
        draw.rounded_rectangle((left, top, left + label_width, top + label_height), radius=10,
                               fill=(246, 235, 216, 235), outline=(197, 177, 150, 130), width=1)

    image.save(OUTPUT, optimize=True)
    print(OUTPUT)


if __name__ == "__main__":
    main()
