"""Paths, optional dependencies, languages and free translation. No Qt in here."""

import asyncio
import atexit
import ctypes
import importlib.util
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import uuid

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
FROZEN = getattr(sys, "frozen", False)

# ---------------------------------------------------------------------------
# Optional dependencies — the app still starts if any of these are missing.
# ---------------------------------------------------------------------------
try:
    import numpy as np
    HAS_NP = True
except Exception:
    np = None
    HAS_NP = False

def _has(mod):
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


class _Lazy:
    """Module stand-in that imports on first use — keeps start-up fast (edge-tts alone costs ~1.3 s)."""

    def __init__(self, name, attr=None):
        self._name, self._attr, self._obj = name, attr, None

    def _load(self):
        if self._obj is None:
            mod = importlib.import_module(self._name)
            self._obj = getattr(mod, self._attr) if self._attr else mod
        return self._obj

    def __getattr__(self, item):
        return getattr(self._load(), item)

    def __call__(self, *a, **k):
        return self._load()(*a, **k)


def warm_imports():
    """Import the lazy modules in the background once the window is up, so the first click is instant."""
    for m in (edge_tts, gTTS, GoogleTranslator, sd):
        try:
            m._load()
        except Exception:
            pass


try:
    import soundfile as sf
    HAS_SF = True
except Exception:
    sf = None
    HAS_SF = False

try:
    import pygame
    HAS_PYGAME = True
except Exception:
    pygame = None
    HAS_PYGAME = False

HAS_SD = _has("sounddevice")
sd = _Lazy("sounddevice")
HAS_EDGE = _has("edge_tts")
edge_tts = _Lazy("edge_tts")
HAS_GTTS = _has("gtts")
gTTS = _Lazy("gtts", "gTTS")
HAS_DEEP = _has("deep_translator")
GoogleTranslator = _Lazy("deep_translator", "GoogleTranslator")
HAS_PYTTSX3 = _has("pyttsx3")
pyttsx3 = _Lazy("pyttsx3")
# Heavy / optional engines are imported lazily so the app opens instantly.
HAS_CV2 = _has("cv2")
HAS_F5 = _has("f5_tts")
HAS_WHISPER = _has("faster_whisper")
HAS_SR = _has("speech_recognition")

# ---------------------------------------------------------------------------
# Paths, logging, housekeeping
# ---------------------------------------------------------------------------


def get_resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_path, relative_path)


def _app_data_dir():
    if os.environ.get("SV_DATA_DIR"):  # the self-test runs in its own sandbox folder
        os.makedirs(os.environ["SV_DATA_DIR"], exist_ok=True)
        return os.environ["SV_DATA_DIR"]
    if IS_WIN:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif IS_MAC:
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    path = os.path.join(base, "StudioVisionAI")
    os.makedirs(path, exist_ok=True)
    return path


DATA_DIR = _app_data_dir()
PROFILES_DIR = os.path.join(DATA_DIR, "voice_profiles")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
for _d in (PROFILES_DIR, HISTORY_DIR):
    os.makedirs(_d, exist_ok=True)
TEMP_DIR = tempfile.mkdtemp(prefix="studiovision_")
atexit.register(lambda: shutil.rmtree(TEMP_DIR, ignore_errors=True))

