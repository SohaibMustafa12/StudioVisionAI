"""Audio I/O, playback with a position clock, voice effects, background beds and mixing."""

import math
import os
import subprocess
import threading
import time
import wave

from .core import (HAS_NP, HAS_PYGAME, HAS_SD, HAS_SF, IS_MAC, IS_WIN, hidden_window_kwargs, log, np, pygame,
                   sd, sf, temp_path)

WORK_SR = 24000


def write_wav(path, samples, sample_rate):
    """Write mono float samples (-1..1) as 16-bit PCM WAV without scipy."""
    data = np.asarray(samples, dtype=np.float32).reshape(-1)
    data = np.clip(data, -1.0, 1.0)
    pcm = (data * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(pcm.tobytes())


def read_audio_mono(path):
    if HAS_SF:
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        return data.mean(axis=1), sr
    with wave.open(path, "rb") as w:
        sr, n, ch, width = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    if width != 2:
        raise RuntimeError("Install soundfile to read this audio format")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return data.reshape(-1, ch).mean(axis=1), sr


def resample(data, sr_from, sr_to):
    if sr_from == sr_to or len(data) == 0:
        return data
    n = int(len(data) * sr_to / sr_from)
    return np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data).astype(np.float32)


def load_work(path):
    """Decode any supported file to mono float32 at WORK_SR."""
    data, sr = read_audio_mono(path)
    return resample(data.astype(np.float32), sr, WORK_SR)


def audio_duration(path):
    try:
        if HAS_SF:
            info = sf.info(path)
            return info.frames / float(info.samplerate)
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return 0.0


def audio_envelope(path, per_second=40):
    """Loudness envelope used to drive the live visuals. Returns (list, duration) or (None, 0)."""
    if not HAS_NP:
        return None, 0.0
    data, sr = None, None
    try:
        data, sr = read_audio_mono(path)
    except Exception:
        if HAS_PYGAME and pygame.mixer.get_init():
            try:
                snd = pygame.mixer.Sound(path)
                arr = pygame.sndarray.array(snd).astype(np.float32)
                data = arr.mean(axis=1) if arr.ndim == 2 else arr
                sr = pygame.mixer.get_init()[0]
            except Exception:
                data = None
    if data is None or len(data) == 0:
        return None, 0.0
    hop = max(1, int(sr / per_second))
    n = len(data) // hop
    if n == 0:
        return None, 0.0
    env = np.sqrt(np.mean(data[: n * hop].reshape(n, hop) ** 2, axis=1))
    env = env / (env.max() + 1e-9)
    return env.tolist(), len(data) / float(sr)


def export_formats():
    """Formats we can write besides the original file: list of (label, ext)."""
    fmts = [("WAV", ".wav")]
    if HAS_SF:
        avail = sf.available_formats()
        if "MP3" in avail:
            fmts.append(("MP3", ".mp3"))
        if "OGG" in avail:
            fmts.append(("OGG Vorbis", ".ogg"))
        if "FLAC" in avail:
            fmts.append(("FLAC", ".flac"))
    return fmts


def convert_audio(src, dst):
    ext = os.path.splitext(dst)[1].lower()
    if ext == os.path.splitext(src)[1].lower():
        import shutil
        shutil.copy2(src, dst)
        return dst
    data = load_work(src)
    if ext == ".wav":
        write_wav(dst, data, WORK_SR)
    else:
        sub = {".mp3": "MPEG_LAYER_III", ".ogg": "VORBIS", ".flac": "PCM_16"}.get(ext)
        sf.write(dst, np.clip(data, -1, 1), WORK_SR, subtype=sub)
    return dst


