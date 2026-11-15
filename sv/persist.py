"""Remembers every setting between launches (QSettings, stored per user)."""

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QPlainTextEdit, QSlider, QSpinBox, QTextEdit


class Store:
    def __init__(self):
        import os
        org = "StudioVisionAI-SelfTest" if os.environ.get("SV_DATA_DIR") else "StudioVisionAI"
        self.s = QSettings(org, "Studio Vision AI")
        self._restoring = False

    def get(self, key, default=None, kind=None):
        if kind is bool:
            v = self.s.value(key, default)
            if isinstance(v, str):
                return v.lower() in ("1", "true", "yes")
            return bool(v) if v is not None else default
        if kind in (int, float):  # QSettings hands numbers back as text on Windows
            try:
                return kind(self.s.value(key, default))
            except (TypeError, ValueError):
                return default
        v = self.s.value(key, default)
        return v if v is not None else default

    def set(self, key, value):
        if not self._restoring:
            self.s.setValue(key, value)

    def bind(self, widget, key):
        """Restore a widget's saved value, then keep saving it as it changes."""
        k = "w/" + key
        self._restoring = True
        try:
            has = self.s.contains(k)
            if isinstance(widget, QLineEdit):
                if has:
                    widget.setText(str(self.s.value(k, "")))
                widget.textChanged.connect(lambda v: self.set(k, v))
            elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
                if has:
                    widget.setPlainText(str(self.s.value(k, "")))
                widget.textChanged.connect(lambda: self.set(k, widget.toPlainText()))
            elif isinstance(widget, QComboBox):
                if has:
                    i = widget.findText(str(self.s.value(k, "")))
                    if i >= 0:
                        widget.setCurrentIndex(i)
                widget.currentIndexChanged.connect(lambda _: self.set(k, widget.currentText()))
            elif isinstance(widget, QCheckBox):
                if has:
                    widget.setChecked(self.get(k, False, bool))
                widget.toggled.connect(lambda v: self.set(k, bool(v)))
            elif isinstance(widget, (QSlider, QSpinBox)):
                if has:
                    widget.setValue(self.get(k, widget.value(), int))
                widget.valueChanged.connect(lambda v: self.set(k, int(v)))
            elif hasattr(widget, "colorChanged"):
                if has:
                    widget.set_color(str(self.s.value(k)), emit=False)
                widget.colorChanged.connect(lambda v: self.set(k, v))
        finally:
            self._restoring = False
        return widget
