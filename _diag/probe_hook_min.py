# -*- coding: utf-8 -*-
"""最小复现：WinEvent 钩子的 ctypes 回调挂掉（exit 0xC000041D）。

只做一件事：装 EVENT_OBJECT_CREATE 钩子，起一个有控制台的 cmd，
看回调里到底哪一步炸。faulthandler 打出 C 级栈。
"""

import ctypes
import faulthandler
import subprocess
import threading
import time
from ctypes import wintypes

faulthandler.enable()

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

EVENT_OBJECT_CREATE = 0x8000
WINEVENT_OUTOFCONTEXT = 0x0000
CREATE_NEW_CONSOLE = 0x00000010

WinEventProc = ctypes.WINFUNCTYPE(
    None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
    wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)

n = [0]


def on_event(hook, ev, hwnd, idobj, idchild, tid, tm):
    n[0] += 1
    print("event #%d hwnd=%r idobj=%r" % (n[0], hwnd, idobj), flush=True)
    buf = ctypes.create_unicode_buffer(256)
    r = user32.GetClassNameW(hwnd, buf, 256)
    print("   GetClassNameW -> %r / %r" % (r, buf.value), flush=True)


user32.SetWinEventHook.restype = wintypes.HANDLE
user32.SetWinEventHook.argtypes = [
    wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WinEventProc,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]


def loop():
    h = user32.SetWinEventHook(
        EVENT_OBJECT_CREATE, EVENT_OBJECT_CREATE, None,
        WinEventProc(on_event), 0, 0, WINEVENT_OUTOFCONTEXT)
    print("hook = %r" % h, flush=True)
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


threading.Thread(target=loop, daemon=True).start()
time.sleep(1.0)

print("=== 起一个带控制台的 cmd ===", flush=True)
p = subprocess.Popen(["cmd.exe", "/c", "ping -n 2 127.0.0.1 >nul"],
                     creationflags=CREATE_NEW_CONSOLE)
p.wait()
time.sleep(1.5)

print("=== 总事件数 = %d ===" % n[0], flush=True)
