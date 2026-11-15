"""Speech engines (Edge with word timings, Google, OS voices, F5 cloning) and speech recognition."""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading

from .audio import WORK_SR, audio_duration, write_wav
from .core import (DATA_DIR, FROZEN, HAS_EDGE, HAS_F5, HAS_GTTS, HAS_NP, HAS_PYTTSX3, HAS_SF, HAS_SR, HAS_WHISPER,
                   IS_MAC, IS_WIN, LANG_NAME, PREFERRED_LOCALE, STATIC_EDGE_VOICES, WELL_KNOWN_VOICES, bcp47,
                   torch_threads,
                   edge_tts, gTTS, get_resource_path, hidden_window_kwargs, locale_matches, log, np, pyttsx3,
                   run_async, sf, temp_path)

# ---------------------------------------------------------------------------
# Edge neural voices
# ---------------------------------------------------------------------------


def fetch_edge_voices():
    cache = os.path.join(DATA_DIR, "edge_voices.json")
    voices = None
    if HAS_EDGE:
        try:
            raw = run_async(edge_tts.list_voices, 20)
            voices = [{"name": v["ShortName"], "locale": v["Locale"], "gender": v.get("Gender", "")}
                      for v in raw]
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(voices, f)
        except Exception as e:
            log.info("Live Edge voice list unavailable: %s", e)
    if not voices and os.path.exists(cache):
        try:
            with open(cache, encoding="utf-8") as f:
                voices = json.load(f)
        except Exception:
            voices = None
    if not voices:
        voices = [{"name": n, "locale": "-".join(n.split("-")[:2]), "gender": g} for n, g in STATIC_EDGE_VOICES]
    return sorted(voices, key=lambda v: (v["locale"], v["name"]))


def pick_edge_voice(voices, lang, gender="Any", prefer=None):
    cands = [v for v in voices if locale_matches(v["locale"], lang)]
    if not cands:
        return None
    if prefer and any(v["name"] == prefer for v in cands):
        return prefer
    if gender in ("Male", "Female"):
        g = [v for v in cands if v["gender"] == gender]
        cands = g or cands
    pref_loc = PREFERRED_LOCALE.get(lang.split("-")[0] if not lang.startswith("zh") else lang)

    def score(v):
        return (0 if pref_loc and v["locale"] == pref_loc else 1,
                0 if v["name"] in WELL_KNOWN_VOICES else 1,
                0 if "Multilingual" not in v["name"] else 1,
                v["name"])
    return sorted(cands, key=score)[0]["name"]


def edge_synthesize(text, voice, rate_pct, pitch_hz, out_path):
    """Returns (path, words) where words = [(start_s, dur_s, word), ...] for karaoke & subtitles.
    If Microsoft changes its handshake and the bundled library is refused, an updated edge-tts in your
    Python install is used instead (⚙ Settings → Repair voice engine)."""
    if ENGINES.prefer_external_edge:
        try:
            return ENGINES.edge_external(text, voice, rate_pct, pitch_hz, out_path)
        except Exception as e:
            log.warning("External Edge failed, trying the bundled one: %s", e)
    try:
        return _edge_local(text, voice, rate_pct, pitch_hz, out_path)
    except RuntimeError as e:
        if "refused" in str(e) and ENGINES.external and ENGINES.ext_caps.get("edge"):
            try:
                result = ENGINES.edge_external(text, voice, rate_pct, pitch_hz, out_path)
                ENGINES.prefer_external_edge = True
                return result
            except Exception as e2:
                log.warning("External Edge fallback failed: %s", e2)
        raise