class AudioPlayer:
    """Plays a file (blocking, call from a worker thread). Tracks a position clock for karaoke."""

    def __init__(self):
        self.backend = None
        self._stop = threading.Event()
        self._proc = None
        self._lock = threading.Lock()
        self._start = 0.0
        self._paused_at = None
        self._paused_total = 0.0
        self.playing = False
        self.volume = 1.0
        # Opening the sound device takes ~1 s on Windows — do it off the UI thread.
        self._ready = threading.Event()
        threading.Thread(target=self._init_backend, daemon=True).start()

    def _init_backend(self):
        backend = None
        if HAS_PYGAME:
            try:
                pygame.mixer.init()
                backend = "pygame"
            except Exception as e:
                log.warning("pygame mixer init failed: %s", e)
        if not backend and HAS_SD and HAS_SF:
            backend = "sounddevice"
        self.backend = backend or "os"
        self._ready.set()

    def wait_ready(self, timeout=10):
        self._ready.wait(timeout)
        return self.backend

    def position(self):
        if not self.playing:
            return 0.0
        now = self._paused_at if self._paused_at is not None else time.monotonic()
        return max(0.0, now - self._start - self._paused_total)

    @property
    def paused(self):
        return self._paused_at is not None

    def toggle_pause(self):
        if not self.playing or self.backend != "pygame":
            return False
        with self._lock:
            if self._paused_at is None:
                pygame.mixer.music.pause()
                self._paused_at = time.monotonic()
            else:
                pygame.mixer.music.unpause()
                self._paused_total += time.monotonic() - self._paused_at
                self._paused_at = None
        return True

    def _begin_clock(self):
        self._start = time.monotonic()
        self._paused_at = None
        self._paused_total = 0.0
        self.playing = True

    def play_blocking(self, path):
        self.wait_ready()
        self.stop()
        time.sleep(0.05)
        self._stop.clear()
        try:
            if self.backend == "pygame":
                with self._lock:
                    try:
                        pygame.mixer.music.unload()
                    except Exception:
                        pass
                    pygame.mixer.music.load(path)
                    pygame.mixer.music.set_volume(self.volume)
                    pygame.mixer.music.play()
                    self._begin_clock()
                try:
                    while not self._stop.is_set() and (pygame.mixer.music.get_busy() or self.paused):
                        time.sleep(0.03)
                finally:
                    with self._lock:
                        pygame.mixer.music.stop()
                        try:
                            pygame.mixer.music.unload()
                        except Exception:
                            pass
            elif self.backend == "sounddevice":
                data, sr = sf.read(path, dtype="float32")
                sd.play(data, sr)
                self._begin_clock()
                duration = len(data) / float(sr)
                while not self._stop.is_set() and time.monotonic() - self._start < duration + 0.2:
                    time.sleep(0.03)
                sd.stop()
            else:
                if IS_MAC:
                    cmd = ["afplay", path]
                elif IS_WIN:
                    cmd = ["powershell", "-NoProfile", "-Command",
                           f"(New-Object Media.SoundPlayer '{path}').PlaySync()"]
                else:
                    cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]
                self._proc = subprocess.Popen(cmd, **hidden_window_kwargs())
                self._begin_clock()
                while self._proc.poll() is None and not self._stop.is_set():
                    time.sleep(0.05)
                if self._proc.poll() is None:
                    self._proc.kill()
        finally:
            self.playing = False
            self._paused_at = None

    def stop(self):
        self._stop.set()
        try:
            if self.backend == "pygame":
                with self._lock:
                    pygame.mixer.music.stop()
            elif self.backend == "sounddevice":
                sd.stop()
            elif self._proc and self._proc.poll() is None:
                self._proc.kill()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Voice effects (pure numpy) — each returns (samples, time_scale)
# ---------------------------------------------------------------------------


def _spectral(x, sr, fn):
    n = 1 << int(math.ceil(math.log2(max(2, len(x)))))
    spec = np.fft.rfft(x, n)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    spec *= fn(freqs)
    return np.fft.irfft(spec, n)[: len(x)].astype(np.float32)


