"""Built-in end-to-end self-test.  Runs the real window, clicks through every feature and checks the results.

    Studio Vision AI.exe --selftest report.json [--quick]      (or: python studio_vision.pyw --selftest …)

It runs in a sandbox data folder with its own settings, mutes playback, and answers every file dialog itself,
so it never touches your history, settings or files."""

import json
import os
import sys
import tempfile
import time
import traceback
import xml.dom.minidom

from PIL import Image
from PyQt6.QtCore import QMimeData, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox

RESULTS = []
ERRORS = []
STATUS_ERRORS = []


class Skip(Exception):
    pass


def pump(sec=0.05):
    app = QApplication.instance()
    end = time.time() + sec
    while True:
        app.processEvents()
        if time.time() >= end:
            break
        time.sleep(0.01)


class FailNow(AssertionError):
    pass


def raise_now(msg):
    raise FailNow(f"app reported an error: {msg}")


def wait(pred, timeout=30, what="condition"):
    end = time.time() + timeout
    while time.time() < end:
        pump(0.03)
        try:
            if pred():
                return True
        except FailNow:
            raise
        except Exception:
            pass
    raise AssertionError(f"timed out after {timeout}s waiting for {what}")


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


class Harness:
    def __init__(self, win, out_dir, quick):
        self.w, self.out, self.quick = win, out_dir, quick
        self.audio = []
        self.scans = []
        self.opened = []
        self.done = []
        self.next_save = None
        self.next_open = None
        self.next_dir = None
        b = win.bridge
        b.audio_ready.connect(lambda info: self.audio.append(info))
        b.done_files.connect(lambda folder, files: self.done.append((folder, files)))
        b.status.connect(lambda t, k: STATUS_ERRORS.append(t) if k == "error" else None)
        self.statuses = []
        b.status.connect(lambda t, k: self.statuses.append(t))
        self.refined = []
        b.words_refined.connect(lambda path, data: self.refined.append((path, data["words"])))
        self._patch()

    # -- dialogs answer themselves ---------------------------------------------------
    def _patch(self):
        h = self

        def save(*a, **k):
            p, h.next_save = h.next_save, None
            return (p or "", "")

        def open_(*a, **k):
            p, h.next_open = h.next_open, None
            return (p or "", "")

        def folder(*a, **k):
            p, h.next_dir = h.next_dir, None
            return p or ""
        QFileDialog.getSaveFileName = staticmethod(save)
        QFileDialog.getOpenFileName = staticmethod(open_)
        QFileDialog.getExistingDirectory = staticmethod(folder)
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        QDesktopServices.openUrl = staticmethod(lambda url: h.opened.append(url.toString()) or True)
        QMenu.exec = lambda self, *a, **k: None

        from . import tab_qr
        tab_qr.ScanResultDialog.exec = lambda dlg: (h.scans.append(getattr(dlg, "_texts", None)), dlg.accept())[-1]
        orig_init = tab_qr.ScanResultDialog.__init__

        def init(dlg, parent, texts, on_edit=None):
            orig_init(dlg, parent, texts, on_edit)
            dlg._texts = texts
        tab_qr.ScanResultDialog.__init__ = init

        def batch_exec(dlg):
            dlg.show()
            pump(0.1)
            dlg.run()
            pump(0.1)
            dlg.accept()
        tab_qr.BatchDialog.exec = batch_exec

        def webcam_exec(dlg):
            dlg.show()
            pump(2.0)
            dlg.reject()
        tab_qr.WebcamDialog.exec = webcam_exec

        def generic_exec(dlg):
            dlg.show()
            pump(0.4)
            dlg.accept()
            return 1
        from . import app as appmod
        from .widgets import CommandPalette
        appmod.SettingsDialog.exec = generic_exec
        CommandPalette.exec = generic_exec
        QMessageBox.exec = lambda box: 0
        QMessageBox.about = staticmethod(lambda *a, **k: None)

    def path(self, name):
        return os.path.join(self.out, name)

    # -- helpers -------------------------------------------------------------------------
    def speak_and_wait(self, timeout=60, **kw):
        n = len(self.audio)
        errs = len(STATUS_ERRORS)
        self.w.speak(**kw)

        def done():
            if len(STATUS_ERRORS) > errs:  # fail fast with the real error instead of a long timeout
                raise_now(STATUS_ERRORS[-1])
            return len(self.audio) > n
        wait(done, timeout, "speech audio")
        info = self.audio[-1]
        check(os.path.exists(info["path"]), "audio file missing")
        check(info["duration"] > 0.3, f"audio too short ({info['duration']:.2f}s)")
        wait(lambda: not self.w.is_busy, 10, "engine to finish")
        self.w.stop_audio()
        return info

    def qr_wait(self):
        g = self.w._gen["qr"]
        self.w.generate_qr()
        wait(lambda: self.w._gen["qr"] > g and self.w.qr_image is not None and not self.w.qr_preview._busy, 30,
             "QR render")
        pump(0.1)
        return self.w.qr_image


