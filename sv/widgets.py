"""Themes and the animated widget kit: glow buttons, sliding tabs, voice orb, karaoke, toasts, confetti…"""

import math
import random
import time

from PyQt6.QtCore import (QEasingCurve, QEvent, QObject, QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt,
                          QTimer, QVariantAnimation, pyqtSignal)
from PyQt6.QtGui import (QBrush, QColor, QConicalGradient, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter,
                         QPainterPath, QPen, QPixmap, QRadialGradient)
from PyQt6.QtWidgets import (QApplication, QColorDialog, QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSizePolicy,
                             QSlider, QTabBar, QTabWidget, QVBoxLayout, QWidget)

from .core import IS_MAC, IS_WIN, guess_lang
from .graphics import hex_to_rgb, luminance

UI_FONT = "Segoe UI" if IS_WIN else ("Helvetica Neue" if IS_MAC else "DejaVu Sans")

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

THEMES = {
    "Dark": {"bg": "#090D16", "bg2": "#0D1322", "surface": "rgba(21, 28, 44, 0.92)", "surface_solid": "#151C2C",
             "field": "#0F172A", "border": "#1E293B", "border2": "#334155", "text": "#E2E8F0", "strong": "#F8FAFC",
             "muted": "#64748B", "soft": "#94A3B8", "preview": "#0B0F19", "checker": "#1E293B",
             "disabled": "#1E293B", "dark": True},
    "Midnight (AMOLED)": {"bg": "#000000", "bg2": "#05060A", "surface": "rgba(12, 13, 19, 0.96)",
                          "surface_solid": "#0C0D13", "field": "#08090E", "border": "#1A1C26", "border2": "#2A2D3A",
                          "text": "#E5E7EB", "strong": "#FFFFFF", "muted": "#6B7280", "soft": "#9CA3AF",
                          "preview": "#050608", "checker": "#15161D", "disabled": "#15161D", "dark": True},
    "Light": {"bg": "#EEF2F8", "bg2": "#E4EAF4", "surface": "rgba(255, 255, 255, 0.96)", "surface_solid": "#FFFFFF",
              "field": "#F8FAFC", "border": "#D5DCE7", "border2": "#B8C2D3", "text": "#1E293B", "strong": "#0F172A",
              "muted": "#64748B", "soft": "#475569", "preview": "#F1F5F9", "checker": "#E2E8F0",
              "disabled": "#E2E8F0", "dark": False},
}
ACCENTS = {
    "Indigo": ("#6366F1", "#8B5CF6", "#818CF8"),
    "Pink": ("#EC4899", "#F43F5E", "#F472B6"),
    "Emerald": ("#10B981", "#14B8A6", "#34D399"),
    "Amber": ("#F59E0B", "#F97316", "#FBBF24"),
    "Ocean": ("#0EA5E9", "#3B82F6", "#38BDF8"),
    "Violet": ("#8B5CF6", "#D946EF", "#A78BFA"),
}
T = dict(THEMES["Dark"])
T.update({"a1": ACCENTS["Indigo"][0], "a2": ACCENTS["Indigo"][1], "a3": ACCENTS["Indigo"][2]})
MOTION = {"on": True}

STATUS_COLORS = {"ok": "#10B981", "info": None, "warn": "#F59E0B", "error": "#EF4444"}


def set_theme(name="Dark", accent="Indigo"):
    T.clear()
    T.update(THEMES.get(name, THEMES["Dark"]))
    a = ACCENTS.get(accent, ACCENTS["Indigo"])
    T.update({"a1": a[0], "a2": a[1], "a3": a[2], "name": name, "accent": accent})


def stylesheet():
    t = T
    sel_text = "#FFFFFF"
    return f"""
* {{ font-family: '{UI_FONT}'; }}
QMainWindow {{ background-color: {t['bg']}; }}
QScrollArea, QScrollArea > QWidget > QWidget, QStackedWidget, QStackedWidget > QWidget {{ background: transparent; }}
QFrame#Card {{ background-color: {t['surface']}; border: 1px solid {t['border']}; border-radius: 14px; }}
QLabel {{ color: {t['text']}; font-size: 12px; background: transparent; }}
QLabel#CardTitle {{ color: {t['strong']}; font-size: 13px; font-weight: 700; }}
QLabel#Hint {{ color: {t['muted']}; font-size: 11px; }}
QLabel#Big {{ color: {t['strong']}; font-size: 18px; font-weight: 800; }}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {{
    background-color: {t['field']}; border: 1px solid {t['border']}; border-radius: 9px; color: {t['strong']};
    padding: 6px 8px; font-size: 12px; selection-background-color: {t['a1']}; selection-color: {sel_text};
}}
QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QSpinBox:hover {{ border: 1px solid {t['border2']}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {t['a1']}; }}
QTextEdit#Translation {{ background-color: {t['preview']}; color: {t['a3']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {t['surface_solid']}; color: {t['strong']}; selection-background-color: {t['a1']};
    selection-color: {sel_text}; border: 1px solid {t['border']}; outline: 0; }}
QCheckBox, QRadioButton {{ color: {t['text']}; font-size: 12px; spacing: 6px; background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {t['border2']}; background: {t['field']}; }}
QCheckBox::indicator:hover {{ border: 1px solid {t['a1']}; }}
QCheckBox::indicator:checked {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {t['a1']}, stop:1 {t['a2']}); border: 1px solid {t['a3']}; }}
QSlider::groove:horizontal {{ height: 6px; background: {t['border']}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {t['a1']}, stop:1 {t['a2']}); border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {t['strong'] if t['dark'] else '#FFFFFF'}; border: 2px solid {t['a1']}; width: 12px; margin: -6px 0; border-radius: 8px; }}
QTabWidget::pane {{ border: none; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: {t['soft']}; padding: 8px 16px; margin-right: 4px; font-weight: 600; font-size: 12px; border: none; }}
QTabBar::tab:selected {{ color: #FFFFFF; }}
QTabBar::tab:hover:!selected {{ color: {t['strong']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border2']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['a1']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
QScrollBar:horizontal {{ height: 0; }}
QToolButton#Variation {{ background: {t['preview']}; border: 2px solid {t['border']}; border-radius: 12px; }}
QToolButton#Variation:hover {{ border: 2px solid {t['a1']}; }}
QToolTip {{ background: {t['surface_solid']}; color: {t['strong']}; border: 1px solid {t['border2']}; padding: 4px; }}
QListWidget {{ background: {t['field']}; border: 1px solid {t['border']}; border-radius: 10px; color: {t['strong']}; outline: 0; }}
QListWidget::item {{ border-radius: 8px; padding: 4px; }}
QListWidget::item:selected {{ background: {t['a1']}; color: #FFFFFF; }}
QListWidget::item:hover:!selected {{ background: {t['border']}; }}
QProgressBar {{ background: {t['field']}; border: 1px solid {t['border']}; border-radius: 7px; height: 14px; text-align: center; color: {t['strong']}; }}
QProgressBar::chunk {{ border-radius: 6px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {t['a1']}, stop:1 {t['a2']}); }}
QMenu {{ background: {t['surface_solid']}; color: {t['strong']}; border: 1px solid {t['border2']}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['a1']}; color: #FFFFFF; }}
QLabel#BubbleA {{ background: {t['field']}; border: 1px solid {t['border2']}; border-radius: 16px; padding: 10px 14px; color: {t['strong']}; }}
QLabel#BubbleB {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {t['a1']}, stop:1 {t['a2']}); border-radius: 16px; padding: 10px 14px; color: #FFFFFF; }}
QLabel#Badge {{ background: {t['field']}; border: 1px solid {t['border']}; border-radius: 10px; padding: 3px 8px; font-size: 11px; }}
QDialog {{ background: {t['bg2']}; }}
QMessageBox {{ background: {t['bg2']}; }}
"""


