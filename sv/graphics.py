"""Colour helpers, font discovery and the procedural logo renderer (pure Pillow, no Qt)."""

import colorsys
import math
import os
import random
import re

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .core import IS_MAC, IS_WIN, get_resource_path

def hex_to_rgb(value):
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*[max(0, min(255, int(c))) for c in rgb[:3]])


def mix(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1[:3], c2[:3]))


def darken(c, amount):
    return mix(c, (0, 0, 0), amount)


def lighten(c, amount):
    return mix(c, (255, 255, 255), amount)


def luminance(rgb):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)



# ---------------------------------------------------------------------------
# Font discovery
# ---------------------------------------------------------------------------


def discover_fonts():
    dirs = [get_resource_path("fonts")]
    if IS_WIN:
        dirs += [os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")]
    elif IS_MAC:
        dirs += ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts",
                 os.path.expanduser("~/Library/Fonts")]
    else:
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
                 os.path.expanduser("~/.local/share/fonts")]
    skip = ("emoji", "symbol", "wingding", "webding", "lastresort", "braille", "marlett", "mtextra",
            "holomdl", "segmdl", "zapfding", "keyboard")
    fonts = {}
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for fn in files:
                if fn.lower().endswith((".ttf", ".otf", ".ttc")) and not any(s in fn.lower() for s in skip):
                    stem = os.path.splitext(fn)[0]
                    fonts.setdefault(stem.replace("_", " "), os.path.join(root, fn))
    return dict(sorted(fonts.items(), key=lambda kv: kv[0].lower()))


PREFERRED_FONTS = ["Montserrat-Bold", "Poppins-Bold", "Inter-Bold", "Avenir Next", "Futura",
                   "Arial Bold", "arialbd", "Helvetica", "segoeuib", "DejaVuSans-Bold", "Arial"]
BOLD_HINTS = ("bold", "black", "heavy", "semibold", "bd", "extrab", "impact", "futura", "avenir")