# ---------------------------------------------------------------------------------------------
# The tests
# ---------------------------------------------------------------------------------------------


def t_startup(h):
    w = h.w
    wait(lambda: w.all_built, 30, "all tabs to build")
    check(w.tabs.count() == 6, "expected 6 tabs")
    wait(lambda: len(w.edge_voice_list) > 100, 40, "Edge voice catalogue")
    wait(lambda: len(w.fonts) > 10, 40, "font discovery")
    wait(lambda: w.player.wait_ready(1) is not None, 20, "audio device")
    w.player.volume = 0.0
    return f"{len(w.edge_voice_list)} voices, {len(w.fonts)} fonts, audio backend {w.player.backend}"


def t_tabs_render(h):
    for i in range(h.w.tabs.count()):
        h.w.tabs.setCurrentIndex(i)
        pump(0.6)
        h.w.grab().save(h.path(f"tab_{i}.png"))
    h.w.tabs.setCurrentIndex(0)
    return "6 tabs rendered"


def t_voice_edge(h):
    w = h.w
    w.dialogue.setChecked(False)
    w.engine.setCurrentIndex(0)
    w.target_lang.setCurrentIndex(0)
    w.effect.setCurrentIndex(0)
    w.bg_music.setCurrentIndex(0)
    w.textbox.setPlainText("Testing one two three. Studio Vision is ready.")
    info = h.speak_and_wait()
    check(len(info["words"]) >= 6, f"expected word timings, got {len(info['words'])}")
    check(w.btn_subs.isEnabled(), "subtitle button should be enabled")
    h.edge_audio = info["path"]
    return f"{len(info['words'])} timed words, {info['duration']:.1f}s"


def t_voice_translate(h):
    from .core import guess_lang
    w = h.w
    w.textbox.setPlainText("Good morning, how are you today?")
    w.target_lang.setCurrentIndex(w.target_lang.findData("ur"))
    info = h.speak_and_wait()
    t = w.trans_box.toPlainText()
    check(guess_lang(t) == "ur", f"translation isn't Urdu: {t!r}")
    w.target_lang.setCurrentIndex(0)
    return f"Urdu: {t[:30]}…, {info['duration']:.1f}s"


def t_language_detect(h):
    from .core import detect_language
    w = h.w
    cases = {"Hola, ¿cómo estás? Me llamo Ana y vivo en Madrid.": "es",
             "Bonjour, je m'appelle Marie et j'habite à Paris.": "fr",
             "Guten Morgen, wie geht es dir heute?": "de", "میرا نام علی ہے": "ur",
             "Hello there, how are you doing today?": "en"}
    for text, want in cases.items():
        got = detect_language(text)
        check(got == want, f"detected {got!r} for {want} text")
    w.engine.setCurrentIndex(0)
    w.target_lang.setCurrentIndex(0)
    w.auto_voice.setChecked(True)
    w.edge_voice.setCurrentIndex(max(0, w.edge_voice.findData("en-US-AriaNeural")))
    h.statuses.clear()
    w.textbox.setPlainText("Hola, ¿cómo estás? Me llamo Ana y vivo en Madrid.")
    h.speak_and_wait()
    switched = [s for s in h.statuses if "Auto-switched" in s]
    check(switched and "es-" in switched[-1], f"Spanish text didn't get a Spanish voice: {switched}")
    return f"5 languages detected; Spanish text → {switched[-1].split(' to ')[1].split(' so')[0]}"


def t_karaoke_refine(h):
    from .speech import ENGINES
    if not ENGINES.caps()["whisper"]:
        raise Skip("Whisper not installed")
    w = h.w
    w.engine.setCurrentIndex(1)  # Google voice: gives no word timings of its own
    h.refined.clear()
    w.textbox.setPlainText("One two three four five six seven eight.")
    info = h.speak_and_wait()
    wait(lambda: any(p == info["path"] for p, _ in h.refined), 90, "Whisper word timings")
    words = [ws for p, ws in h.refined if p == info["path"]][-1]
    w.engine.setCurrentIndex(0)
    check(len(words) == 8, f"expected 8 timed words, got {len(words)}")
    starts = [s for s, _, _ in words]
    check(starts == sorted(starts) and starts[-1] > starts[0] + 0.5, "timings aren't increasing")
    check(w.last_words == words, "karaoke didn't pick up the refined timings")
    return "Google voice words timed by Whisper: " + ", ".join(f"{t}@{s:.2f}" for s, _, t in words[:4]) + "…"


def t_edge_fallback_route(h):
    from .core import temp_path
    from .speech import ENGINES
    caps = ENGINES.caps()
    if not (ENGINES.external and ENGINES.ext_caps.get("edge")):
        raise Skip("no outside Python with edge-tts (only used by the packaged app)")
    p, words = ENGINES.edge_external("Backup route check.", "en-US-AriaNeural", 0, 0, temp_path(".mp3"))
    check(os.path.getsize(p) > 1000 and len(words) >= 3, "external Edge produced nothing")
    return f"repair/fallback route works via {caps.get('external')}"