def qc(hexstr, alpha=None):
    c = QColor(hexstr)
    if alpha is not None:
        c.setAlpha(int(alpha))
    return c


def accent_grad(x1, y1, x2, y2):
    g = QLinearGradient(x1, y1, x2, y2)
    g.setColorAt(0, QColor(T["a1"]))
    g.setColorAt(1, QColor(T["a2"]))
    return g


class WheelGuard(QObject):
    """Stops the mouse wheel from changing dropdowns, sliders and number boxes you merely scroll past.
    The wheel scrolls the page instead; values only change when you click and choose."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Wheel:
            from PyQt6.QtWidgets import QAbstractScrollArea, QAbstractSpinBox, QComboBox
            if isinstance(obj, (QComboBox, QAbstractSpinBox, QSlider)):
                w = obj.parentWidget()
                while w is not None and not isinstance(w, QAbstractScrollArea):
                    w = w.parentWidget()
                if w is not None:
                    QApplication.sendEvent(w.verticalScrollBar(), ev)
                return True
        return False


def install_wheel_guard(app):
    guard = WheelGuard(app)
    app.installEventFilter(guard)
    app._wheel_guard = guard
    return guard


def pil_to_qpixmap(img):
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimg)


def _ms(ms):
    return ms if MOTION["on"] else 0


def stop_anim(anim):
    """Stop an animation that may already have deleted itself."""
    try:
        if anim is not None:
            anim.stop()
    except RuntimeError:
        pass


def animate(owner, start, end, ms, on_value, curve=QEasingCurve.Type.OutCubic, on_done=None):
    """Fire-and-forget value animation kept alive on its owner."""
    anim = QVariantAnimation(owner)
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.setDuration(max(1, _ms(ms)))
    anim.setEasingCurve(curve)
    anim.valueChanged.connect(on_value)
    if on_done:
        anim.finished.connect(on_done)
    anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim


# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------


class GlowButton(QPushButton):
    """Custom-painted gradient button: hover glow, light sheen sweep and a soft press squish."""

    VARIANTS = {"danger": ("#EF4444", "#F97316"), "success": ("#10B981", "#059669"), "warn": ("#F59E0B", "#F97316"),
                "info": ("#0EA5E9", "#3B82F6"), "violet": ("#8B5CF6", "#6366F1"), "pink": ("#EC4899", "#8B5CF6"),
                "red": ("#EF4444", "#DC2626")}

    def __init__(self, text, color=None, color2=None, height=34, parent=None):
        super().__init__(text, parent)
        self._c1, self._c2 = color, color2
        self._hover = 0.0
        self._press = 0.0
        self._sheen = -1.0
        self._anims = {}
        self.setFixedHeight(height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        f = QFont(UI_FONT, 9)
        f.setWeight(QFont.Weight.DemiBold)
        self.setFont(f)

    def sizeHint(self):
        fm = QFontMetricsF(self.font())
        return QSize(int(fm.horizontalAdvance(self.text()) + 30), self.height())

    def minimumSizeHint(self):
        fm = QFontMetricsF(self.font())
        return QSize(int(min(fm.horizontalAdvance(self.text()) + 20, 90)), self.height())

    def _run(self, key, start, end, ms, setter, curve=QEasingCurve.Type.OutCubic):
        stop_anim(self._anims.get(key))

        def step(v):
            setter(float(v))
            self.update()
        self._anims[key] = animate(self, start, end, ms, step, curve)

    def enterEvent(self, e):
        self._run("hover", self._hover, 1.0, 180, lambda v: setattr(self, "_hover", v))
        if self.isEnabled():
            self._run("sheen", 0.0, 1.0, 650, lambda v: setattr(self, "_sheen", v), QEasingCurve.Type.InOutQuad)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._run("hover", self._hover, 0.0, 260, lambda v: setattr(self, "_hover", v))
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._run("press", self._press, 1.0, 90, lambda v: setattr(self, "_press", v))
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._run("press", self._press, 0.0, 260, lambda v: setattr(self, "_press", v), QEasingCurve.Type.OutBack)
        super().mouseReleaseEvent(e)

    def colors(self):
        if self._c1 == "ghost":
            return None
        if self._c1 in self.VARIANTS:
            return self.VARIANTS[self._c1]
        if self._c1 is None:
            return T["a1"], T["a2"]
        return self._c1, self._c2 or self._c1

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = 1 + self._press * 1.6
        r = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        rad = min(9.0, r.height() / 2)
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        cols = self.colors()
        enabled = self.isEnabled()
        if not enabled:
            p.fillPath(path, QColor(T["disabled"]))
            txt = QColor(T["muted"])
        elif cols is None:
            base = QColor(T["field"])
            hov = QColor(T["border"])
            c = QColor.fromRgbF(base.redF() + (hov.redF() - base.redF()) * self._hover,
                                base.greenF() + (hov.greenF() - base.greenF()) * self._hover,
                                base.blueF() + (hov.blueF() - base.blueF()) * self._hover)
            p.fillPath(path, c)
            pen_c = QColor(T["border2"]) if self._hover < 0.5 else QColor(T["a1"])
            p.setPen(QPen(pen_c, 1))
            p.drawPath(path)
            txt = QColor(T["strong"])
        else:
            c1, c2 = QColor(cols[0]), QColor(cols[1])
            if self._hover:
                c1, c2 = c1.lighter(100 + int(14 * self._hover)), c2.lighter(100 + int(14 * self._hover))
            g = QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.fillPath(path, g)
            hi = QLinearGradient(r.topLeft(), r.bottomLeft())
            hi.setColorAt(0, QColor(255, 255, 255, 46))
            hi.setColorAt(0.5, QColor(255, 255, 255, 0))
            p.fillPath(path, hi)
            p.setPen(QPen(QColor(255, 255, 255, 30 + int(50 * self._hover)), 1))
            p.drawPath(path)
            txt = QColor("#FFFFFF")
        if enabled and 0.0 < self._sheen < 1.0:
            p.save()
            p.setClipPath(path)
            x = r.left() - r.height() + (r.width() + 2 * r.height()) * self._sheen
            sg = QLinearGradient(x - 26, 0, x + 26, 0)
            sg.setColorAt(0, QColor(255, 255, 255, 0))
            sg.setColorAt(0.5, QColor(255, 255, 255, 70 if cols is not None else 30))
            sg.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(r, sg)
            p.restore()
        p.setPen(txt)
        p.setFont(self.font())
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text())


class ColorButton(QPushButton):
    colorChanged = pyqtSignal(str)

    def __init__(self, label, color, parent=None):
        super().__init__(parent)
        self._label, self._color = label, color
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._apply()

    def color(self):
        return self._color

    def set_color(self, value, emit=True):
        self._color = value.upper()
        self._apply()
        if emit:
            self.colorChanged.emit(self._color)

    def _apply(self):
        rgb = hex_to_rgb(self._color)
        txt = "#0F172A" if luminance(rgb) > 0.4 else "#FFFFFF"
        self.setText(f"{self._label}  {self._color}")
        self.setStyleSheet(f"QPushButton {{ background: {self._color}; color: {txt}; border: 2px solid "
                           f"rgba(128,128,128,0.35); border-radius: 9px; font-weight: 600; font-size: 11px; }}"
                           f"QPushButton:hover {{ border: 2px solid {T['a3']}; }}")

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._color), self, f"Pick {self._label}")
        if c.isValid():
            self.set_color(c.name())


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


def card(title=None, subtitle=None):
    frame = QFrame()
    frame.setObjectName("Card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(14, 12, 14, 14)
    lay.setSpacing(8)
    if title:
        t = QLabel(title)
        t.setObjectName("CardTitle")
        lay.addWidget(t)
    if subtitle:
        st = QLabel(subtitle)
        st.setObjectName("Hint")
        st.setWordWrap(True)
        lay.addWidget(st)
    return frame, lay


def hint(text):
    lab = QLabel(text)
    lab.setObjectName("Hint")
    lab.setWordWrap(True)
    return lab


def labeled_slider(minimum, maximum, value, fmt):
    row = QHBoxLayout()
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(minimum, maximum)
    slider.setValue(value)
    val = QLabel(fmt(value))
    val.setMinimumWidth(56)
    val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    slider.valueChanged.connect(lambda v: val.setText(fmt(v)))
    row.addWidget(slider, 1)
    row.addWidget(val)
    return row, slider


def scroll_wrap(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(widget)
    return area


def hbox(*widgets, stretch=None, spacing=8):
    row = QHBoxLayout()
    row.setSpacing(spacing)
    for i, w in enumerate(widgets):
        if isinstance(w, int):
            row.addStretch(w)
        elif hasattr(w, "addWidget") and not isinstance(w, QWidget):
            row.addLayout(w)
        else:
            row.addWidget(w, (stretch or {}).get(i, 0))
    return row


# ---------------------------------------------------------------------------
# Background, header, tabs
# ---------------------------------------------------------------------------


class Backdrop(QWidget):
    """Window background: deep gradient with two soft accent glows. Cached; no timers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Root")
        self._cache = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def invalidate(self):
        self._cache = None
        self.update()

    def resizeEvent(self, e):
        self._cache = None
        super().resizeEvent(e)

    def _render(self):
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor(T["bg"]))
        g.setColorAt(1, QColor(T["bg2"]))
        p.fillRect(0, 0, w, h, g)
        for cx, cy, r, col, a in ((w * 0.92, -h * 0.1, max(w, h) * 0.55, T["a1"], 46 if T["dark"] else 34),
                                  (w * 0.02, h * 1.05, max(w, h) * 0.5, T["a2"], 34 if T["dark"] else 26)):
            rg = QRadialGradient(cx, cy, r)
            rg.setColorAt(0, qc(col, a))
            rg.setColorAt(1, qc(col, 0))
            p.fillRect(0, 0, w, h, rg)
        p.end()
        return pm

    def paintEvent(self, e):
        if self._cache is None or self._cache.size() != self.size() * self.devicePixelRatioF():
            self._cache = self._render()
        p = QPainter(self)
        p.drawPixmap(0, 0, self._cache)


