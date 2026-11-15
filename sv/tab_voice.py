"""Voice Studio tab: translate, speak, dialogue mode, effects/music, karaoke + subtitles, voice cloning."""

import hashlib
import json
import os
import re
import shutil
import threading
import time
import wave

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QTextEdit, QVBoxLayout, QWidget)

from .audio import (BACKGROUNDS, VOICE_EFFECTS, audio_duration, audio_envelope, concat_files, convert_audio,
                    export_formats, process_speech, read_audio_mono, resample, write_wav)
from .core import (DATA_DIR, FEATURED_TAGS, HAS_GTTS, HAS_NP, HAS_SD, LANG_NAME, LANGUAGES, PROFILES_DIR,
                   detect_language, flag_emoji, guess_lang, locale_matches, log, np, sd, temp_path, translate_text)
from .speech import (ENGINES, SystemTTS, align_words, edge_synthesize, estimate_words, gtts_synthesize,
                     pick_edge_voice, scale_words, to_srt, to_vtt)
from .widgets import GlowButton, KaraokeView, VoiceOrb, card, hbox, hint, labeled_slider, scroll_wrap

DIALOGUE_RE = re.compile(r"^\s*([^:\n]{1,24}?)\s*[:：]\s*(.+)$")


def parse_dialogue(text):
    """'Ali: hi' lines -> [(speaker, line)]. Lines without a speaker continue the previous one."""
    out = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        m = DIALOGUE_RE.match(raw)
        if m and not re.match(r"^https?$", m.group(1).strip(), re.I):
            out.append([m.group(1).strip(), m.group(2).strip()])
        elif out:
            out[-1][1] += " " + raw.strip()
        else:
            out.append(["Narrator", raw.strip()])
    return [(s, t) for s, t in out if t]


