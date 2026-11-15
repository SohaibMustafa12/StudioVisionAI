"""Windows integration: global hotkeys, grabbing the selected text, start-with-Windows."""

import ctypes
import os
import sys
import time

from .core import FROZEN, IS_WIN, log

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

HOTKEYS = {
    "Ctrl+Alt+S": (MOD_CONTROL | MOD_ALT, ord("S")),
    "Ctrl+Alt+R": (MOD_CONTROL | MOD_ALT, ord("R")),
    "Ctrl+Shift+Space": (MOD_CONTROL | MOD_SHIFT, 0x20),
    "Win+Alt+S": (MOD_WIN | MOD_ALT, ord("S")),
}
TRANSLATE_HOTKEYS = {
    "Ctrl+Alt+T": (MOD_CONTROL | MOD_ALT, ord("T")),
    "Ctrl+Shift+T": (MOD_CONTROL | MOD_SHIFT, ord("T")),
    "Off": None,
}
SHOW_HOTKEYS = {
    "Ctrl+Alt+V": (MOD_CONTROL | MOD_ALT, ord("V")),
    "Ctrl+Alt+Space": (MOD_CONTROL | MOD_ALT, 0x20),
    "Win+Shift+V": (MOD_WIN | MOD_SHIFT, ord("V")),
    "Off": None,
}
HK_SPEAK, HK_TRANSLATE, HK_SHOW = 0x5301, 0x5302, 0x5303


def register_hotkey(hwnd, hk_id, combo):
    if not IS_WIN or not combo:
        return False
    user32 = ctypes.windll.user32
    user32.UnregisterHotKey(ctypes.c_void_p(hwnd), hk_id)
    mods, vk = combo
    ok = bool(user32.RegisterHotKey(ctypes.c_void_p(hwnd), hk_id, mods | MOD_NOREPEAT, vk))
    if not ok:
        log.warning("RegisterHotKey failed for id %s (already used by another app?)", hk_id)
    return ok


def unregister_hotkey(hwnd, hk_id):
    if IS_WIN:
        ctypes.windll.user32.UnregisterHotKey(ctypes.c_void_p(hwnd), hk_id)


def hotkey_id_from_msg(message):
    """Return the hotkey id if this native message is WM_HOTKEY, else None."""
    if not IS_WIN:
        return None
    from ctypes import wintypes
    try:
        msg = wintypes.MSG.from_address(int(message))
    except Exception:
        return None
    if msg.message == WM_HOTKEY:
        return int(msg.wParam)
    return None


def modifiers_down():
    if not IS_WIN:
        return False
    gak = ctypes.windll.user32.GetAsyncKeyState
    return any(gak(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C))


def send_copy():
    """Press Ctrl+C in whatever app has focus."""
    if not IS_WIN:
        return
    kb = ctypes.windll.user32.keybd_event
    kb(0x11, 0, 0, 0)
    kb(0x43, 0, 0, 0)
    time.sleep(0.02)
    kb(0x43, 0, 2, 0)
    kb(0x11, 0, 2, 0)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "StudioVisionAI"


def _launch_command(tray=True):
    flag = " --tray" if tray else ""
    if FROZEN:
        return f'"{sys.executable}"{flag}'
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    main = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "studio_vision.pyw")
    return f'"{pyw if os.path.exists(pyw) else sys.executable}" "{main}"{flag}'


def startup_mode():
    """None = off, False = opens the window, True = starts hidden in the tray."""
    if not IS_WIN:
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            cmd, _ = winreg.QueryValueEx(k, RUN_NAME)
            return "--tray" in cmd
    except OSError:
        return None


def startup_enabled():
    return startup_mode() is not None


def set_startup(enabled, tray=True):
    if not IS_WIN:
        return False
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, _launch_command(tray))
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass
    return True
