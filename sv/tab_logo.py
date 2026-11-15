"""Logo Studio tab: procedural logos, variations, animated intro, brand kit export."""

import os
import random
import threading

from PIL import Image
from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QLabel, QLineEdit, QSizePolicy,
                             QSpinBox, QToolButton, QVBoxLayout, QWidget, QHBoxLayout)

from .core import log
from .exports import export_brand_kit, logo_intro_frames
from .graphics import (LOGO_BACKGROUNDS, LOGO_LAYOUTS, LOGO_STYLES, PALETTES, PREFERRED_FONTS,
                       random_logo_spec, render_logo, rgb_to_hex)
from .qrtools import save_animation
from .widgets import ColorButton, GlowButton, ImagePreview, card, hbox, hint, labeled_slider, pil_to_qpixmap, scroll_wrap


class LogoMixin:
    def _build_logo_tab(self):
        self.logo_timer = QTimer(self)
        self.logo_timer.setSingleShot(True)
        self.logo_timer.timeout.connect(self.generate_logo)
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(12)

        controls = QWidget()
        cl_root = QVBoxLayout(controls)
        cl_root.setContentsMargins(0, 0, 4, 0)
        cl_root.setSpacing(12)

        c, cl = card("Brand")
        self.logo_brand = QLineEdit("Studio Vision")
        self.logo_brand.setPlaceholderText("Brand name")
        self.logo_tagline = QLineEdit("AI Media Lab")
        self.logo_tagline.setPlaceholderText("Tagline (optional)")
        self.logo_mono = QLineEdit()
        self.logo_mono.setPlaceholderText("Monogram letters (auto from brand if empty)")
        self.logo_mono.setMaxLength(3)
        for e in (self.logo_brand, self.logo_tagline, self.logo_mono):
            cl.addWidget(e)
            e.textChanged.connect(self._schedule_logo)
        cl_root.addWidget(c)

        c, cl = card("Design")
        grid = QGridLayout()
        self.logo_style = QComboBox()
        self.logo_style.addItems(LOGO_STYLES)
        self.logo_layout = QComboBox()
        self.logo_layout.addItems(LOGO_LAYOUTS)
        self.logo_bg = QComboBox()
        self.logo_bg.addItems(LOGO_BACKGROUNDS)
        self.logo_palette = QComboBox()
        self.logo_palette.addItem("Custom colours")
        self.logo_palette.addItems(list(PALETTES))
        self.logo_font = QComboBox()
        self.logo_font.addItem("Default font", None)
        self.logo_font.setMaxVisibleItems(20)
        for i, (label, wdg) in enumerate([("Icon style", self.logo_style), ("Layout", self.logo_layout),
                                          ("Background", self.logo_bg), ("Palette", self.logo_palette),
                                          ("Font", self.logo_font)]):
            grid.addWidget(QLabel(label), i, 0)
            grid.addWidget(wdg, i, 1)
        grid.setColumnStretch(1, 1)
        cl.addLayout(grid)
        crow = QHBoxLayout()
        self.logo_p = ColorButton("Primary", "#6366F1")
        self.logo_s = ColorButton("Secondary", "#EC4899")
        self.logo_a = ColorButton("Accent", "#22D3EE")
        for b in (self.logo_p, self.logo_s, self.logo_a):
            crow.addWidget(b)
            b.colorChanged.connect(self._on_logo_color_manual)
        cl.addLayout(crow)
        frow = QHBoxLayout()
        self.logo_text_grad = QCheckBox("Gradient text")
        self.logo_text_grad.setChecked(True)
        self.logo_glow = QCheckBox("Glow")
        self.logo_glow.setChecked(True)
        self.logo_upper = QCheckBox("UPPERCASE")
        self.logo_upper.setChecked(True)
        for chk in (self.logo_text_grad, self.logo_glow, self.logo_upper):
            frow.addWidget(chk)
            chk.toggled.connect(self._schedule_logo)
        cl.addLayout(frow)
        trow, self.logo_tracking = labeled_slider(0, 30, 6, lambda v: f"{v}")
        cl.addWidget(QLabel("Letter spacing"))
        cl.addLayout(trow)
        self.logo_seed = QSpinBox()
        self.logo_seed.setRange(0, 999_999)
        self.logo_seed.setValue(1234)
        b_seed = GlowButton("🎲", "ghost", None, 30)
        b_seed.setFixedWidth(44)
        b_seed.setToolTip("New random seed — same style, different details")
        b_seed.clicked.connect(lambda: self.logo_seed.setValue(random.randint(0, 999_999)))
        cl.addLayout(hbox(QLabel("Variation seed"), self.logo_seed, b_seed, stretch={1: 1}))
        for wdg in (self.logo_style, self.logo_layout, self.logo_bg, self.logo_font):
            wdg.currentIndexChanged.connect(self._schedule_logo)
        self.logo_palette.currentIndexChanged.connect(self._on_palette_changed)
        self.logo_tracking.valueChanged.connect(self._schedule_logo)
        self.logo_seed.valueChanged.connect(self._schedule_logo)
        cl_root.addWidget(c)

        c, cl = card("Generate")
        b_surprise = GlowButton("🎲 Surprise me", "pink", None, 36)
        b_surprise.clicked.connect(self.surprise_logo)
        b_var = GlowButton("🧩 6 variations", "violet", None, 36)
        b_var.clicked.connect(self.logo_variations)
        cl.addLayout(hbox(b_surprise, b_var))
        self.var_lock_colors = QCheckBox("Keep my colours")
        self.var_lock_style = QCheckBox("Keep icon style")
        cl.addLayout(hbox(self.var_lock_colors, self.var_lock_style, 1))
        cl_root.addWidget(c)

        c, cl = card("🚀 Ship it", "One click gives you every size you'll ever need.")
        b_kit = GlowButton("🧳 Export brand kit…", None, None, 36)
        b_kit.setToolTip("Logos, favicons, app icons, social banners, colour palette, animated intro — one folder")
        b_kit.clicked.connect(self.export_brand_kit)
        b_intro = GlowButton("🎬 Animated intro", "pink", None, 36)
        b_intro.setToolTip("A short logo reveal as GIF / WebP — great for stories & video intros")
        b_intro.clicked.connect(self.export_logo_intro)
        cl.addLayout(hbox(b_kit, b_intro))
        b_card = GlowButton("🪪 Design a business card with this logo", "violet", None, 32)
        b_card.clicked.connect(lambda: (self.tabs.setCurrentWidget(self.card_page), self._schedule_card()))
        cl.addWidget(b_card)
        cl_root.addWidget(c)
        cl_root.addStretch()

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.logo_preview = ImagePreview("Your logo renders here live")
        rl.addWidget(self.logo_preview, 3)
        rl.addWidget(hint("Variations — click one to make it yours"))
        vgrid = QGridLayout()
        vgrid.setSpacing(8)
        self.var_buttons = []
        for i in range(6):
            tb = QToolButton()
            tb.setObjectName("Variation")
            tb.setIconSize(QSize(120, 120))
            tb.setMinimumSize(110, 110)
            tb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            tb.setCursor(Qt.CursorShape.PointingHandCursor)
            tb.clicked.connect(lambda _, k=i: self.apply_variation(k))
            vgrid.addWidget(tb, i // 3, i % 3)
            self.var_buttons.append(tb)
        rl.addLayout(vgrid, 2)
        self.logo_export_size = QComboBox()
        for s in (512, 1024, 2048, 4096):
            self.logo_export_size.addItem(f"{s}px", s)
        self.logo_export_size.setCurrentIndex(1)
        b_save = GlowButton("💾 Save", "warn", None, 36)
        b_save.setToolTip("PNG, ICO, JPG or WebP")
        b_save.clicked.connect(self.save_logo)
        b_copy = GlowButton("📋 Copy", "success", None, 36)
        b_copy.clicked.connect(lambda: self._copy_image(self.logo_image, "Logo"))
        b_to_qr = GlowButton("➡ Put in QR", "pink", None, 36)
        b_to_qr.clicked.connect(self.use_studio_logo_in_qr)
        rl.addLayout(hbox(QLabel("Export"), self.logo_export_size, b_save, b_copy, b_to_qr,
                          stretch={2: 1, 3: 1, 4: 1}))

        sc = scroll_wrap(controls)
        sc.setMinimumWidth(390)
        sc.setMaximumWidth(480)
        outer.addWidget(sc)
        outer.addWidget(right, 1)
        QTimer.singleShot(400, self.generate_logo)
        QTimer.singleShot(900, self.logo_variations)
        return page

    def _bind_logo_settings(self):
        for key, w in (("brand", self.logo_brand), ("tagline", self.logo_tagline), ("mono", self.logo_mono),
                       ("style", self.logo_style), ("layout", self.logo_layout), ("bg", self.logo_bg),
                       ("p", self.logo_p), ("s", self.logo_s), ("a", self.logo_a), ("grad", self.logo_text_grad),
                       ("glow", self.logo_glow), ("upper", self.logo_upper), ("tracking", self.logo_tracking),
                       ("seed", self.logo_seed), ("export", self.logo_export_size),
                       ("lock_colors", self.var_lock_colors), ("lock_style", self.var_lock_style)):
            self.store.bind(w, f"logo/{key}")
        self.logo_font.currentIndexChanged.connect(
            lambda _: self.store.set("logo/font", self.logo_font.currentText()))

    # ------------------------------------------------------------- Logo
    def _on_fonts(self, fonts):
        self.fonts = fonts
        if not hasattr(self, "logo_font") or self.logo_font.count() > 1:
            return  # Logo Studio not built yet (it picks fonts up when built) or already filled
        self.logo_font.blockSignals(True)
        for name, path in fonts.items():
            self.logo_font.addItem(name, path)
        saved = self.store.get("logo/font", "")
        idx = self.logo_font.findText(saved) if saved else -1
        if idx < 0:
            for pref in PREFERRED_FONTS:
                idx = next((i for i in range(self.logo_font.count())
                            if self.logo_font.itemText(i).lower().startswith(pref.lower())), -1)
                if idx >= 0:
                    break
        if idx >= 0:
            self.logo_font.setCurrentIndex(idx)
        self.logo_font.blockSignals(False)
        self._schedule_logo()
        if hasattr(self, "_schedule_card"):
            self._schedule_card()

    def regular_font(self):
        """A non-bold text font for small print (cards)."""
        for pref in ("segoeui", "Inter-Regular", "Poppins-Regular", "Arial", "arial", "DejaVuSans", "Helvetica"):
            for name, path in self.fonts.items():
                if name.lower() == pref.lower():
                    return path
        return self.logo_font.currentData()

    def _schedule_logo(self, *_):
        self.logo_timer.start(180)

    def _on_palette_changed(self, idx):
        name = self.logo_palette.currentText()
        if name in PALETTES:
            for key, btn, rgb in zip("psa", (self.logo_p, self.logo_s, self.logo_a), PALETTES[name]):
                btn.set_color(rgb_to_hex(rgb), emit=False)
                self.store.set(f"w/logo/{key}", btn.color())
        self._schedule_logo()

    def _on_logo_color_manual(self, *_):
        self.logo_palette.blockSignals(True)
        self.logo_palette.setCurrentIndex(0)
        self.logo_palette.blockSignals(False)
        self._schedule_logo()

    def _logo_spec(self):
        return {
            "brand": self.logo_brand.text(), "tagline": self.logo_tagline.text(), "mono": self.logo_mono.text(),
            "style": self.logo_style.currentText(), "layout": self.logo_layout.currentText(),
            "background": self.logo_bg.currentText(), "p": self.logo_p.color(), "s": self.logo_s.color(),
            "a": self.logo_a.color(), "font": self.logo_font.currentData(), "seed": self.logo_seed.value(),
            "text_gradient": self.logo_text_grad.isChecked(), "glow": self.logo_glow.isChecked(),
            "uppercase": self.logo_upper.isChecked(), "tracking": self.logo_tracking.value(),
        }

    def _apply_logo_spec(self, spec):
        widgets = [self.logo_style, self.logo_layout, self.logo_bg, self.logo_font, self.logo_palette,
                   self.logo_seed, self.logo_text_grad, self.logo_glow, self.logo_tracking, self.logo_brand,
                   self.logo_tagline, self.logo_mono, self.logo_upper]
        for w in widgets:
            w.blockSignals(True)
        self.logo_style.setCurrentText(spec["style"])
        self.logo_layout.setCurrentText(spec["layout"])
        self.logo_bg.setCurrentText(spec["background"])
        for key, w in (("brand", self.logo_brand), ("tagline", self.logo_tagline), ("mono", self.logo_mono)):
            if key in spec:
                w.setText(spec[key])
        if "uppercase" in spec:
            self.logo_upper.setChecked(spec["uppercase"])
        idx = self.logo_font.findData(spec.get("font"))
        if idx >= 0:
            self.logo_font.setCurrentIndex(idx)
        self.logo_palette.setCurrentIndex(0)
        self.logo_seed.setValue(spec["seed"])
        self.logo_text_grad.setChecked(spec["text_gradient"])
        self.logo_glow.setChecked(spec["glow"])
        self.logo_tracking.setValue(spec["tracking"])
        for btn, key in ((self.logo_p, "p"), (self.logo_s, "s"), (self.logo_a, "a")):
            btn.set_color(spec[key], emit=False)
        for w in widgets:
            w.blockSignals(False)
        # persist what we just applied
        for key, val in (("style", spec["style"]), ("layout", spec["layout"]), ("bg", spec["background"]),
                         ("p", spec["p"]), ("s", spec["s"]), ("a", spec["a"]), ("seed", spec["seed"]),
                         ("grad", spec["text_gradient"]), ("glow", spec["glow"]), ("tracking", spec["tracking"])):
            self.store.set(f"w/logo/{key}", val)
        self.store.set("logo/font", self.logo_font.currentText())
        self.generate_logo()

    def generate_logo(self):
        spec = self._logo_spec()
        self.logo_preview.set_busy(True)
        self._run_bg("logo", lambda: (render_logo(spec, size=640), spec))
        if hasattr(self, "_schedule_card"):
            self._schedule_card()

    def _show_logo_result(self, result):
        img, spec = result
        self.logo_image, self.logo_spec = img, spec
        self.logo_preview.set_busy(False)
        self.logo_preview.set_image(img, "pop")
        self.logo_preview.set_overlay(f"{spec['style']} · seed {spec['seed']}")

    def _show_variations(self, result):
        self.variation_specs = [spec for _, spec in result]
        for btn in self.var_buttons:
            btn.setIcon(QIcon())
        for k, (btn, (img, spec)) in enumerate(zip(self.var_buttons, result)):
            pm = pil_to_qpixmap(img)
            tip = f"{spec['style']} · {spec['background']} · seed {spec['seed']}"
            QTimer.singleShot(k * 85, lambda b=btn, p=pm, t=tip: (b.setIcon(QIcon(p)), b.setToolTip(t)))
        self.set_status("6 fresh variations ready — click one to use it", "ok")

    def surprise_logo(self):
        rng = random.Random()
        spec = random_logo_spec(rng, self._logo_spec(), self.fonts)
        spec["layout"] = rng.choice(["Icon above text", "Icon above text", "Icon beside text"])
        self._apply_logo_spec(spec)
        self.set_status(f"Surprise! {spec['style']} on {spec['background']}", "ok")

    def logo_variations(self):
        base = self._logo_spec()
        rng = random.Random()
        specs = [random_logo_spec(rng, base, self.fonts, self.var_lock_colors.isChecked(),
                                  self.var_lock_style.isChecked()) for _ in range(6)]
        if not self.var_lock_style.isChecked():
            styles = rng.sample(LOGO_STYLES, 6)
            for sp, st in zip(specs, styles):
                sp["style"] = st
        self.set_status("Designing 6 variations…", "info")
        self._run_bg("var", lambda: [(render_logo(sp, size=240), sp) for sp in specs])

    def apply_variation(self, k):
        if k < len(self.variation_specs):
            self._apply_logo_spec(self.variation_specs[k])
            self.set_status(f"Applied variation: {self.variation_specs[k]['style']} — tweak anything you like", "ok")

    def save_logo(self):
        if self.logo_image is None:
            self.set_status("Render a logo first", "warn")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save logo", "logo.png",
                                              "PNG (*.png);;Icon (*.ico);;JPEG (*.jpg);;WebP (*.webp)")
        if not path:
            return
        try:
            spec = self._logo_spec()
            if not os.path.splitext(path)[1]:
                path += ".png"
            if path.lower().endswith(".ico"):
                spec.update({"layout": "Icon only"})
                img = render_logo(spec, size=256)
                img.save(path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
            else:
                img = render_logo(spec, size=self.logo_export_size.currentData())
                if path.lower().endswith((".jpg", ".jpeg")):
                    flat = Image.new("RGB", img.size, (255, 255, 255))
                    flat.paste(img, mask=img.getchannel("A"))
                    img = flat
                img.save(path)
            self.set_status(f"Saved {os.path.basename(path)} ({img.width}×{img.height})", "ok", toast=True)
            self.history.add("logo", spec.get("brand") or "Logo", image=self.logo_image, meta={"spec": spec})
            self._history_changed()
        except Exception as e:
            self.set_status(f"Save failed: {e}", "error")

    def export_logo_intro(self):
        spec = self._logo_spec()
        path, flt = QFileDialog.getSaveFileName(self, "Save animated intro", "logo_intro.gif",
                                                "Animated GIF (*.gif);;Animated WebP (*.webp)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".webp" if "WebP" in flt else ".gif"
        self.set_status("Animating your logo…", "info")

        def work():
            try:
                frames = logo_intro_frames(spec, size=520)
                save_animation(frames, path, 40)
                self.bridge.status.emit(f"Intro saved: {os.path.basename(path)} ({len(frames)} frames)", "ok")
                self.bridge.toast.emit("🎬 Logo intro ready", "ok")
            except Exception as e:
                log.exception("Intro failed")
                self.bridge.status.emit(f"Intro failed: {e}", "error")
        threading.Thread(target=work, daemon=True).start()

    def export_brand_kit(self):
        spec = self._logo_spec()
        folder = QFileDialog.getExistingDirectory(self, "Where should the brand kit go?")
        if not folder:
            return
        self.set_status("Building your brand kit…", "info")

        def work():
            try:
                root, files = export_brand_kit(spec, folder, spec.get("font"),
                                               progress=lambda m: self.bridge.status.emit(f"Brand kit: {m}", "info"))
                self.bridge.done_files.emit(root, files)
            except Exception as e:
                log.exception("Brand kit failed")
                self.bridge.status.emit(f"Brand kit failed: {e}", "error")
        threading.Thread(target=work, daemon=True).start()
        self.history.add("logo", f"Brand kit · {spec.get('brand')}", image=self.logo_image, meta={"spec": spec})
        self._history_changed()
