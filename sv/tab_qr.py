"""QR Studio tab: content types, styles, picture QR, logo/caption, scanner, batch, exports."""

import os
import threading

from PIL import Image
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QImage
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QSpinBox, QStackedWidget, QVBoxLayout,
                             QWidget, QApplication)

from .core import HAS_CV2, HAS_NP, log, temp_path
from .graphics import render_logo
from .qrtools import (EC_LEVELS, HAS_STYLED_QR, QR_DRAWERS, QR_MASKS, QR_TYPES, animated_qr_frames, batch_render,
                      build_payload, decode_frame, decode_image, describe_payload, qr_to_svg, read_csv_rows,
                      render_qr, render_qr_sized, save_animation, scan_score, verify_qr)
from .widgets import (T, ColorButton, GlowButton, ImagePreview, card, hbox, hint, labeled_slider, pil_to_qpixmap,
                      scroll_wrap)


def qimage_to_pil(qimg):
    qimg = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = qimg.constBits()
    ptr.setsize(qimg.sizeInBytes())
    return Image.frombuffer("RGBA", (qimg.width(), qimg.height()), bytes(ptr), "raw", "RGBA",
                            qimg.bytesPerLine(), 1).copy()


class ScanResultDialog(QDialog):
    def __init__(self, parent, texts, on_edit=None):
        super().__init__(parent)
        self.setWindowTitle("QR scan result")
        self.resize(520, 420)
        lay = QVBoxLayout(self)
        for i, text in enumerate(texts[:3]):
            kind, rows, url = describe_payload(text)
            c, cl = card(f"{kind}" + (f"  (code {i + 1})" if len(texts) > 1 else ""))
            form = QFormLayout()
            for k, v in rows:
                lab = QLabel(v or "—")
                lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                lab.setWordWrap(True)
                form.addRow(QLabel(f"{k}:"), lab)
            cl.addLayout(form)
            raw = QPlainTextEdit(text)
            raw.setReadOnly(True)
            raw.setMaximumHeight(90)
            cl.addWidget(raw)
            b_copy = GlowButton("📋 Copy", "success", None, 30)
            b_copy.clicked.connect(lambda _, t=text: (QApplication.clipboard().setText(t), b_copy.setText("✓ Copied")))
            row = [b_copy]
            if url:
                b_open = GlowButton("🔗 Open", "info", None, 30)
                b_open.clicked.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
                row.append(b_open)
            if on_edit:
                b_edit = GlowButton("✨ Restyle as my QR", None, None, 30)
                b_edit.clicked.connect(lambda _, t=text: (on_edit(t), self.accept()))
                row.append(b_edit)
            cl.addLayout(hbox(*row, 1))
            lay.addWidget(c)
        b_close = GlowButton("Close", "ghost", None, 32)
        b_close.clicked.connect(self.accept)
        lay.addWidget(b_close)


