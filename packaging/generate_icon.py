"""Draw the CouchDoom app icon and write packaging/couch-doom.png + couch-doom.ico.

Default palette B: cream sofa, red demon horns, hellfire glow on charcoal (matches the in-app title text).
Run: python packaging/generate_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024
CREAM = (243, 235, 221, 255)
SEAM = (196, 176, 152, 255)
CHARCOAL = (24, 20, 19, 255)
DEMON = (205, 46, 32, 255)
HELLFIRE = ((150, 24, 12, 255), (255, 96, 22, 255), (255, 196, 90, 230))
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def bezier(p0, p1, p2, n=40):
    return [
        (
            (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
            (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1],
        )
        for t in (i / n for i in range(n + 1))
    ]


def horn(d, root_x, root_y, side, w, color):
    base = w * 0.09
    tip = (root_x + side * w * 0.20, root_y - w * 0.33)
    outer = bezier((root_x + side * base, root_y), (root_x + side * w * 0.26, root_y - w * 0.06), tip)
    inner = bezier(tip, (root_x + side * w * 0.07, root_y - w * 0.10), (root_x - side * base, root_y))
    d.polygon(outer + inner, fill=color)


def couch(d, cx, base, w, body=CREAM, seam=SEAM, horns=DEMON):
    h = w * 0.52
    left, right = cx - w / 2, cx + w / 2
    arm, r = w * 0.17, w * 0.055
    back_top = base - h
    horn(d, cx - w * 0.24, back_top + r, -1, w, horns)
    horn(d, cx + w * 0.24, back_top + r, 1, w, horns)
    d.rounded_rectangle((left + arm * 0.5, back_top, right - arm * 0.5, base - h * 0.28), r, fill=body)
    d.rounded_rectangle((left, base - h * 0.64, left + arm, base - h * 0.06), r, fill=body)
    d.rounded_rectangle((right - arm, base - h * 0.64, right, base - h * 0.06), r, fill=body)
    d.rounded_rectangle((left + arm * 0.55, base - h * 0.40, right - arm * 0.55, base - h * 0.06), r * 0.8, fill=body)
    seam_w = max(2, int(w * 0.018))
    d.line((cx, back_top + h * 0.12, cx, base - h * 0.42), fill=seam, width=seam_w)
    d.line((left + arm * 1.05, base - h * 0.40, right - arm * 1.05, base - h * 0.40), fill=seam, width=seam_w)
    leg = w * 0.06
    for lx in (left + arm * 0.3, right - arm * 0.3 - leg):
        d.rectangle((lx, base - h * 0.08, lx + leg, base), fill=seam)


def glow_layer(box, color, blur):
    g = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse(box, fill=color)
    return g.filter(ImageFilter.GaussianBlur(blur))


def render() -> Image.Image:
    img = Image.new("RGBA", (S, S), CHARCOAL)
    img.alpha_composite(glow_layer((S * 0.00, S * 0.50, S * 1.00, S * 1.10), HELLFIRE[0], S * 0.10))
    img.alpha_composite(glow_layer((S * 0.14, S * 0.62, S * 0.86, S * 0.94), HELLFIRE[1], S * 0.06))
    img.alpha_composite(glow_layer((S * 0.30, S * 0.72, S * 0.70, S * 0.86), HELLFIRE[2], S * 0.035))
    couch(ImageDraw.Draw(img), S / 2, S * 0.76, S * 0.72)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), int(S * 0.22), fill=255)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def main() -> None:
    here = Path(__file__).resolve().parent
    icon = render()
    png = here / "couch-doom.png"
    ico = here / "couch-doom.ico"
    icon.save(png)
    icon.save(ico, sizes=[(s, s) for s in ICO_SIZES])
    print(png)
    print(ico)


if __name__ == "__main__":
    main()