class HeaderBanner(QWidget):
    """Top banner with drifting aurora blobs and a shimmering title."""

    def __init__(self, title, subtitle, parent=None):
        super().__init__(parent)
        self.title, self.subtitle = title, subtitle
        self.setFixedHeight(66)
        self.t0 = time.monotonic()
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 14, 0)
        self.lay.addStretch(1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.set_motion(MOTION["on"])

    def set_motion(self, on):
        if on:
            self.timer.start(40)
        else:
            self.timer.stop()
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 16, 16)
        p.fillPath(path, QColor(T["surface_solid"]))
        t = time.monotonic() - self.t0 if MOTION["on"] else 0
        p.save()
        p.setClipPath(path)
        w, h = r.width(), r.height()
        for i, (col, sp, ph) in enumerate(((T["a1"], 0.13, 0.0), (T["a2"], 0.09, 2.1), (T["a3"], 0.11, 4.2))):
            cx = w * (0.5 + 0.42 * math.sin(t * sp + ph))
            cy = h * (0.5 + 0.6 * math.cos(t * sp * 1.3 + ph))
            rg = QRadialGradient(cx, cy, w * 0.28)
            rg.setColorAt(0, qc(col, 70 if T["dark"] else 55))
            rg.setColorAt(1, qc(col, 0))
            p.fillRect(r, rg)
        p.restore()
        p.setPen(QPen(qc(T["border2"], 140), 1))
        p.drawPath(path)
        # shimmering title
        f = QFont(UI_FONT, 16)
        f.setWeight(QFont.Weight.Black)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5)
        p.setFont(f)
        fm = QFontMetricsF(f)
        tw = fm.horizontalAdvance(self.title)
        x0, y0 = 20, 32
        sweep = (t * 0.35) % 1.6 - 0.3
        g = QLinearGradient(x0, 0, x0 + tw, 0)
        g.setColorAt(0, QColor(T["a3"]))
        g.setColorAt(max(0.0, min(1.0, sweep - 0.12)), QColor(T["a1"]))
        g.setColorAt(max(0.0, min(1.0, sweep)), QColor("#FFFFFF") if T["dark"] else QColor(T["a2"]).lighter(140))
        g.setColorAt(max(0.0, min(1.0, sweep + 0.12)), QColor(T["a2"]))
        g.setColorAt(1, QColor(T["a2"]))
        p.setPen(QPen(QBrush(g), 1))
        p.drawText(QPointF(x0, y0), self.title)
        f2 = QFont(UI_FONT, 9)
        p.setFont(f2)
        p.setPen(QColor(T["soft"]))
        p.drawText(QPointF(x0 + 1, y0 + 20), self.subtitle)