class WebcamDialog(QDialog):
    def __init__(self, parent, on_found):
        super().__init__(parent)
        self.setWindowTitle("Scan with webcam")
        self.resize(680, 560)
        self.on_found = on_found
        lay = QVBoxLayout(self)
        self.view = QLabel("Starting camera…")
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setMinimumSize(640, 480)
        self.view.setStyleSheet(f"background: {T['preview']}; border-radius: 12px;")
        lay.addWidget(self.view, 1)
        self.info = hint("Hold a QR code up to the camera")
        lay.addWidget(self.info)
        self.cam_box = QComboBox()
        for i in range(3):
            self.cam_box.addItem(f"Camera {i + 1}", i)
        self.cam_box.currentIndexChanged.connect(self._open)
        b = GlowButton("Close", "ghost", None, 32)
        b.clicked.connect(self.reject)
        lay.addLayout(hbox(QLabel("Device"), self.cam_box, 1, b))
        self.cap = None
        self.frame_n = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        QTimer.singleShot(50, self._open)

    def _open(self, *_):
        import cv2
        if self.cap is not None:
            self.cap.release()
        idx = self.cam_box.currentData() or 0
        self.cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(idx)
        if not self.cap or not self.cap.isOpened():
            self.view.setText("No camera found on this device — try another one, or scan from an image")
            return
        self.timer.start(40)

    def _tick(self):
        import cv2
        ok, frame = self.cap.read()
        if not ok:
            return
        self.frame_n += 1
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
        self.view.setPixmap(pil_to_qpixmap(qimage_to_pil(qimg)).scaled(
            self.view.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if self.frame_n % 3 == 0:
            val = decode_frame(frame)
            if val:
                self.timer.stop()
                self.info.setText("✅ Found one!")
                QTimer.singleShot(150, lambda: (self.accept(), self.on_found([val])))

    def done(self, r):
        self.timer.stop()
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        super().done(r)


class BatchDialog(QDialog):
    def __init__(self, parent, path, spec, on_done):
        super().__init__(parent)
        self.setWindowTitle("Batch QR codes from CSV")
        self.resize(560, 360)
        self.spec, self.on_done, self.parent_win = spec, on_done, parent
        self.header, self.rows = read_csv_rows(path)
        lay = QVBoxLayout(self)
        c, cl = card(f"📑 {os.path.basename(path)} — {len(self.rows)} rows",
                     "Every row becomes a PNG using your current QR style. Pick which column holds the link/text.")
        form = QFormLayout()
        self.content = QComboBox()
        self.name = QComboBox()
        self.caption = QComboBox()
        self.name.addItem("(numbered: qr_001…)", None)
        self.caption.addItem("(no caption / keep current)", None)
        for i, h in enumerate(self.header):
            sample = self.rows[0][i] if self.rows and i < len(self.rows[0]) else ""
            label = f"{h}  —  e.g. {sample[:28]}"
            self.content.addItem(label, i)
            self.name.addItem(label, i)
            self.caption.addItem(label, i)
        self.size = QComboBox()
        for s in (512, 1024, 2048):
            self.size.addItem(f"{s}px", s)
        self.size.setCurrentIndex(1)
        form.addRow("Content column", self.content)
        form.addRow("File name column", self.name)
        form.addRow("Caption column", self.caption)
        form.addRow("Size", self.size)
        cl.addLayout(form)
        self.bar = QProgressBar()
        self.bar.setRange(0, max(1, len(self.rows)))
        cl.addWidget(self.bar)
        lay.addWidget(c)
        self.go = GlowButton("⚡ Choose folder & generate", None, None, 38)
        self.go.clicked.connect(self.run)
        b_cancel = GlowButton("Cancel", "ghost", None, 38)
        b_cancel.clicked.connect(self.reject)
        lay.addLayout(hbox(self.go, b_cancel, stretch={0: 1}))
        self.parent_win.bridge.batch_progress.connect(self._progress)

    def _progress(self, i, n):
        self.bar.setMaximum(max(1, n))
        self.bar.setValue(i)

    def run(self):
        folder = QFileDialog.getExistingDirectory(self, "Save the QR codes into…")
        if not folder:
            return
        out = os.path.join(folder, "QR batch")
        self.go.setEnabled(False)
        args = (self.rows, self.content.currentData(), self.name.currentData(), self.caption.currentData(),
                dict(self.spec), out, self.size.currentData())
        b = self.parent_win.bridge

        def work():
            try:
                files = batch_render(*args, progress=lambda i, n: b.batch_progress.emit(i, n))
                b.done_files.emit(out, files)
            except Exception as e:
                log.exception("Batch failed")
                b.status.emit(f"Batch failed: {e}", "error")
        threading.Thread(target=work, daemon=True).start()
        self.on_done(out)


class QrMixin:
    def _build_qr_tab(self):
        self.qr_timer = QTimer(self)
        self.qr_timer.setSingleShot(True)
        self.qr_timer.timeout.connect(self.generate_qr)
        self.qr_art_path = None
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(12)

        controls = QWidget()
        cl_root = QVBoxLayout(controls)
        cl_root.setContentsMargins(0, 0, 4, 0)
        cl_root.setSpacing(12)

        c, cl = card("Content")
        self.qr_type = QComboBox()
        self.qr_type.addItems([name for name, _ in QR_TYPES])
        cl.addWidget(self.qr_type)
        self.qr_forms = QStackedWidget()
        self.qr_fields = {}
        for _, fields in QR_TYPES:
            self.qr_forms.addWidget(self._qr_form(fields))
        self.qr_type.currentIndexChanged.connect(self._show_qr_form)
        self.qr_type.currentIndexChanged.connect(self._schedule_qr)
        self._show_qr_form(0)
        self.qr_fields["text"].setText("https://example.com")
        cl.addWidget(self.qr_forms)
        cl_root.addWidget(c)

        c, cl = card("Style")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.qr_module = QComboBox()
        self.qr_module.addItems(list(QR_DRAWERS) or ["Square"])
        self.qr_eye = QComboBox()
        self.qr_eye.addItems([k for k in ("Square", "Rounded", "Dots", "Gapped") if k in QR_DRAWERS] or ["Square"])
        self.qr_color_mode = QComboBox()
        self.qr_color_mode.addItems(list(QR_MASKS) or ["Solid"])
        self.qr_ec = QComboBox()
        self.qr_ec.addItems(list(EC_LEVELS))
        self.qr_ec.setCurrentIndex(1)
        self.qr_border = QSpinBox()
        self.qr_border.setRange(1, 10)
        self.qr_border.setValue(3)
        for i, (label, wdg) in enumerate([("Modules", self.qr_module), ("Corner eyes", self.qr_eye),
                                          ("Colouring", self.qr_color_mode), ("Error correction", self.qr_ec),
                                          ("Quiet border", self.qr_border)]):
            grid.addWidget(QLabel(label), i, 0)
            grid.addWidget(wdg, i, 1)
        grid.setColumnStretch(1, 1)
        cl.addLayout(grid)
        self.qr_fg = ColorButton("Code", "#4F46E5")
        self.qr_fg2 = ColorButton("Gradient", "#EC4899")
        self.qr_bg = ColorButton("Background", "#FFFFFF")
        crow = QHBoxLayout()
        for b in (self.qr_fg, self.qr_fg2, self.qr_bg):
            crow.addWidget(b)
            b.colorChanged.connect(self._schedule_qr)
        cl.addLayout(crow)
        prow = QHBoxLayout()
        for name, (f1, f2, bg) in {"Classic": ("#000000", "#000000", "#FFFFFF"),
                                   "Indigo": ("#4F46E5", "#EC4899", "#FFFFFF"),
                                   "Ocean": ("#0369A1", "#14B8A6", "#F0F9FF"),
                                   "Sunset": ("#C2410C", "#DB2777", "#FFF7ED"),
                                   "Forest": ("#166534", "#0F766E", "#F0FDF4")}.items():
            b = GlowButton(name, f1, f2, 26)
            b.clicked.connect(lambda _, a=f1, b_=f2, c_=bg: self._qr_preset(a, b_, c_))
            prow.addWidget(b)
        cl.addLayout(prow)
        for wdg in (self.qr_module, self.qr_eye, self.qr_color_mode, self.qr_ec):
            wdg.currentIndexChanged.connect(self._schedule_qr)
        self.qr_border.valueChanged.connect(self._schedule_qr)
        if not HAS_STYLED_QR:
            cl.addWidget(hint("⚠️ For rounded/dot styles & gradients:  pip install -U \"qrcode[pil]\""))
        cl_root.addWidget(c)

        c, cl = card("🖼️ Picture QR", "Blend a photo into the code — the data rides on tiny dots.")
        b_art = GlowButton("Choose photo…", "violet", None, 30)
        b_art.clicked.connect(self.select_qr_art)
        b_art_clear = GlowButton("✕", "ghost", None, 30)
        b_art_clear.setFixedWidth(40)
        b_art_clear.clicked.connect(self.clear_qr_art)
        cl.addLayout(hbox(b_art, b_art_clear, 1))
        self.qr_art_label = hint("No photo — normal QR")
        cl.addWidget(self.qr_art_label)
        arow, self.qr_art_strength = labeled_slider(25, 85, 60, lambda v: f"{v}%")
        self.qr_art_strength.valueChanged.connect(self._schedule_qr)
        cl.addWidget(QLabel("Photo visibility"))
        cl.addLayout(arow)
        cl_root.addWidget(c)

        c, cl = card("Logo & caption")
        b_logo = GlowButton("🖼️ Choose logo", "violet", None, 30)
        b_logo.clicked.connect(self.select_qr_logo)
        b_use = GlowButton("🎨 Use Logo Studio logo", "pink", None, 30)
        b_use.clicked.connect(self.use_studio_logo_in_qr)
        b_clear = GlowButton("✕", "ghost", None, 30)
        b_clear.setFixedWidth(40)
        b_clear.clicked.connect(self.clear_qr_logo)
        cl.addLayout(hbox(b_logo, b_use, b_clear))
        self.qr_logo_label = hint("No logo attached")
        cl.addWidget(self.qr_logo_label)
        srow, self.qr_logo_size = labeled_slider(10, 30, 22, lambda v: f"{v}%")
        self.qr_logo_size.valueChanged.connect(self._schedule_qr)
        cl.addWidget(QLabel("Logo size"))
        cl.addLayout(srow)
        self.qr_caption = QLineEdit()
        self.qr_caption.setPlaceholderText("Caption under the code (e.g. SCAN ME) — optional")
        self.qr_caption.textChanged.connect(self._schedule_qr)
        cl.addWidget(self.qr_caption)
        cl_root.addWidget(c)

        c, cl = card("🔍 Scan & batch", "Read any QR code, or make hundreds at once from a spreadsheet.")
        b_cam = GlowButton("📷 Webcam", "info", None, 32)
        b_cam.clicked.connect(self.scan_webcam)
        b_cam.setEnabled(HAS_CV2)
        b_img = GlowButton("🖼️ From image", "info", None, 32)
        b_img.clicked.connect(self.scan_file)
        b_clip = GlowButton("📋 Clipboard", "info", None, 32)
        b_clip.clicked.connect(self.scan_clipboard)
        cl.addLayout(hbox(b_cam, b_img, b_clip))
        b_batch = GlowButton("📑 Batch from CSV…", "violet", None, 32)
        b_batch.clicked.connect(self.batch_qr)
        cl.addWidget(b_batch)
        cl.addWidget(hint("Tip: drop a picture of a QR code onto the preview to read it."
                          if HAS_CV2 else "⚠️ Scanning needs:  pip install opencv-python-headless"))
        cl_root.addWidget(c)
        cl_root.addStretch()

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.qr_preview = ImagePreview("Your QR code renders here live")
        self.qr_preview.dropped.connect(self._qr_dropped)
        rl.addWidget(self.qr_preview, 1)
        self.qr_info = QLabel("")
        self.qr_info.setWordWrap(True)
        rl.addWidget(self.qr_info)
        self.qr_score = QLabel("")
        self.qr_score.setWordWrap(True)
        rl.addWidget(self.qr_score)
        self.qr_export_size = QComboBox()
        for s in (512, 1024, 2048, 4096):
            self.qr_export_size.addItem(f"{s}px", s)
        self.qr_export_size.setCurrentIndex(1)
        b_save = GlowButton("💾 Save", "warn", None, 36)
        b_save.setToolTip("PNG, JPG, WebP, SVG (vector) or PDF")
        b_save.clicked.connect(self.save_qr)
        b_gif = GlowButton("🎞 Animated", "pink", None, 36)
        b_gif.setToolTip("Export a looping GIF / WebP with a flowing gradient — still scans on every frame")
        b_gif.clicked.connect(self.save_qr_animation)
        b_copy = GlowButton("📋 Copy", "success", None, 36)
        b_copy.clicked.connect(lambda: self._copy_image(self.qr_image, "QR code"))
        rl.addLayout(hbox(QLabel("Export"), self.qr_export_size, b_save, b_gif, b_copy,
                          stretch={2: 1, 3: 1, 4: 1}))

        sc = scroll_wrap(controls)
        sc.setMinimumWidth(390)
        sc.setMaximumWidth(480)
        outer.addWidget(sc)
        outer.addWidget(right, 1)
        QTimer.singleShot(300, self.generate_qr)
        return page

    def _show_qr_form(self, idx):
        """Stacked pages normally reserve the tallest page's height; size the box to the visible form only."""
        from PyQt6.QtWidgets import QSizePolicy
        for i in range(self.qr_forms.count()):
            pol = QSizePolicy.Policy.Preferred if i == idx else QSizePolicy.Policy.Ignored
            self.qr_forms.widget(i).setSizePolicy(QSizePolicy.Policy.Preferred, pol)
        self.qr_forms.setCurrentIndex(idx)
        self.qr_forms.adjustSize()

    def _qr_form(self, fields):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        for key, placeholder in fields:
            if key == "wifi_sec":
                cb = QComboBox()
                cb.addItems(["WPA", "WEP", "nopass"])
                cb.currentIndexChanged.connect(self._schedule_qr)
                self.qr_fields[key] = cb
                lay.addWidget(cb)
                continue
            if key == "wifi_hidden":
                chk = QCheckBox("Hidden network")
                chk.toggled.connect(self._schedule_qr)
                self.qr_fields[key] = chk
                lay.addWidget(chk)
                continue
            e = QLineEdit()
            e.setPlaceholderText(placeholder)
            e.textChanged.connect(self._schedule_qr)
            self.qr_fields[key] = e
            if key == "wifi_pass":
                e.setEchoMode(QLineEdit.EchoMode.Password)
                show = QCheckBox("Show")
                show.toggled.connect(lambda on, e=e: e.setEchoMode(
                    QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
                lay.addLayout(hbox(e, show, stretch={0: 1}))
                continue
            lay.addWidget(e)
        return w

    def _bind_qr_settings(self):
        for key, w in self.qr_fields.items():
            if key not in ("wifi_pass",):
                self.store.bind(w, f"qr/{key}")
        for key, w in (("type", self.qr_type), ("module", self.qr_module), ("eye", self.qr_eye),
                       ("color", self.qr_color_mode), ("ec", self.qr_ec), ("border", self.qr_border),
                       ("fg", self.qr_fg), ("fg2", self.qr_fg2), ("bg", self.qr_bg), ("logo_size", self.qr_logo_size),
                       ("caption", self.qr_caption), ("art_strength", self.qr_art_strength),
                       ("export", self.qr_export_size)):
            self.store.bind(w, f"qr/{key}")
        self._show_qr_form(self.qr_type.currentIndex())

    # --------------------------------------------------------------- QR
    def _schedule_qr(self, *_):
        self.qr_timer.start(220)

    def _qr_preset(self, fg, fg2, bg):
        # emitting keeps the saved settings in sync; the render timer debounces the three changes
        self.qr_fg.set_color(fg)
        self.qr_fg2.set_color(fg2)
        self.qr_bg.set_color(bg)

    def _qr_values(self):
        out = {}
        for k, w in self.qr_fields.items():
            if isinstance(w, QLineEdit):
                out[k] = w.text()
            elif isinstance(w, QComboBox):
                out[k] = w.currentText()
            elif isinstance(w, QCheckBox):
                out[k] = w.isChecked()
        return out

    def _qr_payload(self):
        return build_payload(self.qr_type.currentIndex(), self._qr_values())

    def _qr_spec(self):
        return {
            "payload": self._qr_payload(), "ec": EC_LEVELS[self.qr_ec.currentText()],
            "border": self.qr_border.value(), "module": self.qr_module.currentText(),
            "eye": self.qr_eye.currentText(), "color_mode": self.qr_color_mode.currentText(),
            "fg": self.qr_fg.color(), "fg2": self.qr_fg2.color(), "bg": self.qr_bg.color(),
            "logo_path": self.qr_logo_path, "logo_ratio": self.qr_logo_size.value() / 100.0,
            "caption": self.qr_caption.text(), "caption_font": self._font_path_for_caption(),
            "art_path": self.qr_art_path, "art_strength": self.qr_art_strength.value() / 100.0,
        }

    def _font_path_for_caption(self):
        return self.logo_font.currentData() if hasattr(self, "logo_font") else None

    def generate_qr(self):
        spec = self._qr_spec()
        if not spec["payload"]:
            self.qr_info.setText("Fill in the content fields to generate a code")
            self.qr_info.setStyleSheet(f"color: {T['soft']};")
            self.qr_score.setText("")
            return
        self.qr_preview.set_busy(True)

        def work():
            img, warnings = render_qr(spec, box_size=10)
            return img, warnings, spec["payload"], scan_score(img, spec["payload"])
        self._run_bg("qr", work)

    def _show_qr_result(self, result):
        img, warnings, payload, score = result
        self.qr_image = img
        self.qr_preview.set_busy(False)
        self.qr_preview.set_image(img, "scan")
        parts = [f"{img.width}×{img.height}px preview · {len(payload)} chars"]
        parts += [f"⚠️ {w}" for w in warnings]
        self.qr_info.setText("\n".join(parts))
        self.qr_info.setStyleSheet("color: %s;" % ("#FBBF24" if warnings else T["soft"]))
        if score is None:
            self.qr_score.setText("Install OpenCV to get a scan-reliability score")
            return
        passed, total, labels = score
        col = "#10B981" if passed == total else "#F59E0B" if passed >= total - 2 else "#EF4444"
        pills = " ".join(
            f"<span style='background:{'#064E3B' if ok else '#7F1D1D'}; color:{'#A7F3D0' if ok else '#FECACA'};"
            f" border-radius:8px; padding:2px 6px;'>&nbsp;{'✓' if ok else '✕'} {name}&nbsp;</span>"
            for name, ok in labels)
        verdict = ("Rock solid — scans everywhere" if passed == total else
                   "Good — may struggle in tough conditions" if passed >= total - 2 else
                   "Risky — raise contrast, use Square modules or shrink the logo")
        self.qr_score.setText(f"<b style='color:{col}'>Scan score {passed}/{total}</b> · {verdict}<br>{pills}")

    def save_qr(self):
        spec = self._qr_spec()
        if not spec["payload"] or self.qr_image is None:
            self.set_status("Create a QR code first", "warn")
            return
        path, flt = QFileDialog.getSaveFileName(self, "Save QR code", "qrcode.png",
                                                "PNG (*.png);;JPEG (*.jpg);;WebP (*.webp);;SVG vector (*.svg);;"
                                                "PDF (*.pdf)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += {"JPEG": ".jpg", "WebP": ".webp", "SVG": ".svg", "PDF": ".pdf"}.get(flt.split(" ")[0], ".png")
        target = self.qr_export_size.currentData()
        try:
            low = path.lower()
            if low.endswith(".svg"):
                if spec.get("art_path"):
                    self.set_status("Picture QR codes can't be vector — saving as PNG instead", "warn")
                    path = os.path.splitext(path)[0] + ".png"
                    low = path.lower()
                else:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(qr_to_svg(spec))
                    self.set_status(f"Saved vector {os.path.basename(path)} — scales to any size", "ok", toast=True)
                    self._qr_history(spec)
                    return
            img, _ = render_qr_sized(spec, target)
            if low.endswith((".jpg", ".jpeg", ".pdf")):
                img = img.convert("RGB")
            if low.endswith(".pdf"):
                img.save(path, "PDF", resolution=300)
            else:
                img.save(path)
            self.set_status(f"Saved {os.path.basename(path)} ({img.width}×{img.height})", "ok", toast=True)
            self._qr_history(spec)
        except Exception as e:
            log.exception("QR save failed")
            self.set_status(f"Save failed: {e}", "error")

    def _qr_history(self, spec):
        if self.qr_image is not None:
            meta = {k: v for k, v in spec.items() if k not in ("logo_path", "art_path", "caption_font")}
            meta["qr_type"] = self.qr_type.currentIndex()
            meta["fields"] = {k: v for k, v in self._qr_values().items() if k != "wifi_pass"}
            title = spec["payload"].replace("\n", " · ")
            self.history.add("qr", title, image=self.qr_image, meta=meta)
            self._history_changed()

    def save_qr_animation(self):
        spec = self._qr_spec()
        if not spec["payload"]:
            self.set_status("Create a QR code first", "warn")
            return
        if spec.get("art_path"):
            spec["art_path"] = None
        path, flt = QFileDialog.getSaveFileName(self, "Save animated QR", "qrcode.gif",
                                                "Animated GIF (*.gif);;Animated WebP (*.webp)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".webp" if "WebP" in flt else ".gif"
        self.set_status("Rendering animation frames…", "info")
        size = min(1024, self.qr_export_size.currentData())

        def work():
            try:
                probe, _ = render_qr(dict(spec, caption=""), box_size=1)
                box = max(4, round(size / max(1, probe.width)))
                frames = animated_qr_frames(spec, 30, box)
                save_animation(frames, path, 60)
                ok = verify_qr(frames[len(frames) // 2], spec["payload"])
                self.bridge.status.emit(f"Saved {os.path.basename(path)} · 30 frames"
                                        + (" · ✅ scans" if ok else ""), "ok")
                self.bridge.toast.emit(f"Animated QR saved: {os.path.basename(path)}", "ok")
            except Exception as e:
                log.exception("Animated QR failed")
                self.bridge.status.emit(f"Animation failed: {e}", "error")
        threading.Thread(target=work, daemon=True).start()

    def select_qr_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose logo", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self._set_qr_logo(path, os.path.basename(path))

    def _set_qr_logo(self, path, label):
        self.qr_logo_path = path
        self.qr_logo_label.setText(f"Attached: {label} — error correction raised to High automatically")
        self._schedule_qr()

    def clear_qr_logo(self):
        self.qr_logo_path = None
        self.qr_logo_label.setText("No logo attached")
        self._schedule_qr()

    def select_qr_art(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Choose photo", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.qr_art_path = path
            self.qr_art_label.setText(f"Photo: {os.path.basename(path)} — always test with your phone")
            self._schedule_qr()

    def clear_qr_art(self):
        self.qr_art_path = None
        self.qr_art_label.setText("No photo — normal QR")
        self._schedule_qr()

    def use_studio_logo_in_qr(self):
        spec = dict(self._logo_spec())
        spec.update({"layout": "Icon only", "background": "Transparent", "glow": False})
        path = temp_path(".png")
        try:
            render_logo(spec, size=512).save(path)
        except Exception as e:
            self.set_status(f"Couldn't render logo: {e}", "error")
            return
        self._set_qr_logo(path, f"Logo Studio ({spec['style']})")
        self.tabs.setCurrentWidget(self.qr_page)

    # ------------------------------------------------------------ scanning
    def _show_scan(self, texts):
        if not texts:
            self.set_status("No QR code found in that image", "warn", toast=True)
            return
        self.history.add("qr", "Scanned: " + texts[0].replace("\n", " · "), meta={"scanned": texts})
        self._history_changed()
        ScanResultDialog(self, texts, on_edit=self._load_payload_into_qr).exec()

    def _scan_pil(self, img):
        try:
            self._show_scan(decode_image(img))
        except Exception as e:
            self.set_status(str(e), "error")

    def scan_file(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Scan a QR code", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            try:
                self._scan_pil(Image.open(path))
            except Exception as e:
                self.set_status(f"Couldn't open image: {e}", "error")

    def scan_clipboard(self):
        img = QApplication.clipboard().image()
        if img.isNull():
            self.set_status("No image on the clipboard — copy a screenshot of a QR code first (Win+Shift+S)", "warn",
                            toast=True)
            return
        self._scan_pil(qimage_to_pil(img))

    def scan_webcam(self):
        if not (HAS_CV2 and HAS_NP):
            self.set_status("Webcam scanning needs:  pip install opencv-python-headless", "warn")
            return
        WebcamDialog(self, self._show_scan).exec()

    def _qr_dropped(self, path):
        if path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")):
            self.scan_file(path)

    def _load_payload_into_qr(self, text):
        up = text.upper()
        f = self.qr_fields
        if up.startswith("WIFI:"):
            _, rows, _ = describe_payload(text)
            vals = dict(rows)
            self.qr_type.setCurrentIndex(1)
            f["ssid"].setText(vals.get("Network", ""))
            f["wifi_pass"].setText(vals.get("Password", ""))
            i = f["wifi_sec"].findText(vals.get("Security", "WPA") or "WPA")
            f["wifi_sec"].setCurrentIndex(max(0, i))
        else:
            self.qr_type.setCurrentIndex(0)
            f["text"].setText(text)
        self.tabs.setCurrentWidget(self.qr_page)
        self._schedule_qr()

    def batch_qr(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a CSV file", "", "CSV (*.csv *.txt)")
        if not path:
            return
        spec = self._qr_spec()
        try:
            dlg = BatchDialog(self, path, spec, lambda out: None)
        except Exception as e:
            self.set_status(f"Couldn't read CSV: {e}", "error")
            return
        if not dlg.rows:
            self.set_status("That CSV looks empty", "warn")
            return
        dlg.exec()

    def _on_done_files(self, folder, files):
        self.set_status(f"✅ {len(files)} files saved in “{os.path.basename(folder)}”", "ok", toast=True)
        self.celebrate()
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