def _edge_local(text, voice, rate_pct, pitch_hz, out_path):
    if not HAS_EDGE:
        raise RuntimeError("edge-tts is not installed (pip install edge-tts)")
    words = []

    async def go():
        comm = edge_tts.Communicate(text, voice, rate=f"{int(rate_pct):+d}%", pitch=f"{int(pitch_hz):+d}Hz",
                                    boundary="WordBoundary")
        with open(out_path, "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    words.append((chunk["offset"] / 1e7, chunk["duration"] / 1e7, chunk["text"]))

    try:
        run_async(go, timeout=max(45, len(text) / 6))
    except Exception as e:
        if "403" in str(e):
            raise RuntimeError("Microsoft's voice server refused the connection — fix it in one click: "
                               "⚙ Settings → Repair voice engine") from e
        if type(e).__name__ == "NoAudioReceived":
            raise RuntimeError(f"voice {voice} can't read this text's language") from e
        raise
    if not os.path.exists(out_path) or os.path.getsize(out_path) < 256:
        raise RuntimeError(f"Edge returned no audio for voice {voice}")
    return out_path, words


def gtts_synthesize(text, lang, out_path, tld="com", slow=False):
    if not HAS_GTTS:
        raise RuntimeError("gTTS is not installed (pip install gTTS)")
    code = lang or "en"
    try:
        from gtts.lang import tts_langs
        langs = tts_langs()
        if code not in langs:
            code = code.split("-")[0] if code.split("-")[0] in langs else "en"
    except Exception:
        pass
    gTTS(text=text, lang=code, tld=tld, slow=slow).save(out_path)
    if not os.path.exists(out_path) or os.path.getsize(out_path) < 256:
        raise RuntimeError("Google TTS returned no audio")
    return out_path


# ---------------------------------------------------------------------------
# Word timing helpers (karaoke + subtitles)
# ---------------------------------------------------------------------------


def estimate_words(text, duration, lead=0.12):
    """Spread words over the clip by length when the engine gives no timings."""
    tokens = text.split()
    if not tokens or duration <= 0:
        return []
    weights = [len(t) + 2 + (4 if re.search(r"[.!?,;:۔،]$", t) else 0) for t in tokens]
    usable = max(0.1, duration - lead - 0.15)
    unit = usable / sum(weights)
    out, t = [], lead
    for tok, w in zip(tokens, weights):
        out.append((t, w * unit * 0.9, tok))
        t += w * unit
    return out


def align_words(text, heard):
    """Put the *original* words of `text` on the timeline Whisper heard (it may spell some differently)."""
    import difflib
    tokens = text.split()
    if not tokens or not heard:
        return []
    norm = lambda s: re.sub(r"[^\w]", "", s.lower())  # noqa: E731
    sm = difflib.SequenceMatcher(None, [norm(t) for t in tokens], [norm(h[2]) for h in heard], autojunk=False)
    times = [None] * len(tokens)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            times[a + k] = heard[b + k][:2]
    # unmatched words: share the gap between their matched neighbours, weighted by length
    i = 0
    end_all = heard[-1][0] + heard[-1][1]
    while i < len(tokens):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(tokens) and times[j] is None:
            j += 1
        t0 = (times[i - 1][0] + times[i - 1][1]) if i > 0 else heard[0][0]
        t1 = times[j][0] if j < len(tokens) else end_all
        span = max(0.05, t1 - t0)
        weights = [len(tokens[k]) + 1 for k in range(i, j)]
        acc = t0
        for k, wgt in zip(range(i, j), weights):
            d = span * wgt / sum(weights)
            times[k] = (acc, d * 0.9)
            acc += d
        i = j
    return [(s, d, tok) for (s, d), tok in zip(times, tokens)]


def scale_words(words, scale=1.0, offset=0.0):
    return [(s * scale + offset, d * scale, w) for s, d, w in words]


def _fmt_ts(sec, sep=","):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def caption_lines(words, max_chars=42, max_words=8):
    lines, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        text = " ".join(x[2] for x in cur)
        nxt = words[i + 1] if i + 1 < len(words) else None
        pause = nxt is not None and nxt[0] - (w[0] + w[1]) > 0.28  # Edge drops punctuation; pauses mark sentences
        if len(text) >= max_chars or len(cur) >= max_words or pause or re.search(r"[.!?۔。！？]$", w[2]):
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    return [(ln[0][0], ln[-1][0] + ln[-1][1], " ".join(x[2] for x in ln)) for ln in lines]


def to_srt(words):
    out = []
    for i, (s, e, text) in enumerate(caption_lines(words), 1):
        out.append(f"{i}\n{_fmt_ts(s)} --> {_fmt_ts(max(e, s + 0.4))}\n{text}\n")
    return "\n".join(out)


def to_vtt(words):
    out = ["WEBVTT\n"]
    for s, e, text in caption_lines(words):
        out.append(f"{_fmt_ts(s, '.')} --> {_fmt_ts(max(e, s + 0.4), '.')}\n{text}\n")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Operating-system voices
# ---------------------------------------------------------------------------

_PS_LIST = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture.Name + '|' + $_.VoiceInfo.Gender }
"""
_PS_SPEAK = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($env:SV_VOICE) { try { $s.SelectVoice($env:SV_VOICE) } catch {} }
$s.Rate = [int]$env:SV_RATE
$s.SetOutputToWaveFile($env:SV_OUT)
$t = [IO.File]::ReadAllText($env:SV_TXT, [Text.Encoding]::UTF8)
$s.Speak($t)
$s.Dispose()
"""


