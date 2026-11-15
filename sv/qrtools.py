"""QR payloads, styled/art/animated/SVG rendering, verification, scanning and batch export."""

import base64
import csv
import datetime as _dt
import io
import math
import os
import re
import urllib.parse

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from .core import HAS_CV2, HAS_NP, log, np, safe_name
from .graphics import _fill, _fit_font, _gradient, _text_mask, contrast_ratio, hex_to_rgb, lighten, luminance, rgb_to_hex

try:
    import qrcode
    import qrcode.constants
    import qrcode.util
    HAS_QR = True
except Exception:
    qrcode = None
    HAS_QR = False

HAS_STYLED_QR = False
QR_DRAWERS = {}
QR_MASKS = {}
if HAS_QR:
    try:
        from qrcode.image.styledpil import StyledPilImage
        try:
            from qrcode.image.styles.moduledrawers.pil import (
                CircleModuleDrawer,
                GappedSquareModuleDrawer,
                HorizontalBarsDrawer,
                RoundedModuleDrawer,
                SquareModuleDrawer,
                VerticalBarsDrawer,
            )
        except ImportError:
            from qrcode.image.styles.moduledrawers import (
                CircleModuleDrawer,
                GappedSquareModuleDrawer,
                HorizontalBarsDrawer,
                RoundedModuleDrawer,
                SquareModuleDrawer,
                VerticalBarsDrawer,
            )
        from qrcode.image.styles.colormasks import (
            HorizontalGradiantColorMask,
            RadialGradiantColorMask,
            SolidFillColorMask,
            SquareGradiantColorMask,
            VerticalGradiantColorMask,
        )
        QR_DRAWERS = {
            "Square": SquareModuleDrawer,
            "Rounded": RoundedModuleDrawer,
            "Dots": CircleModuleDrawer,
            "Gapped": GappedSquareModuleDrawer,
            "Vertical Bars": VerticalBarsDrawer,
            "Horizontal Bars": HorizontalBarsDrawer,
        }
        QR_MASKS = {
            "Solid": SolidFillColorMask,
            "Radial Gradient": RadialGradiantColorMask,
            "Square Gradient": SquareGradiantColorMask,
            "Horizontal Gradient": HorizontalGradiantColorMask,
            "Vertical Gradient": VerticalGradiantColorMask,
        }
        HAS_STYLED_QR = True
    except Exception:
        HAS_STYLED_QR = False

EC_LEVELS = {"Low (7%)": "L", "Medium (15%)": "M", "Quartile (25%)": "Q", "High (30%) — best with logo": "H"}
_EC = {"L": 1, "M": 0, "Q": 3, "H": 2}  # qrcode.constants values

# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

QR_TYPES = [
    ("🔗 Link / Text", [("text", "https://example.com  or any text")]),
    ("📶 Wi-Fi", [("ssid", "Network name (SSID)"), ("wifi_pass", "Password"), ("wifi_sec", ""),
                 ("wifi_hidden", "")]),
    ("✉️ Email", [("email", "name@example.com"), ("subject", "Subject"), ("body", "Message")]),
    ("📞 Phone", [("phone", "+92 300 1234567")]),
    ("💬 SMS", [("sms_to", "+92 300 1234567"), ("sms_body", "Message")]),
    ("🟢 WhatsApp", [("wa_phone", "+92 300 1234567 (with country code)"), ("wa_text", "Pre-filled message")]),
    ("👤 Contact card", [("first", "First name"), ("last", "Last name"), ("org", "Company"), ("title", "Job title"),
                        ("vphone", "Phone"), ("vemail", "Email"), ("vurl", "Website"), ("vaddr", "Address")]),
    ("📍 Location", [("lat", "Latitude (e.g. 31.5204)"), ("lon", "Longitude (e.g. 74.3587)")]),
    ("📅 Event", [("ev_title", "Event title"), ("ev_start", "Start: 2026-11-02 18:00"),
                 ("ev_end", "End: 2026-11-02 21:00 (optional)"), ("ev_loc", "Location"),
                 ("ev_desc", "Description")]),
]


def _qr_escape(value):
    return re.sub(r'([\\;,:"])', r"\\\1", value)


