import sys

sys.stdout.reconfigure(encoding="utf-8")
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32


def enum_windows_proc(hwnd, lParam):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value in (20692, 21120):
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value
        vis = user32.IsWindowVisible(hwnd)
        if title or vis:
            print(f"HWND: {hwnd:#x}, Visible: {vis}, Title: '{title}'")
    return True


WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows(WNDENUMPROC(enum_windows_proc), 0)