class SystemTTS:
    """Uses the OS's own speech engine through a subprocess — avoids pyttsx3's 'only works once' bug."""

    @staticmethod
    def list_voices():
        voices = []
        try:
            if IS_MAC and shutil.which("say"):
                out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=15).stdout
                for line in out.splitlines():
                    m = re.match(r"^(.*?)\s+([a-z]{2,3}[_-][A-Za-z0-9_]+)\s+#", line)
                    if m:
                        voices.append({"id": m.group(1).strip(), "name": m.group(1).strip(),
                                       "lang": m.group(2).replace("_", "-")})
            elif IS_WIN:
                out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_LIST],
                                     capture_output=True, timeout=30, **hidden_window_kwargs()).stdout
                for line in out.decode("utf-8", "ignore").splitlines():
                    parts = line.strip().split("|")
                    if len(parts) >= 2 and parts[0]:
                        voices.append({"id": parts[0], "name": parts[0], "lang": parts[1]})
            else:
                exe = shutil.which("espeak-ng") or shutil.which("espeak")
                if exe:
                    out = subprocess.run([exe, "--voices"], capture_output=True, text=True, timeout=15).stdout
                    for line in out.splitlines()[1:]:
                        parts = line.split()
                        if len(parts) >= 4:
                            voices.append({"id": parts[1], "name": f"{parts[3]} ({parts[1]})", "lang": parts[1]})
        except Exception as e:
            log.info("Native voice listing failed: %s", e)
        if not voices and HAS_PYTTSX3:
            try:
                eng = pyttsx3.init()
                for v in eng.getProperty("voices"):
                    langs = getattr(v, "languages", []) or []
                    lang = langs[0].decode("utf-8", "ignore") if langs and isinstance(langs[0], bytes) else \
                        (langs[0] if langs else "")
                    voices.append({"id": v.id, "name": v.name, "lang": str(lang), "pyttsx3": True})
                eng.stop()
            except Exception as e:
                log.info("pyttsx3 voice listing failed: %s", e)
        return sorted(voices, key=lambda v: (v["lang"], v["name"]))

    @staticmethod
    def synthesize(text, voice, rate_pct, out_base):
        txt = out_base + ".txt"
        with open(txt, "w", encoding="utf-8") as f:
            f.write(text)
        voice_id = (voice or {}).get("id", "")
        if (voice or {}).get("pyttsx3"):
            return SystemTTS._pyttsx3(text, voice_id, rate_pct, out_base + ".wav")
        if IS_MAC and shutil.which("say"):
            out = out_base + ".wav"
            cmd = ["say", "-r", str(int(175 * (1 + rate_pct / 100.0))), "-o", out,
                   "--data-format=LEI16@22050", "-f", txt]
            if voice_id:
                cmd[1:1] = ["-v", voice_id]
            subprocess.run(cmd, check=True, timeout=300, capture_output=True)
        elif IS_WIN:
            out = out_base + ".wav"
            env = dict(os.environ, SV_VOICE=voice_id, SV_OUT=out, SV_TXT=txt,
                       SV_RATE=str(max(-10, min(10, int(rate_pct / 10)))))
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-Command", _PS_SPEAK], env=env, check=True, timeout=300, capture_output=True,
                           **hidden_window_kwargs())
        else:
            exe = shutil.which("espeak-ng") or shutil.which("espeak")
            if not exe:
                return SystemTTS._pyttsx3(text, voice_id, rate_pct, out_base + ".wav")
            out = out_base + ".wav"
            cmd = [exe, "-s", str(int(170 * (1 + rate_pct / 100.0))), "-w", out, "-f", txt]
            if voice_id:
                cmd[1:1] = ["-v", voice_id]
            subprocess.run(cmd, check=True, timeout=300, capture_output=True)
        if not os.path.exists(out) or os.path.getsize(out) < 256:
            raise RuntimeError("System voice produced no audio (does this voice support the language?)")
        return out

    @staticmethod
    def _pyttsx3(text, voice_id, rate_pct, out):
        if not HAS_PYTTSX3:
            raise RuntimeError("No system speech engine found (install espeak-ng or pyttsx3)")
        eng = pyttsx3.init()
        try:
            if voice_id:
                eng.setProperty("voice", voice_id)
            eng.setProperty("rate", int(180 * (1 + rate_pct / 100.0)))
            eng.save_to_file(text, out)
            eng.runAndWait()
        finally:
            eng.stop()
        if not os.path.exists(out):
            raise RuntimeError("pyttsx3 produced no audio")
        return out


