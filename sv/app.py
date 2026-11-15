"""Main window: ties the studios together, plus tray, hotkeys, settings, command palette and drag & drop."""

import os
import sys
import threading
import traceback

from PyQt6.QtCore import QObject, QPoint, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence, QShortcut
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QLabel, QMainWindow,
                             QMenu, QMessageBox, QSystemTrayIcon, QVBoxLayout, QWidget)

from . import APP_NAME, __version__
from .audio import AudioPlayer
from .core import (DATA_DIR, HAS_EDGE, HAS_GTTS, HAS_NP, HAS_PYGAME, HAS_SD, HAS_SF, IS_WIN, get_resource_path,
                   log, total_ram_gb, warm_imports)
from .graphics import discover_fonts, render_logo
from .history import History
from .persist import Store
from .qrtools import HAS_QR
from .speech import ENGINES, SystemTTS, fetch_edge_voices
from .tab_card import CardMixin
from .tab_history import HistoryMixin
from .tab_interp import InterpreterMixin
from .tab_logo import LogoMixin
from .tab_qr import QrMixin
from .tab_voice import VoiceMixin
from .widgets import (ACCENTS, MOTION, STATUS_COLORS, THEMES, AnimatedTabs, Backdrop, CommandPalette,
                      ConfettiOverlay, GlowButton, HeaderBanner, SpeakPill, T, ToastManager, Waveform, card, hint,
                      install_wheel_guard, pil_to_qpixmap, scroll_wrap, set_theme, stylesheet)
from . import winint

INSTANCE_KEY = "StudioVisionAI-single-instance"


class Bridge(QObject):
    """All worker threads talk to the UI only through these signals (Qt widgets aren't thread-safe)."""
    status = pyqtSignal(str, str)
    toast = pyqtSignal(str, str)
    translated = pyqtSignal(str, str, str)
    audio_ready = pyqtSignal(object)
    playback = pyqtSignal(bool)
    envelope = pyqtSignal(object, float)
    level = pyqtSignal(float)
    busy = pyqtSignal(bool)
    edge_voices = pyqtSignal(object)
    sys_voices = pyqtSignal(object)
    profiles_changed = pyqtSignal(str)
    recording = pyqtSignal(bool)
    f5_state = pyqtSignal(str)
    image_ready = pyqtSignal(str, int, object)
    fonts = pyqtSignal(object)
    engines = pyqtSignal(object)
    interp = pyqtSignal(object)
    batch_progress = pyqtSignal(int, int)
    done_files = pyqtSignal(str, object)
    quick_text = pyqtSignal(str, bool)
    preload = pyqtSignal(str, str, str)  # step, state (wait/run/ok/fail/skip), detail
    words_refined = pyqtSignal(str, object)
    repaired = pyqtSignal(bool, str)


def app_icon():
    for name in ("app.ico", "app_logo.png"):
        p = get_resource_path(os.path.join("assets", name))
        if os.path.exists(p):
            return QIcon(p)
    try:
        art = render_logo({"brand": "SV", "style": "App Icon", "layout": "Icon only", "background": "Transparent",
                           "p": "#6366F1", "s": "#EC4899", "a": "#22D3EE", "seed": 7, "mono": "SV",
                           "glow": False}, size=128)
        return QIcon(pil_to_qpixmap(art))
    except Exception:
        return QIcon()


def hbox_form(label, widget):
    from .widgets import hbox
    return hbox(QLabel(label), widget, stretch={1: 1})


class SettingsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Settings")
        self.resize(580, 640)
        outer = QVBoxLayout(self)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 6, 0)
        outer.addWidget(scroll_wrap(body), 1)  # scrolls on small screens; Done stays visible below
        c, cl = card("🎨 Appearance")
        form = QFormLayout()
        self.theme = QComboBox()
        self.theme.addItems(list(THEMES))
        self.theme.setCurrentText(T.get("name", "Dark"))
        self.accent = QComboBox()
        self.accent.addItems(list(ACCENTS))
        self.accent.setCurrentText(T.get("accent", "Indigo"))
        self.motion = QCheckBox("Animations & motion effects")
        self.motion.setChecked(MOTION["on"])
        form.addRow("Theme", self.theme)
        form.addRow("Accent colour", self.accent)
        form.addRow("", self.motion)
        cl.addLayout(form)
        lay.addWidget(c)
        self.theme.currentTextChanged.connect(self._apply_look)
        self.accent.currentTextChanged.connect(self._apply_look)
        self.motion.toggled.connect(self._apply_look)

        c, cl = card("⌨️ Speak anywhere", "Select text in any app (browser, Word, PDF…) and press the hotkey — "
                                          "Studio Vision reads it aloud with your current voice.")
        form = QFormLayout()
        self.hk = QComboBox()
        self.hk.addItems(["Off"] + list(winint.HOTKEYS))
        self.hk.setCurrentText(win.store.get("hotkey/speak", "Ctrl+Alt+S"))
        self.hk2 = QComboBox()
        self.hk2.addItems(list(winint.TRANSLATE_HOTKEYS))
        self.hk2.setCurrentText(win.store.get("hotkey/translate", "Ctrl+Alt+T"))
        form.addRow("Read selection", self.hk)
        form.addRow("Translate & read", self.hk2)
        cl.addLayout(form)
        cl.addWidget(hint("“Translate & read” speaks the selection in the Voice Studio target language."))
        self.pill = QCheckBox("Show a floating mini-player while speaking")
        self.pill.setChecked(win.store.get("ui/pill", True, bool))
        cl.addWidget(self.pill)
        lay.addWidget(c)

        c, cl = card("⚡ Speed")
        self.preload = QCheckBox("Get everything ready when the app opens (loads cloning + recognition models, "
                                 "downloads them once)")
        self.preload.setChecked(win.store.get("ui/preload", True, bool))
        cl.addWidget(self.preload)
        ram = total_ram_gb()
        cl.addWidget(hint(f"Uses ~2–3 GB of memory while the AI models are loaded (this PC has {ram:.0f} GB"
                          f"{' — plenty' if ram >= 12 else ' — the cloning model waits until you use it'})."))
        lay.addWidget(c)

        c, cl = card("🛠️ Repair", "Microsoft sometimes changes how its free voice server works. If Edge voices stop "
                                  "working, this updates the voice library — no reinstall needed.")
        self.b_repair = GlowButton("🔧 Repair voice engine", "info", None, 32)
        self.b_repair.clicked.connect(self._repair)
        cl.addWidget(self.b_repair)
        lay.addWidget(c)

        c, cl = card("🪟 Windows")
        self.tray = QCheckBox("Keep running in the tray when I close the window (hotkeys keep working)")
        self.tray.setChecked(win.store.get("ui/close_to_tray", True, bool))
        self.startup = QComboBox()
        self.startup.addItems(["Don't start with Windows", "Start with Windows — open the window",
                               "Start with Windows — quietly in the tray"])
        self.startup.setCurrentIndex({None: 0, False: 1, True: 2}[winint.startup_mode()])
        self.show_hk = QComboBox()
        self.show_hk.addItems(list(winint.SHOW_HOTKEYS))
        self.show_hk.setCurrentText(win.store.get("hotkey/show", "Ctrl+Alt+V"))
        cl.addWidget(self.tray)
        cl.addWidget(self.startup)
        cl.addLayout(hbox_form("Bring the app up from anywhere", self.show_hk))
        b_data = GlowButton("📂 Open data folder (history, voice profiles, logs)", "ghost", None, 30)
        b_data.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(DATA_DIR)))
        cl.addWidget(b_data)
        lay.addWidget(c)
        lay.addStretch(1)
        b_ok = GlowButton("Done", None, None, 36)
        b_ok.clicked.connect(self.accept)
        outer.addWidget(b_ok)

    def _repair(self):
        self.b_repair.setEnabled(False)
        self.b_repair.setText("⏳ Updating…")
        b = self.win.bridge

        def work():
            try:
                b.repaired.emit(True, "Voice engine repaired: " + ENGINES.repair_voice_engine(
                    lambda m: b.status.emit(m, "info")))
            except Exception as e:
                b.repaired.emit(False, f"Repair failed: {e}")
        threading.Thread(target=work, daemon=True).start()

    def _apply_look(self, *_):
        self.win.apply_theme(self.theme.currentText(), self.accent.currentText(), self.motion.isChecked())

    def accept(self):
        s = self.win.store
        s.set("hotkey/speak", self.hk.currentText())
        s.set("hotkey/translate", self.hk2.currentText())
        s.set("ui/pill", self.pill.isChecked())
        s.set("ui/close_to_tray", self.tray.isChecked())
        s.set("hotkey/show", self.show_hk.currentText())
        was = s.get("ui/preload", True, bool)
        s.set("ui/preload", self.preload.isChecked())
        if self.preload.isChecked() and not was:
            self.win.start_preload()
        try:
            mode = [None, False, True][self.startup.currentIndex()]
            if mode != winint.startup_mode():
                winint.set_startup(mode is not None, tray=bool(mode))
        except Exception as e:
            self.win.set_status(f"Couldn't change start-up setting: {e}", "error")
        self.win.register_hotkeys()
        super().accept()