def t_wheel_guard(h):
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent
    w = h.w
    w.tabs.setCurrentWidget(w.voice_page)
    pump(0.3)
    targets = {"voice engine dropdown": w.engine, "voice dropdown": w.edge_voice, "speed slider": w.rate_slider,
               "target language": w.target_lang, "QR border box": w.qr_border, "logo seed box": w.logo_seed}
    for name, wd in targets.items():
        before = wd.currentIndex() if hasattr(wd, "currentIndex") else wd.value()
        for delta in (-120, 120, -360):
            ev = QWheelEvent(QPointF(5, 5), QPointF(wd.mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, delta),
                             Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
                             False)
            QApplication.sendEvent(wd, ev)
            pump(0.02)
        after = wd.currentIndex() if hasattr(wd, "currentIndex") else wd.value()
        check(before == after, f"scrolling over the {name} changed it ({before} → {after})")
    return f"scroll wheel leaves {len(targets)} dropdowns/sliders/boxes alone"


def t_voice_gtts(h):
    h.w.engine.setCurrentIndex(1)
    h.w.textbox.setPlainText("Google voice check.")
    info = h.speak_and_wait()
    h.w.engine.setCurrentIndex(0)
    return f"{info['duration']:.1f}s"


def t_voice_system(h):
    w = h.w
    wait(lambda: w.system_voices, 40, "system voices")
    w.engine.setCurrentIndex(3)
    w.textbox.setPlainText("System voice check.")
    info = h.speak_and_wait()
    w.engine.setCurrentIndex(0)
    return f"{len(w.system_voices)} system voices, {info['duration']:.1f}s"


def t_voice_effects(h):
    w = h.w
    w.textbox.setPlainText("Effects and music check.")
    out = []
    for eff, bg in ((1, 0), (6, 1), (4, 2), (9, 3)):
        w.effect.setCurrentIndex(eff)
        w.bg_music.setCurrentIndex(bg)
        info = h.speak_and_wait()
        out.append(f"{w.effect.currentText().split(' ', 1)[-1]}+{w.bg_music.currentText().split(' ', 1)[-1]}")
        check(info["words"], "effects lost the word timings")
    w.effect.setCurrentIndex(0)
    w.bg_music.setCurrentIndex(0)
    return ", ".join(out)


def t_voice_dialogue(h):
    w = h.w
    w._insert_sample_dialogue()
    pump(0.6)
    check(len(w.cast_combos) == 3, f"expected 3 speakers, got {list(w.cast_combos)}")
    voices = {c.currentData() for c in w.cast_combos.values()}
    check(len(voices) >= 2, "speakers should get different voices")
    info = h.speak_and_wait(timeout=120)
    check(len(info["words"]) > 20, "dialogue words missing")
    w.dialogue.setChecked(False)
    return f"3 speakers, {len(voices)} distinct voices, {info['duration']:.1f}s"


def t_voice_exports(h):
    w = h.w
    w.textbox.setPlainText("Export check one two.")
    h.speak_and_wait()
    made = []
    for ext in (".srt", ".vtt"):
        h.next_save = h.path("subs" + ext)
        w.export_subtitles()
        data = open(h.next_save or h.path("subs" + ext), encoding="utf-8").read()
        check("-->" in data, f"{ext} has no cues")
        made.append(ext)
    from .audio import export_formats, read_audio_mono
    for _, ext in [("orig", os.path.splitext(w.last_audio)[1])] + export_formats():
        p = h.path("speech" + ext)
        h.next_save = p
        w.save_audio()
        check(os.path.exists(p) and os.path.getsize(p) > 1000, f"audio export {ext} failed")
        data, sr = read_audio_mono(p)
        check(len(data) > sr * 0.3, f"{ext} export is empty")
        made.append(ext)
    return " ".join(made)


def t_voice_replay_pause(h):
    w = h.w
    w.player.volume = 0.0
    w.replay()
    wait(lambda: w.player.playing, 10, "replay to start")
    pump(0.3)
    if w.player.backend == "pygame":
        w.toggle_pause()
        check(w.player.paused, "pause didn't pause")
        t = w.player.position()
        pump(0.4)
        check(abs(w.player.position() - t) < 0.05, "clock moved while paused")
        w.toggle_pause()
        check(not w.player.paused, "resume failed")
    pump(0.3)
    check(w.karaoke.idx >= 0, "karaoke never highlighted a word")
    w.stop_audio()
    wait(lambda: not w.player.playing, 5, "stop")
    return f"karaoke at word {w.karaoke.idx}"


