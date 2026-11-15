"""Brand kit, animated logo intro, palette sheet and business cards (pure Pillow)."""

import math
import os

from PIL import Image, ImageDraw, ImageFilter

from .core import safe_name
from .graphics import (_fill, _fit_font, _gradient, _load_font, _text_mask, darken, hex_to_rgb, lighten, luminance,
                       mix, render_logo, rgb_to_hex)
from .qrtools import build_payload, render_qr_sized, save_animation

# ---------------------------------------------------------------------------
# Small drawing helpers
# ---------------------------------------------------------------------------


def _ease_out_back(t, k=1.70158):
    t -= 1
    return t * t * ((k + 1) * t + k) + 1


def _ease_out(t):
    return 1 - (1 - t) ** 3


def _text(canvas, text, font_path, x, y, max_w, max_h, color, color2=None, align="left", tracking=0.0, angle=0):
    if not text:
        return 0
    font, trk, w, h, top = _fit_font(font_path, text, max_w, max_h, tracking)
    if align == "center":
        x = x + (max_w - w) / 2
    elif align == "right":
        x = x + max_w - w
    mask = _text_mask(canvas.size, text, font, x, y, trk, top)
    canvas.alpha_composite(_fill(mask, color, color2, angle))
    return h


def _blob(canvas, cx, cy, r, color, alpha=90, blur=0.35):
    m = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(m).ellipse([cx - r, cy - r, cx + r, cy + r], fill=alpha)
    canvas.alpha_composite(_fill(m.filter(ImageFilter.GaussianBlur(r * blur)), color))


def _feather(img, frac=0.14):
    """Fade alpha to zero near the edges so a glow layer never shows a hard box when composited."""
    w, h = img.size
    m = Image.new("L", (w, h), 0)
    bw, bh = int(w * frac), int(h * frac)
    ImageDraw.Draw(m).rectangle([bw, bh, w - bw, h - bh], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(max(bw, bh) * 0.5))
    from PIL import ImageChops
    out = img.copy()
    out.putalpha(ImageChops.multiply(img.getchannel("A"), m))
    return out


def _fit_into(img, w, h):
    im = img.copy()
    im.thumbnail((int(w), int(h)), Image.Resampling.LANCZOS)
    return im


def _shine(fg, t, strength=120):
    """Diagonal light sweep clipped to the foreground's alpha. t: 0..1 across."""
    w, h = fg.size
    band = Image.new("L", (w, h), 0)
    cx = -w * 0.3 + 1.6 * w * t
    ImageDraw.Draw(band).polygon([(cx, 0), (cx + w * 0.16, 0), (cx + w * 0.16 - h * 0.5, h), (cx - h * 0.5, h)],
                                 fill=strength)
    band = band.filter(ImageFilter.GaussianBlur(max(1, w * 0.02)))
    from PIL import ImageChops
    alpha = ImageChops.multiply(band, fg.getchannel("A"))
    light = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    light.putalpha(alpha)
    return light


# ---------------------------------------------------------------------------
# Animated logo intro
# ---------------------------------------------------------------------------