def _load_font(path, size):
    size = max(6, int(size))
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    for fallback in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf", "Arial.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(fallback, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1 scalable default font
    except TypeError:
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Logo renderer
# ---------------------------------------------------------------------------

LOGO_STYLES = ["Orbit Rings", "Hexagon Badge", "Shield Crest", "Circle Monogram", "App Icon",
               "Sun Burst", "Diamond Stack", "Venn Blend", "Mountain Peak", "Identicon Grid",
               "Letter Mark", "Lotus Petals", "Neon Ring", "Isometric Cube"]
LOGO_LAYOUTS = ["Icon above text", "Icon beside text", "Icon only", "Text only"]
LOGO_BACKGROUNDS = ["Dark", "Gradient", "Light", "Brand color", "Transparent"]
PALETTES = {
    "Neon": ((99, 102, 241), (236, 72, 153), (34, 211, 238)),
    "Sunset": ((249, 115, 22), (236, 72, 153), (250, 204, 21)),
    "Ocean": ((14, 165, 233), (37, 99, 235), (45, 212, 191)),
    "Forest": ((22, 163, 74), (132, 204, 22), (250, 204, 21)),
    "Royal": ((124, 58, 237), (30, 64, 175), (250, 204, 21)),
    "Fire": ((239, 68, 68), (249, 115, 22), (253, 224, 71)),
    "Mint": ((16, 185, 129), (45, 212, 191), (167, 243, 208)),
    "Gold Luxe": ((202, 138, 4), (250, 204, 21), (120, 53, 15)),
    "Candy": ((244, 114, 182), (167, 139, 250), (125, 211, 252)),
    "Cyberpunk": ((250, 204, 21), (236, 72, 153), (6, 182, 212)),
    "Earth": ((180, 83, 9), (217, 119, 6), (101, 163, 13)),
    "Mono": ((226, 232, 240), (148, 163, 184), (71, 85, 105)),
}


def random_palette(rng):
    h = rng.random()
    scheme = rng.choice(["analogous", "complementary", "triadic", "split"])
    offsets = {"analogous": (0.08, 0.16), "complementary": (0.5, 0.08),
               "triadic": (1 / 3, 2 / 3), "split": (0.42, 0.58)}[scheme]
    s, v = rng.uniform(0.6, 0.9), rng.uniform(0.85, 1.0)

    def c(hh, ss=s, vv=v):
        r, g, b = colorsys.hsv_to_rgb(hh % 1.0, ss, vv)
        return int(r * 255), int(g * 255), int(b * 255)
    return c(h), c(h + offsets[0]), c(h + offsets[1], s * 0.8, 1.0)


def _gradient(size, c1, c2, angle=90):
    w, h = size
    d = int(math.hypot(w, h)) + 4
    g = Image.linear_gradient("L").resize((d, d)).rotate(angle - 90, resample=Image.Resampling.BICUBIC)
    g = g.crop(((d - w) // 2, (d - h) // 2, (d - w) // 2 + w, (d - h) // 2 + h))
    return Image.composite(Image.new("RGBA", size, tuple(c2[:3]) + (255,)),
                           Image.new("RGBA", size, tuple(c1[:3]) + (255,)), g)


def _fill(mask, c1, c2=None, angle=90, alpha=255):
    layer = _gradient(mask.size, c1, c2, angle) if c2 else Image.new("RGBA", mask.size, tuple(c1[:3]) + (255,))
    if alpha < 255:
        mask = mask.point(lambda v: v * alpha // 255)
    layer.putalpha(mask)
    return layer


def _poly(cx, cy, r, n, rot=0.0):
    return [(cx + r * math.cos(math.radians(rot + i * 360 / n - 90)),
             cy + r * math.sin(math.radians(rot + i * 360 / n - 90))) for i in range(n)]


def _text_metrics(font, text, tracking):
    width = sum(font.getlength(ch) for ch in text) + tracking * max(0, len(text) - 1)
    bbox = font.getbbox(text or " ")
    return width, bbox[3] - bbox[1], bbox[1]


def _fit_font(font_path, text, max_w, max_h, tracking_ratio):
    size = max_h
    while True:
        font = _load_font(font_path, size)
        tracking = size * tracking_ratio
        w, h, top = _text_metrics(font, text, tracking)
        if (w <= max_w and h <= max_h * 1.05) or size <= 8:
            return font, tracking, w, h, top
        size = int(size * 0.92)


def _text_mask(canvas_size, text, font, x, y_top, tracking, top_offset):
    mask = Image.new("L", canvas_size, 0)
    d = ImageDraw.Draw(mask)
    cursor = x
    for ch in text:
        d.text((cursor, y_top - top_offset), ch, font=font, fill=255)
        cursor += font.getlength(ch) + tracking
    return mask


def _monogram(canvas, text, font_path, cx, cy, box, c1, c2=None, angle=90):
    if not text:
        return
    font, tracking, w, h, top = _fit_font(font_path, text, box, box * 0.8, 0.02)
    mask = _text_mask(canvas.size, text, font, cx - w / 2, cy - h / 2, tracking, top)
    canvas.alpha_composite(_fill(mask, c1, c2, angle))


def _draw_icon(style, size, cx, cy, r, pal, rng, mono, font_path):
    W, H = size
    p, s, a, fg = pal["p"], pal["s"], pal["a"], pal["icon_fg"]
    icon = Image.new("RGBA", size, (0, 0, 0, 0))
    ang = rng.randint(0, 359)

    def new_mask():
        return Image.new("L", size, 0)

    if style == "Orbit Rings":
        rings = rng.randint(3, 5)
        width = max(2, int(r * 0.07))
        for i in range(rings):
            rad = r * (1 - i * 0.17)
            m = new_mask()
            start = rng.randint(0, 359)
            extent = rng.randint(210, 330)
            ImageDraw.Draw(m).arc([cx - rad, cy - rad, cx + rad, cy + rad], start, start + extent, fill=255,
                                  width=width)
            icon.alpha_composite(_fill(m, mix(p, s, i / max(1, rings - 1)), mix(s, a, i / rings), ang))
            end = math.radians(start + extent)
            dot = width * 0.9
            ex, ey = cx + rad * math.cos(end), cy + rad * math.sin(end)
            dm = new_mask()
            ImageDraw.Draw(dm).ellipse([ex - dot, ey - dot, ex + dot, ey + dot], fill=255)
            icon.alpha_composite(_fill(dm, a))
        if mono and rng.random() < 0.5:
            _monogram(icon, mono, font_path, cx, cy, r * 0.75, fg)
        else:
            m = new_mask()
            d = ImageDraw.Draw(m)
            k = r * 0.28
            d.polygon([(cx, cy - k * 1.3), (cx + k, cy + k * 0.2), (cx - k, cy + k * 0.2)], fill=255)
            icon.alpha_composite(_fill(m, s, a, ang))
            m2 = new_mask()
            ImageDraw.Draw(m2).polygon([(cx, cy + k * 1.2), (cx + k, cy - k * 0.1), (cx - k, cy - k * 0.1)], fill=220)
            icon.alpha_composite(_fill(m2, p, s, ang + 90))

    elif style == "Hexagon Badge":
        rot = rng.choice([0, 30])
        m = new_mask()
        ImageDraw.Draw(m).polygon(_poly(cx, cy, r, 6, rot), fill=255)
        icon.alpha_composite(_fill(m, p, s, ang))
        m2 = new_mask()
        ImageDraw.Draw(m2).polygon(_poly(cx, cy, r * 0.8, 6, rot), outline=255, width=max(2, int(r * 0.035)))
        icon.alpha_composite(_fill(m2, fg, alpha=110))
        _monogram(icon, mono, font_path, cx, cy, r * 0.95, fg)

    elif style == "Shield Crest":
        top, side = cy - r * 0.92, r * 0.82
        pts = [(cx - side, top), (cx, top - r * 0.12 * rng.choice([0, 1])), (cx + side, top), (cx + side, cy)]
        for i in range(1, 21):  # quadratic curve to the tip
            t = i / 20
            x0, y0, x1, y1, x2, y2 = cx + side, cy, cx + side * 0.9, cy + r * 0.62, cx, cy + r
            pts.append(((1 - t) ** 2 * x0 + 2 * (1 - t) * t * x1 + t * t * x2,
                        (1 - t) ** 2 * y0 + 2 * (1 - t) * t * y1 + t * t * y2))
        mirror = [(2 * cx - x, y) for x, y in reversed(pts[3:-1])]
        shape = pts + mirror
        m = new_mask()
        ImageDraw.Draw(m).polygon(shape, fill=255)
        icon.alpha_composite(_fill(m, p, darken(s, 0.15), 90 + rng.randint(-25, 25)))
        band = new_mask()
        bw = r * 0.22
        ImageDraw.Draw(band).polygon([(cx - r * 1.2, cy + bw), (cx + r * 1.2, cy - r * 0.55),
                                      (cx + r * 1.2, cy - r * 0.55 + bw), (cx - r * 1.2, cy + bw * 2)], fill=255)
        icon.alpha_composite(_fill(ImageChops.multiply(band, m), a, alpha=150))
        _monogram(icon, mono, font_path, cx, cy - r * 0.05, r * 0.85, fg)

    elif style == "Circle Monogram":
        m = new_mask()
        ImageDraw.Draw(m).ellipse([cx - r * 0.86, cy - r * 0.86, cx + r * 0.86, cy + r * 0.86], fill=255)
        icon.alpha_composite(_fill(m, p, s, ang))
        ring = new_mask()
        d = ImageDraw.Draw(ring)
        if rng.random() < 0.5:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=255, width=max(2, int(r * 0.04)))
        else:
            dots = rng.choice([24, 36, 48])
            for i in range(dots):
                t = math.radians(i * 360 / dots)
                x, y, dr = cx + r * math.cos(t), cy + r * math.sin(t), r * 0.03
                d.ellipse([x - dr, y - dr, x + dr, y + dr], fill=255)
        icon.alpha_composite(_fill(ring, a, s, ang))
        _monogram(icon, mono, font_path, cx, cy, r * 1.0, fg)

    elif style == "App Icon":
        m = new_mask()
        ImageDraw.Draw(m).rounded_rectangle([cx - r, cy - r, cx + r, cy + r], radius=r * rng.uniform(0.35, 0.5),
                                            fill=255)
        icon.alpha_composite(_fill(m, p, s, ang))
        gloss = new_mask()
        ImageDraw.Draw(gloss).ellipse([cx - r * 1.6, cy - r * 2.1, cx + r * 1.6, cy - r * 0.15], fill=255)
        icon.alpha_composite(_fill(ImageChops.multiply(gloss, m), (255, 255, 255), alpha=38))
        _monogram(icon, mono, font_path, cx, cy, r * 1.15, fg)

    elif style == "Sun Burst":
        rays = rng.choice([8, 12, 16, 24])
        for i in range(rays):
            t = math.radians(i * 360 / rays + ang)
            half = math.pi / rays * 0.8
            length = r if i % 2 == 0 else r * 0.78
            m = new_mask()
            ImageDraw.Draw(m).polygon([(cx, cy),
                                       (cx + length * math.cos(t - half), cy + length * math.sin(t - half)),
                                       (cx + length * math.cos(t + half), cy + length * math.sin(t + half))],
                                      fill=255)
            icon.alpha_composite(_fill(m, p if i % 2 == 0 else s, a, ang))
        m = new_mask()
        ImageDraw.Draw(m).ellipse([cx - r * 0.5, cy - r * 0.5, cx + r * 0.5, cy + r * 0.5], fill=255)
        icon.alpha_composite(_fill(m, pal["bg_solid"]))
        _monogram(icon, mono, font_path, cx, cy, r * 0.6, p, s)

    elif style == "Diamond Stack":
        layers = rng.choice([2, 3, 4])
        colors = [p, s, a, lighten(p, 0.3)]
        for i in range(layers):
            off = (i - (layers - 1) / 2) * r * 0.36
            k = r * (0.62 - i * 0.04)
            m = new_mask()
            ImageDraw.Draw(m).polygon([(cx, cy + off - k), (cx + k, cy + off), (cx, cy + off + k), (cx - k, cy + off)],
                                      fill=255)
            icon.alpha_composite(_fill(m, colors[i], alpha=205))

    elif style == "Venn Blend":
        n = rng.choice([2, 3])
        rr = r * (0.6 if n == 3 else 0.62)
        for i, col in enumerate([p, s, a][:n]):
            t = math.radians(ang + i * 360 / n)
            x, y = cx + r * 0.38 * math.cos(t), cy + r * 0.38 * math.sin(t)
            m = new_mask()
            ImageDraw.Draw(m).ellipse([x - rr, y - rr, x + rr, y + rr], fill=255)
            icon.alpha_composite(_fill(m, col, alpha=175))

    elif style == "Mountain Peak":
        circle = new_mask()
        ImageDraw.Draw(circle).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
        icon.alpha_composite(_fill(circle, lighten(s, 0.55), lighten(p, 0.25), 90))
        sun = new_mask()
        sx, sy, sr_ = cx + r * rng.uniform(-0.4, 0.4), cy - r * rng.uniform(0.2, 0.45), r * 0.2
        ImageDraw.Draw(sun).ellipse([sx - sr_, sy - sr_, sx + sr_, sy + sr_], fill=255)
        icon.alpha_composite(_fill(ImageChops.multiply(sun, circle), a))
        for depth, col in ((0, darken(s, 0.1)), (1, darken(p, 0.25))):
            m = new_mask()
            peaks = [(cx - r * 1.1, cy + r)]
            n = rng.randint(2, 3)
            for j in range(n):
                px = cx - r + (j + 0.5) * 2 * r / n + rng.uniform(-0.15, 0.15) * r
                peaks.append((px, cy - r * rng.uniform(0.0, 0.45) + depth * r * 0.25))
                peaks.append((px + r / n, cy + r * 0.25 + depth * r * 0.15))
            peaks.append((cx + r * 1.1, cy + r))
            ImageDraw.Draw(m).polygon(peaks, fill=255)
            icon.alpha_composite(_fill(ImageChops.multiply(m, circle), col))

    elif style == "Identicon Grid":
        g = rng.choice([5, 7])
        cell = 2 * r / g
        m = new_mask()
        d = ImageDraw.Draw(m)
        bits = [[rng.random() < 0.55 for _ in range((g + 1) // 2)] for _ in range(g)]
        bits[g // 2][g // 2] = True
        for row in range(g):
            for col in range(g):
                if bits[row][min(col, g - 1 - col)]:
                    x0, y0 = cx - r + col * cell, cy - r + row * cell
                    d.rounded_rectangle([x0 + cell * 0.08, y0 + cell * 0.08, x0 + cell * 0.92, y0 + cell * 0.92],
                                        radius=cell * 0.25, fill=255)
        icon.alpha_composite(_fill(m, p, s, ang))

    elif style == "Letter Mark":
        _monogram(icon, mono or "A", font_path, cx, cy - r * 0.08, r * 1.7, p, s, ang)
        m = new_mask()
        ImageDraw.Draw(m).rounded_rectangle([cx - r * 0.6, cy + r * 0.72, cx + r * 0.6, cy + r * 0.84],
                                            radius=r * 0.06, fill=255)
        icon.alpha_composite(_fill(m, a, s, 0))

    elif style == "Lotus Petals":
        n = rng.choice([5, 6, 8, 10, 12])
        pw = r * rng.uniform(0.28, 0.42)
        for i in range(n):
            m = new_mask()
            ImageDraw.Draw(m).ellipse([cx - pw / 2, cy - r, cx + pw / 2, cy], fill=255)
            m = m.rotate(-(i * 360 / n + ang % 30), center=(cx, cy), resample=Image.Resampling.BICUBIC)
            icon.alpha_composite(_fill(m, p if i % 2 == 0 else s, a, ang, alpha=200))
        m = new_mask()
        ImageDraw.Draw(m).ellipse([cx - r * 0.18, cy - r * 0.18, cx + r * 0.18, cy + r * 0.18], fill=255)
        icon.alpha_composite(_fill(m, a))

    elif style == "Neon Ring":
        m = new_mask()
        w = max(3, int(r * rng.uniform(0.1, 0.16)))
        ImageDraw.Draw(m).ellipse([cx - r * 0.85, cy - r * 0.85, cx + r * 0.85, cy + r * 0.85], outline=255, width=w)
        ring = _fill(m, p, s, ang)
        icon.alpha_composite(ring.filter(ImageFilter.GaussianBlur(r * 0.12)))
        icon.alpha_composite(ring)
        for _ in range(rng.randint(3, 6)):
            t = math.radians(rng.randint(0, 359))
            x, y, dr = cx + r * 0.85 * math.cos(t), cy + r * 0.85 * math.sin(t), r * rng.uniform(0.03, 0.06)
            dm = new_mask()
            ImageDraw.Draw(dm).ellipse([x - dr, y - dr, x + dr, y + dr], fill=255)
            icon.alpha_composite(_fill(dm, lighten(a, 0.4)))
        _monogram(icon, mono, font_path, cx, cy, r * 0.9, lighten(p, 0.5), lighten(s, 0.3), ang)

    elif style == "Isometric Cube":
        k = r * 0.9
        hx = k * math.cos(math.radians(30))
        top = [(cx, cy - k), (cx + hx, cy - k / 2), (cx, cy), (cx - hx, cy - k / 2)]
        left = [(cx - hx, cy - k / 2), (cx, cy), (cx, cy + k), (cx - hx, cy + k / 2)]
        right = [(cx + hx, cy - k / 2), (cx, cy), (cx, cy + k), (cx + hx, cy + k / 2)]
        for pts, c1, c2 in ((top, lighten(p, 0.25), p), (left, s, darken(s, 0.25)), (right, darken(p, 0.3), darken(s, 0.4))):
            m = new_mask()
            ImageDraw.Draw(m).polygon(pts, fill=255)
            icon.alpha_composite(_fill(m, c1, c2, ang))
        if rng.random() < 0.5:
            inner = new_mask()
            ImageDraw.Draw(inner).polygon(_poly(cx, cy, k * 0.38, 6, 30), outline=255, width=max(2, int(r * 0.04)))
            icon.alpha_composite(_fill(inner, a))
    return icon


def make_initials(text):
    words = [w for w in re.split(r"[\s\-_]+", text.strip()) if w]
    if not words:
        return "S"
    if len(words) == 1:
        return words[0][:2].upper() if len(words[0]) > 3 else words[0][:1].upper()
    return (words[0][0] + words[1][0]).upper()


def render_logo(spec, size=512, supersample=None):
    """spec: dict(brand, tagline, mono, style, layout, background, p, s, a, font, sub_font, seed,
    text_gradient, glow, uppercase, tracking)"""
    ss = supersample or (2 if size <= 1024 else 1)
    S = size * ss
    rng = random.Random(spec.get("seed", 0))
    layout = spec.get("layout", LOGO_LAYOUTS[0])
    wide = layout in ("Icon beside text", "Text only")
    W, H = (S * 2, S) if wide else (S, S)

    p, s, a = (hex_to_rgb(spec[k]) for k in ("p", "s", "a"))
    bg_kind = spec.get("background", "Dark")
    bg_solid = {"Dark": (11, 15, 26), "Light": (248, 250, 252), "Brand color": p,
                "Gradient": darken(mix(p, s, 0.5), 0.6), "Transparent": (255, 255, 255)}[bg_kind]
    light_bg = bg_kind in ("Light", "Transparent") or (bg_kind == "Brand color" and luminance(p) > 0.4)
    text_fg = (15, 23, 42) if light_bg else (248, 250, 252)
    if bg_kind == "Brand color":
        icon_p, icon_s = (text_fg, mix(text_fg, s, 0.45))
    else:
        icon_p, icon_s = p, s
    pal = {"p": icon_p, "s": icon_s, "a": a, "bg_solid": bg_solid,
           "icon_fg": (255, 255, 255) if bg_kind != "Brand color" else p}

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if bg_kind == "Gradient":
        canvas = _gradient((W, H), darken(p, 0.55), darken(s, 0.6), rng.randint(20, 160))
    elif bg_kind != "Transparent":
        canvas = Image.new("RGBA", (W, H), bg_solid + (255,))
    layer = spec.get("_layer")  # "bg" / "fg": split render used by the animated intro
    if layer == "bg":
        return canvas.resize((W // ss, H // ss), Image.Resampling.LANCZOS) if ss > 1 else canvas
    if layer == "fg":
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    brand = spec.get("brand", "").strip() or "BRAND"
    tagline = spec.get("tagline", "").strip()
    if spec.get("uppercase", True):
        brand, tagline = brand.upper(), tagline.upper()
    mono = (spec.get("mono") or "").strip()[:3] or make_initials(brand)
    font_path, sub_font = spec.get("font"), spec.get("sub_font") or spec.get("font")
    tracking = spec.get("tracking", 6) / 100.0
    style = spec.get("style", LOGO_STYLES[0])

    if layout == "Icon above text":
        icon_box, text_box = (W / 2, H * 0.38, S * 0.24), (W * 0.08, H * 0.68, W * 0.84, "center")
    elif layout == "Icon beside text":
        icon_box, text_box = (S * 0.52, H / 2, S * 0.31), (S * 0.98, None, W - S * 1.08, "left")
    elif layout == "Icon only":
        icon_box, text_box = (W / 2, H / 2, S * 0.38), None
    else:
        icon_box, text_box = None, (W * 0.08, None, W * 0.84, "center")

    if icon_box:
        cx, cy, r = icon_box
        if bg_kind in ("Dark", "Gradient"):  # soft halo behind the icon
            halo = Image.new("L", (W, H), 0)
            ImageDraw.Draw(halo).ellipse([cx - r * 1.3, cy - r * 1.3, cx + r * 1.3, cy + r * 1.3], fill=90)
            canvas.alpha_composite(_fill(halo.filter(ImageFilter.GaussianBlur(r * 0.5)), p))
        icon = _draw_icon(style, (W, H), cx, cy, r, pal, rng, mono, font_path)
        if spec.get("glow", True):
            glow = Image.new("RGBA", (W, H), p + (0,))
            glow.putalpha(icon.getchannel("A").point(lambda v: v * 150 // 255))
            canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(r * 0.12)))
        else:
            shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            shadow.putalpha(icon.getchannel("A").point(lambda v: v * 70 // 255))
            canvas.alpha_composite(ImageChops.offset(shadow, 0, int(r * 0.04)).filter(ImageFilter.GaussianBlur(r * 0.05)))
        canvas.alpha_composite(icon)

    if text_box:
        x0, y0, max_w, align = text_box
        brand_h = S * (0.105 if layout == "Icon above text" else 0.17 if layout == "Icon beside text" else 0.2)
        bfont, btrack, bw, bh, btop = _fit_font(font_path, brand, max_w, brand_h, tracking)
        if tagline:
            tfont, ttrack, tw, th, ttop = _fit_font(sub_font, tagline, max_w, brand_h * 0.38, tracking * 2 + 0.12)
            gap = bh * 0.45
        else:
            tw = th = ttop = gap = 0
            tfont = ttrack = None
        block_h = bh + (gap + th if tagline else 0)
        if y0 is None:
            y0 = (H - block_h) / 2
        bx = x0 + (max_w - bw) / 2 if align == "center" else x0
        mask = _text_mask((W, H), brand, bfont, bx, y0, btrack, btop)
        if bg_kind == "Brand color":
            g1, g2 = text_fg, mix(text_fg, s, 0.3)
        elif light_bg:
            g1, g2 = p, s
        else:
            g1, g2 = lighten(p, 0.15), lighten(s, 0.1)
        if spec.get("text_gradient", True) and min(contrast_ratio(g1, bg_solid), contrast_ratio(g2, bg_solid)) >= 2.2:
            canvas.alpha_composite(_fill(mask, g1, g2, 0))
        else:
            canvas.alpha_composite(_fill(mask, text_fg))
        if tagline:
            tx = x0 + (max_w - tw) / 2 if align == "center" else x0
            tmask = _text_mask((W, H), tagline, tfont, tx, y0 + bh + gap, ttrack, ttop)
            sub_col = a if bg_kind != "Light" else darken(a, 0.35)
            if contrast_ratio(sub_col, bg_solid) < 2.2:
                sub_col = mix(text_fg, a, 0.35)
            canvas.alpha_composite(_fill(tmask, sub_col))

    if ss > 1:
        canvas = canvas.resize((W // ss, H // ss), Image.Resampling.LANCZOS)
    return canvas


def random_logo_spec(rng, base, fonts, lock_colors=False, lock_style=False):
    spec = dict(base)
    spec["seed"] = rng.randint(1, 999_999)
    if not lock_style:
        spec["style"] = rng.choice(LOGO_STYLES)
    if not lock_colors:
        if rng.random() < 0.5:
            pal = PALETTES[rng.choice(list(PALETTES))]
        else:
            pal = random_palette(rng)
        spec["p"], spec["s"], spec["a"] = (rgb_to_hex(c) for c in pal)
        spec["background"] = rng.choice(["Dark", "Dark", "Gradient", "Gradient", "Light", "Brand color"])
    if fonts and rng.random() < 0.7:
        bold = [p for n, p in fonts.items() if any(h in n.lower() for h in BOLD_HINTS)]
        spec["font"] = rng.choice(bold or list(fonts.values()))
    spec["text_gradient"] = rng.random() < 0.6
    spec["glow"] = rng.random() < 0.6
    spec["tracking"] = rng.choice([0, 4, 8, 14])
    return spec