def bandpass(x, sr, lo, hi, soft=0.25):
    def resp(f):
        low = 1 / (1 + (lo / np.maximum(f, 1)) ** (8 * (1 - soft) + 2))
        high = 1 / (1 + (f / hi) ** (8 * (1 - soft) + 2))
        return low * high
    return _spectral(x, sr, resp)


def lowpass(x, sr, cutoff):
    return _spectral(x, sr, lambda f: 1 / (1 + (f / cutoff) ** 6))


def fft_convolve(x, ir):
    n = 1 << int(math.ceil(math.log2(len(x) + len(ir))))
    y = np.fft.irfft(np.fft.rfft(x, n) * np.fft.rfft(ir, n), n)
    return y[: len(x) + len(ir) - 1].astype(np.float32)


def reverb(x, sr, seconds=1.4, wet=0.35, damp=3000):
    rng = np.random.default_rng(7)
    n = int(sr * seconds)
    t = np.arange(n) / sr
    ir = rng.standard_normal(n).astype(np.float32) * np.exp(-t * 6.0 / seconds)
    ir = lowpass(ir, sr, damp)
    ir[0] = 0
    ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
    tail = fft_convolve(x, ir)
    dry = np.concatenate([x, np.zeros(len(tail) - len(x), np.float32)])
    return dry * (1 - wet * 0.5) + tail * wet


def echo(x, sr, delay=0.22, feedback=0.45, taps=5):
    d = int(sr * delay)
    out = np.concatenate([x, np.zeros(d * taps, np.float32)])
    for k in range(1, taps + 1):
        out[d * k: d * k + len(x)] += x * (feedback ** k)
    return out


def _normalize(x, peak=0.92):
    m = float(np.max(np.abs(x))) if len(x) else 0
    return x * (peak / m) if m > 1e-6 else x


VOICE_EFFECTS = ["None", "🤖 Robot", "📻 Old radio", "☎️ Telephone", "🏟️ Stadium hall", "🔁 Echo canyon",
                 "🐿️ Chipmunk", "👹 Giant / deep", "🌊 Underwater", "📢 Megaphone", "👽 Alien"]


def apply_effect(x, sr, name):
    if not name or name == "None":
        return x, 1.0
    key = name.split(" ", 1)[-1].lower()
    t = np.arange(len(x)) / sr
    scale = 1.0
    if "robot" in key:
        y = x * (0.55 + 0.45 * np.sin(2 * np.pi * 55 * t))
        y = y + 0.5 * np.concatenate([np.zeros(int(sr * 0.012)), y[: -int(sr * 0.012)]])
        y = np.round(y * 24) / 24
    elif "radio" in key:
        y = bandpass(x, sr, 350, 3200)
        y = np.tanh(y * 3.2) * 0.6
        y = y + np.random.default_rng(1).standard_normal(len(y)).astype(np.float32) * 0.012
        y = y * (0.92 + 0.08 * np.sin(2 * np.pi * 0.7 * t))
    elif "telephone" in key:
        y = bandpass(x, sr, 420, 3000, 0.6)
        y = np.round(np.tanh(y * 2.0) * 48) / 48
    elif "stadium" in key:
        y = reverb(x, sr, 2.4, 0.55, 2500)
    elif "echo" in key:
        y = echo(x, sr, 0.28, 0.5, 6)
    elif "chipmunk" in key:
        f = 1.38
        y = resample(x, sr, int(sr / f))
        scale = 1 / f
    elif "giant" in key:
        f = 0.76
        y = resample(x, sr, int(sr / f))
        y = reverb(y, sr, 1.0, 0.18, 1800)
        scale = 1 / f
    elif "underwater" in key:
        wob = 1 + 0.004 * np.sin(2 * np.pi * 3.2 * t)
        idx = np.clip(np.cumsum(wob) - 1, 0, len(x) - 1)
        y = np.interp(idx, np.arange(len(x)), x).astype(np.float32)
        y = lowpass(y, sr, 650)
        y = reverb(y, sr, 1.2, 0.3, 900)
    elif "megaphone" in key:
        y = bandpass(x, sr, 600, 2600, 0.5)
        y = np.tanh(y * 6.0)
        y = echo(y, sr, 0.09, 0.25, 2)
    elif "alien" in key:
        y = x * np.sin(2 * np.pi * 160 * t + 3 * np.sin(2 * np.pi * 4 * t))
        y = y * 0.7 + x * 0.3
        y = reverb(y, sr, 0.8, 0.25)
    else:
        return x, 1.0
    return _normalize(np.asarray(y, np.float32)), scale