def t_voice_preview_and_text(h):
    w = h.w
    n = len(h.audio)
    w.preview_voice()
    wait(lambda: len(h.audio) > n, 40, "voice preview")
    w.stop_audio()
    p = h.path("script.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("Loaded from a text file.")
    w.open_text_file(p)
    check(w.textbox.toPlainText() == "Loaded from a text file.", "text file didn't load")
    return "preview + .txt load ok"


def t_voice_clone(h):
    from .speech import ENGINES
    if h.quick:
        raise Skip("quick mode")
    if not ENGINES.caps()["f5"]:
        raise Skip("F5-TTS not installed")
    w = h.w
    w.profile_name.setText("SelfTest")
    w.ref_text.setText("")
    w.import_profile_audio(h.edge_audio)
    wait(lambda: w.profile_combo.findData("SelfTest") >= 0, 120, "profile import (+ auto transcript)")
    from .core import PROFILES_DIR
    transcript = open(os.path.join(PROFILES_DIR, "SelfTest.txt"), encoding="utf-8").read().strip()
    w.profile_combo.setCurrentIndex(w.profile_combo.findData("SelfTest"))
    w.engine.setCurrentIndex(2)
    w.f5_quality.setCurrentIndex(0)
    w.textbox.setPlainText("Hello from my cloned voice.")
    t = time.time()
    h.speak_and_wait(timeout=900)
    first = time.time() - t
    t = time.time()
    h.speak_and_wait(timeout=60)
    again = time.time() - t
    check(again < 8, f"repeat clone should come from the cache, took {again:.0f}s")
    # new text: uses the saved speed figure for a time estimate (this path once crashed)
    h.statuses.clear()
    w.textbox.setPlainText("A second sentence, never cloned before.")
    t = time.time()
    h.speak_and_wait(timeout=900)
    second = time.time() - t
    eta = [s for s in h.statuses if "about" in s and "Cloning" in s]
    w.engine.setCurrentIndex(0)
    check(eta, "no time estimate was shown for the second clone")
    return (f"cloned in {first:.0f}s, repeat {again:.1f}s from cache, new text {second:.0f}s with estimate "
            f"“{eta[-1].split('—')[-1].strip()}”, auto-transcript: {transcript[:30]!r}")


def t_interp_typed(h):
    w = h.w
    w.tabs.setCurrentWidget(w.interp_page_w)
    w.i_speak.setChecked(True)
    w.src_lang.setCurrentIndex(w.src_lang.findData("en"))
    w.dst_lang.setCurrentIndex(w.dst_lang.findData("ur"))
    n_chat, n_audio = len(w.chat.items), len(h.audio)
    w.type_box.setText("Where is the train station?")
    w.interp_typed()
    wait(lambda: len(w.chat.items) > n_chat, 40, "chat bubble")
    wait(lambda: len(h.audio) > n_audio, 40, "translated speech")
    wait(lambda: w.btn_talk.isEnabled(), 30, "interpreter to go idle")
    w.stop_audio()
    o, t, s, d = w.chat.items[-1]
    w.interp_swap()
    check(w.src_lang.currentData() == "ur" and w.dst_lang.currentData() == "en", "swap failed")
    w.interp_swap()
    h.next_save = h.path("chat.txt")
    w.export_chat()
    check(os.path.getsize(h.path("chat.txt")) > 10, "chat export empty")
    return f"{o} → {t}"


def t_interp_recognition(h):
    from .audio import load_work, resample, WORK_SR
    from .core import HAS_SR
    from .speech import ENGINES, transcribe
    x = resample(load_work(h.edge_audio), WORK_SR, 16000)
    out = []
    if ENGINES.caps()["whisper"]:
        text, lang, eng = transcribe(x, 16000, None, "whisper", "base")
        check("three" in text.lower() or "testing" in text.lower(), f"Whisper heard {text!r}")
        out.append(f"Whisper: {text!r} ({lang})")
    if HAS_SR:
        text, lang, eng = transcribe(x, 16000, "en", "google")
        check(eng.startswith("Google"), f"expected Google, got {eng}")
        check("testing" in text.lower() or "three" in text.lower(), f"Google heard {text!r}")
        out.append(f"Google: {text!r}")
    if not out:
        raise Skip("no recogniser installed")
    return " | ".join(out)


def t_interp_mic(h):
    from .core import HAS_SD
    w = h.w
    if not HAS_SD:
        raise Skip("sounddevice not installed")
    try:
        import sounddevice as sd
        if sd.query_devices(kind="input") is None:
            raise Skip("no microphone")
    except Exception as e:
        raise Skip(f"no microphone ({e})")
    w.i_auto.setChecked(False)
    w.interp_toggle()
    wait(lambda: w.i_listening, 5, "listening to start")
    pump(1.2)
    w.interp_toggle()
    wait(lambda: w.btn_talk.isEnabled() and not w.i_listening, 90, "interpreter to finish")
    w.i_auto.setChecked(True)
    return "microphone opened, recorded and closed cleanly"


QR_SAMPLES = {
    0: {"text": "https://studiovision.example/test"},
    1: {"ssid": "Home WiFi", "wifi_pass": "pa;ss:word", "wifi_sec": "WPA"},
    2: {"email": "hello@example.com", "subject": "Hi there", "body": "Testing"},
    3: {"phone": "+92 300 1234567"},
    4: {"sms_to": "+923001234567", "sms_body": "Salam"},
    5: {"wa_phone": "+92 300 1234567", "wa_text": "Hello!"},
    6: {"first": "Alex", "last": "Khan", "org": "Studio Vision", "vphone": "+923001234567"},
    7: {"lat": "31.5204", "lon": "74.3587"},
    8: {"ev_title": "Launch party", "ev_start": "2026-11-02 18:00", "ev_end": "2026-11-02 21:00"},
}


def _fill_qr(w, kind, vals):
    from PyQt6.QtWidgets import QCheckBox, QComboBox
    w.qr_type.setCurrentIndex(kind)
    for k, v in vals.items():
        f = w.qr_fields[k]
        if isinstance(f, QComboBox):
            f.setCurrentText(v)
        elif isinstance(f, QCheckBox):
            f.setChecked(bool(v))
        else:
            f.setText(v)


def t_qr_types(h):
    from .qrtools import verify_qr
    w = h.w
    w.tabs.setCurrentWidget(w.qr_page)
    w.qr_module.setCurrentText("Square")
    w.qr_color_mode.setCurrentText("Solid")
    w.clear_qr_logo()
    w.clear_qr_art()
    w.qr_caption.setText("")
    for kind, vals in QR_SAMPLES.items():
        _fill_qr(w, kind, vals)
        img = h.qr_wait()
        payload = w._qr_payload()
        check(payload, f"type {kind} built no payload")
        check(verify_qr(img, payload), f"type {kind} doesn't decode back")
    return f"{len(QR_SAMPLES)} content types encode + decode"


def t_qr_styles(h):
    from .qrtools import QR_DRAWERS, QR_MASKS, render_qr, verify_qr
    w = h.w
    _fill_qr(w, 0, QR_SAMPLES[0])
    spec = w._qr_spec()
    bad = []
    n = 0
    for mod in QR_DRAWERS:
        for eye in ("Square", "Rounded", "Dots", "Gapped"):
            for mode in QR_MASKS:
                if eye not in ("Square", "Rounded") and mode not in ("Solid", "Radial Gradient"):
                    continue
                s = dict(spec, module=mod, eye=eye, color_mode=mode, fg="#1E1B4B", fg2="#7C3AED")
                img, _ = render_qr(s)
                n += 1
                if not verify_qr(img, s["payload"]):
                    bad.append(f"{mod}/{eye}/{mode}")
    check(len(bad) <= n // 10, f"{len(bad)}/{n} style combos don't scan: {bad[:6]}")
    return f"{n - len(bad)}/{n} style combos verified scannable" + (f" (weak: {', '.join(bad)})" if bad else "")


def t_qr_logo_caption_art(h):
    from .qrtools import verify_qr
    w = h.w
    w.qr_caption.setText("SCAN ME")
    w.use_studio_logo_in_qr()
    img = h.qr_wait()
    check(verify_qr(img, w._qr_payload()), "logo+caption QR doesn't scan")
    w.clear_qr_logo()
    photo = h.path("photo.png")
    Image.radial_gradient("L").resize((500, 500)).convert("RGB").save(photo)
    try:
        for mod in ("Square", "Dots", "Rounded"):
            w.qr_module.setCurrentText(mod)
            w.select_qr_art(photo)
            img = h.qr_wait()
            check(verify_qr(img, w._qr_payload()), f"picture QR ({mod}) doesn't scan")
    finally:
        w.clear_qr_art()
        w.qr_caption.setText("")
        w.qr_module.setCurrentText("Square")
    return "logo + caption + picture QR (3 dot styles) all scan"


def t_qr_exports(h):
    from .qrtools import decode_image
    w = h.w
    _fill_qr(w, 0, QR_SAMPLES[0])
    h.qr_wait()
    payload = w._qr_payload()
    out = []
    for ext in (".png", ".jpg", ".webp", ".pdf", ".svg"):
        p = h.path("qr" + ext)
        h.next_save = p
        w.save_qr()
        check(os.path.exists(p) and os.path.getsize(p) > 300, f"QR {ext} not written")
        if ext in (".png", ".jpg", ".webp"):
            check(payload in decode_image(Image.open(p)), f"saved {ext} doesn't scan")
        if ext == ".svg":
            xml.dom.minidom.parse(p)
            try:
                from PyQt6.QtGui import QImage, QPainter
                from PyQt6.QtSvg import QSvgRenderer
                r = QSvgRenderer(p)
                img = QImage(800, 800, QImage.Format.Format_ARGB32)
                img.fill(0xFFFFFFFF)
                qp = QPainter(img)
                r.render(qp)
                qp.end()
                png = h.path("svg_render.png")
                img.save(png)
                check(payload in decode_image(Image.open(png)), "SVG renders but doesn't scan")
                out.append("svg(scans)")
                continue
            except ImportError:
                pass
        out.append(ext[1:])
    p = h.path("qr_anim.gif")
    h.next_save = p
    w.save_qr_animation()
    wait(lambda: os.path.exists(p) and os.path.getsize(p) > 5000, 90, "animated QR")
    pump(1.0)
    gif = Image.open(p)
    check(getattr(gif, "n_frames", 1) >= 20, "animation has too few frames")
    gif.seek(10)
    check(payload in decode_image(gif.convert("RGB")), "animation frame doesn't scan")
    out.append(f"gif({gif.n_frames} frames, scans)")
    return " ".join(out)


def t_qr_scanning(h):
    from PyQt6.QtGui import QImage
    w = h.w
    _fill_qr(w, 0, QR_SAMPLES[0])
    h.qr_wait()
    payload = w._qr_payload()
    h.scans.clear()
    w.scan_file(h.path("qr.png"))
    check(h.scans and h.scans[-1] and payload in h.scans[-1], "scan from file failed")
    QApplication.clipboard().setImage(QImage(h.path("qr.png")))
    pump(0.2)
    w.scan_clipboard()
    check(len(h.scans) >= 2 and payload in h.scans[-1], "scan from clipboard failed")
    blank = h.path("blank.png")
    Image.new("RGB", (300, 300), "white").save(blank)
    n = len(h.scans)
    w.scan_file(blank)
    check(len(h.scans) == n, "blank image should not produce a result")
    w._load_payload_into_qr("WIFI:T:WPA;S:Cafe;P:secret;;")
    check(w.qr_type.currentIndex() == 1 and w.qr_fields["ssid"].text() == "Cafe", "restyle-from-scan failed")
    w.scan_webcam()
    return "file, clipboard, blank-image and webcam dialog ok"


def t_qr_batch(h):
    from .qrtools import decode_image
    w = h.w
    _fill_qr(w, 0, QR_SAMPLES[0])
    csv_path = h.path("people.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("name,link\nAli,https://a.example\nSara,https://s.example\nZed,https://z.example\n")
    h.done.clear()
    folder = h.path("batch")
    os.makedirs(folder, exist_ok=True)
    h.next_open = csv_path
    h.next_dir = folder
    from . import tab_qr
    orig = tab_qr.BatchDialog.__init__

    def init(dlg, *a, **k):
        orig(dlg, *a, **k)
        dlg.content.setCurrentIndex(1)
        dlg.name.setCurrentIndex(1)
    tab_qr.BatchDialog.__init__ = init
    try:
        w.batch_qr()
        wait(lambda: h.done, 60, "batch to finish")
    finally:
        tab_qr.BatchDialog.__init__ = orig
    files = h.done[-1][1]
    check(len(files) == 3, f"expected 3 files, got {len(files)}")
    check("https://s.example" in decode_image(Image.open([f for f in files if "Sara" in f][0])), "batch QR wrong")
    return ", ".join(os.path.basename(f) for f in files)


def t_qr_privacy(h):
    keys = h.w.store.s.allKeys()
    check(not any("wifi_pass" in k for k in keys), "Wi-Fi password was saved to settings!")
    return "Wi-Fi password never stored"


def t_logo_styles(h):
    from .graphics import LOGO_STYLES
    w = h.w
    w.tabs.setCurrentWidget(w.logo_page)
    for style in LOGO_STYLES:
        w.logo_style.setCurrentText(style)
        g = w._gen["logo"]
        w.generate_logo()
        wait(lambda: w._gen["logo"] > g and w.logo_spec and w.logo_spec["style"] == style and
             not w.logo_preview._busy, 30, f"logo {style}")
    for layout in ("Icon above text", "Icon beside text", "Icon only", "Text only"):
        w.logo_layout.setCurrentText(layout)
        w.generate_logo()
        wait(lambda: w.logo_spec["layout"] == layout and not w.logo_preview._busy, 30, f"layout {layout}")
    w.logo_layout.setCurrentText("Icon above text")
    return f"{len(LOGO_STYLES)} styles × 4 layouts rendered"


def t_logo_generate(h):
    w = h.w
    g = w._gen["var"]
    w.logo_variations()
    wait(lambda: w._gen["var"] > g and len(w.variation_specs) == 6, 60, "variations")
    pump(0.8)
    w.apply_variation(2)
    check(w.logo_style.currentText() == w.variation_specs[2]["style"], "variation not applied")
    w.surprise_logo()
    wait(lambda: not w.logo_preview._busy, 30, "surprise logo")
    return "variations + apply + surprise ok"


def t_logo_exports(h):
    w = h.w
    wait(lambda: w.logo_image is not None, 30, "logo")
    out = []
    for ext in (".png", ".ico", ".jpg", ".webp"):
        p = h.path("logo" + ext)
        h.next_save = p
        w.save_logo()
        check(os.path.exists(p) and os.path.getsize(p) > 500, f"logo {ext} not written")
        Image.open(p).load()
        out.append(ext[1:])
    p = h.path("intro.gif")
    h.next_save = p
    w.export_logo_intro()
    wait(lambda: os.path.exists(p) and os.path.getsize(p) > 10000, 90, "logo intro")
    pump(1.5)
    gif = Image.open(p)
    total_ms = 0
    for k in range(gif.n_frames):  # GIF saving merges identical hold frames, so check duration, not count
        gif.seek(k)
        total_ms += gif.info.get("duration", 0)
    check(gif.n_frames >= 12 and total_ms >= 1200, f"intro too short ({gif.n_frames} frames, {total_ms} ms)")
    out.append("intro.gif")
    h.done.clear()
    h.next_dir = h.path("kit")
    os.makedirs(h.next_dir, exist_ok=True)
    w.export_brand_kit()
    wait(lambda: h.done, 180, "brand kit")
    root, files = h.done[-1]
    check(len(files) >= 20, f"brand kit only has {len(files)} files")
    for f in files:
        check(os.path.getsize(f) > 100, f"empty kit file {os.path.basename(f)}")
    out.append(f"brand kit ({len(files)} files)")
    return " ".join(out)


def t_cards(h):
    from .exports import CARD_TEMPLATES
    from .qrtools import decode_image
    w = h.w
    w.tabs.setCurrentWidget(w.card_page)
    w.card_fields["name"].setText("Alex Khan")
    for tpl in CARD_TEMPLATES:
        w.card_template.setCurrentText(tpl)
        g = w._gen["card"]
        w.generate_card()
        wait(lambda: w._gen["card"] > g and w.card_front is not None and not w.card_preview._busy, 40,
             f"card {tpl}")
        vals = decode_image(w.card_front)
        check(any("FN:Alex Khan" in v for v in vals), f"{tpl}: card QR doesn't scan")
    for name, fn in (("card_front.png", w.save_card_png), ("card.pdf", w.save_card_pdf),
                     ("sheet.pdf", w.save_card_sheet)):
        h.next_save = h.path(name)
        fn()
        check(os.path.getsize(h.path(name)) > 5000, f"{name} not written")
    check(os.path.exists(h.path("card_back.png")), "card back not written")
    w.card_to_qr()
    check(w.qr_type.currentIndex() == 6 and "FN:Alex Khan" in w._qr_payload(), "card → QR failed")
    return f"{len(CARD_TEMPLATES)} templates scan, PNG/PDF/print sheet written"


def t_history(h):
    w = h.w
    w.tabs.setCurrentWidget(w.history_page)
    pump(0.5)
    w._refresh_history()
    n = w.h_list.count()
    check(n >= 5, f"history only has {n} items")
    kinds = set()
    for i in range(min(n, 40)):
        w.h_list.setCurrentRow(i)
        pump(0.05)
        e = w._entry()
        if e["kind"] in kinds:
            continue
        kinds.add(e["kind"])
        if w.h_restore.isEnabled():
            w._history_restore()
            w.tabs.setCurrentWidget(w.history_page)
            pump(0.2)
            w._refresh_history()
            w.h_list.setCurrentRow(i)
        if w.h_export.isEnabled():
            ext = os.path.splitext(w.history.path(e))[1]
            h.next_save = h.path(f"hist_{e['kind']}{ext}")
            w._history_export()
            check(os.path.exists(h.path(f"hist_{e['kind']}{ext}")), f"history export of {e['kind']} failed")
        if e["kind"] == "audio":
            w._history_primary()
            wait(lambda: w.player.playing, 10, "history playback")
            w.stop_audio()
    w.h_search.setText("zzzz-no-match")
    pump(0.1)
    check(w.h_list.count() == 0, "search filter broken")
    w.h_search.setText("")
    w.h_list.setCurrentRow(0)
    before = len(w.history.entries)
    w._history_delete()
    check(len(w.history.entries) == before - 1, "delete failed")
    return f"{n} items, kinds tested: {', '.join(sorted(kinds))}"


def t_themes(h):
    from .widgets import ACCENTS, THEMES
    w = h.w
    for th in THEMES:
        for ac in list(ACCENTS)[:3]:
            w.apply_theme(th, ac, True)
            pump(0.1)
    w.apply_theme("Light", "Emerald", True)
    pump(0.3)
    w.grab().save(h.path("theme_light.png"))
    w.apply_theme("Dark", "Indigo", False)
    pump(0.2)
    w.apply_theme("Dark", "Indigo", True)
    return f"{len(THEMES)} themes × 3 accents + motion off/on"


def t_palette_settings(h):
    w = h.w
    w.open_palette()
    w.open_settings()
    acts = w.palette_actions()
    safe = [a for a in acts if a[0].startswith(("🎙️ Go", "✨ Go", "🎨 Go", "🪪 Go", "🕘", "🌙", "☀️", "🖤",
                                                 "🎨 Accent", "🎉", "ℹ️", "🎭"))]
    for title, _, fn in safe:
        fn()
        pump(0.05)
    w.apply_theme("Dark", "Indigo", True)
    w.dialogue.setChecked(False)
    return f"{len(acts)} commands listed, {len(safe)} executed"


def t_hotkeys(h):
    from . import winint
    from .core import IS_WIN
    if not IS_WIN:
        raise Skip("Windows only")
    hwnd = int(h.w.winId())
    ok = winint.register_hotkey(hwnd, 0x53FF, (winint.MOD_CONTROL | winint.MOD_ALT | winint.MOD_SHIFT, 0x7B))
    winint.unregister_hotkey(hwnd, 0x53FF)
    check(ok, "couldn't register a global hotkey")
    n = len(h.audio)
    h.w._quick_speak("Quick speak check.")
    wait(lambda: len(h.audio) > n, 40, "quick speak audio")
    h.w.stop_audio()
    return "global hotkey registration + quick-speak ok"


def t_tray_and_drop(h):
    w = h.w
    w.store.set("ui/close_to_tray", True)
    w.close()
    pump(0.3)
    check(not w.isVisible(), "close should hide to tray")
    w.show_from_tray()
    pump(0.3)
    check(w.isVisible(), "show from tray failed")
    w._dropped_image(h.path("qr.png"))
    md = QMimeData()
    md.setText("Dropped text")
    w.textbox.setPlainText("")

    class Ev:
        def mimeData(self):
            return md
    w.dropEvent(Ev())
    check(w.textbox.toPlainText() == "Dropped text", "text drop failed")
    md2 = QMimeData()
    p = h.path("drop.txt")
    open(p, "w", encoding="utf-8").write("From a dropped file")
    md2.setUrls([QUrl.fromLocalFile(p)])

    class Ev2:
        def mimeData(self):
            return md2
    w.dropEvent(Ev2())
    check(w.textbox.toPlainText() == "From a dropped file", "file drop failed")
    w.toasts.show("Toast check", "ok")
    w.celebrate()
    pump(0.5)
    return "tray hide/show, drag & drop, toast, confetti ok"


def t_errors_handled(h):
    w = h.w
    w.tabs.setCurrentWidget(w.voice_page)
    w.textbox.setPlainText("")
    n = len(h.audio)
    w.speak()
    pump(0.5)
    check(len(h.audio) == n, "empty text should not speak")
    w.qr_type.setCurrentIndex(0)
    w.qr_fields["text"].setText("")
    w.generate_qr()
    pump(0.3)
    check("Fill in" in w.qr_info.text(), "empty QR should prompt")
    w.qr_fields["text"].setText("https://studiovision.example/test")
    bad = h.path("bad.csv")
    open(bad, "w").write("")
    h.next_open = bad
    w.batch_qr()
    w.export_subtitles() if w.last_words else None
    return "empty input, empty CSV and missing data handled gracefully"


def t_preload(h):
    w = h.w
    if h.quick:
        raise Skip("quick mode")
    w.start_preload()
    wait(lambda: not getattr(w, "_preloading", False), 1200, "preload to finish")
    st = w.preload_state
    fails = {k: d for k, (s, d) in st.items() if s == "fail"}
    check(not fails, f"preload failures: {fails}")
    return ", ".join(f"{k.split(' (')[0]}={s}" for k, (s, _) in st.items())


TESTS = [t_startup, t_tabs_render, t_wheel_guard, t_voice_edge, t_voice_translate, t_language_detect, t_karaoke_refine,
         t_edge_fallback_route, t_voice_gtts, t_voice_system, t_voice_effects,
         t_voice_dialogue, t_voice_exports, t_voice_replay_pause, t_voice_preview_and_text, t_interp_typed,
         t_interp_recognition, t_interp_mic, t_qr_types, t_qr_styles, t_qr_logo_caption_art, t_qr_exports,
         t_qr_scanning, t_qr_batch, t_qr_privacy, t_logo_styles, t_logo_generate, t_logo_exports, t_cards,
         t_history, t_themes, t_palette_settings, t_hotkeys, t_tray_and_drop, t_errors_handled, t_preload,
         t_voice_clone]


def run(app, win, report_path, quick=False):
    out_dir = tempfile.mkdtemp(prefix="sv_selftest_")
    h = Harness(win, out_dir, quick)
    sys.excepthook = lambda t, e, tb: ERRORS.append("".join(traceback.format_exception(t, e, tb)))
    win.show()
    pump(0.5)
    for fn in TESTS:
        name = fn.__name__[2:]
        ERRORS.clear()
        STATUS_ERRORS.clear()
        t0 = time.time()
        try:
            detail = fn(h)
            ok = "pass"
            if ERRORS:
                ok, detail = "fail", "uncaught exception: " + ERRORS[-1].strip().splitlines()[-1]
            elif STATUS_ERRORS and name not in ("errors_handled",):
                ok, detail = "fail", "error shown to user: " + STATUS_ERRORS[-1]
        except Skip as e:
            ok, detail = "skip", str(e)
        except Exception as e:
            ok, detail = "fail", f"{type(e).__name__}: {e}"
            if not isinstance(e, AssertionError):
                detail += " | " + traceback.format_exc().strip().splitlines()[-3].strip()
        RESULTS.append({"test": name, "result": ok, "seconds": round(time.time() - t0, 1), "detail": str(detail)})
        print(f"[{ok.upper():4}] {name:<24} {time.time() - t0:6.1f}s  {detail}", flush=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump({"results": RESULTS, "artifacts": out_dir}, f, indent=1, ensure_ascii=False)
    win._really_quit = True
    win.close()
    fails = sum(r["result"] == "fail" for r in RESULTS)
    return fails