class SlidingTabBar(QTabBar):
    """Tab bar with an accent pill that glides to the selected tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pos = 0.0
        self._anim = None
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.currentChanged.connect(self._glide)

    def _glide(self, idx):
        stop_anim(self._anim)

        def step(v):
            self._pos = float(v)
            self.update()
        self._anim = animate(self, self._pos, idx, 340, step, QEasingCurve.Type.OutBack)

    def _rect_at(self, f):
        n = self.count()
        if n == 0:
            return QRectF()
        i = int(max(0, min(n - 1, math.floor(f))))
        j = min(n - 1, i + 1)
        frac = max(0.0, min(1.0, f - i))
        a, b = QRectF(self.tabRect(i)), QRectF(self.tabRect(j))
        return QRectF(a.x() + (b.x() - a.x()) * frac, a.y(), a.width() + (b.width() - a.width()) * frac, a.height())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # track
        if self.count():
            full = QRectF(self.tabRect(0)).united(QRectF(self.tabRect(self.count() - 1))).adjusted(-3, 2, 1, -2)
            tp = QPainterPath()
            tp.addRoundedRect(full, 11, 11)
            p.fillPath(tp, QColor(T["field"]))
        r = self._rect_at(self._pos).adjusted(2, 4, -2, -4)
        path = QPainterPath()
        path.addRoundedRect(r, 9, 9)
        glow = QRadialGradient(r.center(), r.width() * 0.7)
        glow.setColorAt(0, qc(T["a1"], 70))
        glow.setColorAt(1, qc(T["a1"], 0))
        p.fillRect(r.adjusted(-14, -10, 14, 10), glow)
        p.fillPath(path, accent_grad(r.left(), 0, r.right(), 0))
        p.end()
        super().paintEvent(e)


class AnimatedTabs(QTabWidget):
    """QTabWidget whose pages fade and slide in."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabBar(SlidingTabBar(self))
        self._last = 0
        self.currentChanged.connect(self._animate_page)

    def _animate_page(self, idx):
        page = self.widget(idx)
        direction = 1 if idx >= self._last else -1
        self._last = idx
        if page is None or not MOTION["on"]:
            return
        eff = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(eff)
        eff.setOpacity(0.0)
        base = page.pos()

        def step(v):
            v = float(v)
            try:
                eff.setOpacity(min(1.0, v * 1.15))
                page.move(int(base.x() + (1 - v) * 36 * direction), base.y())
            except RuntimeError:
                pass

        def done():
            try:
                page.setGraphicsEffect(None)
                page.move(base)
            except RuntimeError:
                pass
        animate(page, 0, 1, 320, step, QEasingCurve.Type.OutCubic, done)


# ---------------------------------------------------------------------------
# Image preview with transitions
# ---------------------------------------------------------------------------