class StudioWindow(VoiceMixin, InterpreterMixin, QrMixin, LogoMixin, CardMixin, HistoryMixin, QMainWindow):
    def __init__(self, start_hidden=False):
        super().__init__()
        self.store = Store()
        set_theme(self.store.get("ui/theme", "Dark"), self.store.get("ui/accent", "Indigo"))
        MOTION["on"] = self.store.get("ui/motion", True, bool)
        self.bridge = Bridge()
        self.player = AudioPlayer()
        self.history = History()
        from .core import STATIC_EDGE_VOICES
        self.edge_voice_list = [{"name": n, "locale": "-".join(n.split("-")[:2]), "gender": g}
                                for n, g in STATIC_EDGE_VOICES]
        self.system_voices = []
        self.fonts = {}
        self.last_audio = None
        self.is_busy = False
        self.is_recording = False
        self._trans_cache = None
        self._gen = {"qr": 0, "logo": 0, "var": 0, "card": 0}
        self.qr_image = None
        self.qr_logo_path = None
        self.logo_image = None
        self.logo_spec = None
        self.variation_specs = []
        self._hotkeys_ok = {}
        self._really_quit = False
        self._tray_hint_shown = self.store.get("ui/tray_hint_shown", False, bool)

        b = self.bridge
        b.status.connect(self.set_status)
        b.toast.connect(lambda t, k: self.toasts.show(t, k))
        b.translated.connect(self._on_translated)
        b.audio_ready.connect(self._on_audio_ready)
        b.playback.connect(self._on_playback)
        b.envelope.connect(lambda env, dur: self.waveform.play(env, dur, self.player.position) if env
                           else self.waveform.busy())
        b.level.connect(self._on_level)
        b.busy.connect(self._on_busy)
        b.edge_voices.connect(self._on_edge_voices)
        b.sys_voices.connect(self._on_sys_voices)
        b.profiles_changed.connect(self.refresh_profiles)
        b.recording.connect(self._on_recording_state)
        b.f5_state.connect(lambda t: self.f5_state_label.setText(t))
        b.image_ready.connect(self._on_image_ready)
        b.fonts.connect(self._on_fonts)
        b.engines.connect(self._on_engines)
        b.interp.connect(self._on_interp)
        b.done_files.connect(self._on_done_files)
        b.quick_text.connect(self._quick_speak)
        b.preload.connect(self._on_preload)
        b.words_refined.connect(self._on_words_refined)
        b.repaired.connect(lambda ok, msg: self.set_status(msg, "ok" if ok else "error", toast=True))
        self.preload_state = {}

        self._build_ui()
        self._bind_settings()
        self._setup_shortcuts()
        self._setup_tray()
        self.pill = SpeakPill()
        self.pill.stop_clicked.connect(self.stop_audio)

        threading.Thread(target=lambda: b.edge_voices.emit(fetch_edge_voices()), daemon=True).start()
        threading.Thread(target=lambda: b.sys_voices.emit(SystemTTS.list_voices()), daemon=True).start()
        threading.Thread(target=lambda: b.fonts.emit(discover_fonts()), daemon=True).start()
        threading.Thread(target=lambda: b.engines.emit(ENGINES.detect()), daemon=True).start()
        self._report_missing()
        QTimer.singleShot(0, self._build_next_tab)
        QTimer.singleShot(300, self.register_hotkeys)
        geo = self.store.get("ui/geometry")
        if geo is not None:
            try:
                self.restoreGeometry(geo)
            except Exception:
                pass

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.setWindowTitle(f"{APP_NAME} — Voice, QR, Logo & Card Studio")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(900, 660)
        self.resize(1240, 840)
        self.setStyleSheet(stylesheet())
        self.setAcceptDrops(True)

        root = Backdrop()
        self.backdrop = root
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(14, 12, 14, 10)
        main.setSpacing(10)

        self.header = HeaderBanner("STUDIO VISION AI", "Speak · Translate · Interpret · QR · Logos · Cards — "
                                                       "all free, all on your PC")
        hl = self.header.lay
        self.ready_badge = GlowButton("⚡ Engines", "ghost", None, 32)
        self.ready_badge.setToolTip("What's loaded and ready — click for details")
        self.ready_badge.clicked.connect(self.show_readiness)
        hl.addWidget(self.ready_badge)
        b_cmd = GlowButton("⌘ Commands  Ctrl+K", "ghost", None, 32)
        b_cmd.clicked.connect(self.open_palette)
        b_set = GlowButton("⚙ Settings", "ghost", None, 32)
        b_set.clicked.connect(self.open_settings)
        self.btn_max = GlowButton("⤢ Maximize", "ghost", None, 32)
        self.btn_max.clicked.connect(self.toggle_maximize)
        self.btn_full = GlowButton("⛶ Fullscreen", None, None, 32)
        self.btn_full.clicked.connect(self.toggle_fullscreen)
        for w in (b_cmd, b_set, self.btn_max, self.btn_full):
            hl.addWidget(w)
        main.addWidget(self.header)

        self.tabs = AnimatedTabs()
        main.addWidget(self.tabs, 1)
        # Voice Studio is built now; the other studios are built right after the window first paints, so the
        # app appears in about half the time. Each tab gets a holder widget so references stay stable.
        self.voice_page = self._build_voice_tab()
        self.tabs.addTab(self.voice_page, "🎙️  Voice Studio")
        self._pending_tabs = []
        for attr, label, builder, binder in (
                ("interp_page_w", "🌐  Live Interpreter", self._build_interp_tab, self._bind_interp_settings),
                ("qr_page", "✨  QR Studio", self._build_qr_tab, self._bind_qr_settings),
                ("logo_page", "🎨  Logo Studio", self._build_logo_tab, self._bind_logo_settings),
                ("card_page", "🪪  Card Studio", self._build_card_tab, self._bind_card_settings),
                ("history_page", "🕘  History", self._build_history_tab, None)):
            holder = QWidget()
            lay = QVBoxLayout(holder)
            lay.setContentsMargins(0, 0, 0, 0)
            setattr(self, attr, holder)
            self.tabs.addTab(holder, label)
            self._pending_tabs.append((holder, builder, binder))
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.all_built = False

        self.waveform = Waveform()
        main.addWidget(self.waveform)
        self.status_label = QLabel("● Ready")
        self.status_label.setWordWrap(True)
        main.addWidget(self.status_label)
        self.set_status("Ready — press Ctrl+K for every command", "ok")

        self.toasts = ToastManager(root)
        self.confetti = ConfettiOverlay(root)

    def _bind_settings(self):
        s = self.store
        for key, w in (("text", self.textbox), ("target", self.target_lang), ("engine", self.engine),
                       ("rate", self.rate_slider), ("pitch", self.pitch_slider), ("auto", self.auto_voice),
                       ("gender", self.gender), ("tld", self.gtts_tld), ("slow", self.gtts_slow),
                       ("quality", self.f5_quality), ("effect", self.effect), ("bg", self.bg_music),
                       ("bg_vol", self.bg_volume), ("dialogue", self.dialogue)):
            s.bind(w, f"voice/{key}")

    def _bind_interp_settings(self):
        for key, w in (("src", self.src_lang), ("dst", self.dst_lang), ("gender", self.i_gender),
                       ("engine", self.i_engine), ("size", self.i_size), ("speak", self.i_speak),
                       ("convo", self.i_convo), ("auto", self.i_auto)):
            self.store.bind(w, f"interp/{key}")

    def _build_next_tab(self):
        """Build one deferred studio per event-loop turn so the window stays responsive while it fills in."""
        if not self._pending_tabs:
            self.all_built = True
            if self.fonts:
                self._on_fonts(self.fonts)
            self._on_engines(ENGINES.caps())
            tab = self.store.get("ui/tab", 0, int)
            if 0 < tab < self.tabs.count():
                self.tabs.setCurrentIndex(tab)
            if self.store.get("ui/preload", True, bool):
                self.start_preload()
            else:
                threading.Thread(target=warm_imports, daemon=True).start()
            return
        holder, builder, binder = self._pending_tabs.pop(0)
        try:
            holder.layout().addWidget(builder())
            if binder:
                binder()
        except Exception:
            log.exception("Building a tab failed")
            self.set_status("A studio failed to load — see the log in the data folder", "error")
        QTimer.singleShot(0, self._build_next_tab)

    def _on_tab_changed(self, idx):
        if self.all_built:
            self.store.set("ui/tab", idx)
        if not self.all_built:
            return
        if self.tabs.widget(idx) is self.history_page and self._history_dirty:
            self._refresh_history()
        if self.tabs.widget(idx) is self.card_page and self.card_front is None:
            self._schedule_card()

    def apply_theme(self, name, accent, motion=True):
        set_theme(name, accent)
        MOTION["on"] = motion
        self.store.set("ui/theme", name)
        self.store.set("ui/accent", accent)
        self.store.set("ui/motion", motion)
        self.setStyleSheet(stylesheet())
        self.backdrop.invalidate()
        self.header.set_motion(motion)
        for name in ("qr_fg", "qr_fg2", "qr_bg", "logo_p", "logo_s", "logo_a"):
            if hasattr(self, name):
                getattr(self, name)._apply()
        self.set_status(self.status_label.text().lstrip("● "), getattr(self, "_status_kind", "ok"))
        for w in self.findChildren(QWidget):
            w.update()

    # ---------------------------------------------------------- shortcuts
    def _setup_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key.Key_F11), self).activated.connect(self.toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self._escape)
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(self.speak)
        QShortcut(QKeySequence("Ctrl+Enter"), self).activated.connect(self.speak)
        QShortcut(QKeySequence.StandardKey.Save, self).activated.connect(self._save_current)
        QShortcut(QKeySequence("Ctrl+K"), self).activated.connect(self.open_palette)
        QShortcut(QKeySequence("Ctrl+,"), self).activated.connect(self.open_settings)
        for i in range(6):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self).activated.connect(
                lambda i=i: self.tabs.setCurrentIndex(i))

    def palette_actions(self):
        go = self.tabs.setCurrentWidget
        return [
            ("⚡ Speak the text", "Ctrl+Enter", self.speak),
            ("⏹ Stop audio", "Esc", self.stop_audio),
            ("💾 Save audio", "", self.save_audio),
            ("💬 Export subtitles (.srt / .vtt)", "", self.export_subtitles),
            ("🎭 Toggle dialogue mode", "", lambda: self.dialogue.setChecked(not self.dialogue.isChecked())),
            ("🌐 Translate the text", "", self.translate_only),
            ("🎙️ Go to Voice Studio", "Ctrl+1", lambda: go(self.voice_page)),
            ("🌐 Live interpreter — start talking", "Ctrl+2", lambda: (go(self.interp_page_w), self.interp_toggle())),
            ("✨ Go to QR Studio", "Ctrl+3", lambda: go(self.qr_page)),
            ("📷 Scan a QR with the webcam", "", self.scan_webcam),
            ("🖼️ Scan a QR from an image", "", self.scan_file),
            ("📋 Scan a QR from the clipboard", "", self.scan_clipboard),
            ("📑 Batch QR codes from CSV", "", self.batch_qr),
            ("🎞 Save animated QR", "", self.save_qr_animation),
            ("💾 Save QR code (PNG / SVG / PDF)", "", self.save_qr),
            ("🎨 Go to Logo Studio", "Ctrl+4", lambda: go(self.logo_page)),
            ("🎲 Surprise me with a logo", "", self.surprise_logo),
            ("🧩 Six logo variations", "", self.logo_variations),
            ("🧳 Export brand kit", "", self.export_brand_kit),
            ("🎬 Animated logo intro", "", self.export_logo_intro),
            ("🪪 Go to Card Studio", "Ctrl+5", lambda: go(self.card_page)),
            ("🖨️ Card print sheet (A4 PDF)", "", self.save_card_sheet),
            ("🕘 History", "Ctrl+6", lambda: go(self.history_page)),
            ("⚙ Settings", "Ctrl+,", self.open_settings),
            ("🌙 Theme: Dark", "", lambda: self.apply_theme("Dark", T.get("accent", "Indigo"), MOTION["on"])),
            ("☀️ Theme: Light", "", lambda: self.apply_theme("Light", T.get("accent", "Indigo"), MOTION["on"])),
            ("🖤 Theme: Midnight (AMOLED)", "", lambda: self.apply_theme("Midnight (AMOLED)",
                                                                       T.get("accent", "Indigo"), MOTION["on"])),
        ] + [(f"🎨 Accent: {a}", "", lambda a=a: self.apply_theme(T.get("name", "Dark"), a, MOTION["on"]))
             for a in ACCENTS] + [
            ("🎉 Celebrate", "", self.celebrate),
            ("⛶ Fullscreen", "F11", self.toggle_fullscreen),
            ("ℹ️ About Studio Vision", "", self.about),
        ]

    def open_palette(self):
        CommandPalette(self, self.palette_actions()).exec()

    def open_settings(self):
        SettingsDialog(self).exec()

    def about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<h3>{APP_NAME} {__version__}</h3><p>Voice, interpreter, QR, logo and business-card "
                          f"studio. Everything runs free — no API keys, no accounts.</p>"
                          f"<p>Data folder:<br><code>{DATA_DIR}</code></p>")

    # ----------------------------------------------------------- tray etc.
    def _setup_tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(f"{APP_NAME} — select text anywhere and press your hotkey")
        menu = QMenu()
        for label, fn in (("Show Studio Vision", self.show_from_tray), ("Read clipboard aloud", self._speak_clipboard),
                          ("Stop speaking", self.stop_audio), (None, None), ("Settings…", self._tray_settings),
                          ("Quit", self.quit_app)):
            if label is None:
                menu.addSeparator()
                continue
            act = QAction(label, menu)
            act.triggered.connect(fn)
            menu.addAction(act)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show_from_tray()
                                    if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray_menu = menu
        self.tray.show()

    def _tray_settings(self):
        self.show_from_tray()
        self.open_settings()

    def show_from_tray(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        self._really_quit = True
        self.close()

    def register_hotkeys(self):
        if not IS_WIN:
            return
        hwnd = int(self.winId())
        speak = self.store.get("hotkey/speak", "Ctrl+Alt+S")
        trans = self.store.get("hotkey/translate", "Ctrl+Alt+T")
        winint.unregister_hotkey(hwnd, winint.HK_SPEAK)
        winint.unregister_hotkey(hwnd, winint.HK_TRANSLATE)
        bad = []
        if speak != "Off" and not winint.register_hotkey(hwnd, winint.HK_SPEAK, winint.HOTKEYS.get(speak)):
            bad.append(speak)
        combo = winint.TRANSLATE_HOTKEYS.get(trans)
        if combo and not winint.register_hotkey(hwnd, winint.HK_TRANSLATE, combo):
            bad.append(trans)
        show = self.store.get("hotkey/show", "Ctrl+Alt+V")
        winint.unregister_hotkey(hwnd, winint.HK_SHOW)
        combo = winint.SHOW_HOTKEYS.get(show)
        if combo and not winint.register_hotkey(hwnd, winint.HK_SHOW, combo):
            bad.append(show)
        self._hotkeys_ok = {"speak": speak != "Off" and speak not in bad, "translate": bool(
            winint.TRANSLATE_HOTKEYS.get(trans)) and trans not in bad, "show": bool(combo) and show not in bad}
        if bad:
            self.set_status(f"Hotkey {', '.join(bad)} is used by another app — pick another in Settings", "warn")

    def nativeEvent(self, event_type, message):
        hk = winint.hotkey_id_from_msg(message) if IS_WIN else None
        if hk == winint.HK_SHOW:
            self.show_from_tray()
            return True, 0
        if hk in (winint.HK_SPEAK, winint.HK_TRANSLATE):
            self._grab_selection(translate=hk == winint.HK_TRANSLATE)
            return True, 0
        # Not super().nativeEvent(): that call crashes PyQt6 6.11 with an access violation.
        return False, 0

    def _grab_selection(self, translate=False, tries=0):
        """Wait for the user to let go of the hotkey, press Ctrl+C in their app, then read the clipboard."""
        if winint.modifiers_down() and tries < 40:
            QTimer.singleShot(25, lambda: self._grab_selection(translate, tries + 1))
            return
        cb = QApplication.clipboard()
        before = cb.text()
        marker = "⁣sv-probe⁣"
        cb.setText(marker)
        winint.send_copy()

        def read(attempt=0):
            txt = cb.text()
            if (txt == marker or not txt) and attempt < 8:
                QTimer.singleShot(40, lambda: read(attempt + 1))
                return
            got = txt if txt and txt != marker else ""
            if before:
                cb.setText(before)
            text = got.strip() or (before or "").strip()
            if not text:
                self.tray.showMessage(APP_NAME, "Select some text first, then press the hotkey",
                                      QSystemTrayIcon.MessageIcon.Information, 2500)
                return
            self._quick_speak(text, translate)
        QTimer.singleShot(90, read)

    def _speak_clipboard(self):
        text = QApplication.clipboard().text().strip()
        if text:
            self._quick_speak(text, False)

    def _quick_speak(self, text, translate=False):
        text = text[:6000]
        lang = self.target_lang.currentData() if translate else None
        if translate and not lang:
            self.set_status("Pick a target language in Voice Studio for “Translate & read”", "warn")
            lang = None
        if self.store.get("ui/pill", True, bool):
            self.pill.popup(("🌐 " if lang else "🔊 ") + text)
            self.pill.orb.set_mode("busy")
        self.stop_audio()
        self.speak(text, lang, quick=True)

    def closeEvent(self, event):
        self.store.set("ui/geometry", self.saveGeometry())
        if not self._really_quit and self.store.get("ui/close_to_tray", True, bool) and self.tray.isVisible():
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                hk = self.store.get("hotkey/speak", "Ctrl+Alt+S")
                self.tray.showMessage(APP_NAME, f"Still here in the tray. Select text anywhere and press {hk} to "
                                                f"hear it. Right-click the tray icon to quit.",
                                      QSystemTrayIcon.MessageIcon.Information, 5000)
                self._tray_hint_shown = True
                self.store.set("ui/tray_hint_shown", True)
            return
        self.is_recording = False
        self.i_listening = False
        self.player.stop()
        ENGINES.shutdown()
        if IS_WIN:
            hwnd = int(self.winId())
            winint.unregister_hotkey(hwnd, winint.HK_SPEAK)
            winint.unregister_hotkey(hwnd, winint.HK_TRANSLATE)
            winint.unregister_hotkey(hwnd, winint.HK_SHOW)
        self.tray.hide()
        self.pill.close()
        super().closeEvent(event)
        QApplication.instance().quit()

    # ----------------------------------------------------- drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasUrls():
            for u in md.urls():
                if not u.isLocalFile():
                    continue
                path = u.toLocalFile()
                low = path.lower()
                if low.endswith((".txt", ".md", ".srt")):
                    self.open_text_file(path)
                elif low.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
                    self._dropped_image(path)
                elif low.endswith((".wav", ".mp3", ".flac", ".ogg")):
                    self.import_profile_audio(path)
                    self.set_status(f"Importing {os.path.basename(path)} as a voice profile…", "info")
                elif low.endswith(".csv"):
                    self.tabs.setCurrentWidget(self.qr_page)
                    from .tab_qr import BatchDialog
                    BatchDialog(self, path, self._qr_spec(), lambda out: None).exec()
                return
        elif md.hasText():
            self.textbox.setPlainText(md.text())
            self.tabs.setCurrentWidget(self.voice_page)

    def _dropped_image(self, path):
        menu = QMenu(self)
        acts = [("🔍 Scan the QR code in it", lambda: self.scan_file(path)),
                ("🖼️ Use as the QR's centre logo", lambda: (self._set_qr_logo(path, os.path.basename(path)),
                                                          self.tabs.setCurrentWidget(self.qr_page))),
                ("🌄 Make a picture QR with it", lambda: (self.select_qr_art(path),
                                                         self.tabs.setCurrentWidget(self.qr_page)))]
        for label, fn in acts:
            a = QAction(label, menu)
            a.triggered.connect(fn)
            menu.addAction(a)
        menu.exec(self.cursor().pos())

    # ---------------------------------------------------------- utilities
    # ------------------------------------------------------- preloading
    PRELOAD_STEPS = ["Audio device", "Voice & translation libraries", "QR scanner (OpenCV)",
                     "Offline speech recogniser (Whisper)", "Voice-cloning model (F5-TTS)", "Voice-profile transcripts",
                     "Edge voice server"]

    def start_preload(self):
        """Get every engine ready in the background (downloads models once), so nothing waits on first use."""
        if getattr(self, "_preloading", False):
            return
        self._preloading = True
        for s in self.PRELOAD_STEPS:
            self._on_preload(s, "wait", "")
        size = self.i_size.currentData() if hasattr(self, "i_size") else "base"
        threading.Thread(target=self._preload_worker, args=(size,), daemon=True).start()

    def _preload_worker(self, whisper_size):
        emit = self.bridge.preload.emit

        def step(name, fn):
            emit(name, "run", "")
            try:
                detail = fn()
                emit(name, "skip" if detail is False else "ok", "" if detail in (None, False) else str(detail))
            except Exception as e:
                log.exception("Preload %s failed", name)
                emit(name, "fail", str(e).splitlines()[0][:160])

        step("Audio device", lambda: self.player.wait_ready(20))
        step("Voice & translation libraries", warm_imports)

        def cv():
            from .qrtools import _detectors
            _detectors()
        step("QR scanner (OpenCV)", cv)
        caps = ENGINES.detect()
        self.bridge.engines.emit(caps)

        def whisper():
            if not caps.get("whisper"):
                return False
            import numpy as np
            from .audio import write_wav
            from .core import temp_path
            wav = temp_path(".wav")
            write_wav(wav, np.zeros(16000, np.float32), 16000)
            ENGINES.transcribe_whisper(wav, "en", whisper_size,
                                       status=lambda m: emit("Offline speech recogniser (Whisper)", "run", m))
            return f"{whisper_size} model loaded"
        step("Offline speech recogniser (Whisper)", whisper)

        def f5():
            if not caps.get("f5"):
                return False
            if total_ram_gb() < 12:
                return "skipped — under 12 GB RAM, it loads the first time you clone instead"
            ENGINES.f5_load(lambda m: emit("Voice-cloning model (F5-TTS)", "run", m))
            self.bridge.f5_state.emit(f"Model ready on {ENGINES.f5_device}")
            return f"ready on {ENGINES.f5_device}"
        step("Voice-cloning model (F5-TTS)", f5)

        def transcripts():
            from .core import PROFILES_DIR
            if not caps.get("whisper"):
                return False
            done = 0
            for fn in os.listdir(PROFILES_DIR):
                if not fn.lower().endswith(".wav"):
                    continue
                txt = os.path.join(PROFILES_DIR, fn[:-4] + ".txt")
                if os.path.exists(txt) and open(txt, encoding="utf-8").read().strip():
                    continue
                text, _ = ENGINES.transcribe_whisper(os.path.join(PROFILES_DIR, fn), None, whisper_size)
                if text:
                    with open(txt, "w", encoding="utf-8") as f:
                        f.write(text)
                    done += 1
            if done:
                self.bridge.profiles_changed.emit("")
            return f"{done} transcribed" if done else "all profiles have transcripts"
        step("Voice-profile transcripts", transcripts)

        def edge_check():
            # one tiny real request, so a broken Edge handshake is caught now — not when you click Speak
            from .speech import edge_synthesize
            from .core import temp_path
            p, words = edge_synthesize("Ready.", "en-US-AriaNeural", 0, 0, temp_path(".mp3"))
            return "online" + (" (via your Python install)" if ENGINES.prefer_external_edge else "")
        step("Edge voice server", edge_check)
        emit("__done__", "ok", "")

    def _on_preload(self, name, state, detail):
        if name == "__done__":
            self._preloading = False
            fails = [n for n, (s, _) in self.preload_state.items() if s == "fail"]
            if fails:
                self.set_status(f"Ready, but {len(fails)} engine(s) couldn't load — click the badge for details",
                                "warn")
            else:
                self.set_status("Everything is loaded and ready ⚡", "ok")
        else:
            self.preload_state[name] = (state, detail)
            if state == "run" and detail:
                self.set_status(f"Preparing: {detail}", "info")
        self._update_ready_badge()

    def _update_ready_badge(self):
        st = self.preload_state
        if not st:
            self.ready_badge.setText("⚡ Engines")
            return
        done = sum(1 for s, _ in st.values() if s in ("ok", "skip", "fail"))
        fails = sum(1 for s, _ in st.values() if s == "fail")
        if done < len(st):
            self.ready_badge.setText(f"⏳ Getting ready {done}/{len(st)}")
        elif fails:
            self.ready_badge.setText(f"⚠️ Ready ({fails} issue{'s' if fails > 1 else ''})")
        else:
            self.ready_badge.setText("✅ All ready")

    def show_readiness(self):
        icons = {"wait": "⏸", "run": "⏳", "ok": "✅", "fail": "❌", "skip": "➖"}
        rows = "".join(f"<tr><td>{icons.get(s, '?')}</td><td><b>{n}</b></td><td>{d or {'skip': 'not installed'}.get(s, '')}"
                       f"</td></tr>" for n, (s, d) in self.preload_state.items())
        box = QMessageBox(self)
        box.setWindowTitle("Engine readiness")
        box.setText("<p>Everything below loads in the background when the app opens, so nothing waits when you "
                    "use it. Models download once and are reused.</p><table cellspacing='6'>" + (rows or
                    "<tr><td>Preloading is off — turn it on in ⚙ Settings.</td></tr>") + "</table>")
        reload_btn = box.addButton("Load everything now", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is reload_btn:
            self.start_preload()

    def _on_engines(self, caps):
        self._apply_engine_caps(caps)
        if hasattr(self, "i_caps"):
            self._interp_caps(caps)

    def _on_level(self, lv):
        self.waveform.push_level(lv)
        self.orb.set_level(min(1.0, lv * 8))

    def _report_missing(self):
        missing = []
        for flag, pkg in ((HAS_EDGE, "edge-tts"), (HAS_GTTS, "gTTS"), (HAS_QR, "qrcode[pil]"),
                          (HAS_NP, "numpy"), (HAS_PYGAME or (HAS_SD and HAS_SF), "pygame")):
            if not flag:
                missing.append(pkg)
        if missing:
            self.set_status("Some features are off. Install: pip install " + " ".join(f'"{m}"' for m in missing),
                            "warn")

    def set_status(self, text, kind="ok", toast=False):
        if kind and kind.startswith("#"):  # old-style colour argument
            kind = {"#10B981": "ok", "#EF4444": "error", "#F59E0B": "warn"}.get(kind.upper(), "info")
        self._status_kind = kind
        color = STATUS_COLORS.get(kind) or T["a3"]
        self.status_label.setText(f"● {text}")
        self.status_label.setStyleSheet(f"color: {color}; font-weight: 600; font-size: 12px;")
        log.info("STATUS %s", text)
        if toast or kind == "error":
            self.toasts.show(text, kind)

    def celebrate(self):
        self.confetti.burst(QPoint(self.width() // 2, int(self.height() * 0.3)))

    def _escape(self):
        if self.isFullScreen():
            self._exit_fullscreen()
        else:
            self.stop_audio()

    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
            self.btn_max.setText("⤢ Maximize")
        else:
            self.showMaximized()
            self.btn_max.setText("⤡ Restore")

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self._exit_fullscreen()
        else:
            self.showFullScreen()
            self.btn_full.setText("⛶ Exit Fullscreen")

    def _exit_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.btn_full.setText("⛶ Fullscreen")

    def _save_current(self):
        w = self.tabs.currentWidget()
        {self.voice_page: self.save_audio, self.qr_page: self.save_qr, self.logo_page: self.save_logo,
         self.card_page: self.save_card_pdf, self.interp_page_w: self.export_chat}.get(w, lambda: None)()

    def _copy_image(self, img, label):
        if img is None:
            self.set_status(f"Nothing to copy yet — render a {label.lower()} first", "warn")
            return
        QApplication.clipboard().setPixmap(pil_to_qpixmap(img))
        self.set_status(f"{label} copied to clipboard", "ok", toast=True)

    def _run_bg(self, target, fn):
        """Render something off the UI thread; only the newest result for each target is shown."""
        self._gen[target] += 1
        gen = self._gen[target]

        def work():
            try:
                result = fn()
            except Exception as e:
                log.exception("Render failed")
                result = e
            self.bridge.image_ready.emit(target, gen, result)
        threading.Thread(target=work, daemon=True).start()

    def _on_image_ready(self, target, gen, result):
        if gen != self._gen[target]:
            return  # a newer render superseded this one
        if isinstance(result, Exception):
            {"qr": self.qr_preview, "logo": self.logo_preview, "card": self.card_preview}.get(
                target, self.logo_preview).set_busy(False)
            self.set_status(f"{target.upper()} error: {result}", "error")
            return
        if target == "qr":
            self._show_qr_result(result)
        elif target == "logo":
            self._show_logo_result(result)
        elif target == "var":
            self._show_variations(result)
        elif target == "card":
            self._show_card_result(result)


def _send_to_running_instance():
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def main():
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    install_wheel_guard(app)
    if "--selftest" in sys.argv:
        from . import selftest
        i = sys.argv.index("--selftest")
        report = sys.argv[i + 1] if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--") else \
            os.path.join(DATA_DIR, "selftest.json")
        window = StudioWindow()
        return selftest.run(app, window, report, quick="--quick" in sys.argv)
    if _send_to_running_instance():
        return 0
    QLocalServer.removeServer(INSTANCE_KEY)
    server = QLocalServer()
    server.listen(INSTANCE_KEY)

    start_hidden = "--tray" in sys.argv
    window = StudioWindow(start_hidden)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), window.show_from_tray()))

    def excepthook(exc_type, exc, tb):
        log.error("Unhandled: %s", "".join(traceback.format_exception(exc_type, exc, tb)))
        try:
            window.set_status(f"Unexpected error: {exc}", "error")
        except Exception:
            pass
    sys.excepthook = excepthook
    if not start_hidden:
        window.show()
    return app.exec()