logging.basicConfig(
    filename=os.path.join(DATA_DIR, "studio_vision.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("studio")


def _migrate_legacy_profiles():
    """Old versions saved profiles to ./voice_profiles relative to wherever the app was started."""
    for legacy in {os.path.join(os.getcwd(), "voice_profiles")}:
        if os.path.isdir(legacy) and os.path.abspath(legacy) != os.path.abspath(PROFILES_DIR):
            for name in os.listdir(legacy):
                src, dst = os.path.join(legacy, name), os.path.join(PROFILES_DIR, name)
                if os.path.isfile(src) and not os.path.exists(dst):
                    try:
                        shutil.copy2(src, dst)
                    except OSError:
                        pass


_migrate_legacy_profiles()


def temp_path(ext):
    return os.path.join(TEMP_DIR, f"{uuid.uuid4().hex}{ext}")


APP_ID = "StudioVisionAI.App.3"
if IS_WIN:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def hidden_window_kwargs():
    if IS_WIN:
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


def run_async(coro_factory, timeout):
    async def runner():
        return await asyncio.wait_for(coro_factory(), timeout=timeout)
    return asyncio.run(runner())


def safe_name(raw, fallback="file"):
    return re.sub(r"[^\w\-. ]+", "_", raw or "").strip(" ._") or fallback

# ---------------------------------------------------------------------------
# Languages & voices
# ---------------------------------------------------------------------------


LANGUAGES = [
    ("None (speak original text)", None),
    ("Urdu", "ur"), ("English", "en"), ("Hindi", "hi"), ("Arabic", "ar"), ("Punjabi", "pa"),
    ("Bengali", "bn"), ("Persian", "fa"), ("Turkish", "tr"), ("Spanish", "es"), ("French", "fr"),
    ("German", "de"), ("Italian", "it"), ("Portuguese", "pt"), ("Russian", "ru"),
    ("Japanese", "ja"), ("Korean", "ko"), ("Chinese (Simplified)", "zh-CN"),
    ("Chinese (Traditional)", "zh-TW"), ("Dutch", "nl"), ("Polish", "pl"), ("Ukrainian", "uk"),
    ("Indonesian", "id"), ("Malay", "ms"), ("Vietnamese", "vi"), ("Thai", "th"), ("Tamil", "ta"),
    ("Telugu", "te"), ("Swahili", "sw"), ("Greek", "el"), ("Swedish", "sv"),
]
LANG_NAME = {code: name for name, code in LANGUAGES if code}

# Offline fallback list, used when the live Edge voice catalogue can't be downloaded.
STATIC_EDGE_VOICES = [
    ("en-US-GuyNeural", "Male"), ("en-US-JennyNeural", "Female"), ("en-US-AriaNeural", "Female"),
    ("en-US-AnaNeural", "Female"), ("en-US-ChristopherNeural", "Male"), ("en-GB-RyanNeural", "Male"),
    ("en-GB-SoniaNeural", "Female"), ("en-AU-WilliamNeural", "Male"), ("en-AU-NatashaNeural", "Female"),
    ("en-IN-PrabhatNeural", "Male"), ("en-IN-NeerjaNeural", "Female"), ("en-NG-AbeoNeural", "Male"),
    ("en-IE-ConnorNeural", "Male"), ("ur-PK-AsadNeural", "Male"), ("ur-PK-UzmaNeural", "Female"),
    ("ur-IN-SalmanNeural", "Male"), ("ur-IN-GulNeural", "Female"), ("hi-IN-MadhurNeural", "Male"),
    ("hi-IN-SwaraNeural", "Female"), ("ar-SA-HamedNeural", "Male"), ("ar-SA-ZariyahNeural", "Female"),
    ("ar-EG-ShakirNeural", "Male"), ("ar-EG-SalmaNeural", "Female"), ("bn-BD-PradeepNeural", "Male"),
    ("bn-BD-NabanitaNeural", "Female"), ("fa-IR-FaridNeural", "Male"), ("fa-IR-DilaraNeural", "Female"),
    ("tr-TR-AhmetNeural", "Male"), ("tr-TR-EmelNeural", "Female"), ("es-ES-AlvaroNeural", "Male"),
    ("es-ES-ElviraNeural", "Female"), ("es-MX-JorgeNeural", "Male"), ("es-MX-DaliaNeural", "Female"),
    ("fr-FR-HenriNeural", "Male"), ("fr-FR-DeniseNeural", "Female"), ("de-DE-ConradNeural", "Male"),
    ("de-DE-KatjaNeural", "Female"), ("it-IT-DiegoNeural", "Male"), ("it-IT-ElsaNeural", "Female"),
    ("pt-BR-AntonioNeural", "Male"), ("pt-BR-FranciscaNeural", "Female"), ("ru-RU-DmitryNeural", "Male"),
    ("ru-RU-SvetlanaNeural", "Female"), ("ja-JP-KeitaNeural", "Male"), ("ja-JP-NanamiNeural", "Female"),
    ("ko-KR-InJoonNeural", "Male"), ("ko-KR-SunHiNeural", "Female"), ("zh-CN-YunxiNeural", "Male"),
    ("zh-CN-XiaoxiaoNeural", "Female"), ("zh-TW-YunJheNeural", "Male"), ("zh-TW-HsiaoChenNeural", "Female"),
    ("nl-NL-MaartenNeural", "Male"), ("nl-NL-ColetteNeural", "Female"), ("pl-PL-MarekNeural", "Male"),
    ("pl-PL-ZofiaNeural", "Female"), ("uk-UA-OstapNeural", "Male"), ("uk-UA-PolinaNeural", "Female"),
    ("id-ID-ArdiNeural", "Male"), ("id-ID-GadisNeural", "Female"), ("ms-MY-OsmanNeural", "Male"),
    ("ms-MY-YasminNeural", "Female"), ("vi-VN-NamMinhNeural", "Male"), ("vi-VN-HoaiMyNeural", "Female"),
    ("th-TH-NiwatNeural", "Male"), ("th-TH-PremwadeeNeural", "Female"), ("ta-IN-ValluvarNeural", "Male"),
    ("ta-IN-PallaviNeural", "Female"), ("te-IN-MohanNeural", "Male"), ("te-IN-ShrutiNeural", "Female"),
    ("sw-KE-RafikiNeural", "Male"), ("sw-KE-ZuriNeural", "Female"), ("el-GR-NestorasNeural", "Male"),
    ("el-GR-AthinaNeural", "Female"), ("sv-SE-MattiasNeural", "Male"), ("sv-SE-SofieNeural", "Female"),
]
WELL_KNOWN_VOICES = {name for name, _ in STATIC_EDGE_VOICES}
FEATURED_TAGS = {
    "en-US-AnaNeural": "Anime / young",
    "ja-JP-NanamiNeural": "Anime style",
    "ko-KR-SunHiNeural": "K-drama",
    "en-GB-RyanNeural": "British",
    "en-AU-WilliamNeural": "Aussie",
    "en-IN-PrabhatNeural": "Indian accent",
    "en-NG-AbeoNeural": "Nigerian",
    "en-IE-ConnorNeural": "Irish",
}
PREFERRED_LOCALE = {"en": "en-US", "ur": "ur-PK", "es": "es-ES", "pt": "pt-BR", "ar": "ar-SA",
                    "fr": "fr-FR", "de": "de-DE", "bn": "bn-BD", "sw": "sw-KE", "hi": "hi-IN",
                    "pa": "pa-IN", "fa": "fa-IR", "tr": "tr-TR", "it": "it-IT", "ru": "ru-RU",
                    "ja": "ja-JP", "ko": "ko-KR", "nl": "nl-NL", "pl": "pl-PL", "uk": "uk-UA",
                    "id": "id-ID", "ms": "ms-MY", "vi": "vi-VN", "th": "th-TH", "ta": "ta-IN",
                    "te": "te-IN", "el": "el-GR", "sv": "sv-SE"}


def bcp47(lang):
    """'ur' -> 'ur-PK' for speech recognisers that want a region."""
    if not lang:
        return "en-US"
    if "-" in lang:
        return lang
    return PREFERRED_LOCALE.get(lang, lang)


def locale_matches(locale, lang):
    if not locale or not lang:
        return False
    locale, lang = locale.lower().replace("_", "-"), lang.lower()
    if lang in ("zh-cn", "zh-tw"):
        return locale.startswith(lang) or (lang == "zh-tw" and locale.startswith("zh-hk"))
    return locale.split("-")[0] == lang.split("-")[0]


def flag_emoji(locale):
    parts = locale.replace("_", "-").split("-")
    if len(parts) < 2 or len(parts[1]) != 2 or not parts[1].isalpha():
        return "🌐"
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in parts[1].upper())


def guess_lang(text):
    """Offline script detection so non-Latin text is never sent to a voice that can't read it."""
    counts = {}

    def bump(key):
        counts[key] = counts.get(key, 0) + 1

    for ch in text:
        o = ord(ch)
        if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0xFB50 <= o <= 0xFEFF:
            bump("arabic")
        elif 0x0900 <= o <= 0x097F:
            bump("hi")
        elif 0x0980 <= o <= 0x09FF:
            bump("bn")
        elif 0x0A00 <= o <= 0x0A7F:
            bump("pa")
        elif 0x0B80 <= o <= 0x0BFF:
            bump("ta")
        elif 0x0C00 <= o <= 0x0C7F:
            bump("te")
        elif 0x0E00 <= o <= 0x0E7F:
            bump("th")
        elif 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:
            bump("ko")
        elif 0x3040 <= o <= 0x30FF:
            bump("kana")
        elif 0x4E00 <= o <= 0x9FFF:
            bump("cjk")
        elif 0x0400 <= o <= 0x04FF:
            bump("cyr")
        elif 0x0370 <= o <= 0x03FF:
            bump("el")
        elif ch.isalpha():
            bump("latin")
    if not counts:
        return None
    top = max(counts, key=counts.get)
    if top == "latin":
        return None  # Latin script: could be many languages — don't guess
    if top == "arabic":
        if any(c in text for c in "ٹڈڑںےۓھ"):
            return "ur"
        if any(c in text for c in "پچژگک") and "ة" not in text:
            return "fa"
        return "ar"
    if top in ("kana",) or (top == "cjk" and counts.get("kana")):
        return "ja"
    if top == "cjk":
        return "zh-CN"
    if top == "cyr":
        return "uk" if any(c in text for c in "іїєґ") else "ru"
    return top


# ---------------------------------------------------------------------------
# Translation (free, no keys) with multiple fallbacks
# ---------------------------------------------------------------------------


def _chunk_text(text, limit=1500):
    parts = re.split(r"(?<=[.!?。！？۔\n])\s+", text)
    chunks, cur = [], ""
    for part in parts:
        while len(part) > limit:
            chunks.append(part[:limit])
            part = part[limit:]
        if len(cur) + len(part) + 1 > limit and cur:
            chunks.append(cur)
            cur = part
        else:
            cur = f"{cur} {part}".strip()
    if cur:
        chunks.append(cur)
    return chunks or [text]


def _http_json(url, data=None, timeout=15):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0 StudioVision"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _translate_google_web(text, target, source="auto"):
    url = (f"https://translate.googleapis.com/translate_a/single?client=gtx&dt=t&sl={urllib.parse.quote(source)}"
           f"&tl={urllib.parse.quote(target)}")
    data = _http_json(url, data=urllib.parse.urlencode({"q": text}).encode("utf-8"))
    return "".join(seg[0] for seg in data[0] if seg and seg[0])


def _translate_mymemory(text, target, source="auto"):
    if source == "auto":
        source = guess_lang(text) or "en"
    if source.split("-")[0] == target.split("-")[0]:
        return text
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(
        {"q": text, "langpair": f"{source}|{target}"})
    data = _http_json(url)
    result = (data.get("responseData") or {}).get("translatedText") or ""
    if "MYMEMORY WARNING" in result.upper():
        raise RuntimeError("MyMemory daily free limit reached")
    return result


def _translate_deep(text, target, source="auto"):
    return GoogleTranslator(source=source, target=target).translate(text)


_DETECTED = {}


def detect_language(text):
    """Script check first (offline); for Latin-script text ask Google's free endpoint which language it is."""
    g = guess_lang(text)
    if g:
        return g
    sample = re.sub(r"\s+", " ", text or "").strip()[:400]
    if len(re.findall(r"[A-Za-zÀ-ÿ]", sample)) < 4:
        return None
    if sample in _DETECTED:
        return _DETECTED[sample]
    code = None
    try:
        url = "https://translate.googleapis.com/translate_a/single?client=gtx&dt=t&sl=auto&tl=en"
        data = _http_json(url, data=urllib.parse.urlencode({"q": sample}).encode("utf-8"), timeout=6)
        code = data[2] if len(data) > 2 and isinstance(data[2], str) else None
    except Exception as e:
        log.info("Language detection unavailable: %s", e)
    if code:
        code = {"zh-CN": "zh-CN", "zh-TW": "zh-TW", "iw": "he", "jw": "jv"}.get(code, code.split("-")[0])
    _DETECTED[sample] = code
    return code


def total_ram_gb():
    if IS_WIN:
        class MEMSTAT(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = MEMSTAT()
        st.dwLength = ctypes.sizeof(MEMSTAT)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return st.ullTotalPhys / 1024 ** 3
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except Exception:
        return 16.0


def torch_threads():
    """PyTorch on a CPU runs fastest with one thread per *physical* core; hyper-threads just fight."""
    n = os.cpu_count() or 4
    return str(max(1, n // 2 if n >= 8 else n))


def translate_text(text, target, source="auto"):
    providers = []
    if HAS_DEEP:
        providers.append(("Google", _translate_deep))
    providers += [("Google (web)", _translate_google_web), ("MyMemory", _translate_mymemory)]
    out, used = [], set()
    for chunk in _chunk_text(text):
        errors = []
        for name, fn in providers:
            try:
                res = fn(chunk, target, source or "auto")
                if res and res.strip():
                    out.append(res.strip())
                    used.add(name)
                    break
                errors.append(f"{name}: empty result")
            except Exception as e:  # network/provider issue -> next provider
                errors.append(f"{name}: {e}")
        else:
            raise RuntimeError("All free translators failed — check your internet.\n" + "\n".join(errors))
    return " ".join(out), ", ".join(sorted(used))