class VoiceMixin:
    ENGINE_EDGE, ENGINE_GTTS, ENGINE_CLONE, ENGINE_SYSTEM = range(4)

    # ------------------------------------------------------------------ UI
    def _build_voice_tab(self):
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(12)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 4, 0)
        ll.setSpacing(12)

        c, cl = card("1 · Your text")
        self.textbox = QTextEdit()
        self.textbox.setPlaceholderText("Type or paste anything — any language…  (drop a .txt file here too)")
        self.textbox.setPlainText("Hello! This is Studio Vision AI. I can translate and speak in hundreds of voices.")
        self.textbox.setMinimumHeight(130)
        self.textbox.setAcceptRichText(False)
        self.char_count = QLabel()
        self.char_count.setObjectName("Hint")
        self.textbox.textChanged.connect(self._update_char_count)
        cl.addWidget(self.textbox)
        self.dialogue = QCheckBox("🎭 Dialogue mode")
        self.dialogue.setToolTip("Write lines like  Ali: Hello!  — every speaker gets their own voice")
        self.dialogue.toggled.connect(self._on_dialogue_toggled)
        b_open = GlowButton("📂 Open .txt", "ghost", None, 28)
        b_open.clicked.connect(self.open_text_file)
        btn_clear = GlowButton("🧹 Clear", "ghost", None, 28)
        btn_clear.clicked.connect(lambda: self.textbox.clear())
        cl.addLayout(hbox(self.char_count, 1, self.dialogue, b_open, btn_clear, stretch={0: 1}))
        ll.addWidget(c)

        self.cast_card, cl = card("🎭 Cast", "Each speaker found in your script gets a voice. Lines look like "
                                            "“Sara: Did you hear that?”. Uses Edge neural voices.")
        self.cast_grid = QGridLayout()
        self.cast_grid.setHorizontalSpacing(8)
        cl.addLayout(self.cast_grid)
        b_sample = GlowButton("✍️ Insert a sample script", "ghost", None, 28)
        b_sample.clicked.connect(self._insert_sample_dialogue)
        cl.addWidget(b_sample)
        self.cast_combos = {}
        self.cast_card.setVisible(False)
        ll.addWidget(self.cast_card)
        self.cast_timer = QTimer(self)
        self.cast_timer.setSingleShot(True)
        self.cast_timer.timeout.connect(self._refresh_cast)

        c, cl = card("2 · Translation", "Pick a target language and the text is translated for free before speaking. "
                                        "Edit the translation if you like — your edits are what gets spoken.")
        self.target_lang = QComboBox()
        for name, code in LANGUAGES:
            self.target_lang.addItem(name, code)
        self.target_lang.currentIndexChanged.connect(self._on_target_changed)
        self.btn_translate = GlowButton("🌐 Translate", "info", None, 32)
        self.btn_translate.clicked.connect(self.translate_only)
        cl.addLayout(hbox(QLabel("Target language"), self.target_lang, self.btn_translate, stretch={1: 1}))
        self.trans_box = QTextEdit()
        self.trans_box.setObjectName("Translation")
        self.trans_box.setPlaceholderText("Translation appears here…")
        self.trans_box.setMinimumHeight(80)
        self.trans_box.setAcceptRichText(False)
        cl.addWidget(self.trans_box)
        swap = GlowButton("⇅ Use translation as my text", "ghost", None, 28)
        swap.clicked.connect(self._use_translation)
        cl.addWidget(swap)
        ll.addWidget(c)

        c, cl = card("🎤 Now playing")
        self.karaoke = KaraokeView()
        cl.addWidget(self.karaoke)
        self.btn_pause = GlowButton("⏯ Pause", "ghost", None, 30)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_subs = GlowButton("💬 Export subtitles", "violet", None, 30)
        self.btn_subs.setToolTip("Save .srt / .vtt captions with exact word timings — drop them into any video editor")
        self.btn_subs.clicked.connect(self.export_subtitles)
        self.btn_subs.setEnabled(False)
        cl.addLayout(hbox(self.btn_pause, self.btn_subs, 1))
        ll.addWidget(c)
        ll.addStretch()

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 4, 0)
        rl.setSpacing(12)

        c, cl = card()
        self.orb = VoiceOrb(150)
        self.orb.setToolTip("Click to speak / stop")
        self.orb.clicked.connect(lambda: self.stop_audio() if (self.player.playing or self.is_busy) else self.speak())
        self.orb_label = QLabel("Ready when you are")
        self.orb_label.setObjectName("Hint")
        orb_row = QHBoxLayout()
        orb_row.addStretch(1)
        orb_row.addWidget(self.orb)
        orb_row.addStretch(1)
        cl.addLayout(orb_row)
        lab_row = QHBoxLayout()
        lab_row.addStretch(1)
        lab_row.addWidget(self.orb_label)
        lab_row.addStretch(1)
        cl.addLayout(lab_row)
        rl.addWidget(c)

        c, cl = card("3 · Voice engine")
        self.engine = QComboBox()
        self.engine.addItems(["🌍 Edge Neural voices — 400+ voices & accents (online, free)",
                              "🗣️ Google voice — every language (online, free)",
                              "🧬 My cloned voice — F5-TTS (offline, free)",
                              "💻 System voices (offline, free)"])
        cl.addWidget(self.engine)
        self.engine_pages = [self._edge_page(), self._gtts_page(), self._clone_page(), self._system_page()]
        for pg in self.engine_pages:
            cl.addWidget(pg)
        self.engine.currentIndexChanged.connect(self._on_engine_changed)
        srow, self.rate_slider = labeled_slider(-50, 100, 0, lambda v: f"{v:+d}%")
        cl.addWidget(QLabel("Speed"))
        cl.addLayout(srow)
        self.pitch_label = QLabel("Pitch (Edge voices)")
        cl.addWidget(self.pitch_label)
        prow, self.pitch_slider = labeled_slider(-50, 50, 0, lambda v: f"{v:+d} Hz")
        cl.addLayout(prow)
        self.auto_voice = QCheckBox("Auto-match the voice to the language (prevents silent output)")
        self.auto_voice.setChecked(True)
        self.auto_voice.toggled.connect(self._refresh_edge_combo)
        cl.addWidget(self.auto_voice)
        rl.addWidget(c)

        c, cl = card("4 · Effects & music", "Studio effects and a background bed, mixed locally.")
        self.effect = QComboBox()
        self.effect.addItems(VOICE_EFFECTS)
        self.bg_music = QComboBox()
        self.bg_music.addItems(BACKGROUNDS)
        self.bg_music.currentIndexChanged.connect(self._on_bg_changed)
        grid = QGridLayout()
        grid.addWidget(QLabel("Voice effect"), 0, 0)
        grid.addWidget(self.effect, 0, 1)
        grid.addWidget(QLabel("Background"), 1, 0)
        grid.addWidget(self.bg_music, 1, 1)
        grid.setColumnStretch(1, 1)
        cl.addLayout(grid)
        self.music_file = None
        self.btn_music = GlowButton("🎵 Choose music file…", "ghost", None, 28)
        self.btn_music.clicked.connect(self._choose_music)
        self.btn_music.setVisible(False)
        cl.addWidget(self.btn_music)
        vrow, self.bg_volume = labeled_slider(5, 60, 22, lambda v: f"{v}%")
        self.bg_vol_label = QLabel("Music volume")
        cl.addWidget(self.bg_vol_label)
        cl.addLayout(vrow)
        rl.addWidget(c)

        self.btn_speak = GlowButton("⚡ Speak  (Ctrl+Enter)", None, None, 44)
        self.btn_speak.clicked.connect(self.speak)
        self.btn_stop = GlowButton("⏹ Stop", "danger", None, 44)
        self.btn_stop.clicked.connect(self.stop_audio)
        rl.addLayout(hbox(self.btn_speak, self.btn_stop, stretch={0: 3, 1: 1}))
        self.btn_replay = GlowButton("🔁 Replay", "ghost", None, 34)
        self.btn_replay.clicked.connect(self.replay)
        self.btn_save_audio = GlowButton("💾 Save audio", "warn", None, 34)
        self.btn_save_audio.clicked.connect(self.save_audio)
        self.btn_replay.setEnabled(False)
        self.btn_save_audio.setEnabled(False)
        rl.addLayout(hbox(self.btn_replay, self.btn_save_audio, stretch={0: 1, 1: 1}))
        rl.addStretch()

        outer.addWidget(scroll_wrap(left), 1)
        outer.addWidget(scroll_wrap(right), 1)
        self._update_char_count()
        self._on_engine_changed(0)
        self._on_bg_changed()

        # karaoke + orb clock
        self.av_timer = QTimer(self)
        self.av_timer.timeout.connect(self._av_tick)
        self.av_timer.start(33)
        self.last_words = []
        self.last_env = None
        self.last_duration = 0.0
        self._job_seq = 0
        return page

    def _edge_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.voice_search = QLineEdit()
        self.voice_search.setPlaceholderText("🔍 Search voices (e.g. 'British', 'ur-PK', 'Jenny')")
        self.voice_search.textChanged.connect(self._refresh_edge_combo)
        self.gender = QComboBox()
        self.gender.addItems(["Any", "Male", "Female"])
        self.gender.currentIndexChanged.connect(self._refresh_edge_combo)
        lay.addLayout(hbox(self.voice_search, self.gender, stretch={0: 1}))
        self.edge_voice = QComboBox()
        self.edge_voice.setMaxVisibleItems(18)
        self.edge_voice.currentIndexChanged.connect(
            lambda _: self.store.set("voice/edge", self.edge_voice.currentData() or ""))
        self.btn_preview_voice = GlowButton("▶ Preview", "ghost", None, 30)
        self.btn_preview_voice.setToolTip("Hear a short sample of this voice")
        self.btn_preview_voice.clicked.connect(self.preview_voice)
        lay.addLayout(hbox(self.edge_voice, self.btn_preview_voice, stretch={0: 1}))
        self.edge_hint = hint("Loading the full voice catalogue…")
        lay.addWidget(self.edge_hint)
        return w

    def _gtts_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(hint("Google's voice automatically speaks the target language (or the detected language). "
                           "Great fallback for languages Edge doesn't cover, like Punjabi."))
        self.gtts_tld = QComboBox()
        for label, tld in [("Default", "com"), ("UK", "co.uk"), ("Australia", "com.au"), ("India", "co.in"),
                           ("Canada", "ca"), ("Ireland", "ie"), ("South Africa", "co.za")]:
            self.gtts_tld.addItem(label, tld)
        self.gtts_slow = QCheckBox("Slow & clear")
        lay.addLayout(hbox(QLabel("English accent"), self.gtts_tld, self.gtts_slow, stretch={1: 1}))
        if not HAS_GTTS:
            lay.addWidget(hint("⚠️ Install with:  pip install gTTS"))
        return w

    def _clone_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.clone_missing = hint("⚠️ Voice cloning needs F5-TTS (free & offline):  pip install f5-tts\n"
                                  "Everything else in the app works without it.")
        lay.addWidget(self.clone_missing)
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        b_del = GlowButton("🗑", "red", None, 30)
        b_del.setFixedWidth(40)
        b_del.setToolTip("Delete this profile")
        b_del.clicked.connect(self.delete_profile)
        b_open = GlowButton("📂", "ghost", None, 30)
        b_open.setFixedWidth(40)
        b_open.setToolTip("Open the profiles folder")
        b_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(PROFILES_DIR)))
        lay.addLayout(hbox(QLabel("Voice profile"), self.profile_combo, b_del, b_open, stretch={1: 1}))
        self.profile_info = hint("")
        lay.addWidget(self.profile_info)
        self.f5_quality = QComboBox()
        self.f5_quality.addItem("⚡ Fast (8 steps)", 8)
        self.f5_quality.addItem("⚖️ Balanced (16 steps)", 16)
        self.f5_quality.addItem("💎 Best (32 steps)", 32)
        self.f5_quality.setCurrentIndex(1)
        self.btn_load_f5 = GlowButton("Load model", "ghost", None, 30)
        self.btn_load_f5.clicked.connect(self.load_f5)
        lay.addLayout(hbox(QLabel("Quality"), self.f5_quality, self.btn_load_f5, stretch={1: 1}))
        self.f5_state_label = hint("Model not loaded yet — it loads automatically the first time you speak.")
        lay.addWidget(self.f5_state_label)
        rec_title = QLabel("New profile — record 5–12 seconds of clear speech")
        rec_title.setObjectName("CardTitle")
        lay.addWidget(rec_title)
        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("Profile name (e.g. My voice)")
        self.ref_text = QLineEdit()
        self.ref_text.setPlaceholderText("Exactly what you'll say (leave empty = auto-transcribe locally)")
        lay.addWidget(self.profile_name)
        lay.addWidget(self.ref_text)
        self.btn_record = GlowButton("🔴 Record", "red", None, 32)
        self.btn_record.clicked.connect(self.toggle_recording)
        self.btn_record.setEnabled(HAS_SD and HAS_NP)
        b_import = GlowButton("📥 Import audio file", "violet", None, 32)
        b_import.clicked.connect(self.import_profile_audio)
        lay.addLayout(hbox(self.btn_record, b_import))
        if not (HAS_SD and HAS_NP):
            lay.addWidget(hint("⚠️ Recording needs:  pip install sounddevice numpy"))
        lay.addWidget(hint("Tip: the base model speaks English & Chinese best. Other languages may sound odd."))
        self.refresh_profiles()
        self._apply_engine_caps(ENGINES.caps())
        return w

    def _system_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.sys_voice = QComboBox()
        self.sys_voice.addItem("Loading system voices…", None)
        lay.addWidget(self.sys_voice)
        lay.addWidget(hint("Works without internet. With auto-match on, a voice for the target language is picked "
                           "if your OS has one installed (Settings → Time & language → Speech to add more)."))
        return w

    def _apply_engine_caps(self, caps):
        f5 = caps.get("f5")
        self.clone_missing.setVisible(not f5)
        self.btn_load_f5.setEnabled(bool(f5))
        if f5 and caps.get("external"):
            self.f5_state_label.setText(f"Uses your Python install for cloning: {caps['external']}")

    # ------------------------------------------------------------- helpers
    def _update_char_count(self):
        text = self.textbox.toPlainText()
        lang = guess_lang(text)
        detected = f" · detected script: {LANG_NAME.get(lang, lang)}" if lang else ""
        words = len(text.split())
        secs = words / 2.6
        self.char_count.setText(f"{len(text)} characters · ~{secs:.0f}s of speech{detected}")
        if self.dialogue.isChecked():
            self.cast_timer.start(400)

    def open_text_file(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open text", "", "Text (*.txt *.md *.srt *.csv);;All (*.*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            self.set_status(f"Couldn't open file: {e}", "error")
            return
        if path.lower().endswith(".srt"):
            text = "\n".join(ln for ln in text.splitlines()
                             if ln.strip() and not ln.strip().isdigit() and "-->" not in ln)
        self.textbox.setPlainText(text)
        self.tabs.setCurrentIndex(0)
        self.set_status(f"Loaded {os.path.basename(path)}", "ok")

    def _on_dialogue_toggled(self, on):
        self.cast_card.setVisible(on)
        if on:
            self._refresh_cast()

    def _insert_sample_dialogue(self):
        self.textbox.setPlainText("Sara: Did you hear that? Studio Vision can do whole conversations now.\n"
                                  "Ali: No way. Different voices for each of us?\n"
                                  "Sara: Yep — and it can even translate the whole script.\n"
                                  "Narrator: And so, a podcast was born.")
        self.dialogue.setChecked(True)

    def _voice_label(self, v):
        person = v["name"].split("-", 2)[-1].replace("Neural", "")
        sym = "♂" if v["gender"] == "Male" else "♀" if v["gender"] == "Female" else ""
        tag = FEATURED_TAGS.get(v["name"])
        return f"{flag_emoji(v['locale'])}  {v['locale']} · {person} {sym}" + (f"  — {tag}" if tag else "")

    def _refresh_cast(self):
        speakers = []
        for s, _ in parse_dialogue(self.textbox.toPlainText()):
            if s not in speakers:
                speakers.append(s)
        speakers = speakers[:8]
        lang = self.target_lang.currentData() or guess_lang(self.textbox.toPlainText()) or "en"
        voices = [v for v in self.edge_voice_list if locale_matches(v["locale"], lang)] or self.edge_voice_list
        old = {k: c.currentData() for k, c in self.cast_combos.items()}
        while self.cast_grid.count():
            item = self.cast_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cast_combos = {}
        males = [v["name"] for v in voices if v["gender"] == "Male"]
        females = [v["name"] for v in voices if v["gender"] == "Female"]
        for i, sp in enumerate(speakers):
            combo = QComboBox()
            for v in voices:
                combo.addItem(self._voice_label(v), v["name"])
            pool = (females if i % 2 == 0 else males) or males or females
            default = pool[(i // 2) % len(pool)] if pool else None
            idx = combo.findData(old.get(sp) or default)
            combo.setCurrentIndex(max(0, idx))
            self.cast_grid.addWidget(QLabel(f"🎙 {sp}"), i, 0)
            self.cast_grid.addWidget(combo, i, 1)
            self.cast_combos[sp] = combo
        self.cast_grid.setColumnStretch(1, 1)
        if not speakers:
            self.cast_grid.addWidget(hint("No speakers yet — write lines like  Name: text"), 0, 0, 1, 2)

    def _on_bg_changed(self, *_):
        kind = self.bg_music.currentText()
        self.btn_music.setVisible("music file" in kind)
        on = kind != "None"
        self.bg_volume.setEnabled(on)
        self.bg_vol_label.setEnabled(on)

    def _choose_music(self):
        path, _ = QFileDialog.getOpenFileName(self, "Background music", "", "Audio (*.mp3 *.wav *.ogg *.flac)")
        if path:
            self.music_file = path
            self.btn_music.setText(f"🎵 {os.path.basename(path)[:34]}")

    def _on_target_changed(self):
        self._refresh_edge_combo()
        self._refresh_sys_combo()
        if self.dialogue.isChecked():
            self._refresh_cast()

    def _on_engine_changed(self, idx):
        for i, pg in enumerate(self.engine_pages):
            pg.setVisible(i == idx)
        self.pitch_slider.setEnabled(idx == self.ENGINE_EDGE)
        self.pitch_label.setEnabled(idx == self.ENGINE_EDGE)
        if idx == self.ENGINE_CLONE and ENGINES.caps()["f5"] and not ENGINES.f5_loaded:
            self.f5_state_label.setText("Model loads on first use (or press Load model).")

    def _on_edge_voices(self, voices):
        self.edge_voice_list = voices
        self.edge_hint.setText(f"{len(voices)} voices available — all free.")
        self._refresh_edge_combo(prefer=self.store.get("voice/edge", ""))
        if self.dialogue.isChecked():
            self._refresh_cast()

    def _refresh_edge_combo(self, *_, prefer=None):
        current = prefer or self.edge_voice.currentData()
        lang = self.target_lang.currentData()
        query = self.voice_search.text().strip().lower()
        gender = self.gender.currentText()
        voices = self.edge_voice_list
        if self.auto_voice.isChecked() and lang:
            matching = [v for v in voices if locale_matches(v["locale"], lang)]
            if matching:
                voices = matching
            else:
                self.edge_hint.setText(f"No Edge voice for {LANG_NAME.get(lang, lang)} — the Google voice will be "
                                       f"used automatically.")
        if gender in ("Male", "Female"):
            voices = [v for v in voices if v["gender"] == gender] or voices
        if query:
            def text_of(v):
                return f"{v['name']} {v['locale']} {FEATURED_TAGS.get(v['name'], '')}".lower()
            voices = [v for v in voices if query in text_of(v)] or voices
        featured = [v for v in voices if v["name"] in FEATURED_TAGS]
        rest = [v for v in voices if v["name"] not in FEATURED_TAGS]
        self.edge_voice.blockSignals(True)
        self.edge_voice.clear()
        for v in (featured + rest if not lang else rest + featured):
            self.edge_voice.addItem(self._voice_label(v), v["name"])
        idx = self.edge_voice.findData(current)
        if idx < 0 and lang:
            best = pick_edge_voice(voices, lang, gender)
            idx = self.edge_voice.findData(best)
        if idx < 0:
            idx = self.edge_voice.findData("en-US-AriaNeural")
        self.edge_voice.setCurrentIndex(max(0, idx))
        self.edge_voice.blockSignals(False)

    def _on_sys_voices(self, voices):
        self.system_voices = voices
        self._refresh_sys_combo()

    def _refresh_sys_combo(self):
        if not hasattr(self, "sys_voice"):
            return
        current = self.sys_voice.currentData()
        self.sys_voice.clear()
        if not self.system_voices:
            self.sys_voice.addItem("Default system voice", None)
            return
        lang = self.target_lang.currentData()
        for i, v in enumerate(self.system_voices):
            self.sys_voice.addItem(f"{flag_emoji(v['lang'])}  {v['name']}  ({v['lang']})", i)
        idx = self.sys_voice.findData(current)
        if lang and self.auto_voice.isChecked():
            match = next((i for i, v in enumerate(self.system_voices) if locale_matches(v["lang"], lang)), None)
            if match is not None and (current is None or not locale_matches(
                    self.system_voices[current]["lang"] if isinstance(current, int) and current < len(
                        self.system_voices) else "", lang)):
                idx = self.sys_voice.findData(match)
        self.sys_voice.setCurrentIndex(max(0, idx))

    def _use_translation(self):
        t = self.trans_box.toPlainText().strip()
        if t:
            self.textbox.setPlainText(t)
            self.target_lang.setCurrentIndex(0)
            self.trans_box.clear()

    def _on_translated(self, source, target, result):
        self._trans_cache = (source, target, result)
        self.trans_box.setPlainText(result)

    def translate_only(self):
        text = self.textbox.toPlainText().strip()
        lang = self.target_lang.currentData()
        if not text:
            self.set_status("Type some text first", "warn")
            return
        if not lang:
            self.set_status("Pick a target language to translate into", "warn")
            return
        self.set_status(f"Translating to {LANG_NAME[lang]}…", "info")

        def work():
            try:
                if self.dialogue.isChecked():
                    lines = parse_dialogue(text)
                    result = "\n".join(f"{s}: {translate_text(t, lang)[0]}" for s, t in lines)
                    provider = "Google"
                else:
                    result, provider = translate_text(text, lang)
                self.bridge.translated.emit(text, lang, result)
                self.bridge.status.emit(f"Translated to {LANG_NAME[lang]} via {provider}", "ok")
            except Exception as e:
                self.bridge.status.emit(str(e).splitlines()[0], "error")
        threading.Thread(target=work, daemon=True).start()

    # -------------------------------------------------------------- speech
    def _snapshot_job(self, text=None, lang="__ui__"):
        """Read every widget value here on the UI thread; worker threads never touch widgets."""
        text = self.textbox.toPlainText().strip() if text is None else text
        lang = self.target_lang.currentData() if lang == "__ui__" else lang
        override = None
        if lang and self._trans_cache and self._trans_cache[0] == text and self._trans_cache[1] == lang:
            override = self.trans_box.toPlainText().strip() or None
        sys_idx = self.sys_voice.currentData()
        return {
            "text": text, "lang": lang, "override": override, "engine": self.engine.currentIndex(),
            "edge_voice": self.edge_voice.currentData() or "en-US-AriaNeural", "gender": self.gender.currentText(),
            "auto": self.auto_voice.isChecked(), "rate": self.rate_slider.value(),
            "pitch": self.pitch_slider.value(), "tld": self.gtts_tld.currentData(),
            "slow": self.gtts_slow.isChecked(), "profile": self.profile_combo.currentData(),
            "nfe": self.f5_quality.currentData(),
            "sys_voice": self.system_voices[sys_idx] if isinstance(sys_idx, int) and sys_idx < len(
                self.system_voices) else None,
            "voices": list(self.edge_voice_list), "sys_voices": list(self.system_voices),
            "dialogue": self.dialogue.isChecked(),
            "cast": {k: c.currentData() for k, c in self.cast_combos.items()},
            "effect": self.effect.currentText(), "background": self.bg_music.currentText(),
            "bg_volume": self.bg_volume.value() / 100.0, "music_file": self.music_file,
        }

    def speak(self, text=None, lang="__ui__", quick=False):
        if self.is_busy and not quick:
            self.set_status("Already working on it… (press Stop to cancel)", "warn")
            return
        job = self._snapshot_job(text, lang)
        if not job["text"]:
            self.set_status("Type some text first", "warn")
            return
        if job["engine"] == self.ENGINE_CLONE and not job["profile"] and not job["dialogue"]:
            self.set_status("Record or import a voice profile first (see the cloning panel)", "warn")
            return
        if quick:
            job.update({"dialogue": False, "effect": "None", "background": "None", "quick": True})
        self._job_seq += 1
        job["seq"] = self._job_seq
        self.player.stop()
        threading.Thread(target=self._speech_worker, args=(job,), daemon=True).start()

    def preview_voice(self):
        v = self.edge_voice.currentData()
        if not v or self.is_busy:
            return
        loc = v.split("-")[0]
        samples = {"en": "Hi! This is how I sound. Want me to read something for you?",
                   "ur": "السلام علیکم! میری آواز ایسی ہے۔", "hi": "नमस्ते! मेरी आवाज़ ऐसी है।",
                   "ar": "مرحبا! هذا هو صوتي.", "es": "¡Hola! Así suena mi voz.", "fr": "Bonjour ! Voici ma voix.",
                   "de": "Hallo! So klingt meine Stimme.", "ja": "こんにちは！これが私の声です。",
                   "zh": "你好！这是我的声音。", "ko": "안녕하세요! 제 목소리예요.", "tr": "Merhaba! Sesim böyle."}
        text = samples.get(loc, samples["en"])
        job = self._snapshot_job(text, None)
        job.update({"engine": self.ENGINE_EDGE, "auto": False, "dialogue": False, "effect": "None",
                    "background": "None", "preview": True})
        self._job_seq += 1
        job["seq"] = self._job_seq
        self.player.stop()
        threading.Thread(target=self._speech_worker, args=(job,), daemon=True).start()

    def _speech_worker(self, job):
        emit = self.bridge.status.emit
        self.bridge.busy.emit(True)
        path = None
        try:
            text, lang = job["text"], job["lang"]
            estimated, speak_lang = False, lang
            if job["dialogue"]:
                path, words, spoken = self._synthesize_dialogue(job)
            else:
                if lang:
                    if job["override"]:
                        text = job["override"]
                    else:
                        emit(f"Translating to {LANG_NAME[lang]}…", "info")
                        text, _ = translate_text(text, lang)
                        if not job.get("quick"):
                            self.bridge.translated.emit(job["text"], lang, text)
                # Latin-script text (Spanish, French…) is detected online so auto-match picks a fitting voice
                speak_lang = lang or (detect_language(text) if job["auto"] else guess_lang(text))
                path, words = self._synthesize(job, text, speak_lang)
                estimated = not words
                if estimated:
                    words = estimate_words(text, audio_duration(path))
                spoken = text
            if job["effect"] != "None" or job["background"] != "None":
                emit("Mixing effects & music…", "info")
                path, scale, offset = process_speech(path, job["effect"], job["background"], job["bg_volume"],
                                                     job["music_file"])
                words = scale_words(words, scale, offset)
            env, duration = audio_envelope(path)
            self.bridge.audio_ready.emit({"path": path, "words": words, "text": spoken, "env": env,
                                          "duration": duration, "job": {k: job[k] for k in (
                                              "engine", "edge_voice", "effect", "background", "lang", "dialogue")},
                                          "preview": job.get("preview", False), "quick": job.get("quick", False),
                                          "estimated": estimated, "lang": speak_lang})
        except Exception as e:
            log.exception("Speech failed")
            emit(str(e).splitlines()[0] if str(e) else repr(e), "error")
            self.bridge.busy.emit(False)
            return
        self.bridge.busy.emit(False)
        if job["seq"] == self._job_seq:
            self._play(path, env, duration)

    def _synthesize_dialogue(self, job):
        emit = self.bridge.status.emit
        lines = parse_dialogue(job["text"])
        if not lines:
            raise RuntimeError("No dialogue lines found — write lines like  Name: text")
        lang = job["lang"]
        override_lines = parse_dialogue(job["override"]) if job["override"] else None
        parts, all_words, spoken = [], [], []
        for i, (sp, line) in enumerate(lines):
            if override_lines and i < len(override_lines):
                line = override_lines[i][1]
            elif lang:
                emit(f"Translating line {i + 1}/{len(lines)}…", "info")
                line, _ = translate_text(line, lang)
            voice = job["cast"].get(sp) or job["edge_voice"]
            emit(f"🎭 {sp} ({voice.split('-')[-1].replace('Neural', '')}) — line {i + 1}/{len(lines)}", "info")
            sub = dict(job, edge_voice=voice, auto=bool(lang), dialogue=False)
            sub["engine"] = self.ENGINE_EDGE
            p, words = self._synthesize(sub, line, lang or detect_language(line))
            if not words:
                words = estimate_words(line, audio_duration(p))
            parts.append((p, words))
            spoken.append(f"{sp}: {line}")
        path, starts = concat_files([p for p, _ in parts])
        for (p, words), st in zip(parts, starts):
            all_words += scale_words(words, 1.0, st)
        return path, all_words, "\n".join(spoken)

    def _synthesize(self, job, text, lang):
        """Returns (path, words_or_empty)."""
        emit = self.bridge.status.emit
        engine = job["engine"]
        errors = []

        def try_edge(voice=None):
            v = voice or job["edge_voice"]
            if lang and job["auto"]:
                cur_loc = next((x["locale"] for x in job["voices"] if x["name"] == v), "-".join(v.split("-")[:2]))
                if not locale_matches(cur_loc, lang):
                    auto = pick_edge_voice(job["voices"], lang, job["gender"])
                    if not auto:
                        raise RuntimeError(f"no Edge voice for {LANG_NAME.get(lang, lang)}")
                    emit(f"Auto-switched to {auto} so it can read {LANG_NAME.get(lang, lang)}", "info")
                    v = auto
            emit(f"Generating speech with {v}…", "info")
            return edge_synthesize(text, v, job["rate"], job["pitch"], temp_path(".mp3"))

        def try_gtts():
            emit(f"Generating speech with Google voice ({LANG_NAME.get(lang, lang or 'English')})…", "info")
            return gtts_synthesize(text, lang, temp_path(".mp3"), job["tld"], job["slow"]), []

        def try_system():
            voice = job["sys_voice"]
            if lang and job["auto"] and (not voice or not locale_matches(voice["lang"], lang)):
                voice = next((v for v in job["sys_voices"] if locale_matches(v["lang"], lang)), voice)
            emit("Generating speech with system voice…", "info")
            return SystemTTS.synthesize(text, voice, job["rate"], temp_path("")), []

        if engine == self.ENGINE_CLONE:
            return self._clone(job, text, lang), []

        chain = {self.ENGINE_EDGE: [("Edge", try_edge), ("Google", try_gtts), ("System", try_system)],
                 self.ENGINE_GTTS: [("Google", try_gtts), ("Edge", try_edge), ("System", try_system)],
                 self.ENGINE_SYSTEM: [("System", try_system), ("Edge", try_edge), ("Google", try_gtts)]}[engine]
        for i, (name, fn) in enumerate(chain):
            try:
                result = fn()
                if i > 0:
                    emit(f"{chain[0][0]} failed ({errors[0]}) — used {name} instead", "warn")
                return result
            except Exception as e:
                log.warning("%s TTS failed: %s", name, e)
                errors.append(f"{name}: {str(e).splitlines()[0] if str(e) else type(e).__name__}")
        raise RuntimeError("Couldn't generate speech — " + " | ".join(errors))

    def _clone(self, job, text, lang):
        emit = self.bridge.status.emit
        name = job["profile"]
        wav_path = os.path.join(PROFILES_DIR, f"{name}.wav")
        txt_path = os.path.join(PROFILES_DIR, f"{name}.txt")
        if not os.path.exists(wav_path):
            raise RuntimeError(f"Profile audio missing: {wav_path}")
        ref_text = ""
        if os.path.exists(txt_path):
            with open(txt_path, encoding="utf-8") as f:
                ref_text = f.read().strip()
        if lang and lang.split("-")[0] not in ("en", "zh"):
            emit(f"Heads-up: the clone model is trained on English/Chinese; {LANG_NAME.get(lang, lang)} may "
                 f"sound off", "warn")
            time.sleep(1.2)
        speed = max(0.5, min(2.0, 1 + job["rate"] / 100.0))
        # Same profile + text + settings -> reuse the earlier result instantly (cloning takes ~1 min on a CPU)
        key = hashlib.sha1(json.dumps([name, os.path.getmtime(wav_path), ref_text, text, job["nfe"], speed])
                           .encode("utf-8")).hexdigest()[:20]
        cache_dir = os.path.join(DATA_DIR, "clone_cache")
        os.makedirs(cache_dir, exist_ok=True)
        cached = os.path.join(cache_dir, key + ".wav")
        if os.path.exists(cached):
            emit("Using your earlier clone of this exact text ⚡", "ok")
            out = temp_path(".wav")
            shutil.copy2(cached, out)
            return out
        rate = self.store.get("clone/sec_per_char", 0.0, float)
        eta = f" — about {max(5, rate * len(text) * job['nfe'] / 8):.0f}s" if rate else ""

        def status(m):
            m = m + eta if m.startswith("Cloning") else m
            emit(m, "info")
            self.bridge.f5_state.emit(m)
        out = temp_path(".wav")
        t0 = time.time()
        ENGINES.f5_synthesize(text, wav_path, ref_text, job["nfe"], speed, out, status=status)
        spent = time.time() - t0
        # remember the speed (normalised to 8 steps) for next time's estimate
        self.store.set("clone/sec_per_char", round(spent / max(1, len(text)) * 8 / max(1, job["nfe"]), 4))
        self.bridge.f5_state.emit(f"Model ready on {ENGINES.f5_device} · last clip took {spent:.0f}s")
        try:
            shutil.copy2(out, cached)
            old = sorted((os.path.join(cache_dir, f) for f in os.listdir(cache_dir)), key=os.path.getmtime)
            for f in old[:-150]:
                os.remove(f)
        except OSError:
            pass
        return out

    def _play(self, path, env=None, duration=None):
        if env is None:
            env, duration = audio_envelope(path)
        self.bridge.envelope.emit(env, duration)
        self.bridge.playback.emit(True)
        self.bridge.status.emit("▶ Playing…", "ok")
        try:
            self.player.play_blocking(path)
        finally:
            self.bridge.playback.emit(False)

    def _on_audio_ready(self, info):
        if info.get("preview"):
            self.last_env, self.last_duration = info["env"], info["duration"]
            self.karaoke.set_words(info["words"])
            return
        self.last_audio = info["path"]
        self.last_words = info["words"]
        self.last_env, self.last_duration = info["env"], info["duration"]
        self.karaoke.set_words(info["words"])
        self.btn_replay.setEnabled(True)
        self.btn_save_audio.setEnabled(True)
        self.btn_subs.setEnabled(bool(info["words"]))
        title = info["text"].replace("\n", " ")
        words_json = json.dumps(info["words"], ensure_ascii=False)
        entry = self.history.add("audio", title, src_path=info["path"],
                                 meta={"engine": info["job"]["engine"], "voice": info["job"]["edge_voice"],
                                       "effect": info["job"]["effect"], "text": info["text"][:4000],
                                       "duration": info["duration"]},
                                 thumb=self._wave_thumb(info["env"]),
                                 extra_files={"words": (words_json, ".json")})
        self._history_changed()
        if info.get("estimated") and ENGINES.caps().get("whisper") and info["duration"] < 240:
            # this engine gave no word timings — let Whisper time the real audio in the background
            path, text, lang = info["path"], info["text"], info.get("lang")

            def work():
                try:
                    heard = ENGINES.word_timings(path, lang)
                    words = align_words(text, heard)
                    if words:
                        self.bridge.words_refined.emit(path, {"words": words, "entry": entry})
                except Exception as e:
                    log.info("Word timing refinement skipped: %s", e)
            threading.Thread(target=work, daemon=True).start()

    def _on_words_refined(self, path, data):
        words = data["words"]
        entry = data.get("entry")
        if entry:
            p = self.history.path(entry, "words")
            if p:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(words, f, ensure_ascii=False)
        if path == self.last_audio:
            self.last_words = words
            self.karaoke.set_words(words)
            if self.player.playing:
                self.karaoke.set_time(self.player.position())

    def _wave_thumb(self, env):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (180, 120), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, 179, 119], radius=16, fill=(30, 27, 75, 255))
        if env:
            n = 40
            step = max(1, len(env) // n)
            for i in range(n):
                v = max(env[i * step: i * step + step] or [0.05])
                h = 8 + v * 80
                x = 12 + i * 4
                d.rounded_rectangle([x, 60 - h / 2, x + 2, 60 + h / 2], radius=1, fill=(165, 180, 252, 255))
        return img

    def _av_tick(self):
        if self.player.playing:
            t = self.player.position()
            self.karaoke.set_time(t)
            if self.last_env and self.last_duration:
                i = int(t / self.last_duration * len(self.last_env))
                lv = self.last_env[i] if 0 <= i < len(self.last_env) else 0.0
                self.orb.set_level(lv)
                if hasattr(self, "pill") and self.pill.isVisible():
                    self.pill.orb.set_level(lv)

    def _on_playback(self, playing):
        if playing:
            self.btn_stop.setEnabled(True)
            self.orb.set_mode("play")
            self.orb_label.setText("Speaking…")
            self.btn_pause.setText("⏸ Pause")
        else:
            self.waveform.stop()
            self.orb.set_mode("idle")
            self.orb_label.setText("Ready when you are")
            self.karaoke.finish()
            self.btn_pause.setText("⏯ Pause")
            if hasattr(self, "pill"):
                self.pill.fade_out()
            if not self.is_recording:
                self.set_status("Done — replay, save audio or export subtitles anytime", "ok")

    def _on_busy(self, busy):
        self.is_busy = busy
        self.btn_speak.setEnabled(not busy)
        self.btn_speak.setText("⏳ Working…" if busy else "⚡ Speak  (Ctrl+Enter)")
        if busy:
            self.waveform.busy()
            self.orb.set_mode("busy")
            self.orb_label.setText("Thinking…")
            if hasattr(self, "pill") and self.pill.isVisible():
                self.pill.orb.set_mode("busy")
        elif not self.player.playing:
            self.orb.set_mode("idle")
            self.orb_label.setText("Ready when you are")

    def toggle_pause(self):
        if self.player.toggle_pause():
            self.btn_pause.setText("▶ Resume" if self.player.paused else "⏸ Pause")
            self.orb.set_mode("idle" if self.player.paused else "play")

    def stop_audio(self):
        self._job_seq += 1  # anything still rendering won't auto-play
        self.player.stop()
        self.waveform.stop()
        self.orb.set_mode("idle")
        if hasattr(self, "pill"):
            self.pill.fade_out()

    def replay(self):
        if self.last_audio and os.path.exists(self.last_audio):
            self.player.stop()
            self.karaoke.set_words(self.last_words)
            threading.Thread(target=self._play, args=(self.last_audio,), daemon=True).start()

    def save_audio(self):
        if not self.last_audio or not os.path.exists(self.last_audio):
            self.set_status("Generate some speech first", "warn")
            return
        ext = os.path.splitext(self.last_audio)[1].lower()
        fmts = [(f"Original ({ext[1:].upper()})", ext)] + [f for f in export_formats() if f[1] != ext]
        filters = ";;".join(f"{label} (*{e})" for label, e in fmts)
        path, flt = QFileDialog.getSaveFileName(self, "Save audio", f"speech{ext}", filters)
        if not path:
            return
        chosen = next((e for label, e in fmts if flt.startswith(label)), ext)
        if not os.path.splitext(path)[1]:
            path += chosen
        try:
            convert_audio(self.last_audio, path)
            self.set_status(f"Saved {os.path.basename(path)}", "ok", toast=True)
        except Exception as e:
            self.set_status(f"Save failed: {e}", "error")

    def export_subtitles(self):
        if not self.last_words:
            self.set_status("Speak something first — subtitles come from the last clip", "warn")
            return
        path, flt = QFileDialog.getSaveFileName(self, "Export subtitles", "subtitles.srt",
                                                "SubRip (*.srt);;WebVTT (*.vtt)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".vtt" if "vtt" in flt.lower() else ".srt"
        data = to_vtt(self.last_words) if path.lower().endswith(".vtt") else to_srt(self.last_words)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
        self.set_status(f"Subtitles saved: {os.path.basename(path)} — import it with the audio in any editor",
                        "ok", toast=True)

    # ----------------------------------------------------- voice profiles
    def refresh_profiles(self, select=None):
        current = select or self.profile_combo.currentData()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        names = sorted(os.path.splitext(f)[0] for f in os.listdir(PROFILES_DIR) if f.lower().endswith(".wav"))
        for n in names:
            self.profile_combo.addItem(n, n)
        if not names:
            self.profile_combo.addItem("No profiles yet — record one below", None)
        idx = self.profile_combo.findData(current)
        self.profile_combo.setCurrentIndex(max(0, idx))
        self.profile_combo.blockSignals(False)
        self._on_profile_selected()

    def _on_profile_selected(self):
        name = self.profile_combo.currentData()
        if not name:
            self.profile_info.setText("")
            return
        txt = os.path.join(PROFILES_DIR, f"{name}.txt")
        transcript = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                transcript = f.read().strip()
        dur = ""
        try:
            with wave.open(os.path.join(PROFILES_DIR, f"{name}.wav"), "rb") as w:
                dur = f"{w.getnframes() / float(w.getframerate()):.1f}s · "
        except Exception:
            pass
        self.profile_info.setText(f"{dur}Transcript: “{transcript or 'auto-transcribe'}”")

    def delete_profile(self):
        name = self.profile_combo.currentData()
        if not name:
            return
        if QMessageBox.question(self, "Delete profile", f"Delete voice profile “{name}”?") != \
                QMessageBox.StandardButton.Yes:
            return
        for ext in (".wav", ".txt"):
            try:
                os.remove(os.path.join(PROFILES_DIR, name + ext))
            except OSError:
                pass
        self.refresh_profiles()
        self.set_status(f"Deleted profile {name}", "ok")

    def _profile_name(self, fallback="MyVoice"):
        raw = self.profile_name.text().strip() or fallback
        return re.sub(r"[^\w\-]+", "_", raw).strip("_") or "MyVoice"

    def toggle_recording(self):
        if self.is_recording:
            self.is_recording = False
            return
        self.player.stop()
        self.is_recording = True
        threading.Thread(target=self._record_worker, args=(self._profile_name(), self.ref_text.text().strip()),
                         daemon=True).start()

    def _on_recording_state(self, on):
        self.btn_record.setText("⏹ Stop recording" if on else "🔴 Record")
        self.orb.set_mode("record" if on else "idle")
        if not on:
            self.is_recording = False
            self.waveform.stop()

    def _record_worker(self, name, transcript):
        sr, max_sec = 24000, 15
        chunks = []
        self.bridge.recording.emit(True)
        try:
            def callback(indata, frames, time_info, status):
                chunks.append(indata.copy())
                self.bridge.level.emit(float(np.sqrt(np.mean(indata ** 2))))

            start = time.monotonic()
            with sd.InputStream(samplerate=sr, channels=1, dtype="float32", callback=callback, blocksize=1200):
                while self.is_recording and time.monotonic() - start < max_sec:
                    left = max_sec - (time.monotonic() - start)
                    self.bridge.status.emit(f"🎙 Recording… speak now ({left:.0f}s left, press Stop when done)",
                                            "error")
                    time.sleep(0.25)
            if not chunks:
                raise RuntimeError("No audio captured — check microphone permissions")
            self._save_profile(name, transcript, np.concatenate(chunks).reshape(-1), sr)
        except Exception as e:
            log.exception("Recording failed")
            self.bridge.status.emit(f"Recording error: {e}", "error")
        finally:
            self.bridge.recording.emit(False)

    def _save_profile(self, name, transcript, audio, sr):
        audio = resample(audio, sr, 24000)
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        if peak < 0.01:
            raise RuntimeError("That was silent — is the right microphone selected?")
        loud = np.where(np.abs(audio) > max(0.01, peak * 0.06))[0]
        pad = int(0.2 * 24000)
        audio = audio[max(0, loud[0] - pad): min(len(audio), loud[-1] + pad)]
        if len(audio) < 24000 * 2:
            raise RuntimeError("Too short — record at least 3 seconds of speech")
        audio = audio[: 24000 * 15]
        audio = audio * (0.9 / max(1e-6, float(np.max(np.abs(audio)))))
        wav_path = os.path.join(PROFILES_DIR, f"{name}.wav")
        write_wav(wav_path, audio, 24000)
        if not transcript and ENGINES.caps().get("whisper"):
            # an exact transcript makes cloning faster and better than F5's own (much larger) transcriber
            try:
                self.bridge.status.emit("Writing down what you said (offline)…", "info")
                transcript, _ = ENGINES.transcribe_whisper(wav_path, None, "base")
            except Exception as e:
                log.warning("Profile auto-transcribe failed: %s", e)
        with open(os.path.join(PROFILES_DIR, f"{name}.txt"), "w", encoding="utf-8") as f:
            f.write(transcript)
        self.bridge.profiles_changed.emit(name)
        self.bridge.status.emit(f"Voice profile “{name}” saved ({len(audio) / 24000:.1f}s)", "ok")

    def import_profile_audio(self, path=None):
        if not HAS_NP:
            self.set_status("Importing needs numpy:  pip install numpy", "warn")
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Choose a voice sample", "",
                                                  "Audio (*.wav *.mp3 *.flac *.ogg)")
        if not path:
            return
        name = self._profile_name(os.path.splitext(os.path.basename(path))[0])
        transcript = self.ref_text.text().strip()

        def work():
            try:
                data, sr = read_audio_mono(path)
                self._save_profile(name, transcript, data.astype(np.float32), sr)
            except Exception as e:
                self.bridge.status.emit(f"Import failed: {e}", "error")
        threading.Thread(target=work, daemon=True).start()

    def load_f5(self):
        def work():
            try:
                ENGINES.f5_load(lambda m: (self.bridge.status.emit(m, "info"), self.bridge.f5_state.emit(m)))
                self.bridge.f5_state.emit(f"Model ready on {ENGINES.f5_device}")
                self.bridge.status.emit("Voice-cloning model ready", "ok")
            except Exception as e:
                log.exception("F5 load failed")
                self.bridge.f5_state.emit(f"Load failed: {e}")
                self.bridge.status.emit(f"Clone model error: {e}", "error")
        threading.Thread(target=work, daemon=True).start()