def logo_intro_frames(spec, size=480, frames=44):
    bg = render_logo(dict(spec, _layer="bg"), size=size)
    fg = _feather(render_logo(dict(spec, _layer="fg"), size=size), 0.06)
    W, H = fg.size
    out = []
    pop, shine_end = int(frames * 0.38), int(frames * 0.72)
    for k in range(frames):
        frame = bg.copy()
        if k < pop:
            t = k / max(1, pop - 1)
            s = 0.5 + 0.5 * _ease_out_back(t)
            a = min(1.0, _ease_out(t) * 1.4)
            rot = -10 * (1 - _ease_out(t))
            f = fg.resize((max(1, int(W * s)), max(1, int(H * s))), Image.Resampling.LANCZOS)
            f = f.rotate(rot, resample=Image.Resampling.BICUBIC, expand=False)
            if a < 1:
                f.putalpha(f.getchannel("A").point(lambda v, a=a: int(v * a)))
            frame.alpha_composite(f, ((W - f.width) // 2, (H - f.height) // 2))
        else:
            frame.alpha_composite(fg)
            if k < shine_end:
                frame.alpha_composite(_shine(fg, (k - pop) / max(1, shine_end - pop)))
        out.append(frame)
    # GIFs can't do soft alpha: flatten transparent logos onto white
    if spec.get("background") == "Transparent":
        flat = []
        for f in out:
            base = Image.new("RGBA", f.size, (255, 255, 255, 255))
            base.alpha_composite(f)
            flat.append(base.convert("RGB"))
        return flat
    return [f.convert("RGB") for f in out]


# ---------------------------------------------------------------------------
# Palette sheet & brand kit
# ---------------------------------------------------------------------------


def palette_sheet(spec, font_path=None, size=(1600, 900)):
    W, H = size
    img = Image.new("RGBA", size, (248, 250, 252, 255))
    cols = [("Primary", spec["p"]), ("Secondary", spec["s"]), ("Accent", spec["a"])]
    tints = []
    for name, hx in cols:
        rgb = hex_to_rgb(hx)
        tints.append((name, rgb, [lighten(rgb, 0.6), lighten(rgb, 0.3), rgb, darken(rgb, 0.3), darken(rgb, 0.55)]))
    _text(img, (spec.get("brand") or "Brand").upper() + " — COLOUR PALETTE", font_path, 80, 60, W - 160, 60,
          (15, 23, 42), tracking=0.06)
    cw = (W - 160 - 2 * 40) / 3
    for i, (name, rgb, shades) in enumerate(tints):
        x0 = 80 + i * (cw + 40)
        m = Image.new("L", size, 0)
        ImageDraw.Draw(m).rounded_rectangle([x0, 170, x0 + cw, 520], radius=28, fill=255)
        img.alpha_composite(_fill(m, rgb))
        txt = (15, 23, 42) if luminance(rgb) > 0.45 else (255, 255, 255)
        _text(img, name.upper(), font_path, x0 + 30, 200, cw - 60, 36, txt, tracking=0.08)
        _text(img, rgb_to_hex(rgb), font_path, x0 + 30, 400, cw - 60, 56, txt)
        _text(img, "RGB %d, %d, %d" % rgb, font_path, x0 + 30, 470, cw - 60, 26, txt)
        sw = cw / 5
        for j, sh in enumerate(shades):
            m2 = Image.new("L", size, 0)
            ImageDraw.Draw(m2).rounded_rectangle([x0 + j * sw + 4, 560, x0 + (j + 1) * sw - 4, 680], radius=14,
                                                 fill=255)
            img.alpha_composite(_fill(m2, sh))
            _text(img, rgb_to_hex(sh), font_path, x0 + j * sw + 4, 700, sw - 8, 20, (71, 85, 105), align="center")
    return img


def social_banner(spec, size, font_path=None):
    W, H = size
    p, s, a = (hex_to_rgb(spec[k]) for k in ("p", "s", "a"))
    img = _gradient(size, darken(p, 0.55), darken(s, 0.6), 25)
    _blob(img, W * 0.85, H * 0.15, H * 0.7, s, 110)
    _blob(img, W * 0.1, H * 0.95, H * 0.6, p, 120)
    _blob(img, W * 0.55, H * 0.5, H * 0.35, a, 50)
    layout = "Icon beside text" if W / H > 1.6 else "Icon above text"
    logo = render_logo(dict(spec, layout=layout, background="Dark", _layer="fg"),
                       size=int(min(W / (2 if layout == "Icon beside text" else 1), H) * 0.9))
    logo = _fit_into(_feather(logo, 0.06), W * 0.78, H * 0.78)
    img.alpha_composite(logo, ((W - logo.width) // 2, (H - logo.height) // 2))
    return img


def export_brand_kit(spec, folder, font_path=None, progress=lambda m: None):
    brand = safe_name(spec.get("brand") or "Brand", "Brand")
    root = os.path.join(folder, f"{brand} Brand Kit")
    os.makedirs(os.path.join(root, "social"), exist_ok=True)
    os.makedirs(os.path.join(root, "web"), exist_ok=True)
    files = []

    def save(img, *parts, **kw):
        path = os.path.join(root, *parts)
        img.save(path, **kw)
        files.append(path)

    progress("Logos…")
    for sz in (512, 1024, 2048):
        save(render_logo(spec, size=sz), f"logo_{sz}.png")
    save(render_logo(dict(spec, background="Transparent", glow=False), size=1024), "logo_transparent.png")
    icon = dict(spec, layout="Icon only")
    save(render_logo(icon, size=1024), "icon_1024.png")
    save(render_logo(dict(icon, background="Transparent", glow=False), size=1024), "icon_transparent.png")
    progress("Favicons & app icons…")
    ico = render_logo(icon, size=256)
    save(ico, "web", "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    for name, px in (("favicon-32.png", 32), ("favicon-192.png", 192), ("apple-touch-icon.png", 180),
                     ("android-512.png", 512)):
        save(render_logo(icon, size=max(px, 64)).resize((px, px), Image.Resampling.LANCZOS), "web", name)
    progress("Social media banners…")
    for name, size in (("x_header_1500x500.png", (1500, 500)), ("linkedin_banner_1584x396.png", (1584, 396)),
                       ("youtube_banner_2560x1440.png", (2560, 1440)), ("link_preview_1200x630.png", (1200, 630)),
                       ("post_1080x1080.png", (1080, 1080)), ("story_1080x1920.png", (1080, 1920))):
        save(social_banner(spec, size, font_path).convert("RGB"), "social", name, quality=95)
    save(render_logo(icon, size=400), "social", "profile_picture_400.png")
    progress("Palette sheet…")
    save(palette_sheet(spec, font_path), "palette.png")
    progress("Animated intro…")
    frames = logo_intro_frames(spec, size=420)
    save_animation(frames, os.path.join(root, "logo_intro.gif"), ms=40)
    files.append(os.path.join(root, "logo_intro.gif"))
    with open(os.path.join(root, "README.txt"), "w", encoding="utf-8") as f:
        f.write(f"{spec.get('brand')} — brand kit made with Studio Vision AI\n\n")
        f.write(f"Primary   {spec['p']}\nSecondary {spec['s']}\nAccent    {spec['a']}\n")
        f.write(f"Font      {os.path.basename(spec.get('font') or 'default')}\n")
        f.write(f"Icon      {spec.get('style')} (seed {spec.get('seed')})\n\n")
        f.write("web/favicon.ico goes in your site root; apple-touch-icon.png for iPhone home screens.\n")
    return root, files


# ---------------------------------------------------------------------------
# Business cards (3.5 x 2 in @ 300 dpi)
# ---------------------------------------------------------------------------

CARD_W, CARD_H = 1050, 600
CARD_TEMPLATES = ["Midnight", "Clean White", "Gradient Wave", "Split Panel", "Neon Edge"]


def _icon(kind, size, color):
    s = size * 4
    m = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(m)
    w = max(2, s // 12)
    if kind == "phone":
        d.rounded_rectangle([s * .3, s * .1, s * .7, s * .9], radius=s * .1, outline=255, width=w)
        d.line([s * .43, s * .78, s * .57, s * .78], fill=255, width=w)
    elif kind == "mail":
        d.rounded_rectangle([s * .1, s * .25, s * .9, s * .75], radius=s * .06, outline=255, width=w)
        d.line([s * .12, s * .3, s * .5, s * .55, s * .88, s * .3], fill=255, width=w, joint="curve")
    elif kind == "web":
        d.ellipse([s * .1, s * .1, s * .9, s * .9], outline=255, width=w)
        d.ellipse([s * .33, s * .1, s * .67, s * .9], outline=255, width=w)
        d.line([s * .1, s * .5, s * .9, s * .5], fill=255, width=w)
    else:  # pin
        d.ellipse([s * .25, s * .08, s * .75, s * .58], outline=255, width=w)
        d.polygon([(s * .3, s * .45), (s * .7, s * .45), (s * .5, s * .92)], fill=255)
        d.ellipse([s * .4, s * .23, s * .6, s * .43], fill=0)
    m = m.resize((size, size), Image.Resampling.LANCZOS)
    return _fill(m, color)


def card_payload(info):
    first, _, last = (info.get("name") or "").strip().partition(" ")
    return build_payload(6, {"first": first, "last": last, "org": info.get("company"), "title": info.get("title"),
                             "vphone": info.get("phone"), "vemail": info.get("email"), "vurl": info.get("website"),
                             "vaddr": info.get("address")})


def _card_qr(info, dark, size):
    payload = card_payload(info)
    if not payload:
        return None
    if luminance(dark) > 0.25:
        dark = darken(dark, 0.45)
    spec = {"payload": payload, "ec": "M", "border": 1, "module": "Rounded", "eye": "Rounded",
            "color_mode": "Solid", "fg": rgb_to_hex(dark), "fg2": rgb_to_hex(dark), "bg": "#FFFFFF"}
    img, _ = render_qr_sized(spec, size)
    return img


def render_card(info, logo_spec, template="Midnight", side="front", font_bold=None, font_regular=None):
    W, H = CARD_W, CARD_H
    p, s, a = (hex_to_rgb(logo_spec[k]) for k in ("p", "s", "a"))
    font_bold = font_bold or logo_spec.get("font")
    font_regular = font_regular or font_bold
    dark_bg = template in ("Midnight", "Gradient Wave", "Neon Edge")
    ink = (248, 250, 252) if dark_bg else (15, 23, 42)
    sub = mix(ink, a, 0.45) if dark_bg else darken(p, 0.2)

    # background
    if template == "Midnight":
        img = _gradient((W, H), (11, 15, 26), darken(mix(p, s, 0.5), 0.72), 120)
        _blob(img, W * 0.95, H * 0.05, H * 0.55, p, 80)
        _blob(img, W * 0.05, H * 1.0, H * 0.45, s, 70)
    elif template == "Clean White":
        img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).rectangle([0, 0, 22, H], fill=255)
        img.alpha_composite(_fill(m, p, s, 90))
    elif template == "Gradient Wave":
        img = _gradient((W, H), darken(p, 0.25), darken(s, 0.35), 20)
        wave = Image.new("L", (W, H), 0)
        pts = [(x, H * 0.78 + math.sin(x / W * math.pi * 2.2) * H * 0.07) for x in range(0, W + 10, 10)]
        ImageDraw.Draw(wave).polygon(pts + [(W, H), (0, H)], fill=70)
        img.alpha_composite(_fill(wave, (255, 255, 255)))
    elif template == "Split Panel":
        img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).rectangle([0, 0, int(W * 0.38), H], fill=255)
        img.alpha_composite(_fill(m, p, s, 70))
    else:  # Neon Edge
        img = Image.new("RGBA", (W, H), (8, 10, 18, 255))
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).rounded_rectangle([18, 18, W - 18, H - 18], radius=30, outline=255, width=5)
        ring = _fill(m, p, s, 0)
        img.alpha_composite(ring.filter(ImageFilter.GaussianBlur(14)))
        img.alpha_composite(ring)

    if side == "back":
        colourful = template in ("Clean White", "Split Panel", "Gradient Wave")
        if template in ("Clean White", "Split Panel"):
            img = _gradient((W, H), p, s, 35)
        # gradient backs need a white mark; dark backs keep the full-colour logo
        icon = render_logo(dict(logo_spec, layout="Icon above text", _layer="fg",
                                background="Brand color" if colourful else "Dark"), size=520)
        icon = _fit_into(_feather(icon, 0.06), W * 0.6, H * 0.8)
        img.alpha_composite(icon, ((W - icon.width) // 2, (H - icon.height) // 2 - 10))
        if info.get("website"):
            _text(img, info["website"], font_regular, 0, H - 70, W, 30,
                  (248, 250, 252), align="center", tracking=0.06)
        return img

    qr = _card_qr(info, p if not dark_bg else darken(p, 0.4), 230)
    qx = W - (qr.width if qr is not None else 0) - 70

    # logo mark
    icon_spec = dict(logo_spec, layout="Icon only", background="Transparent", glow=False)
    if template == "Split Panel":
        mark = render_logo(dict(logo_spec, layout="Icon above text", background="Brand color", _layer="fg"),
                           size=400)
        mark = _fit_into(_feather(mark, 0.06), W * 0.32, H * 0.7)
        img.alpha_composite(mark, (int(W * 0.19 - mark.width / 2), (H - mark.height) // 2))
        x0, max_w = int(W * 0.43), int(W * 0.38)
    else:
        mark = _fit_into(render_logo(icon_spec, size=200), 110, 110)
        img.alpha_composite(mark, (70, 60))
        x0, max_w = 70, int(W * 0.56)
        if logo_spec.get("brand"):
            _text(img, (logo_spec["brand"] or "").upper(), font_bold, 200, 92, max_w - 140, 40,
                  ink if template != "Neon Edge" else lighten(p, 0.4), tracking=0.1)
    if qr is not None:
        max_w = min(max_w, qx - 40 - x0)

    # name / title
    y = 215 if template != "Split Panel" else 110
    h = _text(img, info.get("name") or "Your Name", font_bold, x0, y, max_w, 66,
              lighten(p, 0.35) if template == "Neon Edge" else ink,
              lighten(s, 0.3) if template == "Neon Edge" else None)
    y += h + 18
    if info.get("title") or info.get("company"):
        line = " · ".join(x for x in (info.get("title"), info.get("company")) if x)
        _text(img, line.upper(), font_regular, x0, y, max_w, 26, sub, tracking=0.08)
        y += 52
    else:
        y += 20
    # contact rows
    for kind, key in (("phone", "phone"), ("mail", "email"), ("web", "website"), ("pin", "address")):
        val = (info.get(key) or "").strip()
        if not val:
            continue
        ic = _icon(kind, 30, a if dark_bg else p)
        img.alpha_composite(ic, (x0, int(y)))
        _text(img, val, font_regular, x0 + 46, y + 2, max_w - 46, 26, ink)
        y += 46
        if y > H - 50:
            break

    # QR
    if qr is not None:
        qy = (H - qr.height) // 2
        plate = Image.new("L", (W, H), 0)
        ImageDraw.Draw(plate).rounded_rectangle([qx - 16, qy - 16, qx + qr.width + 16, qy + qr.height + 16],
                                                radius=24, fill=255)
        img.alpha_composite(_fill(plate, (255, 255, 255)))
        img.alpha_composite(qr.convert("RGBA"), (qx, qy))
        _text(img, "SCAN TO SAVE", font_regular, qx - 16, qy + qr.height + 26, qr.width + 32, 18,
              sub if not dark_bg else mix(ink, a, 0.3), align="center", tracking=0.18)
    return img


def print_sheet(front, back=None, dpi=300):
    """A4 sheet with 10 cards and crop marks. Returns [front_sheet, back_sheet?]."""
    A4 = (2480, 3508)
    cols, rows = 2, 5
    gx = (A4[0] - cols * CARD_W) // 2
    gy = (A4[1] - rows * CARD_H) // 2

    def sheet(card, mirror=False):
        page = Image.new("RGB", A4, (255, 255, 255))
        d = ImageDraw.Draw(page)
        for r in range(rows):
            for c in range(cols):
                cc = cols - 1 - c if mirror else c
                x, y = gx + cc * CARD_W, gy + r * CARD_H
                page.paste(card.convert("RGB"), (x, y))
        for c in range(cols + 1):
            x = gx + c * CARD_W
            d.line([x, 0, x, gy - 20], fill=(0, 0, 0), width=2)
            d.line([x, A4[1] - gy + 20, x, A4[1]], fill=(0, 0, 0), width=2)
        for r in range(rows + 1):
            y = gy + r * CARD_H
            d.line([0, y, gx - 20, y], fill=(0, 0, 0), width=2)
            d.line([A4[0] - gx + 20, y, A4[0], y], fill=(0, 0, 0), width=2)
        return page
    pages = [sheet(front)]
    if back is not None:
        pages.append(sheet(back, mirror=True))
    return pages


def save_pdf(pages, path, dpi=300):
    rgb = [p.convert("RGB") for p in pages]
    rgb[0].save(path, "PDF", resolution=dpi, save_all=True, append_images=rgb[1:])
    return path


__all__ = ["logo_intro_frames", "palette_sheet", "export_brand_kit", "render_card", "CARD_TEMPLATES",
           "print_sheet", "save_pdf", "card_payload", "_load_font"]