def _ics_time(value):
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            d = _dt.datetime.strptime(value, fmt)
            return d.strftime("%Y%m%d") if fmt in ("%Y-%m-%d", "%d/%m/%Y") else d.strftime("%Y%m%dT%H%M00")
        except ValueError:
            continue
    return None


def build_payload(kind, v):
    """kind: index into QR_TYPES. v: dict of field -> str/bool."""
    val = lambda k: str(v.get(k) or "").strip()  # noqa: E731
    if kind == 0:
        return val("text")
    if kind == 1:
        if not val("ssid"):
            return ""
        sec = val("wifi_sec") or "WPA"
        pw = f";P:{_qr_escape(val('wifi_pass'))}" if sec != "nopass" else ""
        hidden = ";H:true" if v.get("wifi_hidden") else ""
        return f"WIFI:T:{sec};S:{_qr_escape(val('ssid'))}{pw}{hidden};;"
    if kind == 2:
        if not val("email"):
            return ""
        q = {k: x for k, x in (("subject", val("subject")), ("body", val("body"))) if x}
        return f"mailto:{val('email')}" + ("?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote) if q else "")
    if kind == 3:
        return f"tel:{re.sub(r'[^0-9+]', '', val('phone'))}" if val("phone") else ""
    if kind == 4:
        return f"SMSTO:{re.sub(r'[^0-9+]', '', val('sms_to'))}:{val('sms_body')}" if val("sms_to") else ""
    if kind == 5:
        num = re.sub(r"[^0-9]", "", val("wa_phone"))
        if not num:
            return ""
        return f"https://wa.me/{num}" + (f"?text={urllib.parse.quote(val('wa_text'))}" if val("wa_text") else "")
    if kind == 6:
        if not (val("first") or val("last")):
            return ""
        lines = ["BEGIN:VCARD", "VERSION:3.0", f"N:{val('last')};{val('first')}",
                 f"FN:{(val('first') + ' ' + val('last')).strip()}"]
        for key, tag in (("org", "ORG"), ("title", "TITLE"), ("vphone", "TEL"), ("vemail", "EMAIL"),
                         ("vurl", "URL"), ("vaddr", "ADR:;;")):
            if val(key):
                lines.append(f"{tag}{'' if tag.endswith(';') else ':'}{val(key)}")
        return "\n".join(lines + ["END:VCARD"])
    if kind == 7:
        try:
            lat, lon = float(val("lat")), float(val("lon"))
        except ValueError:
            return ""
        return f"geo:{lat},{lon}"
    if kind == 8:
        start = _ics_time(val("ev_start"))
        if not (val("ev_title") and start):
            return ""
        lines = ["BEGIN:VEVENT", f"SUMMARY:{val('ev_title')}", f"DTSTART:{start}"]
        end = _ics_time(val("ev_end"))
        if end:
            lines.append(f"DTEND:{end}")
        if val("ev_loc"):
            lines.append(f"LOCATION:{val('ev_loc')}")
        if val("ev_desc"):
            lines.append(f"DESCRIPTION:{val('ev_desc')}")
        return "\n".join(lines + ["END:VEVENT"])
    return ""


def describe_payload(text):
    """Human summary of decoded QR content: (kind_label, [(field, value), ...], url_or_None)."""
    t = text.strip()
    up = t.upper()
    if up.startswith("WIFI:"):
        fields = dict(re.findall(r"([TSPH]):((?:\\.|[^;])*)", t[5:]))
        unesc = lambda s: re.sub(r"\\(.)", r"\1", s)  # noqa: E731
        return "📶 Wi-Fi network", [("Network", unesc(fields.get("S", ""))), ("Security", fields.get("T", "")),
                                   ("Password", unesc(fields.get("P", "")))], None
    if up.startswith("MAILTO:"):
        return "✉️ Email", [("To", urllib.parse.unquote(t[7:].split("?")[0]))], t
    if up.startswith("TEL:"):
        return "📞 Phone number", [("Number", t[4:])], t
    if up.startswith("SMSTO:"):
        parts = t[6:].split(":", 1)
        return "💬 SMS", [("To", parts[0]), ("Message", parts[1] if len(parts) > 1 else "")], None
    if up.startswith("BEGIN:VCARD"):
        rows = [(k, v) for k, v in re.findall(r"^(FN|ORG|TITLE|TEL|EMAIL|URL)[^:]*:(.*)$", t, re.M)]
        return "👤 Contact card", rows, None
    if up.startswith("BEGIN:VEVENT"):
        rows = re.findall(r"^(SUMMARY|DTSTART|DTEND|LOCATION|DESCRIPTION)[^:]*:(.*)$", t, re.M)
        return "📅 Calendar event", rows, None
    if up.startswith("GEO:"):
        coords = t[4:].split("?")[0]
        return "📍 Location", [("Coordinates", coords)], f"https://www.google.com/maps?q={coords}"
    if re.match(r"^https?://", t, re.I):
        label = "🟢 WhatsApp chat" if "wa.me/" in t else "🔗 Link"
        return label, [("URL", t)], t
    return "📝 Text", [("Text", t)], None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _make_qr(payload, ec_key, border, box_size=10):
    qr = qrcode.QRCode(version=None, error_correction=_EC[ec_key], box_size=box_size, border=border)
    qr.add_data(payload)
    qr.make(fit=True)
    return qr


def _ec_for(spec):
    return "H" if spec.get("logo_path") or spec.get("art_path") else spec.get("ec", "M")


def _qr_base(spec, box_size=10, fg=None, fg2=None, bg=None, mode=None):
    if not HAS_QR:
        raise RuntimeError("qrcode is not installed (pip install \"qrcode[pil]\")")
    qr = _make_qr(spec["payload"], _ec_for(spec), spec.get("border", 3), box_size)
    fg = fg or hex_to_rgb(spec["fg"])
    fg2 = fg2 or hex_to_rgb(spec["fg2"])
    bg = bg or hex_to_rgb(spec["bg"])
    module, eye = spec.get("module", "Square"), spec.get("eye", "Square")
    mode = mode or spec.get("color_mode", "Solid")
    warnings = []
    if HAS_STYLED_QR and (module != "Square" or eye != "Square" or mode != "Solid"):
        mask_cls = QR_MASKS.get(mode, QR_MASKS["Solid"])
        if mode == "Solid":
            mask = mask_cls(back_color=bg, front_color=fg)
        elif mode in ("Radial Gradient", "Square Gradient"):
            mask = mask_cls(back_color=bg, center_color=fg, edge_color=fg2)
        elif mode == "Horizontal Gradient":
            mask = mask_cls(back_color=bg, left_color=fg, right_color=fg2)
        else:
            mask = mask_cls(back_color=bg, top_color=fg, bottom_color=fg2)
        kwargs = {"image_factory": StyledPilImage, "module_drawer": QR_DRAWERS[module](), "color_mask": mask}
        try:
            img = qr.make_image(eye_drawer=QR_DRAWERS.get(eye, QR_DRAWERS["Square"])(), **kwargs)
        except TypeError:
            img = qr.make_image(**kwargs)
    else:
        if not HAS_STYLED_QR and (module != "Square" or mode != "Solid"):
            warnings.append("Upgrade qrcode (pip install -U \"qrcode[pil]\") for styles/gradients")
        img = qr.make_image(fill_color=rgb_to_hex(fg), back_color=rgb_to_hex(bg))
    img = getattr(img, "_img", img)
    return img.convert("RGBA"), warnings


def _decorate(img, spec, caption_colors=None):
    """Add the centre logo plate and the caption strip."""
    fg, fg2, bg = hex_to_rgb(spec["fg"]), hex_to_rgb(spec["fg2"]), hex_to_rgb(spec["bg"])
    logo_path = spec.get("logo_path")
    if logo_path and os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGBA")
        ratio = max(0.08, min(0.3, spec.get("logo_ratio", 0.22)))
        target = int(img.width * ratio)
        logo.thumbnail((target, target), Image.Resampling.LANCZOS)
        pad = max(4, target // 10)
        plate_w, plate_h = logo.width + pad * 2, logo.height + pad * 2
        plate = Image.new("RGBA", (plate_w, plate_h), (0, 0, 0, 0))
        ImageDraw.Draw(plate).rounded_rectangle([0, 0, plate_w - 1, plate_h - 1], radius=pad * 2,
                                                fill=bg + (255,))
        plate.alpha_composite(logo, (pad, pad))
        img.alpha_composite(plate, ((img.width - plate_w) // 2, (img.height - plate_h) // 2))

    caption = (spec.get("caption") or "").strip()
    if caption:
        extra = int(img.height * 0.14)
        framed = Image.new("RGBA", (img.width, img.height + extra), bg + (255,))
        framed.alpha_composite(img, (0, 0))
        font, tracking, w, h, top = _fit_font(spec.get("caption_font"), caption, img.width * 0.86, extra * 0.5, 0.08)
        mask = _text_mask(framed.size, caption, font, (img.width - w) / 2, img.height + (extra - h) / 2 - extra * 0.12,
                          tracking, top)
        c1, c2 = caption_colors or (fg, fg2 if spec.get("color_mode", "Solid") != "Solid" else None)
        framed.alpha_composite(_fill(mask, c1, c2, 0))
        img = framed
    return img


def _warnings(spec):
    fg, bg = hex_to_rgb(spec["fg"]), hex_to_rgb(spec["bg"])
    out = []
    cr = contrast_ratio(fg, bg)
    if cr < 3:
        out.append(f"Low contrast ({cr:.1f}:1) — many phones won't scan this")
    if luminance(fg) > luminance(bg):
        out.append("Light code on dark background — some older scanners struggle")
    return out


def render_qr(spec, box_size=10):
    if spec.get("art_path") and os.path.exists(spec["art_path"]):
        return render_art_qr(spec, box_size=max(box_size, 12))
    img, warnings = _qr_base(spec, box_size)
    img = _decorate(img, spec)
    return img, warnings + _warnings(spec)


def _function_cells(n, version):
    """Cells (row, col) of finder/separator/timing/alignment patterns (code coords, no border)."""
    cells = set()
    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):
        for r in range(r0 - 1, r0 + 8):
            for c in range(c0 - 1, c0 + 8):
                if 0 <= r < n and 0 <= c < n:
                    cells.add((r, c))
    for i in range(n):
        cells.add((6, i))
        cells.add((i, 6))
    pos = qrcode.util.pattern_position(version)
    for r in pos:
        for c in pos:
            if (r, c) in cells and ((r < 9 and c < 9) or (r < 9 and c > n - 10) or (r > n - 10 and c < 9)):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    cells.add((r + dr, c + dc))
    return cells


def render_art_qr(spec, box_size=12):
    """Picture QR that is guaranteed to scan: if a busy photo would break it, the photo is faded step by step
    until our checker can read it."""
    vis = spec.get("art_strength", 0.6)
    img, warnings = _render_art_qr(spec, box_size)
    if not (HAS_CV2 and HAS_NP):
        return img, warnings
    tries = 0
    while scan_score(img, spec["payload"])[0] < 3 and vis > 0.2 and tries < 6:
        vis = round(vis - 0.12, 2)
        tries += 1
        img, warnings = _render_art_qr(dict(spec, art_strength=vis), box_size)
    if tries:
        warnings = warnings + [f"Photo faded to {int(max(vis, 0.2) * 100)}% so the code stays scannable"]
    return img, warnings


def _render_art_qr(spec, box_size=12):
    """Halftone 'picture QR': the photo shows through, small dots carry the data."""
    qr = _make_qr(spec["payload"], "H", spec.get("border", 3), 1)
    matrix = qr.get_matrix()
    border = spec.get("border", 3)
    size = len(matrix)
    n = size - 2 * border
    B = box_size
    fg, bg = hex_to_rgb(spec["fg"]), hex_to_rgb(spec["bg"])
    # the data colour must stay genuinely dark for scanners, whatever colour the user picked
    dark = fg
    while luminance(dark) > 0.035:
        dark = tuple(int(c * 0.8) for c in dark)
    light = bg if luminance(bg) > 0.6 else (255, 255, 255)
    photo = Image.open(spec["art_path"]).convert("RGB")
    photo = ImageOps.fit(photo, (size * B, size * B), Image.Resampling.LANCZOS)
    photo = ImageEnhance.Contrast(photo).enhance(1.1)
    vis = max(0.2, min(0.9, spec.get("art_strength", 0.6)))
    # Tint the photo inside every module toward that module's value, so each cell's average brightness
    # agrees with the data while the picture still shows through (how pro "art QR" generators do it).
    module_mask = Image.new("L", (size, size), 0)
    module_mask.putdata([255 if matrix[r][c] else 0 for r in range(size) for c in range(size)])
    module_mask = module_mask.resize(photo.size, Image.Resampling.NEAREST)
    gray = ImageOps.grayscale(photo).convert("RGB")
    dark_layer = Image.blend(Image.new("RGB", photo.size, dark), Image.blend(gray, photo, 0.5), vis * 0.42)
    light_layer = Image.blend(Image.new("RGB", photo.size, light), photo, vis * 0.5)
    # guarantee contrast whatever the photo: light cells never below ~68% grey, dark cells never above ~43%
    from PIL import ImageChops
    light_layer = ImageChops.lighter(light_layer, Image.new("RGB", photo.size, (174, 174, 174)))
    dark_layer = ImageChops.darker(dark_layer, Image.new("RGB", photo.size, (110, 110, 110)))
    canvas = Image.composite(dark_layer, light_layer, module_mask).convert("RGBA")
    d = ImageDraw.Draw(canvas)
    func = _function_cells(n, qr.version)
    dot = B * 0.42
    round_dot = spec.get("module") in ("Dots", "Rounded")
    for r in range(size):
        for c in range(size):
            on = matrix[r][c]
            cr, cc = r - border, c - border
            x0, y0 = c * B, r * B
            if not (0 <= cr < n and 0 <= cc < n):
                continue
            col = (dark if on else light) + (255,)
            if (cr, cc) in func:
                d.rectangle([x0, y0, x0 + B - 1, y0 + B - 1], fill=col)
            else:
                o = (B - dot) / 2
                box = [x0 + o, y0 + o, x0 + o + dot, y0 + o + dot]
                if round_dot:
                    d.ellipse(box, fill=col)
                else:
                    d.rectangle(box, fill=col)
    # quiet zone stays clean so scanners lock on
    q = Image.new("RGBA", canvas.size, bg + (255,))
    inner = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(inner).rectangle([border * B, border * B, (size - border) * B - 1, (size - border) * B - 1],
                                    fill=255)
    q.paste(canvas, (0, 0), inner)
    img = _decorate(q, dict(spec, logo_path=None))
    return img, _warnings(spec) + ["Picture QR: test with your phone — busy photos scan less reliably"]


# ---------------------------------------------------------------------------
# SVG (vector) export
# ---------------------------------------------------------------------------


def _rounded_ring(x, y, s, t, r_out, r_in):
    """Even-odd path: outer rounded square minus inner rounded square."""
    def rr(x, y, w, r):
        r = min(r, w / 2)
        return (f"M{x + r},{y}h{w - 2 * r}a{r},{r} 0 0 1 {r},{r}v{w - 2 * r}a{r},{r} 0 0 1 {-r},{r}"
                f"h{-(w - 2 * r)}a{r},{r} 0 0 1 {-r},{-r}v{-(w - 2 * r)}a{r},{r} 0 0 1 {r},{-r}z")
    return rr(x, y, s, r_out) + rr(x + t, y + t, s - 2 * t, r_in)


def qr_to_svg(spec, box=10):
    qr = _make_qr(spec["payload"], _ec_for(spec), spec.get("border", 3), 1)
    m = qr.get_matrix()
    size = len(m)
    border = spec.get("border", 3)
    n = size - 2 * border
    W = size * box
    fg, fg2, bg = spec["fg"], spec["fg2"], spec["bg"]
    mode, module, eye = spec.get("color_mode", "Solid"), spec.get("module", "Square"), spec.get("eye", "Square")
    caption = (spec.get("caption") or "").strip()
    H = W + (int(W * 0.14) if caption else 0)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'viewBox="0 0 {W} {H}" width="{W}" height="{H}" shape-rendering="geometricPrecision">']
    if mode == "Solid":
        paint = fg
    else:
        paint = "url(#g)"
        if mode in ("Radial Gradient", "Square Gradient"):
            out.append(f'<defs><radialGradient id="g" cx="50%" cy="50%" r="70%"><stop offset="0" stop-color="{fg}"/>'
                       f'<stop offset="1" stop-color="{fg2}"/></radialGradient></defs>')
        else:
            x2, y2 = ("1", "0") if mode == "Horizontal Gradient" else ("0", "1")
            out.append(f'<defs><linearGradient id="g" x1="0" y1="0" x2="{x2}" y2="{y2}"><stop offset="0" '
                       f'stop-color="{fg}"/><stop offset="1" stop-color="{fg2}"/></linearGradient></defs>')
    out.append(f'<rect width="{W}" height="{H}" fill="{bg}"/>')
    finders = [(border, border), (border, border + n - 7), (border + n - 7, border)]

    def in_finder(r, c):
        return any(r0 <= r < r0 + 7 and c0 <= c < c0 + 7 for r0, c0 in finders)

    shapes = []
    for r in range(size):
        for c in range(size):
            if not m[r][c] or in_finder(r, c):
                continue
            x, y = c * box, r * box
            if module == "Dots":
                shapes.append(f'<circle cx="{x + box / 2}" cy="{y + box / 2}" r="{box * 0.45}"/>')
            elif module == "Rounded":
                shapes.append(f'<rect x="{x}" y="{y}" width="{box}" height="{box}" rx="{box * 0.35}"/>')
            elif module == "Gapped":
                g = box * 0.1
                shapes.append(f'<rect x="{x + g}" y="{y + g}" width="{box - 2 * g}" height="{box - 2 * g}"/>')
            elif module == "Vertical Bars":
                shapes.append(f'<rect x="{x + box * 0.1}" y="{y}" width="{box * 0.8}" height="{box}" rx="{box * 0.3}"/>')
            elif module == "Horizontal Bars":
                shapes.append(f'<rect x="{x}" y="{y + box * 0.1}" width="{box}" height="{box * 0.8}" rx="{box * 0.3}"/>')
            else:
                shapes.append(f'<rect x="{x}" y="{y}" width="{box + 0.02}" height="{box + 0.02}"/>')
    for r0, c0 in finders:
        x, y, s = c0 * box, r0 * box, 7 * box
        if eye == "Dots":
            cx, cy = x + s / 2, y + s / 2
            shapes.append(f'<circle cx="{cx}" cy="{cy}" r="{s / 2 - box / 2}" fill="none" stroke="{paint}" '
                          f'stroke-width="{box}"/>')
            shapes.append(f'<circle cx="{cx}" cy="{cy}" r="{box * 1.5}"/>')
        else:
            r_out = {"Rounded": box * 2, "Gapped": 0}.get(eye, 0)
            shapes.append(f'<path fill-rule="evenodd" d="{_rounded_ring(x, y, s, box, r_out, max(0, r_out - box))}"/>')
            r_in = box * 0.8 if eye == "Rounded" else 0
            shapes.append(f'<rect x="{x + 2 * box}" y="{y + 2 * box}" width="{3 * box}" height="{3 * box}" '
                          f'rx="{r_in}"/>')
    out.append(f'<g fill="{paint}">' + "".join(shapes) + "</g>")
    logo_path = spec.get("logo_path")
    if logo_path and os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGBA")
        ratio = max(0.08, min(0.3, spec.get("logo_ratio", 0.22)))
        target = int(W * ratio)
        logo.thumbnail((target * 2, target * 2), Image.Resampling.LANCZOS)
        lw, lh = target, int(target * logo.height / logo.width)
        pad = max(4, target // 10)
        buf = io.BytesIO()
        logo.save(buf, "PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        px, py = (W - lw) / 2, (W - lh) / 2
        out.append(f'<rect x="{px - pad}" y="{py - pad}" width="{lw + 2 * pad}" height="{lh + 2 * pad}" '
                   f'rx="{pad * 2}" fill="{bg}"/>')
        out.append(f'<image x="{px}" y="{py}" width="{lw}" height="{lh}" xlink:href="data:image/png;base64,{b64}"/>')
    if caption:
        fs = int(W * 0.065)
        esc = caption.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        out.append(f'<text x="{W / 2}" y="{W + (H - W) * 0.48}" text-anchor="middle" dominant-baseline="middle" '
                   f'font-family="Segoe UI, Arial, sans-serif" font-weight="800" letter-spacing="{fs * 0.08}" '
                   f'font-size="{fs}" fill="{paint}">{esc}</text>')
    out.append("</svg>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Animated QR (GIF / WebP)
# ---------------------------------------------------------------------------


def animated_qr_frames(spec, frames=30, box_size=8):
    """Flowing gradient + a soft shine sweep. Data modules never change, so every frame scans."""
    mono, _ = _qr_base(dict(spec, logo_path=None), box_size, fg=(0, 0, 0), fg2=(0, 0, 0), bg=(255, 255, 255),
                       mode="Solid")
    mask = ImageOps.invert(mono.convert("L"))
    fg, fg2, bg = hex_to_rgb(spec["fg"]), hex_to_rgb(spec["fg2"]), hex_to_rgb(spec["bg"])
    if spec.get("color_mode", "Solid") == "Solid":
        fg2 = lighten(fg, 0.0)
    w, h = mask.size
    out = []
    for k in range(frames):
        t = k / frames
        angle = int(360 * t)
        base = Image.new("RGBA", (w, h), bg + (255,))
        layer = _gradient((w, h), fg, fg2, angle) if fg != fg2 else Image.new("RGBA", (w, h), fg + (255,))
        # shine band
        band = Image.new("L", (w, h), 0)
        cx = -w * 0.5 + 2 * w * t
        ImageDraw.Draw(band).polygon([(cx - w * 0.12, 0), (cx + w * 0.12, 0), (cx - h * 0.4 + w * 0.12, h),
                                      (cx - h * 0.4 - w * 0.12, h)], fill=120)
        band = band.filter(ImageFilter.GaussianBlur(w * 0.03))
        shine = Image.new("RGBA", (w, h), lighten(fg, 0.45) + (0,))
        shine.putalpha(band)
        layer.alpha_composite(shine)
        layer.putalpha(mask)
        base.alpha_composite(layer)
        out.append(_decorate(base, spec, caption_colors=(fg, fg2 if fg2 != fg else None)).convert("RGB"))
    return out


def save_animation(frames, path, ms=60):
    if path.lower().endswith(".webp"):
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=ms, loop=0, quality=90)
    else:
        pal = [f.convert("P", palette=Image.Palette.ADAPTIVE, colors=255) for f in frames]
        pal[0].save(path, save_all=True, append_images=pal[1:], duration=ms, loop=0, optimize=False, disposal=2)
    return path


# ---------------------------------------------------------------------------
# Verification & scanning (OpenCV)
# ---------------------------------------------------------------------------


def _detectors():
    import cv2
    dets = []
    if hasattr(cv2, "QRCodeDetectorAruco"):
        try:
            dets.append(cv2.QRCodeDetectorAruco())
        except Exception:
            pass
    dets.append(cv2.QRCodeDetector())
    return dets


def _flatten(img):
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        rgb = Image.new("RGB", img.size, (255, 255, 255))
        rgb.paste(img, mask=img.getchannel("A"))
        return rgb
    return img.convert("RGB")


def decode_image(img):
    """Return a list of every QR payload found in a PIL image."""
    if not (HAS_CV2 and HAS_NP):
        raise RuntimeError("Scanning needs OpenCV:  pip install opencv-python-headless")
    rgb = _flatten(img)
    if max(rgb.size) > 2000:
        rgb.thumbnail((2000, 2000))
    found = []
    for scale in (1.0, 0.5, 1.6, 0.3):
        im = rgb if scale == 1.0 else rgb.resize((max(64, int(rgb.width * scale)), max(64, int(rgb.height * scale))))
        for arr in (np.array(im)[:, :, ::-1].copy(), np.array(ImageOps.autocontrast(im.convert("L")))):
            for det in _detectors():
                try:
                    ok, vals, _, _ = det.detectAndDecodeMulti(arr)
                    if ok:
                        found += [v for v in vals if v]
                    if not found:
                        v, _, _ = det.detectAndDecode(arr)
                        if v:
                            found.append(v)
                except Exception:
                    continue
            if found:
                return list(dict.fromkeys(found))
    return []


def decode_frame(bgr):
    """Fast single-frame decode for the webcam scanner (numpy BGR array)."""
    for det in _detectors():
        try:
            v, _, _ = det.detectAndDecode(bgr)
            if v:
                return v
        except Exception:
            continue
    return None


def verify_qr(img, payload):
    """True/False if OpenCV is available, None if we can't check."""
    if not (HAS_CV2 and HAS_NP):
        return None
    try:
        vals = decode_image(img)
        return payload in vals if vals else False
    except Exception:
        return None


def scan_score(img, payload):
    """Stress-test a code like a real phone would see it. Returns (passed, total, labels) or None."""
    if not (HAS_CV2 and HAS_NP):
        return None
    rgb = _flatten(img)
    tests = [
        ("Sharp", lambda im: im),
        ("Small on screen", lambda im: im.resize((max(90, im.width // 4),) * 2)),
        ("Blurry camera", lambda im: im.filter(ImageFilter.GaussianBlur(max(1.5, im.width / 260)))),
        ("Tilted 12°", lambda im: im.rotate(12, expand=True, fillcolor=(255, 255, 255))),
        ("Dim light", lambda im: ImageEnhance.Brightness(ImageEnhance.Contrast(im).enhance(0.55)).enhance(0.7)),
    ]
    import cv2
    det = cv2.QRCodeDetector()
    labels, passed = [], 0
    for name, fn in tests:
        try:
            im = fn(rgb.copy())
            arr = np.array(im)[:, :, ::-1].copy()
            v, _, _ = det.detectAndDecode(arr)
            if not v:
                for d2 in _detectors()[:1]:
                    v, _, _ = d2.detectAndDecode(arr)
            ok = v == payload
        except Exception:
            ok = False
        passed += ok
        labels.append((name, ok))
    return passed, len(tests), labels


# ---------------------------------------------------------------------------
# Batch from CSV
# ---------------------------------------------------------------------------


def read_csv_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(f, dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return [], []
    header = rows[0]
    has_header = csv.Sniffer().has_header(sample) if len(rows) > 1 else False
    if not has_header:
        header = [f"Column {i + 1}" for i in range(len(rows[0]))]
        return header, rows
    return header, rows[1:]


def batch_render(rows, content_col, name_col, caption_col, spec, out_dir, size=1024, progress=lambda i, n: None):
    os.makedirs(out_dir, exist_ok=True)
    used, written = set(), []
    for i, row in enumerate(rows):
        progress(i, len(rows))
        content = row[content_col].strip() if content_col < len(row) else ""
        if not content:
            continue
        s = dict(spec, payload=content)
        if caption_col is not None and caption_col < len(row):
            s["caption"] = row[caption_col].strip()
        name = safe_name(row[name_col] if name_col is not None and name_col < len(row) else "", f"qr_{i + 1:03d}")
        base, k = name, 2
        while name.lower() in used:
            name = f"{base}_{k}"
            k += 1
        used.add(name.lower())
        probe, _ = render_qr(s, box_size=1)
        img, _ = render_qr(s, box_size=max(4, round(size / max(1, probe.width))))
        if img.width != size:
            img = img.resize((size, round(img.height * size / img.width)), Image.Resampling.LANCZOS)
        p = os.path.join(out_dir, name + ".png")
        img.save(p)
        written.append(p)
    progress(len(rows), len(rows))
    return written


def render_qr_sized(spec, size):
    probe, _ = render_qr(spec, box_size=1)
    box = max(4, round(size / max(1, probe.width)))
    img, w = render_qr(spec, box_size=box)
    if img.width != size:
        img = img.resize((size, round(img.height * size / img.width)), Image.Resampling.LANCZOS)
    return img, w


__all__ = ["QR_TYPES", "EC_LEVELS", "QR_DRAWERS", "QR_MASKS", "HAS_QR", "HAS_STYLED_QR", "build_payload",
           "describe_payload", "render_qr", "render_qr_sized", "qr_to_svg", "animated_qr_frames", "save_animation",
           "decode_image", "decode_frame", "verify_qr", "scan_score", "read_csv_rows", "batch_render", "log", "math"]
