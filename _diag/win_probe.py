# -*- coding: utf-8 -*-
"""枚举所有标题含「视频知识库」的顶层窗口，看清楚 FindWindowW 到底拿到了谁。"""
import ctypes
import ctypes.wintypes as wt
import os
import sys

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

u32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
u32.ClientToScreen.restype = wt.BOOL


def proc_name(pid):
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return "?"
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.c_ulong(1024)
        return os.path.basename(buf.value) if k32.QueryFullProcessImageNameW(
            h, 0, buf, ctypes.byref(n)) else "?"
    finally:
        k32.CloseHandle(h)


rows = []


def cb(hwnd, _):
    b = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(hwnd, b, 256)
    t = ctypes.create_unicode_buffer(512)
    u32.GetWindowTextW(hwnd, t, 512)
    if "视频知识库" in t.value:
        pid = ctypes.c_ulong()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        r = wt.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        cr = wt.RECT()
        u32.GetClientRect(hwnd, ctypes.byref(cr))
        pt = wt.POINT(0, 0)
        u32.ClientToScreen(hwnd, ctypes.byref(pt))
        rows.append((int(hwnd), b.value, t.value, bool(u32.IsWindowVisible(hwnd)),
                     (r.left, r.top, r.right - r.left, r.bottom - r.top),
                     (cr.right, cr.bottom), (pt.x, pt.y), proc_name(pid.value), pid.value))
    return True


u32.EnumWindows(ENUMPROC(cb), None)
print("含「视频知识库」的顶层窗口 %d 个：" % len(rows))
for h, cls, title, vis, rect, client, origin, pname, pid in rows:
    print("  hwnd=%-9d pid=%-6d %-22s vis=%-5s winRect=%-24s client=%-12s clientOrigin=%s  title=%r"
          % (h, pid, pname, vis, rect, client, origin, title))

print("\nFindWindowW(None, '视频知识库 · 工作台') =", u32.FindWindowW(None, "视频知识库 · 工作台"))

# 也看看有没有 Ctrl+Alt+空格 那种无声窗口：列出所有 WindowsForms 类窗口
rows2 = []


def cb2(hwnd, _):
    b = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(hwnd, b, 256)
    if "WindowsForms" in b.value or b.value == "Chrome_WidgetWin_1":
        t = ctypes.create_unicode_buffer(512)
        u32.GetWindowTextW(hwnd, t, 512)
        pid = ctypes.c_ulong()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        r = wt.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        rows2.append((int(hwnd), b.value, t.value, bool(u32.IsWindowVisible(hwnd)),
                      (r.left, r.top, r.right - r.left, r.bottom - r.top), proc_name(pid.value)))
    return True


u32.EnumWindows(ENUMPROC(cb2), None)
print("\nWinForms / Chromium 窗口 %d 个：" % len(rows2))
for h, cls, title, vis, rect, pname in rows2[:25]:
    print("  hwnd=%-9d %-24s vis=%-5s rect=%-24s %s  title=%r" % (h, cls, vis, rect, pname, title))