# ---------------------------------------------------------------------------
# Background beds (generated) + mixing
# ---------------------------------------------------------------------------

BACKGROUNDS = ["None", "🌙 Calm pad", "☕ Lo-fi beat", "🎬 Cinematic drone", "🎵 My own music file…"]

_NOTE = {"A2": 110.0, "C3": 130.81, "D3": 146.83, "E3": 164.81, "F3": 174.61, "G3": 196.0, "A3": 220.0,
         "B3": 246.94, "C4": 261.63, "D4": 293.66, "E4": 329.63, "F4": 349.23, "G4": 392.0, "A4": 440.0}
_PROG = [("A2", "A3", "C4", "E4"), ("F3", "A3", "C4", "F4"), ("C3", "G3", "C4", "E4"), ("G3", "B3", "D4", "G4")]


def _pad(seconds, sr, chord_len=4.0):
    n = int(seconds * sr)
    out = np.zeros(n, np.float32)
    seg = int(chord_len * sr)
    t = np.arange(seg + sr) / sr
    env = np.minimum(1, t / 1.2) * np.exp(-np.maximum(0, t - chord_len) * 3)
    for i, start in enumerate(range(0, n, seg)):
        chord = _PROG[i % len(_PROG)]
        tone = np.zeros(len(t), np.float32)
        for k, note in enumerate(chord):
            f = _NOTE[note]
            for det in (-0.6, 0.6):
                tone += np.sin(2 * np.pi * (f + det) * t + k) * (0.22 if k == 0 else 0.14)
        tone *= env
        end = min(n, start + len(tone))
        out[start:end] += tone[: end - start]
    return lowpass(out, sr, 1400)


def _lofi(seconds, sr):
    n = int(seconds * sr)
    pad = _pad(seconds, sr) * 0.7
    beat = 60 / 78
    rng = np.random.default_rng(3)
    drums = np.zeros(n, np.float32)
    kt = np.arange(int(0.35 * sr)) / sr
    kick = np.sin(2 * np.pi * (48 + 70 * np.exp(-kt * 30)) * kt) * np.exp(-kt * 9)
    ht = np.arange(int(0.06 * sr)) / sr
    hat = rng.standard_normal(len(ht)).astype(np.float32) * np.exp(-ht * 70) * 0.25
    hat = bandpass(hat, sr, 5000, 11000)
    step = 0
    pos = 0.0
    while pos < seconds:
        i = int(pos * sr)
        if step % 4 in (0, 2) or (step % 8 == 7):
            e = min(n, i + len(kick))
            drums[i:e] += kick[: e - i] * (0.9 if step % 4 == 0 else 0.6)
        j = int((pos + beat / 2) * sr)
        for p in (i, j):
            e = min(n, p + len(hat))
            if p < n:
                drums[p:e] += hat[: e - p]
        pos += beat
        step += 1
    crackle = (rng.random(n) > 0.9993).astype(np.float32) * rng.standard_normal(n).astype(np.float32) * 0.2
    return lowpass(pad + drums * 0.8, sr, 5000) + crackle