# ---------------------------------------------------------------------------
# Heavy local engines: F5-TTS voice cloning + faster-whisper recognition.
# Run in-process when importable; the packaged .exe borrows a Python install that has them.
# ---------------------------------------------------------------------------

_CHECK = ("import importlib.util as u, json, sys; "
          "print(json.dumps({'f5': u.find_spec('f5_tts') is not None, "
          "'whisper': u.find_spec('faster_whisper') is not None, 'edge': u.find_spec('edge_tts') is not None, "
          "'exe': sys.executable}))")


def _python_candidates():
    seen, out = set(), []

    def add(p):
        if p and os.path.isfile(p):
            key = os.path.normcase(os.path.abspath(p))
            if key not in seen and "windowsapps" not in key:
                seen.add(key)
                out.append(p)
    if IS_WIN:
        for root in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python"),
                     os.environ.get("ProgramFiles", r"C:\Program Files"), r"C:\\"):
            for p in sorted(glob.glob(os.path.join(root, "Python3*", "python.exe")), reverse=True):
                add(p)
        add(shutil.which("python"))
        py = shutil.which("py")
        if py:
            try:
                res = subprocess.run([py, "-3", "-c", "import sys;print(sys.executable)"], capture_output=True,
                                     text=True, timeout=15, **hidden_window_kwargs())
                add(res.stdout.strip())
            except Exception:
                pass
    else:
        add(shutil.which("python3"))
        add(shutil.which("python"))
    return out