class ImagePreview(QWidget):
    dropped = pyqtSignal(str)

    def __init__(self, placeholder, parent=None):
        super().__init__(parent)
        self._pix = None
        self._old = None
        self._placeholder = placeholder
        self._overlay = ""
        self._prog = 1.0
        self._effect = "fade"
        self._anim = None
        self._busy = False
        self._busy_t = 0.0
        self._scaled = {}
        self._drag = False
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAcceptDrops(True)
        self._btimer = QTimer(self)
        self._btimer.timeout.connect(self._busy_tick)

    def _checker(self):
        pm = QPixmap(24, 24)
        pm.fill(QColor(T["preview"]))
        q = QPainter(pm)
        q.fillRect(0, 0, 12, 12, QColor(T["checker"]))
        q.fillRect(12, 12, 12, 12, QColor(T["checker"]))
        q.end()
        return QBrush(pm)

    def set_image(self, pil_img, effect="fade"):
        new = pil_to_qpixmap(pil_img) if pil_img is not None else None
        self._scaled = {}
        if MOTION["on"] and effect and self._pix is not None and new is not None:
            self._old, self._pix, self._effect = self._pix, new, effect
            stop_anim(self._anim)

            def step(v):
                self._prog = float(v)
                self.update()
            ms = {"scan": 620, "pop": 420}.get(effect, 300)
            curve = QEasingCurve.Type.InOutCubic if effect == "scan" else QEasingCurve.Type.OutCubic
            self._prog = 0.0
            self._anim = animate(self, 0, 1, ms, step, curve, lambda: setattr(self, "_old", None))
        elif MOTION["on"] and effect and new is not None:
            self._old, self._pix, self._effect = None, new, "pop"
            self._prog = 0.0
            self._anim = animate(self, 0, 1, 420, lambda v: (setattr(self, "_prog", float(v)), self.update()))
        else:
            self._pix, self._old, self._prog = new, None, 1.0
        self.update()

    def set_overlay(self, text):
        self._overlay = text
        self.update()

    def set_busy(self, on):
        self._busy = on
        if on and MOTION["on"]:
            self._btimer.start(30)
        else:
            self._btimer.stop()
        self.update()

    def _busy_tick(self):
        self._busy_t = (self._busy_t + 0.025) % 1.0
        self.update()

    def _target(self, pix, area):
        pw, ph = pix.width(), pix.height()
        scale = min(area.width() / pw, area.height() / ph)
        w, h = pw * scale, ph * scale
        return QRectF(area.x() + (area.width() - w) / 2, area.y() + (area.height() - h) / 2, w, h)

    def _scaled_pix(self, pix, w, h):
        key = (pix.cacheKey(), int(w), int(h))
        if key not in self._scaled:
            dpr = self.devicePixelRatioF()
            s = pix.scaled(int(w * dpr), int(h * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            s.setDevicePixelRatio(dpr)
            if len(self._scaled) > 6:
                self._scaled.clear()
            self._scaled[key] = s
        return self._scaled[key]

    def _draw(self, p, pix, area, opacity=1.0, scale=1.0):
        target = self._target(pix, area)
        if scale != 1.0:
            c = target.center()
            target = QRectF(c.x() - target.width() * scale / 2, c.y() - target.height() * scale / 2,
                            target.width() * scale, target.height() * scale)
        p.save()
        p.setOpacity(opacity)
        p.fillRect(target, self._checker())
        p.drawPixmap(target.topLeft(), self._scaled_pix(pix, target.width(), target.height()))
        p.restore()
        return target

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        p.fillPath(path, QColor(T["preview"]))
        p.setPen(QPen(QColor(T["a1"]) if self._drag else QColor(T["border"]), 2 if self._drag else 1))
        p.drawPath(path)
        area = rect.adjusted(16, 16, -16, -16)
        if self._pix is None:
            p.setPen(QColor(T["muted"]))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._placeholder)
        else:
            pr = self._prog
            if self._effect == "scan" and self._old is not None and pr < 1:
                tgt = self._draw(p, self._old, area)
                p.save()
                y = tgt.top() + tgt.height() * pr
                p.setClipRect(QRectF(tgt.left(), tgt.top(), tgt.width(), y - tgt.top()))
                self._draw(p, self._pix, area)
                p.restore()
                g = QLinearGradient(0, y - 18, 0, y + 4)
                g.setColorAt(0, qc(T["a1"], 0))
                g.setColorAt(0.8, qc(T["a3"], 170))
                g.setColorAt(1, qc(T["a3"], 0))
                p.fillRect(QRectF(tgt.left() - 6, y - 18, tgt.width() + 12, 22), g)
                p.fillRect(QRectF(tgt.left() - 6, y - 1, tgt.width() + 12, 2), QColor("#FFFFFF"))
            elif self._effect == "pop":
                if self._old is not None and pr < 1:
                    self._draw(p, self._old, area, 1 - pr)
                s = 0.9 + 0.1 * QEasingCurve(QEasingCurve.Type.OutBack).valueForProgress(pr)
                self._draw(p, self._pix, area, min(1.0, pr * 1.6), s)
            else:
                if self._old is not None and pr < 1:
                    self._draw(p, self._old, area, 1 - pr)
                self._draw(p, self._pix, area, pr)
        if self._busy:
            w = rect.width() * 0.28
            x = rect.left() + (rect.width() + w) * self._busy_t - w
            g = QLinearGradient(x, 0, x + w, 0)
            g.setColorAt(0, qc(T["a1"], 0))
            g.setColorAt(0.5, QColor(T["a3"]))
            g.setColorAt(1, qc(T["a2"], 0))
            p.save()
            p.setClipPath(path)
            p.fillRect(QRectF(rect.left(), rect.top(), rect.width(), 3), g)
            p.restore()
        if self._overlay:
            p.setPen(QColor(T["a3"]))
            p.drawText(rect.adjusted(0, 0, 0, -6), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                       self._overlay)

    # drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            self._drag = True
            self.update()
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._drag = False
        self.update()

    def dropEvent(self, e):
        self._drag = False
        self.update()
        for u in e.mimeData().urls():
            if u.isLocalFile():
                self.dropped.emit(u.toLocalFile())
                break


# ---------------------------------------------------------------------------
# Audio visuals
# ---------------------------------------------------------------------------


class Waveform(QWidget):
    """Shows real loudness while playing, mic level while recording, and a calm line when idle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.mode = "idle"
        self.env, self.duration, self.clock = None, 0.0, None
        self.levels = [0.0] * 90
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    def _tick(self):
        if self.mode != "idle":
            self.phase += 0.12
            self.update()

    def play(self, env, duration, clock=None):
        self.env, self.duration, self.clock = env, duration, clock
        self._start = time.monotonic()
        self.mode = "play"

    def busy(self):
        if self.mode == "idle":
            self.mode = "busy"

    def push_level(self, level):
        self.mode = "record"
        self.levels = self.levels[1:] + [min(1.0, level * 6)]

    def stop(self):
        self.mode, self.env = "idle", None
        self.levels = [0.0] * 90
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        mid = h / 2
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, QColor(T["a1"]))
        grad.setColorAt(0.5, QColor(T["a2"]))
        grad.setColorAt(1.0, QColor(T["a3"]))
        if self.mode == "idle":
            p.setPen(QPen(qc(T["border2"], 160), 1))
            p.drawLine(0, int(mid), w, int(mid))
            return
        bars = 90
        bw = w / bars
        values = []
        if self.mode == "record":
            values = self.levels
        elif self.mode == "play" and self.env:
            t = self.clock() if self.clock else time.monotonic() - self._start
            idx = int(t / max(self.duration, 0.01) * len(self.env))
            for i in range(bars):
                j = idx - bars // 2 + i
                values.append(self.env[j] if 0 <= j < len(self.env) else 0.02)
        else:
            for i in range(bars):
                values.append(0.25 + 0.2 * math.sin(i * 0.25 + self.phase) * math.sin(i * 0.07 + self.phase / 3))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        for i, v in enumerate(values):
            bh = max(2.0, v * (h - 6))
            p.drawRoundedRect(QRectF(i * bw + bw * 0.2, mid - bh / 2, bw * 0.6, bh), bw * 0.3, bw * 0.3)
        if self.mode == "play":
            p.setPen(qc(T["strong"], 120))
            p.drawLine(int(w / 2), 4, int(w / 2), h - 4)


class VoiceOrb(QWidget):
    """A living blob that breathes when idle, swirls while thinking and dances with the voice."""
    clicked = pyqtSignal()

    def __init__(self, size=150, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.mode = "idle"
        self.target = 0.0
        self.level = 0.0
        self.t0 = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_mode(self, mode):
        self.mode = mode
        if mode == "idle":
            self.target = 0.0

    def set_level(self, v):
        self.target = max(0.0, min(1.0, float(v)))

    def _tick(self):
        if not self.isVisible():
            return
        self.level += (self.target - self.level) * (0.35 if self.target > self.level else 0.12)
        self.update()

    def mousePressEvent(self, e):
        self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        t = (time.monotonic() - self.t0) if MOTION["on"] else 0.0
        R = min(w, h) * 0.3
        lv = self.level
        if self.mode == "record":
            c1, c2, c3 = QColor("#EF4444"), QColor("#F97316"), QColor("#FCA5A5")
        else:
            c1, c2, c3 = QColor(T["a1"]), QColor(T["a2"]), QColor(T["a3"])
        breath = 0.04 * math.sin(t * 1.6)
        # halo
        halo = QRadialGradient(cx, cy, R * (1.9 + lv * 0.5))
        ha = QColor(c1)
        ha.setAlpha(int(70 + 90 * lv))
        halo.setColorAt(0, ha)
        halo.setColorAt(1, qc(c1.name(), 0))
        p.fillRect(self.rect(), halo)
        # blob
        amp = 0.03 + lv * 0.32 + (0.06 if self.mode == "busy" else 0)
        path = QPainterPath()
        n = 96
        for i in range(n + 1):
            th = 2 * math.pi * i / n
            k = (0.5 * math.sin(3 * th + t * 2.1) + 0.3 * math.sin(5 * th - t * 2.9) + 0.2 * math.sin(7 * th + t * 4.3))
            r = R * (1 + breath + amp * k)
            x, y = cx + r * math.cos(th), cy + r * math.sin(th)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        cg = QConicalGradient(cx, cy, (t * 40) % 360)
        cg.setColorAt(0, c1)
        cg.setColorAt(0.33, c2)
        cg.setColorAt(0.66, c3)
        cg.setColorAt(1, c1)
        p.fillPath(path, cg)
        hl = QRadialGradient(cx - R * 0.35, cy - R * 0.4, R * 1.1)
        hl.setColorAt(0, QColor(255, 255, 255, 120))
        hl.setColorAt(0.5, QColor(255, 255, 255, 18))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(path, hl)
        if self.mode == "busy":
            pen = QPen(QColor(255, 255, 255, 200), 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            rr = R * 1.45
            p.drawArc(QRectF(cx - rr, cy - rr, rr * 2, rr * 2), int(-t * 360 * 16) % (360 * 16), 90 * 16)
        elif self.mode == "record":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 230))
            p.drawEllipse(QPointF(cx, cy), R * 0.22, R * 0.22)


class KaraokeView(QWidget):
    """Shows the spoken text; the current word gets a gliding highlight pill."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.words = []
        self.idx = -1
        self.rects = []
        self.rtl = False
        self._hl = None
        self._anim = None
        self._scroll = 0.0
        self._scroll_target = 0.0
        self.placeholder = "Words light up here as they're spoken ✨"
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        f = QFont(UI_FONT, 12)
        f.setWeight(QFont.Weight.DemiBold)
        self.setFont(f)

    def set_words(self, words):
        self.words = list(words or [])
        text = " ".join(w[2] for w in self.words)
        self.rtl = guess_lang(text) in ("ur", "ar", "fa")
        self.idx = -1
        self._hl = None
        self._scroll = self._scroll_target = 0.0
        self._layout()
        self.update()

    def resizeEvent(self, e):
        self._layout()
        super().resizeEvent(e)

    def _layout(self):
        fm = QFontMetricsF(self.font())
        lh = fm.height() * 1.65
        space = fm.horizontalAdvance(" ") * 1.2
        maxw = self.width() - 32
        x, y = 0.0, 0.0
        rects = []
        for _, _, word in self.words:
            ww = fm.horizontalAdvance(word) + 12
            if x + ww > maxw and x > 0:
                x, y = 0.0, y + lh
            rects.append(QRectF(x, y, ww, fm.height() + 8))
            x += ww + space
        if self.rtl:
            rects = [QRectF(maxw - r.x() - r.width(), r.y(), r.width(), r.height()) for r in rects]
        self.rects = [r.translated(16, 14) for r in rects]

    def set_time(self, t):
        if not self.words:
            return
        i = -1
        for k, (s, d, _) in enumerate(self.words):
            if s <= t + 0.02:
                i = k
            else:
                break
        if i == self.idx:
            return
        self.idx = i
        if i < 0 or i >= len(self.rects):
            self.update()
            return
        target = self.rects[i]
        start = self._hl or target
        stop_anim(self._anim)

        def step(v):
            v = float(v)
            self._hl = QRectF(start.x() + (target.x() - start.x()) * v, start.y() + (target.y() - start.y()) * v,
                              start.width() + (target.width() - start.width()) * v,
                              start.height() + (target.height() - start.height()) * v)
            self._scroll += (self._scroll_target - self._scroll) * 0.35
            self.update()
        visible_h = self.height() - 28
        if target.bottom() - self._scroll_target > visible_h:
            self._scroll_target = max(0.0, target.top() - 14)
        elif target.top() < self._scroll_target:
            self._scroll_target = max(0.0, target.top() - 14)
        self._anim = animate(self, 0, 1, 150, step)

    def finish(self):
        self.idx = len(self.words)
        self._hl = None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        p.fillPath(path, QColor(T["preview"]))
        p.setPen(QPen(QColor(T["border"]), 1))
        p.drawPath(path)
        if not self.words:
            p.setPen(QColor(T["muted"]))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.placeholder)
            return
        p.setClipPath(path)
        p.translate(0, -self._scroll)
        if self._hl is not None and 0 <= self.idx < len(self.words):
            hp = QPainterPath()
            hp.addRoundedRect(self._hl, 8, 8)
            glow = QRadialGradient(self._hl.center(), self._hl.width())
            glow.setColorAt(0, qc(T["a1"], 90))
            glow.setColorAt(1, qc(T["a1"], 0))
            p.fillRect(self._hl.adjusted(-16, -12, 16, 12), glow)
            p.fillPath(hp, accent_grad(self._hl.left(), 0, self._hl.right(), 0))
        p.setFont(self.font())
        for k, (r, (_, _, word)) in enumerate(zip(self.rects, self.words)):
            if k == self.idx:
                p.setPen(QColor("#FFFFFF"))
            elif k < self.idx:
                p.setPen(QColor(T["strong"]))
            else:
                p.setPen(qc(T["muted"], 230))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, word)


