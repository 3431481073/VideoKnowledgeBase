# -*- coding: utf-8 -*-
"""合成鼠标点击到底能不能驱动 WebView2？用 JS 状态直接回答，不看像素。

像素相同有两种可能：
  (A) 点击没落地                      -> 状态不会变
  (B) 点击落地了，但 PrintWindow 给的是旧帧 -> 状态会变
只有读 JS 状态能把两者分开。所以这个探针在 pythonw 里跑真实应用，
一边用 mouse_event 点击，一边用 evaluate_js 读 VKBProcess.state()。
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
OUT = os.path.join(DIAG, "click_results.txt")
T0 = time.monotonic()

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
g32 = ctypes.windll.gdi32

# 【关键】先把本进程设成 per-monitor DPI aware，否则 Win32 返回的是被
# 虚拟化过的坐标，而页面用的是 CSS 像素 —— 本机 150%，两者差 1.5 倍，
# 点击会落在别的地方。实测：客户区 1838 物理像素 vs 视口 1225 CSS 像素。
try:
    u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # PER_MONITOR_AWARE_V2
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        u32.SetProcessDPIAware()
ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
u32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
u32.ClientToScreen.restype = wt.BOOL
PW_RENDERFULLCONTENT = 0x00000002

TITLE = "视频知识库 · 工作台"


def log(m):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("t=%6.2f  %s\n" % (time.monotonic() - T0, m))


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


def own_hwnd():
    """属于本进程的窗口（按 pid 挑，不按标题）。"""
    me = k32.GetCurrentProcessId()
    found = []

    def cb(hwnd, _):
        pid = ctypes.c_ulong()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == me and u32.IsWindowVisible(hwnd):
            cr = wt.RECT()
            u32.GetClientRect(hwnd, ctypes.byref(cr))
            if cr.right > 200 and cr.bottom > 200:
                found.append(int(hwnd))
        return True

    u32.EnumWindows(ENUMPROC(cb), None)
    return found[0] if found else 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def snapshot(hwnd):
    r = wt.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(r))
    w, h = r.right, r.bottom
    if w <= 0 or h <= 0:
        return None
    hdc = u32.GetDC(hwnd)
    mem = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    g32.SelectObject(mem, bmp)
    u32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)
    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mem)
    u32.ReleaseDC(hwnd, hdc)
    raw = buf.raw
    colors = set()
    for y in range(0, h, 3):
        for x in range(0, w, 4):
            i = (y * w + x) * 4
            colors.add((raw[i] >> 2, raw[i + 1] >> 2, raw[i + 2] >> 2))
    return frozenset(colors), len(colors)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


u32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
u32.SendInput.restype = wt.UINT
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]

INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


u32.GetDpiForWindow.argtypes = [wt.HWND]


def dpi_scale(hwnd, css_w):
    """物理像素 / CSS 像素。优先用窗口 DPI，并拿客户区宽度交叉验证。"""
    with_cr = 0
    cr = wt.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(cr))
    with_cr = cr.right
    dpi = u32.GetDpiForWindow(hwnd)
    return (dpi / 96.0 if dpi else 1.0), with_cr


def synth_click(hwnd, vx, vy):
    """用 SendInput（显式结构）而不是 mouse_event —— 后者不声明 argtypes 时
    dwExtraInfo 是 ULONG_PTR(8 字节) 却按 int(4 字节) 传，很容易不生效。

    vx/vy 是**视口 CSS 坐标**，这里按 DPI 比例换算成物理屏幕坐标。
    """
    pt = wt.POINT(0, 0)
    u32.ClientToScreen(hwnd, ctypes.byref(pt))
    sc = u32.GetDpiForWindow(hwnd) / 96.0
    sx, sy = pt.x + int(round(vx * sc)), pt.y + int(round(vy * sc))
    u32.SetCursorPos(sx, sy)
    time.sleep(0.25)
    arr = (INPUT * 2)(
        INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, None))),
        INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, None))),
    )
    n = u32.SendInput(2, arr, ctypes.sizeof(INPUT))
    return sx, sy, n


def driver():
    import webview
    while not webview.windows:
        time.sleep(0.05)
    w = webview.windows[0]
    for _ in range(200):
        try:
            if w.evaluate_js("!!(window.VKB_DEBUG && VKB_DEBUG.ready())"):
                break
        except Exception:
            pass
        time.sleep(0.1)
    time.sleep(1.0)

    hwnd = own_hwnd()
    log("本进程窗口 hwnd=%s" % hwnd)
    if not hwnd:
        log("FAIL 找不到自己的窗口")
        os._exit(3)
    u32.ShowWindow(hwnd, 5)
    # SetForegroundWindow 会被 Windows 拒绝（后台进程不能抢焦点，实测
    # 前台窗口仍是 False）。用 ALT 键的经典绕法：先敲一下 ALT 让本进程
    # "拿到最近一次输入"，再抢前台就允许了；不行就退而求其次置顶。
    for attempt in range(3):
        u32.keybd_event(0x12, 0, 0, 0)
        u32.keybd_event(0x12, 0, 2, 0)
        u32.SetForegroundWindow(hwnd)
        time.sleep(0.4)
        if u32.GetForegroundWindow() == hwnd:
            break
    u32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)   # TOPMOST
    time.sleep(0.5)
    log("前台窗口是不是自己 = %s" % (u32.GetForegroundWindow() == hwnd))

    def state():
        try:
            return json.loads(w.evaluate_js("JSON.stringify(VKBProcess.state())") or "{}")
        except Exception as e:
            return {"error": str(e)}

    s0 = state()
    log("点击前 state: open=%s page=%s" % (s0.get("open"), s0.get("page")))
    p0 = snapshot(hwnd)
    log("点击前画面: 颜色 %s 种" % (p0[1] if p0 else None))

    # 直接问页面：视口坐标 (1144,423) 上是哪个元素？坐标错了立刻能看出来
    try:
        probe = w.evaluate_js(
            "(function(){var r=document.querySelector('#btnProcess').getBoundingClientRect();"
            "var el=document.elementFromPoint(r.left+r.width/2, r.top+r.height/2);"
            "return JSON.stringify({rect:{x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)},"
            "hit: el? (el.id||el.className) : null});})()")
        log("页面自述 #btnProcess 中心/命中 = %s" % probe)
    except Exception as e:
        log("坐标自检失败 %s" % e)

    wr = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(wr))
    cr = wt.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(cr))
    o = wt.POINT(0, 0)
    u32.ClientToScreen(hwnd, ctypes.byref(o))
    log("窗口矩形=%s 客户区=%s 客户区原点=%s"
        % ((wr.left, wr.top, wr.right - wr.left, wr.bottom - wr.top),
           (cr.right, cr.bottom), (o.x, o.y)))

    inner_w = w.evaluate_js("window.innerWidth") or 0
    sc = u32.GetDpiForWindow(hwnd) / 96.0
    log("DPI 比例=%.4f 客户区物理宽=%d 视口 CSS 宽=%s（应满足 物理宽/CSS宽≈比例）"
        % (sc, cr.right, inner_w))

    sx, sy, sent = synth_click(hwnd, 1144, 423)
    cp = wt.POINT(0, 0)
    u32.GetCursorPos(ctypes.byref(cp))
    log("要求光标到 (%d,%d)，实际停在 (%d,%d)，SendInput 送达 %s/2"
        % (sx, sy, cp.x, cp.y, sent))
    # 反算：光标位置除以 DPI 比例，应该回到按钮中心 (1144,423)
    vx2, vy2 = int(round((cp.x - o.x) / sc)), int(round((cp.y - o.y) / sc))
    try:
        hit = w.evaluate_js(
            "(function(){var e=document.elementFromPoint(%d,%d);"
            "return e? (e.id||e.className) : 'null';})()" % (vx2, vy2))
        log("光标反算成视口坐标 (%d,%d)，那里的元素 = %s" % (vx2, vy2, hit))
    except Exception as e:
        log("命中自检失败 %s" % e)
    time.sleep(1.5)

    s1 = state()
    log("点击后 state: open=%s page=%s" % (s1.get("open"), s1.get("page")))
    p1 = snapshot(hwnd)
    log("点击后画面: 颜色 %s 种" % (p1[1] if p1 else None))

    log("== 结论 ==")
    log("合成点击能驱动界面 = %s" % (s1.get("open") is True))
    log("PrintWindow 能反映画面变化 = %s" % (bool(p0 and p1 and p0[0] != p1[0])))
    time.sleep(0.3)
    os._exit(0)


def main():
    f = open(os.path.join(DIAG, "click_stderr.txt"), "w", encoding="utf-8", buffering=1)
    sys.stdout = f
    sys.stderr = f
    if os.path.exists(OUT):
        os.remove(OUT)
    sys.path.insert(0, os.path.join(ROOT, "src"))
    import app_web
    threading.Thread(target=driver, daemon=True).start()
    app_web.main()


if __name__ == "__main__":
    main()
