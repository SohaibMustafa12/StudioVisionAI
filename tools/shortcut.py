"""Create a .lnk shortcut that carries the app's AppUserModelID (so the taskbar groups it with the window).
Usage: shortcut.py <lnk_path> <target_exe> <icon> <app_id> <description>"""

import sys

import win32com.client
from win32com.propsys import propsys, pscon
from win32com.shell import shellcon


def make(lnk, target, icon, app_id, desc):
    import os
    sh = win32com.client.Dispatch("WScript.Shell")
    s = sh.CreateShortcut(lnk)
    s.TargetPath = target
    s.WorkingDirectory = os.path.dirname(target)
    s.IconLocation = icon + ",0"
    s.Description = desc
    s.Save()
    store = propsys.SHGetPropertyStoreFromParsingName(lnk, None, shellcon.GPS_READWRITE,
                                                      propsys.IID_IPropertyStore)
    store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(app_id))
    store.Commit()


if __name__ == "__main__":
    make(*sys.argv[1:6])
    print("shortcut:", sys.argv[1])
