"""Card Studio tab: business cards built from your Logo Studio brand + a contact QR code."""

import os

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from .core import log
from .exports import CARD_TEMPLATES, print_sheet, render_card, save_pdf
from .widgets import GlowButton, ImagePreview, card, hbox, hint, scroll_wrap

# (key, label, example) — fields start empty so nobody else's details ship with the app; the example is a hint
CARD_FIELDS = [("name", "Full name", "e.g. Alex Khan"), ("title", "Job title", "e.g. Founder"),
               ("company", "Company", "e.g. Studio Vision"), ("phone", "Phone", "e.g. +1 555 123 4567"),
               ("email", "Email", "e.g. hello@example.com"), ("website", "Website", "e.g. example.com"),
               ("address", "City / address", "e.g. London, UK")]


class CardMixin:
    def _build_card_tab(self):
        self.card_timer = QTimer(self)
        self.card_timer.setSingleShot(True)
        self.card_timer.timeout.connect(self.generate_card)
        self.card_front = self.card_back = None
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(12)

        controls = QWidget()
        cl_root = QVBoxLayout(controls)
        cl_root.setContentsMargins(0, 0, 4, 0)
        cl_root.setSpacing(12)
        c, cl = card("Your details", "The QR on the card saves all of this straight into a phone's contacts.")
        form = QFormLayout()
        self.card_fields = {}
        for key, label, example in CARD_FIELDS:
            e = QLineEdit()
            e.setPlaceholderText(example)
            e.textChanged.connect(self._schedule_card)
            self.card_fields[key] = e
            form.addRow(QLabel(label), e)
        cl.addLayout(form)
        b_fill = GlowButton("⇣ Copy into my QR contact card", "ghost", None, 30)
        b_fill.clicked.connect(self.card_to_qr)
        cl.addWidget(b_fill)
        cl_root.addWidget(c)

        c, cl = card("Look", "Colours, font and logo come from Logo Studio — change them there and the card follows.")
        self.card_template = QComboBox()
        self.card_template.addItems(CARD_TEMPLATES)
        self.card_template.currentIndexChanged.connect(self._schedule_card)
        cl.addLayout(hbox(QLabel("Template"), self.card_template, stretch={1: 1}))
        b_logo = GlowButton("🎨 Edit logo & colours", "violet", None, 32)
        b_logo.clicked.connect(lambda: self.tabs.setCurrentWidget(self.logo_page))
        b_shuffle = GlowButton("🔀 Next template", "pink", None, 32)
        b_shuffle.clicked.connect(lambda: self.card_template.setCurrentIndex(
            (self.card_template.currentIndex() + 1) % self.card_template.count()))
        cl.addLayout(hbox(b_logo, b_shuffle))
        cl_root.addWidget(c)

        c, cl = card("Export", "Cards are 3.5 × 2 in at 300 dpi — print-shop ready.")
        b_png = GlowButton("💾 Front + back PNG", "warn", None, 34)
        b_png.clicked.connect(self.save_card_png)
        b_pdf = GlowButton("📄 PDF (2 pages)", "info", None, 34)
        b_pdf.clicked.connect(self.save_card_pdf)
        cl.addLayout(hbox(b_png, b_pdf))
        b_sheet = GlowButton("🖨️ A4 print sheet — 10 cards with crop marks", None, None, 34)
        b_sheet.clicked.connect(self.save_card_sheet)
        cl.addWidget(b_sheet)
        b_copy = GlowButton("📋 Copy front", "success", None, 30)
        b_copy.clicked.connect(lambda: self._copy_image(self.card_front, "Card"))
        cl.addWidget(b_copy)
        cl_root.addWidget(c)
        cl_root.addStretch()

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(hint("Front"))
        self.card_preview = ImagePreview("Your card renders here")
        rl.addWidget(self.card_preview, 3)
        rl.addWidget(hint("Back"))
        self.card_preview_back = ImagePreview("")
        rl.addWidget(self.card_preview_back, 2)

        sc = scroll_wrap(controls)
        sc.setMinimumWidth(390)
        sc.setMaximumWidth(480)
        outer.addWidget(sc)
        outer.addWidget(right, 1)
        return page

    def _bind_card_settings(self):
        for key, w in self.card_fields.items():
            self.store.bind(w, f"card/{key}")
        self.store.bind(self.card_template, "card/template")

    def _schedule_card(self, *_):
        if hasattr(self, "card_timer"):
            self.card_timer.start(350)

    def _card_info(self):
        info = {k: e.text().strip() for k, e in self.card_fields.items()}
        if not info.get("company"):
            info["company"] = self.logo_brand.text().strip()
        return info

    def generate_card(self):
        info, spec, tpl = self._card_info(), self._logo_spec(), self.card_template.currentText()
        bold, regular = spec.get("font"), self.regular_font()
        self.card_preview.set_busy(True)
        self._run_bg("card", lambda: (render_card(info, spec, tpl, "front", bold, regular),
                                      render_card(info, spec, tpl, "back", bold, regular)))

    def _show_card_result(self, result):
        self.card_front, self.card_back = result
        self.card_preview.set_busy(False)
        self.card_preview.set_image(self.card_front, "pop")
        self.card_preview_back.set_image(self.card_back, "fade")

    def _card_name(self):
        return (self.card_fields["name"].text().strip() or "card").replace(" ", "_")

    def _card_saved(self, path):
        self.set_status(f"Saved {os.path.basename(path)}", "ok", toast=True)
        self.celebrate()
        self.history.add("card", self.card_fields["name"].text() or "Business card", image=self.card_front,
                         meta={"info": self._card_info(), "template": self.card_template.currentText()})
        self._history_changed()

    def save_card_png(self):
        if self.card_front is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save card (front)", f"{self._card_name()}_front.png",
                                              "PNG (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        self.card_front.save(path, dpi=(300, 300))
        back = path[:-4].replace("_front", "") + "_back.png"
        self.card_back.save(back, dpi=(300, 300))
        self._card_saved(path)

    def save_card_pdf(self):
        if self.card_front is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save card PDF", f"{self._card_name()}.pdf", "PDF (*.pdf)")
        if path:
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            try:
                save_pdf([self.card_front, self.card_back], path)
                self._card_saved(path)
            except Exception as e:
                log.exception("Card PDF failed")
                self.set_status(f"PDF failed: {e}", "error")

    def save_card_sheet(self):
        if self.card_front is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save A4 print sheet", f"{self._card_name()}_print_sheet.pdf",
                                              "PDF (*.pdf)")
        if path:
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            save_pdf(print_sheet(self.card_front, self.card_back), path)
            self._card_saved(path)
            self.set_status("Print sheet saved — print at 100% (no scaling), double-sided, flip on long edge", "ok")

    def card_to_qr(self):
        info = self._card_info()
        first, _, last = info["name"].partition(" ")
        f = self.qr_fields
        self.qr_type.setCurrentIndex(6)
        for key, val in (("first", first), ("last", last), ("org", info["company"]), ("title", info["title"]),
                         ("vphone", info["phone"]), ("vemail", info["email"]), ("vurl", info["website"]),
                         ("vaddr", info["address"])):
            f[key].setText(val)
        self.tabs.setCurrentWidget(self.qr_page)
        self.set_status("Contact QR filled from your card details", "ok")
