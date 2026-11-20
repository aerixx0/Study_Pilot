"""StudyPilot credentials in the current Windows user's Credential Manager."""

import ctypes
from ctypes import wintypes
import json
import os

TARGET = "StudyPilot.LocalAI"
FIELDS = {"SILICONFLOW_API_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"}
RELAY_FIELDS = {"STUDYPILOT_RELAY_TOKEN"}


class Credential(ctypes.Structure):
    _fields_ = [
        ("flags", wintypes.DWORD), ("type", wintypes.DWORD), ("target", wintypes.LPWSTR),
        ("comment", wintypes.LPWSTR), ("written", wintypes.FILETIME), ("size", wintypes.DWORD),
        ("blob", ctypes.c_void_p), ("persist", wintypes.DWORD), ("attribute_count", wintypes.DWORD),
        ("attributes", ctypes.c_void_p), ("alias", wintypes.LPWSTR), ("username", wintypes.LPWSTR),
    ]


def read_credentials(*, target=TARGET):
    if os.name != "nt":
        return {}
    api = ctypes.WinDLL("Advapi32", use_last_error=True)
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(Credential))]
    api.CredFree.argtypes = [ctypes.c_void_p]
    handle = ctypes.POINTER(Credential)()
    if not api.CredReadW(target, 1, 0, ctypes.byref(handle)):
        if ctypes.get_last_error() != 1168:  # ERROR_NOT_FOUND
            raise OSError("无法读取 Windows 凭据管理器。")
        return {}
    try:
        values = json.loads(ctypes.string_at(handle.contents.blob, handle.contents.size))
        if isinstance(values, dict):
            return {key: value for key, value in values.items()
                    if key in (FIELDS if target == TARGET else RELAY_FIELDS) and isinstance(value, str)}
        return {}
    except (ValueError, UnicodeError):
        return {}
    finally:
        api.CredFree(handle)


def write_credentials(values, *, target=TARGET):
    if os.name != "nt":
        raise ValueError("Windows 凭据管理器仅适用于 Windows。")
    fields = FIELDS if target == TARGET else RELAY_FIELDS
    payload = json.dumps({key: value for key, value in values.items() if key in fields},
                         ensure_ascii=True).encode("ascii")
    if len(payload) > 2560:
        raise ValueError("凭据太长，请检查输入。")
    buffer = ctypes.create_string_buffer(payload)
    entry = Credential(type=1, target=target, size=len(payload), blob=ctypes.addressof(buffer),
                       persist=2, username="StudyPilot")
    api = ctypes.WinDLL("Advapi32", use_last_error=True)
    api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    if not api.CredWriteW(ctypes.byref(entry), 0):
        raise OSError("无法保存到 Windows 凭据管理器。")
