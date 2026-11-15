"""History tab: everything you've made, searchable, replayable and restorable."""

import datetime as dt
import json
import os
import shutil

from PIL import Image
from PyQt6.QtCore import QSize, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
                             QListWidgetItem, QMessageBox, QWidget)

from .core import HISTORY_DIR
from .history import KIND_LABEL
from .widgets import GlowButton, ImagePreview, card, hbox, hint


class HistoryMixin:
    def _build_history_tab(self):
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(12)

        c, cl = card()
        self.h_kind = QComboBox()
        self.h_kind.addItem("Everything", None)
        for k, label in KIND_LABEL.items():
            self.h_kind.addItem(label, k)
        self.h_kind.currentIndexChanged.connect(self._refresh_history)
        self.h_search = QLineEdit()
        self.h_search.setPlaceholderText("🔍 Search your history…")
        self.h_search.textChanged.connect(self._refresh_history)
        b_folder = GlowButton("📂 Folder", "ghost", None, 30)
        b_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(HISTORY_DIR)))
        b_clear = GlowButton("🧹 Clear all", "red", None, 30)
        b_clear.clicked.connect(self._clear_history)
        cl.addLayout(hbox(self.h_kind, self.h_search, b_folder, b_clear, stretch={1: 1}))
        self.h_list = QListWidget()
        self.h_list.setViewMode(QListView.ViewMode.IconMode)
        self.h_list.setIconSize(QSize(150, 110))
        self.h_list.setGridSize(QSize(176, 168))
        self.h_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.h_list.setMovement(QListView.Movement.Static)
        self.h_list.setWordWrap(True)
        self.h_list.setSpacing(6)
        self.h_list.currentItemChanged.connect(self._on_history_selected)
        self.h_list.itemDoubleClicked.connect(lambda _: self._history_primary())
        cl.addWidget(self.h_list, 1)
        self.h_count = hint("")
        cl.addWidget(self.h_count)
        outer.addWidget(c, 3)

        c, cl = card("Details")
        self.h_preview = ImagePreview("Pick something on the left")
        self.h_preview.setMinimumSize(220, 220)
        cl.addWidget(self.h_preview, 1)
        self.h_title = QLabel("")
        self.h_title.setObjectName("CardTitle")
        self.h_title.setWordWrap(True)
        self.h_meta = hint("")
        cl.addWidget(self.h_title)
        cl.addWidget(self.h_meta)
        self.h_primary = GlowButton("▶ Play", None, None, 36)
        self.h_primary.clicked.connect(self._history_primary)
        self.h_restore = GlowButton("♻️ Restore settings", "violet", None, 34)
        self.h_restore.clicked.connect(self._history_restore)
        self.h_export = GlowButton("💾 Export copy", "warn", None, 34)
        self.h_export.clicked.connect(self._history_export)
        self.h_show = GlowButton("📂 Show file", "ghost", None, 34)
        self.h_show.clicked.connect(self._history_show)
        self.h_delete = GlowButton("🗑 Delete", "red", None, 34)
        self.h_delete.clicked.connect(self._history_delete)
        cl.addWidget(self.h_primary)
        cl.addLayout(hbox(self.h_restore, self.h_export))
        cl.addLayout(hbox(self.h_show, self.h_delete))
        outer.addWidget(c, 2)
        self._history_dirty = True
        self._set_history_buttons(None)
        return page

    def _history_changed(self):
        self._history_dirty = True
        if hasattr(self, "h_list") and self.tabs.currentWidget() is getattr(self, "history_page", None):
            self._refresh_history()

    def _refresh_history(self, *_):
        self._history_dirty = False
        self.h_list.clear()
        entries = self.history.list(self.h_kind.currentData(), self.h_search.text())
        for e in entries[:300]:
            when = dt.datetime.fromtimestamp(e["created"]).strftime("%d %b, %H:%M")
            title = e["title"] if len(e["title"]) < 46 else e["title"][:44] + "…"
            it = QListWidgetItem(f"{KIND_LABEL.get(e['kind'], e['kind'])}\n{title}\n{when}")
            th = self.history.path(e, "thumb")
            if th and os.path.exists(th):
                it.setIcon(QIcon(th))
            it.setData(Qt.ItemDataRole.UserRole, e["id"])
            it.setSizeHint(QSize(170, 162))
            self.h_list.addItem(it)
        total = len(self.history.entries)
        self.h_count.setText(f"{len(entries)} of {total} items · stored privately on this PC")

    def _entry(self):
        it = self.h_list.currentItem()
        if not it:
            return None
        eid = it.data(Qt.ItemDataRole.UserRole)
        return next((e for e in self.history.entries if e["id"] == eid), None)

    def _set_history_buttons(self, e):
        kind = e["kind"] if e else None
        self.h_primary.setEnabled(bool(e) and kind in ("audio", "qr", "logo", "card", "interp"))
        self.h_primary.setText({"audio": "▶ Play", "interp": "🔊 Speak again", "qr": "🔍 Open image",
                                "logo": "🔍 Open image", "card": "🔍 Open image"}.get(kind, "▶ Open"))
        self.h_restore.setEnabled(bool(e) and kind in ("qr", "logo", "card", "audio"))
        has_file = bool(e) and bool(self.history.path(e)) and os.path.exists(self.history.path(e) or "")
        self.h_export.setEnabled(has_file)
        self.h_show.setEnabled(has_file)
        self.h_delete.setEnabled(bool(e))

    def _on_history_selected(self, *_):
        e = self._entry()
        self._set_history_buttons(e)
        if not e:
            return
        self.h_title.setText(e["title"])
        when = dt.datetime.fromtimestamp(e["created"]).strftime("%A %d %B %Y, %H:%M")
        meta = e.get("meta", {})
        extra = []
        if e["kind"] == "audio":
            extra.append(f"{meta.get('duration', 0):.1f}s · {meta.get('voice', '')}")
            if meta.get("effect") and meta["effect"] != "None":
                extra.append(f"effect: {meta['effect']}")
        elif e["kind"] == "interp":
            extra.append(f"{meta.get('original', '')} → {meta.get('translated', '')}")
        self.h_meta.setText(" · ".join([when] + extra))
        img_path = self.history.path(e) if e["kind"] in ("qr", "logo", "card") else self.history.path(e, "thumb")
        try:
            self.h_preview.set_image(Image.open(img_path) if img_path and os.path.exists(img_path) else None, "fade")
        except Exception:
            self.h_preview.set_image(None)

    def _history_primary(self):
        e = self._entry()
        if not e:
            return
        p = self.history.path(e)
        if e["kind"] == "audio" and p and os.path.exists(p):
            words = []
            wp = self.history.path(e, "words")
            if wp and os.path.exists(wp):
                with open(wp, encoding="utf-8") as f:
                    words = [tuple(w) for w in json.load(f)]
            self.last_audio, self.last_words = p, words
            self.btn_replay.setEnabled(True)
            self.btn_save_audio.setEnabled(True)
            self.btn_subs.setEnabled(bool(words))
            self.replay()
            self.set_status(f"Playing from history: {e['title'][:60]}", "ok")
        elif e["kind"] == "interp":
            meta = e.get("meta", {})
            self.speak(meta.get("translated", ""), None, quick=True)
        elif p and os.path.exists(p):
            QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def _history_restore(self):
        e = self._entry()
        if not e:
            return
        meta = e.get("meta", {})
        if e["kind"] == "logo" and meta.get("spec"):
            self._apply_logo_spec(meta["spec"])
            self.tabs.setCurrentWidget(self.logo_page)
        elif e["kind"] == "qr" and "fields" in meta:
            self.qr_type.setCurrentIndex(meta.get("qr_type", 0))
            for k, v in meta["fields"].items():
                w = self.qr_fields.get(k)
                if w is None:
                    continue
                if isinstance(v, bool):
                    w.setChecked(v)
                elif hasattr(w, "setText"):
                    w.setText(v)
                else:
                    i = w.findText(v)
                    w.setCurrentIndex(max(0, i))
            for k, w in (("module", self.qr_module), ("eye", self.qr_eye), ("color_mode", self.qr_color_mode)):
                if meta.get(k):
                    w.setCurrentText(meta[k])
            for k, b in (("fg", self.qr_fg), ("fg2", self.qr_fg2), ("bg", self.qr_bg)):
                if meta.get(k):
                    b.set_color(meta[k])
            if meta.get("caption") is not None:
                self.qr_caption.setText(meta["caption"])
            self.tabs.setCurrentWidget(self.qr_page)
        elif e["kind"] == "qr" and meta.get("scanned"):
            self._load_payload_into_qr(meta["scanned"][0])
        elif e["kind"] == "card" and meta.get("info"):
            for k, v in meta["info"].items():
                if k in self.card_fields:
                    self.card_fields[k].setText(v)
            if meta.get("template"):
                self.card_template.setCurrentText(meta["template"])
            self.tabs.setCurrentWidget(self.card_page)
        elif e["kind"] == "audio" and meta.get("text"):
            self.textbox.setPlainText(meta["text"])
            self.tabs.setCurrentWidget(self.voice_page)
        else:
            self.set_status("Nothing to restore for this item", "warn")
            return
        self.set_status("Restored — tweak away", "ok")

    def _history_export(self):
        e = self._entry()
        p = self.history.path(e) if e else None
        if not p or not os.path.exists(p):
            return
        ext = os.path.splitext(p)[1]
        dest, _ = QFileDialog.getSaveFileName(self, "Export copy", f"{e['kind']}_{e['id']}{ext}", f"*{ext}")
        if dest:
            shutil.copy2(p, dest)
            self.set_status(f"Exported {os.path.basename(dest)}", "ok", toast=True)

    def _history_show(self):
        e = self._entry()
        p = self.history.path(e) if e else None
        if p and os.path.exists(p):
            if os.name == "nt":
                import subprocess
                subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(p)))

    def _history_delete(self):
        e = self._entry()
        if e:
            self.history.remove(e["id"])
            self._refresh_history()
            self.h_preview.set_image(None)
            self.h_title.setText("")
            self.h_meta.setText("")
            self._set_history_buttons(None)

    def _clear_history(self):
        if not self.history.entries:
            return
        if QMessageBox.question(self, "Clear history", f"Delete all {len(self.history.entries)} history items? "
                                "Files you exported elsewhere are not touched.") == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self._refresh_history()
