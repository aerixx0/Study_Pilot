"""Small native dialogs used by the installed Start Menu shortcuts."""

import ctypes
from ctypes import wintypes
from pathlib import Path


def message(text, *, error=False, confirm=False):
    flags = 0x10 if error else 0x40
    if confirm:
        flags |= 0x04 | 0x100  # Yes/No, default to No.
    dialog = ctypes.windll.user32.MessageBoxW
    dialog.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    return dialog(None, text, "StudyPilot", flags) == 6


def choose_folder():
    class BrowseInfo(ctypes.Structure):
        _fields_ = [
            ("owner", wintypes.HWND), ("root", ctypes.c_void_p),
            ("display", wintypes.LPWSTR), ("title", wintypes.LPCWSTR),
            ("flags", wintypes.UINT), ("callback", ctypes.c_void_p),
            ("param", wintypes.LPARAM), ("image", ctypes.c_int),
        ]

    shell, ole = ctypes.windll.shell32, ctypes.windll.ole32
    shell.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BrowseInfo)]
    shell.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell.SHGetPathFromIDListEx.argtypes = [ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    result = ole.CoInitializeEx(None, 2)
    try:
        display = ctypes.create_unicode_buffer(260)
        info = BrowseInfo(None, None, ctypes.cast(display, wintypes.LPWSTR), "选择旧版 StudyPilot 项目、data 或 accounts 文件夹", 0x41)
        item = shell.SHBrowseForFolderW(ctypes.byref(info))
        if not item:
            return None
        try:
            path = ctypes.create_unicode_buffer(32768)
            if not shell.SHGetPathFromIDListEx(item, path, len(path), 0):
                raise OSError("无法读取选中的文件夹。")
            return Path(path.value)
        finally:
            ole.CoTaskMemFree(item)
    finally:
        if result in (0, 1):
            ole.CoUninitialize()
