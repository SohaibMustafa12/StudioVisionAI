"""Live Interpreter tab: talk → transcribe → translate → speak, as a chat. Two-way conversation mode."""

import os
import threading
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from .audio import audio_envelope
from .core import HAS_NP, HAS_SD, HAS_SR, LANG_NAME, LANGUAGES, log, np, sd, translate_text
from .speech import ENGINES, estimate_words, language_label, pick_edge_voice, transcribe
from .widgets import GlowButton, VoiceOrb, card, hbox, hint, scroll_wrap

SR = 16000


class ChatView(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.inner = QWidget()
        self.lay = QVBoxLayout(self.inner)
        self.lay.setContentsMargins(4, 4, 4, 4)
        self.lay.setSpacing(10)
        self.lay.addStretch(1)
        self.setWidget(self.inner)
        self.items = []
        self.empty = hint("Tap the orb and start talking. I'll translate and speak it back — "
                          "turn on conversation mode to pass the laptop back and forth.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lay.insertWidget(0, self.empty)

    def add(self, original, translated, src, dst, side="A"):
        self.empty.hide()
        lab = QLabel(f"<div style='font-size:11px; opacity:0.75'>{language_label(src)} · {_esc(original)}</div>"
                     f"<div style='font-size:15px; font-weight:600; margin-top:4px'>{_esc(translated)}</div>"
                     f"<div style='font-size:10px; margin-top:4px'>→ {language_label(dst)}</div>")
        lab.setObjectName("BubbleA" if side == "A" else "BubbleB")
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lab.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        lab.setMaximumWidth(520)
        row = QHBoxLayout()
        if side == "A":
            row.addWidget(lab)
            row.addStretch(1)
        else:
            row.addStretch(1)
            row.addWidget(lab)
        self.lay.insertLayout(self.lay.count() - 1, row)
        self.items.append((original, translated, src, dst))
        QTimer.singleShot(60, lambda: self.verticalScrollBar().setValue(self.verticalScrollBar().maximum()))

    def clear(self):
        while self.lay.count() > 2:
            item = self.lay.takeAt(1)
            if item.layout():
                while item.layout().count():
                    w = item.layout().takeAt(0).widget()
                    if w:
                        w.deleteLater()
        self.items = []
        self.empty.show()


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class InterpreterMixin:
    def _build_interp_tab(self):
        page = QWidget()
        self.interp_page = page
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(12)

        c, cl = card("💬 Conversation")
        self.chat = ChatView()
        cl.addWidget(self.chat, 1)
        self.type_box = QLineEdit()
        self.type_box.setPlaceholderText("…or type a sentence and press Enter to translate & speak it")
        self.type_box.returnPressed.connect(self.interp_typed)
        b_exp = GlowButton("💾 Export chat", "ghost", None, 30)
        b_exp.clicked.connect(self.export_chat)
        b_clr = GlowButton("🧹 Clear", "ghost", None, 30)
        b_clr.clicked.connect(self.chat.clear)
        cl.addLayout(hbox(self.type_box, b_exp, b_clr, stretch={0: 1}))
        outer.addWidget(c, 3)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 4, 0)
        rl.setSpacing(12)
        c, cl = card()
        self.iorb = VoiceOrb(200)
        self.iorb.setToolTip("Tap to talk (Space)")
        self.iorb.clicked.connect(self.interp_toggle)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.iorb)
        row.addStretch(1)
        cl.addLayout(row)
        self.iorb_label = QLabel("Tap the orb or press Space to talk")
        self.iorb_label.setObjectName("Hint")
        self.iorb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.iorb_label)
        self.btn_talk = GlowButton("🎙 Tap to talk", None, None, 44)
        self.btn_talk.clicked.connect(self.interp_toggle)
        cl.addWidget(self.btn_talk)
        rl.addWidget(c)

        c, cl = card("Languages")
        self.src_lang = QComboBox()
        self.src_lang.addItem("🔎 Auto-detect (offline engine)", None)
        self.dst_lang = QComboBox()
        for name, code in LANGUAGES[1:]:
            self.src_lang.addItem(name, code)
            self.dst_lang.addItem(name, code)
        self.src_lang.setCurrentIndex(self.src_lang.findData("en"))
        self.dst_lang.setCurrentIndex(self.dst_lang.findData("ur"))
        b_swap = GlowButton("⇄", "ghost", None, 32)
        b_swap.setFixedWidth(44)
        b_swap.setToolTip("Swap languages")
        b_swap.clicked.connect(self.interp_swap)
        grid = QGridLayout()
        grid.addWidget(QLabel("I speak"), 0, 0)
        grid.addWidget(self.src_lang, 0, 1)
        grid.addWidget(b_swap, 0, 2, 2, 1)
        grid.addWidget(QLabel("Translate to"), 1, 0)
        grid.addWidget(self.dst_lang, 1, 1)
        grid.setColumnStretch(1, 1)
        cl.addLayout(grid)
        self.i_gender = QComboBox()
        self.i_gender.addItems(["Any", "Female", "Male"])
        cl.addLayout(hbox(QLabel("Voice"), self.i_gender, stretch={1: 1}))
        rl.addWidget(c)

        c, cl = card("Options")
        self.i_engine = QComboBox()
        self.i_engine.addItem("Auto (offline if available)", "auto")
        self.i_engine.addItem("Offline — Whisper (private)", "whisper")
        self.i_engine.addItem("Online — Google (fast)", "google")
        self.i_size = QComboBox()
        self.i_size.addItem("base (fast, 140 MB)", "base")
        self.i_size.addItem("small (better, 460 MB)", "small")
        self.i_size.addItem("medium (best, 1.5 GB)", "medium")
        cl.addLayout(hbox(QLabel("Recogniser"), self.i_engine, stretch={1: 1}))
        cl.addLayout(hbox(QLabel("Offline model"), self.i_size, stretch={1: 1}))
        self.i_speak = QCheckBox("Speak the translation aloud")
        self.i_speak.setChecked(True)
        self.i_convo = QCheckBox("Conversation mode — swap languages after each turn")
        self.i_auto = QCheckBox("Stop listening automatically when I pause")
        self.i_auto.setChecked(True)
        for w in (self.i_speak, self.i_convo, self.i_auto):
            cl.addWidget(w)
        self.i_caps = hint("")
        cl.addWidget(self.i_caps)
        rl.addWidget(c)
        rl.addStretch()
        outer.addWidget(scroll_wrap(right), 2)

        sc = QShortcut(QKeySequence(Qt.Key.Key_Space), page)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(self.interp_toggle)
        self.i_listening = False
        self.i_side = "A"
        self._interp_caps(ENGINES.caps())
        return page

    def _interp_caps(self, caps):
        parts = []
        parts.append("✅ Offline Whisper ready" if caps.get("whisper") else "⚪ Offline Whisper not installed")
        parts.append("✅ Google online recogniser" if HAS_SR else "⚪ Online recogniser missing (SpeechRecognition)")
        if not (HAS_SD and HAS_NP):
            parts.append("⚠️ Microphone needs sounddevice + numpy")
        self.i_caps.setText("  ·  ".join(parts))

    def interp_swap(self):
        s, d = self.src_lang.currentData(), self.dst_lang.currentData()
        if s is None:
            s = "en"
        self.src_lang.setCurrentIndex(self.src_lang.findData(d))
        self.dst_lang.setCurrentIndex(self.dst_lang.findData(s))
        self.i_side = "B" if self.i_side == "A" else "A"

    def interp_toggle(self):
        if self.i_listening:
            self.i_listening = False
            return
        if not (HAS_SD and HAS_NP):
            self.set_status("Microphone needs:  pip install sounddevice numpy", "warn")
            return
        if self.is_busy:
            return
        self.player.stop()
        self.i_listening = True
        job = {"src": self.src_lang.currentData(), "dst": self.dst_lang.currentData(),
               "engine": self.i_engine.currentData(), "size": self.i_size.currentData(),
               "auto": self.i_auto.isChecked(), "speak": self.i_speak.isChecked(),
               "gender": self.i_gender.currentText(), "voices": list(self.edge_voice_list), "side": self.i_side}
        self._interp_ui("listen")
        threading.Thread(target=self._interp_worker, args=(job,), daemon=True).start()

    def _interp_ui(self, state):
        if state == "listen":
            self.iorb.set_mode("record")
            self.btn_talk.setText("⏹ Done talking")
            self.iorb_label.setText("Listening… speak now")
        elif state == "think":
            self.iorb.set_mode("busy")
            self.btn_talk.setText("⏳ Translating…")
            self.btn_talk.setEnabled(False)
            self.iorb_label.setText("Understanding & translating…")
        elif state == "speak":
            self.iorb.set_mode("play")
            self.iorb_label.setText("Speaking the translation…")
        else:
            self.iorb.set_mode("idle")
            self.btn_talk.setText("🎙 Tap to talk")
            self.btn_talk.setEnabled(True)
            self.iorb_label.setText("Tap the orb or press Space to talk")

    def _interp_worker(self, job):
        b = self.bridge
        try:
            chunks, state = [], {"speech": False, "quiet": 0.0, "noise": 0.004}

            def cb(indata, frames, t, status):
                chunks.append(indata.copy())
                lv = float(np.sqrt(np.mean(indata ** 2)))
                b.interp.emit({"level": lv})
                if lv > max(0.015, state["noise"] * 4):
                    state["speech"] = True
                    state["quiet"] = 0.0
                else:
                    if not state["speech"]:
                        state["noise"] = state["noise"] * 0.95 + lv * 0.05
                    state["quiet"] += frames / SR
            start = time.monotonic()
            with sd.InputStream(samplerate=SR, channels=1, dtype="float32", callback=cb, blocksize=800):
                while self.i_listening and time.monotonic() - start < 45:
                    if job["auto"] and state["speech"] and state["quiet"] > 1.3:
                        break
                    time.sleep(0.05)
            self.i_listening = False
            if not chunks:
                raise RuntimeError("No audio captured — check microphone permissions")
            audio = np.concatenate(chunks).reshape(-1)
            if not state["speech"] or float(np.max(np.abs(audio))) < 0.01:
                b.interp.emit({"state": "idle"})
                b.status.emit("I didn't hear anything — try again a little closer to the mic", "warn")
                return
            b.interp.emit({"state": "think"})
            text, det, eng = transcribe(audio, SR, job["src"], job["engine"], job["size"],
                                        status=lambda m: b.status.emit(m, "info"))
            if not text.strip():
                b.interp.emit({"state": "idle"})
                b.status.emit("Couldn't make out any words — try again", "warn")
                return
            src = job["src"] or det or "auto"
            self._interp_translate_and_speak(text, src, job, eng)
        except Exception as e:
            log.exception("Interpreter failed")
            self.i_listening = False
            b.interp.emit({"state": "idle"})
            b.status.emit(f"Interpreter: {str(e).splitlines()[0]}", "error")

    def _interp_translate_and_speak(self, text, src, job, eng=""):
        b = self.bridge
        dst = job["dst"]
        if src != "auto" and src.split("-")[0] == dst.split("-")[0]:
            translated = text
        else:
            translated, _ = translate_text(text, dst, src if src != "auto" else "auto")
        b.interp.emit({"bubble": (text, translated, src, dst, job["side"])})
        b.status.emit(f"Heard via {eng}: “{text[:60]}”" if eng else "Translated", "ok")
        if job["speak"]:
            sub = self._snapshot_job(translated, None)
            sub.update({"engine": self.ENGINE_EDGE, "auto": True, "gender": job["gender"],
                        "voices": job["voices"], "dialogue": False, "effect": "None", "background": "None"})
            voice = pick_edge_voice(job["voices"], dst, job["gender"])
            if voice:
                sub["edge_voice"] = voice
            path, words = self._synthesize(sub, translated, dst)
            env, dur = audio_envelope(path)
            words = words or estimate_words(translated, dur)
            b.audio_ready.emit({"path": path, "words": words, "text": translated, "env": env, "duration": dur,
                                "job": {"engine": 0, "edge_voice": sub["edge_voice"], "effect": "None",
                                        "background": "None", "lang": dst, "dialogue": False},
                                "preview": True})
            b.interp.emit({"state": "speak"})
            self._play(path, env, dur)
        b.interp.emit({"state": "idle", "turn_done": True})

    def interp_typed(self):
        text = self.type_box.text().strip()
        if not text:
            return
        self.type_box.clear()
        job = {"dst": self.dst_lang.currentData(), "speak": self.i_speak.isChecked(),
               "gender": self.i_gender.currentText(), "voices": list(self.edge_voice_list), "side": self.i_side}
        src = self.src_lang.currentData() or "auto"
        self._interp_ui("think")

        def work():
            try:
                self._interp_translate_and_speak(text, src, job)
            except Exception as e:
                self.bridge.interp.emit({"state": "idle"})
                self.bridge.status.emit(f"Interpreter: {e}", "error")
        threading.Thread(target=work, daemon=True).start()

    def _on_interp(self, ev):
        if "level" in ev:
            self.iorb.set_level(min(1.0, ev["level"] * 9))
            self.waveform.push_level(ev["level"])
        if "bubble" in ev:
            o, t, s, d, side = ev["bubble"]
            self.chat.add(o, t, s, d, side)
            self.history.add("interp", f"{o} → {t}", meta={"src": s, "dst": d, "original": o, "translated": t})
            self._history_changed()
        if "state" in ev:
            self._interp_ui(ev["state"])
            if ev["state"] != "listen" and ev["state"] != "speak":
                self.waveform.stop()
        if ev.get("turn_done") and self.i_convo.isChecked():
            self.interp_swap()
            self.set_status(f"Your turn, {LANG_NAME.get(self.src_lang.currentData(), '')} speaker 🎙", "info")

    def export_chat(self):
        if not self.chat.items:
            self.set_status("Nothing to export yet", "warn")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export conversation", "conversation.txt", "Text (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            for o, t, s, d in self.chat.items:
                f.write(f"[{language_label(s)}] {o}\n[{language_label(d)}] {t}\n\n")
        self.set_status(f"Conversation saved: {os.path.basename(path)}", "ok", toast=True)