class HeavyEngines:
    def __init__(self):
        self.lock = threading.Lock()  # F5 model
        self.wlock = threading.Lock()  # Whisper model
        # two outside workers so cloning (minutes of CPU) never blocks recognition / Edge, and vice-versa
        self._call_locks = {"f5": threading.Lock(), "asr": threading.Lock()}
        self._procs = {"f5": None, "asr": None}
        self.f5_model = None
        self.f5_device = "?"
        self.whisper_model = None
        self.whisper_size = None
        self.external = None
        self.ext_caps = {"f5": False, "whisper": False, "edge": False}
        self._req = 0
        self.prefer_external_edge = False

    # -- capability detection --------------------------------------------------
    def detect(self):
        """Look for an outside Python that has the heavy packages (only needed when frozen/missing)."""
        if HAS_F5 and HAS_WHISPER:
            return self.caps()
        cache = os.path.join(DATA_DIR, "engines.json")
        try:
            with open(cache, encoding="utf-8") as f:
                c = json.load(f)
            if c.get("v") == 2 and c.get("exe") and os.path.isfile(c["exe"]) and \
                    os.path.getmtime(c["exe"]) == c.get("mtime"):
                self.external = c["exe"]
                self.ext_caps = {k: c.get(k, False) for k in ("f5", "whisper", "edge")}
                return self.caps()
        except Exception:
            pass
        for exe in _python_candidates():
            if not FROZEN and os.path.normcase(exe) == os.path.normcase(sys.executable):
                continue
            try:
                res = subprocess.run([exe, "-c", _CHECK], capture_output=True, text=True, timeout=25,
                                     **hidden_window_kwargs())
                info = json.loads(res.stdout.strip().splitlines()[-1])
            except Exception:
                continue
            if info.get("f5") or info.get("whisper"):
                self.external = exe
                self.ext_caps = {k: bool(info.get(k)) for k in ("f5", "whisper", "edge")}
                try:
                    with open(cache, "w", encoding="utf-8") as f:
                        json.dump({"v": 2, "exe": exe, "mtime": os.path.getmtime(exe), **self.ext_caps}, f)
                except Exception:
                    pass
                break
        return self.caps()

    def caps(self):
        return {"f5": HAS_F5 or self.ext_caps["f5"], "whisper": HAS_WHISPER or self.ext_caps["whisper"],
                "external": self.external if not (HAS_F5 and HAS_WHISPER) else None}

    @property
    def f5_loaded(self):
        return self.f5_model is not None or (self._procs["f5"] is not None and self.f5_device != "?")

    # -- external workers ------------------------------------------------------
    def _worker(self, kind):
        proc = self._procs[kind]
        if proc and proc.poll() is None:
            return proc
        script = get_resource_path(os.path.join("sv", "worker.py"))
        if not os.path.exists(script):
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker.py")
        errlog = open(os.path.join(DATA_DIR, f"engine_worker_{kind}.log"), "a", encoding="utf-8")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        for k in ("PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY"):
            env.pop(k, None)
        proc = subprocess.Popen([self.external, "-u", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=errlog, text=True, encoding="utf-8", env=env, **hidden_window_kwargs())
        self._procs[kind] = proc
        return proc

    def _call(self, cmd, status, **args):
        kind = "f5" if cmd.startswith("f5") else "asr"
        with self._call_locks[kind]:
            return self._call_locked(kind, cmd, status, **args)

    def _call_locked(self, kind, cmd, status, **args):
        proc = self._worker(kind)
        self._req += 1
        rid = self._req
        proc.stdin.write(json.dumps({"id": rid, "cmd": cmd, **args}) + "\n")
        proc.stdin.flush()
        while True:
            line = proc.stdout.readline()
            if not line:
                self._procs[kind] = None
                if kind == "f5":
                    self.f5_device = "?"
                raise RuntimeError("The voice engine process stopped unexpectedly (see engine_worker log)")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "status" in msg:
                status(msg["status"])
                continue
            if msg.get("id") == rid:
                if not msg.get("ok"):
                    raise RuntimeError(msg.get("error", "engine error"))
                return msg.get("result")

    def shutdown(self, kinds=("f5", "asr")):
        for kind in kinds:
            proc = self._procs.get(kind)
            if proc and proc.poll() is None:
                try:
                    proc.stdin.write(json.dumps({"id": 0, "cmd": "quit"}) + "\n")
                    proc.stdin.flush()
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
            self._procs[kind] = None

    # -- F5 voice cloning --------------------------------------------------------
    def f5_load(self, status=lambda m: None):
        with self.lock:
            if HAS_F5:
                return self._f5_load_local(status)
            if self.external and self.ext_caps["f5"]:
                status("Loading voice-cloning model in your Python install… (first run downloads ~1.3 GB)")
                res = self._call("f5_load", status)
                self.f5_device = res.get("device", "cpu")
                return True
            raise RuntimeError("F5-TTS isn't installed. Run:  pip install f5-tts  (free, runs offline)")

    def _f5_load_local(self, status):
        if self.f5_model is not None:
            return self.f5_model
        threads = torch_threads()
        os.environ.setdefault("OMP_NUM_THREADS", threads)
        os.environ.setdefault("MKL_NUM_THREADS", threads)
        status("Loading voice-cloning model… (first run downloads ~1.3 GB once, free)")
        import torch
        import torchaudio
        torch.set_num_threads(int(threads))
        if HAS_SF:
            # torchaudio.load needs extra native backends on some systems; soundfile is reliable.
            def _sf_load(filepath, *args, **kwargs):
                data, sr = sf.read(filepath, dtype="float32", always_2d=True)
                return torch.from_numpy(data.T.copy()), sr
            torchaudio.load = _sf_load
        from f5_tts.api import F5TTS
        self.f5_model = F5TTS()
        self.f5_device = str(getattr(self.f5_model, "device", "cpu"))
        return self.f5_model

    def f5_synthesize(self, gen_text, ref_file, ref_text, nfe_step, speed, out_path, status=lambda m: None):
        self.f5_load(status)
        with self.lock:
            status(f"Cloning voice on {self.f5_device} ({nfe_step} steps)…")
            if HAS_F5:
                import torch
                with torch.inference_mode():
                    wav_out, sr, _ = self.f5_model.infer(ref_file=ref_file, ref_text=ref_text or "",
                                                         gen_text=gen_text, nfe_step=int(nfe_step),
                                                         speed=float(speed), show_info=lambda *a, **k: None)
                write_wav(out_path, wav_out, sr)
            else:
                self._call("f5_synth", status, gen_text=gen_text, ref_file=ref_file, ref_text=ref_text or "",
                           nfe=int(nfe_step), speed=float(speed), out=out_path)
        return out_path

    # -- faster-whisper ------------------------------------------------------------
    def transcribe_whisper(self, wav_path, lang=None, size="base", status=lambda m: None):
        with self.wlock:  # separate from the cloning lock: Whisper never waits for F5
            if HAS_WHISPER:
                if self.whisper_model is None or self.whisper_size != size:
                    status(f"Loading offline speech recogniser ({size})… first run downloads it once")
                    from faster_whisper import WhisperModel
                    self.whisper_model = WhisperModel(size, device="cpu", compute_type="int8")
                    self.whisper_size = size
                # pass samples, not a path: faster-whisper's file decoder breaks with PyAV >= 19
                from .audio import read_audio_mono, resample
                data, sr = read_audio_mono(wav_path)
                samples = resample(data.astype(np.float32), sr, 16000)
                segs, info = self.whisper_model.transcribe(samples, language=(lang or None) and lang.split("-")[0],
                                                           vad_filter=True, beam_size=1)
                return " ".join(s.text.strip() for s in segs).strip(), info.language
            if self.external and self.ext_caps["whisper"]:
                res = self._call("whisper", status, path=wav_path, lang=(lang or "").split("-")[0], size=size)
                return res["text"], res["lang"]
        raise RuntimeError("Offline recognition needs faster-whisper (pip install faster-whisper)")

    def word_timings(self, audio_path, lang=None, size="base"):
        """Exact per-word timings for any clip (used for karaoke/subtitles on engines that don't report them)."""
        from .audio import load_work, resample, WORK_SR
        samples = resample(load_work(audio_path), WORK_SR, 16000)
        code = (lang or None) and lang.split("-")[0]
        with self.wlock:  # separate from the cloning lock: Whisper never waits for F5
            if HAS_WHISPER:
                if self.whisper_model is None or self.whisper_size != size:
                    from faster_whisper import WhisperModel
                    self.whisper_model = WhisperModel(size, device="cpu", compute_type="int8")
                    self.whisper_size = size
                segs, _ = self.whisper_model.transcribe(samples, language=code, word_timestamps=True, beam_size=1)
                return [(w.start, max(0.05, w.end - w.start), w.word.strip()) for s in segs for w in (s.words or [])]
            if self.external and self.ext_caps["whisper"]:
                wav = temp_path(".wav")
                write_wav(wav, samples, 16000)
                res = self._call("whisper_words", lambda m: None, path=wav, lang=code or "", size=size)
                return [tuple(w) for w in res["words"]]
        return []

    def edge_external(self, text, voice, rate_pct, pitch_hz, out_path):
        """Edge TTS through the outside Python — the fallback when the bundled library gets out of date."""
        if not (self.external and self.ext_caps.get("edge")):
            raise RuntimeError("no outside Python with edge-tts")
        res = self._call("edge", lambda m: None, text=text, voice=voice, rate=f"{int(rate_pct):+d}%",
                         pitch=f"{int(pitch_hz):+d}Hz", out=out_path)
        return out_path, [tuple(w) for w in res["words"]]

    def repair_voice_engine(self, status=lambda m: None):
        """Update edge-tts in the Python install we can write to; returns a short report."""
        target = sys.executable if not FROZEN else self.external
        if not target:
            raise RuntimeError("No Python install found to update — install Python from python.org first")
        status("Updating the Edge voice library (pip install -U edge-tts)…")
        res = subprocess.run([target, "-m", "pip", "install", "-U", "edge-tts"], capture_output=True, text=True,
                             timeout=300, **hidden_window_kwargs())
        if res.returncode != 0:
            raise RuntimeError((res.stderr or res.stdout).strip().splitlines()[-1][:200])
        ver = subprocess.run([target, "-c", "import edge_tts;print(edge_tts.__version__)"], capture_output=True,
                             text=True, timeout=60, **hidden_window_kwargs()).stdout.strip()
        if FROZEN:
            self.ext_caps["edge"] = True
            self.prefer_external_edge = True
            self.shutdown(("asr",))  # restart the Edge/recognition worker so it imports the new library
        return f"edge-tts {ver} ready" + (" (used via your Python install)" if FROZEN else " — restart the app")


ENGINES = HeavyEngines()


def transcribe(samples, sr, lang=None, prefer="auto", whisper_size="base", status=lambda m: None):
    """Speech -> text. Returns (text, detected_lang, engine_name)."""
    caps = ENGINES.caps()
    wav = temp_path(".wav")
    write_wav(wav, samples, sr)
    errors = []
    order = ["whisper", "google"] if prefer in ("auto", "whisper") else ["google", "whisper"]
    for eng in order:
        try:
            if eng == "whisper" and caps["whisper"]:
                text, det = ENGINES.transcribe_whisper(wav, lang, whisper_size, status)
                return text, det or lang, "Whisper (offline)"
            if eng == "google" and HAS_SR:
                import speech_recognition as srec
                pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
                rec = srec.Recognizer()
                try:
                    text = rec.recognize_google(srec.AudioData(pcm, int(sr), 2), language=bcp47(lang))
                except srec.UnknownValueError:
                    text = ""
                return text, lang, "Google (online)"
        except Exception as e:
            log.warning("%s recognition failed: %s", eng, e)
            errors.append(f"{eng}: {e}")
    if errors:
        raise RuntimeError("Speech recognition failed — " + " | ".join(errors))
    raise RuntimeError("No speech recogniser available (install SpeechRecognition or faster-whisper)")


def language_label(code):
    return LANG_NAME.get(code, LANG_NAME.get((code or "").split("-")[0], code or "?"))


__all__ = ["fetch_edge_voices", "pick_edge_voice", "edge_synthesize", "gtts_synthesize", "SystemTTS", "ENGINES",
           "transcribe", "estimate_words", "scale_words", "to_srt", "to_vtt", "caption_lines", "language_label",
           "audio_duration", "WORK_SR", "HAS_NP"]