def _drone(seconds, sr):
    n = int(seconds * sr)
    t = np.arange(n) / sr
    swell = 0.6 + 0.4 * np.sin(2 * np.pi * t / 9.0 - 1.5)
    tone = (np.sin(2 * np.pi * 55 * t) * 0.5 + np.sin(2 * np.pi * 82.4 * t) * 0.3 +
            np.sin(2 * np.pi * 110.3 * t) * 0.2) * swell
    noise = lowpass(np.random.default_rng(5).standard_normal(n).astype(np.float32), sr, 400) * 0.6 * swell
    return reverb((tone + noise).astype(np.float32), sr, 2.0, 0.4)[:n]


def make_background(kind, seconds, sr=WORK_SR, music_file=None):
    key = (kind or "").lower()
    if "pad" in key:
        bed = _pad(seconds, sr)
    elif "lo-fi" in key:
        bed = _lofi(seconds, sr)
    elif "drone" in key:
        bed = _drone(seconds, sr)
    elif "music" in key and music_file and os.path.exists(music_file):
        src = load_work(music_file)
        if len(src) == 0:
            return None
        reps = int(math.ceil(seconds * sr / len(src)))
        bed = np.tile(src, reps)[: int(seconds * sr)]
    else:
        return None
    return _normalize(bed.astype(np.float32), 0.8)


def mix_with_background(voice, sr, bed, volume=0.25, lead_in=0.7, tail=1.4):
    """Duck the bed under speech, with a lead-in and a fade-out tail. Returns (mix, offset_seconds)."""
    pad_l, pad_r = int(lead_in * sr), int(tail * sr)
    v = np.concatenate([np.zeros(pad_l, np.float32), voice, np.zeros(pad_r, np.float32)])
    bed = bed[: len(v)] if len(bed) >= len(v) else np.pad(bed, (0, len(v) - len(bed)))
    hop = max(1, sr // 50)
    m = len(v) // hop
    env = np.sqrt(np.mean(v[: m * hop].reshape(m, hop) ** 2, axis=1)) if m else np.zeros(1)
    env = np.convolve(env, np.ones(12) / 12, mode="same")
    duck = 1 - 0.55 * np.clip(env / (env.max() + 1e-9) * 3, 0, 1)
    duck = np.interp(np.arange(len(v)), np.arange(m) * hop, duck) if m else np.ones(len(v))
    fade = np.ones(len(v), np.float32)
    fade[: pad_l] = np.linspace(0, 1, pad_l) if pad_l else fade[:0]
    if pad_r:
        fade[-pad_r:] = np.linspace(1, 0, pad_r)
    out = v + bed * volume * duck * fade
    return _normalize(out.astype(np.float32), 0.95), lead_in


def process_speech(path, effect="None", background="None", bg_volume=0.25, music_file=None):
    """Apply effect + background to a rendered speech file.
    Returns (out_path, time_scale, time_offset). Unchanged input returns (path, 1, 0)."""
    if (not effect or effect == "None") and (not background or background == "None"):
        return path, 1.0, 0.0
    if not HAS_NP:
        raise RuntimeError("Effects need numpy (pip install numpy)")
    x = load_work(path)
    x, scale = apply_effect(x, WORK_SR, effect)
    offset = 0.0
    if background and background != "None":
        bed = make_background(background, len(x) / WORK_SR + 3.0, WORK_SR, music_file)
        if bed is not None:
            x, offset = mix_with_background(x, WORK_SR, bed, bg_volume)
    out = temp_path(".wav")
    write_wav(out, x, WORK_SR)
    return out, scale, offset


def concat_files(paths, gap=0.35):
    """Join several speech files. Returns (out_path, [start_seconds of each part])."""
    parts, starts, t = [], [], 0.0
    silence = np.zeros(int(gap * WORK_SR), np.float32)
    for i, p in enumerate(paths):
        x = load_work(p)
        starts.append(t)
        parts.append(x)
        t += len(x) / WORK_SR
        if i < len(paths) - 1:
            parts.append(silence)
            t += gap
    out = temp_path(".wav")
    write_wav(out, np.concatenate(parts) if parts else np.zeros(1, np.float32), WORK_SR)
    return out, starts