# ---------------------------------------------------------------------------
# Toasts & confetti
# ---------------------------------------------------------------------------


class Toast(QWidget):
    ICONS = {"ok": "✓", "info": "✦", "warn": "!", "error": "✕"}

    def __init__(self, parent, text, kind="info"):
        super().__init__(parent)
        self.text, self.kind = text, kind
        self.opacity = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        f = QFont(UI_FONT, 10)
        f.setWeight(QFont.Weight.DemiBold)
        self.setFont(f)
        fm = QFontMetricsF(f)
        w = min(420, max(220, fm.horizontalAdvance(text) + 76))
        lines = max(1, math.ceil((fm.horizontalAdvance(text) + 1) / (w - 70)))
        self.resize(int(w), int(max(48, 22 + lines * fm.height() + 6)))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def color(self):
        return QColor(STATUS_COLORS.get(self.kind) or T["a1"])

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.opacity)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, QColor(T["surface_solid"]))
        p.setPen(QPen(qc(T["border2"], 200), 1))
        p.drawPath(path)
        c = self.color()
        side = QPainterPath()
        side.addRoundedRect(QRectF(r.left() + 6, r.top() + 8, 4, r.height() - 16), 2, 2)
        p.fillPath(side, c)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QPointF(r.left() + 30, r.center().y()), 11, 11)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(r.left() + 19, r.center().y() - 11, 22, 22), Qt.AlignmentFlag.AlignCenter,
                   self.ICONS.get(self.kind, "✦"))
        p.setPen(QColor(T["strong"]))
        flags = Qt.AlignmentFlag.AlignVCenter.value | Qt.TextFlag.TextWordWrap.value
        p.drawText(r.adjusted(50, 4, -12, -4), flags, self.text)

    def mousePressEvent(self, e):
        self.dismiss()

    def dismiss(self):
        mgr = getattr(self, "manager", None)
        if mgr:
            mgr.dismiss(self)


