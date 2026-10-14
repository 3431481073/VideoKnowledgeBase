# -*- coding: utf-8 -*-
"""对照：把 argtypes/restype 全部显式声明之后，同样的钩子还炸不炸。

假设（待证伪）：上一次的 access violation 是因为没声明 argtypes ——
64 位 HWND 被 ctypes 当 c_int 传，截断成野句柄。
观察 A（这里不炸）-> 假设成立，正式探针照这个写法改。
观察 B（这里还炸）-> 假设不成立，得换别的检测手段。
"""

import ctypes
import faulthandler
import subprocess
import threading
import time
from ctypes import wintypes

faulthandler.enable()

print("wintypes 有哪些名字: %s" % [n for n in
      ("LONG", "HANDLE", "HWND", "DWORD", "MSG", "WPARAM", "LPARAM",
       "BOOL", "UINT", "POINT", "HMODULE") if hasattr(wintypes, n)], flush=True)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---------------- 关键：全部显式声明 ----------------
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]

EVENT_OBJECT_CREATE = 0x8000
WINEVENT_OUTOFCONTEXT = 0x0000
CREATE_NEW_CONSOLE = 0x00000010

WinEventProc = ctypes.WINFUNCTYPE(
    None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
    wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)

user32.SetWinEventHook.restype = wintypes.HANDLE
user32.SetWinEventHook.argtypes = [
    wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WinEventProc,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]

n = [0]
hits = []


def on_event(hook, ev, hwnd, idobj, idchild, tid, tm):
    n[0] += 1
    try:
        buf = ctypes.create_unicode_buffer(512)
        if user32.GetClassNameW(hwnd, buf, 512):
            hits.append((hwnd, buf.value))
    except Exception as e:                                # noqa: BLE001
        hits.append((hwnd, "ERR %s" % e))


_keep = None          # ★ 必须把这个回调实例**存住**，否则它被 GC 掉，跳板成野指针


def loop():
    global _keep
    _keep = WinEventProc(on_event)
    h = user32.SetWinEventHook(
        EVENT_OBJECT_CREATE, EVENT_OBJECT_CREATE, None,
        _keep, 0, 0, WINEVENT_OUTOFCONTEXT)
    print("hook = %r  (回调实例已存住: %r)" % (h, _keep), flush=True)
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
print("=== 抓到 %d 个窗口类 ===" % len(hits), flush=True)
for h, c in hits[:40]:
    print("    %-8s %s" % (h, c), flush=True)
cons = [c for _h, c in hits if c == "ConsoleWindowClass"]
print("=== ConsoleWindowClass 命中 %d 个 ===" % len(cons), flush=True)
