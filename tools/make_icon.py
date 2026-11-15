"""Render the app icon (assets/app.ico + app_logo.png) with the app's own logo engine."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw  # noqa: E402

from sv.graphics import _fill, _gradient, render_logo  # noqa: E402


def main():
    out = os.path.join(ROOT, "assets")
    os.makedirs(out, exist_ok=True)
    S = 1024
    # rounded-square tile with the brand gradient, then the orbit mark on top
    tile = _gradient((S, S), (79, 70, 229), (219, 39, 119), 135)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.23), fill=255)
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    icon.paste(tile, (0, 0), mask)
    shine = Image.new("L", (S, S), 0)
    ImageDraw.Draw(shine).ellipse([-S * 0.3, -S * 0.9, S * 1.3, S * 0.45], fill=46)
    from PIL import ImageChops
    icon.alpha_composite(_fill(ImageChops.multiply(shine, mask), (255, 255, 255)))
    mark = render_logo({"brand": "SV", "mono": "SV", "style": "Orbit Rings", "layout": "Icon only",
                        "background": "Brand color", "p": "#6366F1", "s": "#EC4899", "a": "#67E8F9",
                        "seed": 4, "glow": False, "_layer": "fg", "font": _bold_font()}, size=S)
    mark = mark.resize((int(S * 0.94), int(S * 0.94)), Image.Resampling.LANCZOS)
    icon.alpha_composite(mark, ((S - mark.width) // 2, (S - mark.height) // 2))
    # repaint the monogram white so it stays readable at 16-32 px
    from sv.graphics import _monogram
    _monogram(icon, "SV", _bold_font(), S / 2, S / 2, S * 0.38 * 0.94 * 0.78, (255, 255, 255))
    icon.save(os.path.join(out, "app_logo.png"))
    icon.save(os.path.join(out, "app.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
                                                   (256, 256)])
    print("icon written to", out)


def _bold_font():
    for p in (r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"):
        if os.path.exists(p):
            return p
    return None


if __name__ == "__main__":
    main()
