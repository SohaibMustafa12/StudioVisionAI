# PyInstaller recipe — build with:  powershell -ExecutionPolicy Bypass -File build_and_install.ps1
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = SPECPATH

datas = [("assets", "assets"), ("sv/worker.py", "sv")]
datas += collect_data_files("speech_recognition")  # bundled FLAC encoder for online recognition
datas += collect_data_files("gtts")

# these are imported lazily at runtime (fast start-up), so PyInstaller has to be told about them
hiddenimports = (collect_submodules("qrcode") + collect_submodules("pyttsx3") + collect_submodules("edge_tts") +
                 collect_submodules("gtts") + collect_submodules("deep_translator") +
                 ["win32com.client", "pythoncom", "pywintypes", "speech_recognition", "sounddevice", "cv2",
                  "aiohttp", "certifi"])

a = Analysis(
    ["studio_vision.pyw"],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "torch", "tensorflow", "f5_tts", "faster_whisper", "IPython", "pandas",
              "scipy", "PyQt6.QtWebEngineCore", "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.Qt3DCore",
              "PyQt6.QtMultimedia", "PyQt6.QtBluetooth", "PyQt6.QtPdf", "PyQt6.QtSql"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Studio Vision AI",
    icon="assets/app.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Studio Vision AI")