class ToastManager(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.toasts = []
        host.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self.host and ev.type() == QEvent.Type.Resize:
            self._relayout(animate_it=False)
        return False

    def _slots(self):
        y = self.host.height() - 64
        out = []
        for t in reversed(self.toasts):
            y -= t.height()
            out.append((t, QPoint(self.host.width() - t.width() - 18, y)))
            y -= 8
        return out

    def _relayout(self, animate_it=True):
        for t, pos in self._slots():
            if animate_it and MOTION["on"] and t.isVisible():
                a = QPropertyAnimation(t, b"pos", t)
                a.setDuration(220)
                a.setEndValue(pos)
                a.setEasingCurve(QEasingCurve.Type.OutCubic)
                a.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
            else:
                t.move(pos)

    def show(self, text, kind="info", ms=3200):
        t = Toast(self.host, text, kind)
        t.manager = self
        self.toasts.append(t)
        while len(self.toasts) > 4:
            self.dismiss(self.toasts[0], fast=True)
        slots = dict((id(a), b) for a, b in self._slots())
        end = slots[id(t)]
        t.move(end + QPoint(60, 0))
        t.show()
        t.raise_()

        def step(v):
            v = float(v)
            t.opacity = v
            t.move(int(end.x() + (1 - v) * 60), end.y())
            t.update()
        animate(t, 0, 1, 280, step, QEasingCurve.Type.OutBack)
        self._relayout()
        QTimer.singleShot(ms, lambda: self.dismiss(t))

    def dismiss(self, t, fast=False):
        if t not in self.toasts:
            return
        self.toasts.remove(t)

        def step(v):
            try:
                t.opacity = float(v)
                t.update()
            except RuntimeError:
                pass

        def done():
            try:
                t.deleteLater()
            except RuntimeError:
                pass
        animate(t, t.opacity, 0, 1 if fast else 220, step, on_done=done)
        self._relayout()


class ConfettiOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.parts = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.last = time.monotonic()
        self.hide()
        parent.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    def burst(self, origin=None, count=150):
        if not MOTION["on"]:
            return
        self.setGeometry(self.parent().rect())
        ox, oy = (origin.x(), origin.y()) if origin is not None else (self.width() / 2, self.height() * 0.35)
        cols = [T["a1"], T["a2"], T["a3"], "#FACC15", "#34D399", "#F472B6", "#60A5FA"]
        rng = random.Random()
        for _ in range(count):
            ang = rng.uniform(-math.pi, 0) + rng.uniform(-0.3, 0.3)
            sp = rng.uniform(320, 900)
            self.parts.append([ox, oy, math.cos(ang) * sp, math.sin(ang) * sp - 150, rng.uniform(0, 360),
                               rng.uniform(-540, 540), QColor(rng.choice(cols)), rng.choice((0, 1, 2)),
                               rng.uniform(5, 10), rng.uniform(1.6, 2.6)])
        self.last = time.monotonic()
        self.show()
        self.raise_()
        if not self.timer.isActive():
            self.timer.start(16)

    def _tick(self):
        now = time.monotonic()
        dt = min(0.05, now - self.last)
        self.last = now
        alive = []
        for pt in self.parts:
            pt[2] *= 0.992
            pt[3] += 980 * dt
            pt[0] += pt[2] * dt
            pt[1] += pt[3] * dt
            pt[4] += pt[5] * dt
            pt[9] -= dt
            if pt[9] > 0 and pt[1] < self.height() + 30:
                alive.append(pt)
        self.parts = alive
        if not alive:
            self.timer.stop()
            self.hide()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for x, y, _, _, rot, _, col, shape, size, life in self.parts:
            p.save()
            p.translate(x, y)
            p.rotate(rot)
            c = QColor(col)
            c.setAlphaF(max(0.0, min(1.0, life / 0.6)))
            p.setBrush(c)
            p.setPen(Qt.PenStyle.NoPen)
            if shape == 0:
                p.drawRect(QRectF(-size / 2, -size / 4, size, size / 2))
            elif shape == 1:
                p.drawEllipse(QPointF(0, 0), size / 3, size / 3)
            else:
                p.drawRoundedRect(QRectF(-size / 2, -size / 2, size, size * 0.35), 2, 2)
            p.restore()


# ---------------------------------------------------------------------------
# Command palette (Ctrl+K)
# ---------------------------------------------------------------------------


class CommandPalette(QDialog):
    def __init__(self, parent, actions):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.actions = actions
        self.setModal(True)
        self.resize(560, 420)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        box = QFrame()
        box.setObjectName("Card")
        outer.addWidget(box)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 12, 12, 12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("⌕  Type a command…  (Esc to close)")
        self.search.setMinimumHeight(38)
        self.list = QListWidget()
        lay.addWidget(self.search)
        lay.addWidget(self.list, 1)
        lay.addWidget(hint("↑↓ to move · Enter to run · try 'qr', 'brand kit', 'theme', 'scan'"))
        self.search.textChanged.connect(self._filter)
        self.search.installEventFilter(self)
        self.list.itemActivated.connect(self._run)
        self._filter("")

    @staticmethod
    def _match(query, text):
        q, t = query.lower().replace(" ", ""), text.lower()
        i = 0
        for ch in t:
            if i < len(q) and ch == q[i]:
                i += 1
        return i == len(q)

    def _filter(self, q):
        self.list.clear()
        for title, shortcut, fn in self.actions:
            if not q or self._match(q, title):
                it = QListWidgetItem(f"{title}" + (f"      {shortcut}" if shortcut else ""))
                it.setData(Qt.ItemDataRole.UserRole, fn)
                it.setSizeHint(QSize(0, 34))
                self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, ev):
        if obj is self.search and ev.type() == QEvent.Type.KeyPress:
            k = ev.key()
            if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.list.currentRow() + (1 if k == Qt.Key.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
                return True
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                it = self.list.currentItem()
                if it:
                    self._run(it)
                return True
        return super().eventFilter(obj, ev)

    def _run(self, item):
        fn = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        if fn:
            QTimer.singleShot(60, fn)

    def showEvent(self, e):
        par = self.parent()
        if par:
            g = par.geometry()
            self.move(g.x() + (g.width() - self.width()) // 2, g.y() + int(g.height() * 0.16))
        self.setWindowOpacity(0.0)
        animate(self, 0, 1, 180, lambda v: self.setWindowOpacity(float(v)))
        self.search.setFocus()
        super().showEvent(e)


# ---------------------------------------------------------------------------
# Floating "speaking" pill used by the global quick-speak hotkey
# ---------------------------------------------------------------------------


class SpeakPill(QWidget):
    stop_clicked = pyqtSignal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)
        self.orb = VoiceOrb(56)
        self.label = QLabel("")
        self.label.setStyleSheet(f"color: {T['strong']}; font-weight: 600; font-size: 12px;")
        self.label.setMaximumWidth(260)
        self.btn = GlowButton("⏹", "danger", None, 32)
        self.btn.setFixedWidth(40)
        self.btn.clicked.connect(self.stop_clicked.emit)
        lay.addWidget(self.orb)
        lay.addWidget(self.label, 1)
        lay.addWidget(self.btn)
        self.resize(380, 78)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(path, qc(T["surface_solid"], 245))
        p.setPen(QPen(QColor(T["a1"]), 1.5))
        p.drawPath(path)

    def popup(self, text):
        fm = QFontMetricsF(self.label.font())
        self.label.setText(fm.elidedText(text.replace("\n", " "), Qt.TextElideMode.ElideRight, 250))
        self.label.setStyleSheet(f"color: {T['strong']}; font-weight: 600; font-size: 12px;")
        scr = QApplication.primaryScreen().availableGeometry()
        self.move(scr.right() - self.width() - 24, scr.bottom() - self.height() - 24)
        self.setWindowOpacity(0.0)
        self.show()
        animate(self, 0, 1, 220, lambda v: self.setWindowOpacity(float(v)))

    def fade_out(self):
        if self.isVisible():
            animate(self, self.windowOpacity(), 0, 260, lambda v: self.setWindowOpacity(float(v)),
                    on_done=self.hide)
