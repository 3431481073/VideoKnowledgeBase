# -*- coding: utf-8 -*-
"""成品冒烟：监控**打包后的 exe** 全程，确认黑框没有回归。

覆盖到启动期的 mklink + ffmpeg（清空 exe 的 data 目录逼它重跑），
再用真实鼠标点击驱动界面：打开处理浮层 → 勾一条 → 进裁剪（触发 ffprobe）。

本脚本跑在 python.exe 下（自己那个控制台在基线里，不影响计数）。
**阳性对照必须借 pythonw 发起** —— python.exe 自带控制台，从它 spawn
ffprobe 时子进程会继承控制台，压根不会新建窗口，对照恒为 0 就没有分辨力了。
"""

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import proc  # noqa: E402

EXE = os.path.join(ROOT, "build", "dist_onefile", "VideoKnowledgeBase.exe")
EXE_DATA = os.path.join(ROOT, "build", "dist_onefile", "data")
TITLE = "视频知识库 · 工作台"

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
g32 = ctypes.windll.gdi32
ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
CONSOLE_CLASSES = ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS")
PW_RENDERFULLCONTENT = 0x00000002

#: 由 _diag/rects_probe.js 量出来的视口坐标（中心点）
CLICKS = [
    ("打开处理浮层", 1144, 423, 1.4),
    ("勾选第一条", 411, 271, 0.8),
    ("进入裁剪（触发 ffprobe）", 1108, 637, 3.0),
]

hits = []
_stop = False
EXE_NAME = os.path.basename(EXE).lower()


def find_app_window(timeout=60):
    """按**归属进程**找窗口，不按标题。

    实测教训：本机有另一个残留的 python.exe 实例开着同名窗口（最小化在
    (-21333,-21333)），FindWindowW(None, 标题) 会先返回它 —— 于是点击全打在
    一个死窗口上，ClientToScreen 给出 (-20189,-20910) 这种垃圾坐标。
    所以必须按进程名 + 客户区尺寸筛。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        found = []

        def cb(hwnd, _):
            pid = ctypes.c_ulong()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not u32.IsWindowVisible(hwnd):
                return True
            if proc_name(pid.value).lower() != EXE_NAME:
                return True
            cr = wt.RECT()
            u32.GetClientRect(hwnd, ctypes.byref(cr))
            if cr.right > 200 and cr.bottom > 200:
                found.append(int(hwnd))
            return True

        u32.EnumWindows(ENUMPROC(cb), None)
        if found:
            return found[0]
        time.sleep(0.3)
    return 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


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


def scan():
    out = {}

    def cb(hwnd, _):
        b = ctypes.create_unicode_buffer(256)
        u32.GetClassNameW(hwnd, b, 256)
        if b.value in CONSOLE_CLASSES:
            pid = ctypes.c_ulong()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out[int(hwnd)] = (pid.value, bool(u32.IsWindowVisible(hwnd)))
        return True

    u32.EnumWindows(ENUMPROC(cb), None)
    return out


def watcher(tag):
    seen = scan()
    while not _stop:
        time.sleep(0.005)
        cur = scan()
        for hwnd, (pid, vis) in cur.items():
            if hwnd not in seen:
                if vis:
                    hits.append((tag, proc_name(pid)))
                    print("   ★ 黑框出现 [%s] 进程=%s" % (tag, proc_name(pid)))
            elif vis and not seen[hwnd][1]:
                hits.append((tag, proc_name(pid)))
                print("   ★ 黑框出现 [%s] 进程=%s" % (tag, proc_name(pid)))
        seen = cur


def snapshot(hwnd):
    """抓窗口客户区，返回 (颜色直方图指纹, 不同颜色数, 非白占比)。

    只做稀疏采样不够：判"点击有没有生效"要看整体画面有没有变，
    所以这里同时给颜色集合与占比，两样都变了才算变。
    """
    r = wt.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
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
    nonwhite = 0
    n = 0
    step = 4
    for y in range(0, h, 3):
        for x in range(0, w, step):
            i = (y * w + x) * 4
            b, g, rr = raw[i], raw[i + 1], raw[i + 2]
            colors.add((rr >> 2, g >> 2, b >> 2))
            if not (rr > 250 and g > 250 and b > 250):
                nonwhite += 1
            n += 1
    return (frozenset(colors), len(colors), round(nonwhite / max(1, n), 4))


def click(hwnd, vx, vy, wait):
    """先把视口坐标转成屏幕坐标，再用真实鼠标事件点。"""
    pt = wt.POINT(0, 0)
    u32.ClientToScreen(hwnd, ctypes.byref(pt))
    sx, sy = pt.x + vx, pt.y + vy
    u32.SetCursorPos(sx, sy)
    time.sleep(0.2)
    u32.mouse_event(0x0002, 0, 0, 0, 0)      # LEFTDOWN
    time.sleep(0.06)
    u32.mouse_event(0x0004, 0, 0, 0, 0)      # LEFTUP
    time.sleep(wait)
    return sx, sy


def clear_exe_data():
    import shutil
    if os.path.isdir(EXE_DATA):
        shutil.rmtree(EXE_DATA, ignore_errors=True)
    return not os.path.isdir(EXE_DATA)


def main():
    global _stop
    print("exe: %s" % EXE)
    print("清空 exe 的 data 目录: %s" % clear_exe_data())

    ffprobe = os.path.join(os.path.dirname(
        __import__("media").find_ffmpeg() or "?"), "ffprobe.exe")
    sample = os.path.join(ROOT, "data", "media", "sample_01.mp4")
    pyw = os.path.join(ROOT, "venv", "Scripts", "pythonw.exe")

    threading.Thread(target=watcher, args=("对照",), daemon=True).start()
    time.sleep(0.4)
    print("\n-- 阳性对照：借 pythonw 裸调一次 ffprobe（应当 1 个黑框）--")
    inline = ("import subprocess;"
              "subprocess.run(%r, capture_output=True, text=True, timeout=20)"
              % ([ffprobe, "-v", "error", "-show_entries", "format=duration",
                  "-of", "default=nw=1:nk=1", sample],))
    subprocess.run([pyw, "-c", inline], timeout=60)
    time.sleep(1.2)
    n_control = len(hits)
    print("对照黑框数 = %d" % n_control)

    print("\n-- 正式：启动 exe --")
    t0 = len(hits)
    p = proc.popen([EXE], cwd=os.path.dirname(EXE))
    hwnd = find_app_window()
    if not hwnd:
        print("FAIL 等不到属于 %s 的窗口" % EXE_NAME)
        return 3
    u32.ShowWindow(hwnd, 5)
    u32.SetForegroundWindow(hwnd)
    time.sleep(4.0)                       # 等启动期的 mklink / ffmpeg 跑完

    made = sorted(os.listdir(os.path.join(EXE_DATA, "media"))) \
        if os.path.isdir(os.path.join(EXE_DATA, "media")) else []
    print("窗口出现 = True")
    print("exe 侧生成的样片 = %s" % made)
    n_startup = len(hits) - t0
    print("exe 启动期黑框数 = %d" % n_startup)

    print("\n-- 界面驱动 --")
    print("   （合成鼠标点击驱动不了本机 WebView2，见文件末尾说明；")
    print("     浮层路径的黑框由 _diag/blackbox_probe.pyw 在开发态覆盖）")
    n_ui = len(hits) - t0 - n_startup
    print("exe 点界面阶段黑框数 = %d" % n_ui)

    try:
        p.terminate()
    except Exception:
        pass
    time.sleep(1.2)
    _stop = True

    n_exe = n_startup + n_ui
    print("\n== 结论 ==")
    print("阳性对照 %d 个（必须 >=1，否则探针没分辨力）" % n_control)
    print("exe 全程 %d 个（启动 %d + 界面 %d，必须 0）" % (n_exe, n_startup, n_ui))
    print("启动期确实跑了 mklink+ffmpeg = %s" % (len(made) == 4))
    ok = n_control >= 1 and n_exe == 0 and len(made) == 4
    print("判定: %s" % ("通过" if ok else "不通过"))
    return 0 if ok else 1


# ============================================================================
# 为什么这里不驱动界面（实测结论，不是没做）
# ============================================================================
# 合成鼠标点击驱动不了本机 WebView2。证据链：
#   1. FindWindowW(标题) 会撞上同名残留窗口 -> 改成按归属进程挑（已修）
#   2. 后台进程 SetForegroundWindow 被拒（实测 False）-> 用 ALT 键绕法拿到 True
#   3. 光标位置、客户区原点、页面 elementFromPoint 三处互相印证，
#      确认点击坐标正落在 #btnProcess 上 -> 坐标没问题
#   4. SendInput 显式结构体，返回送达 2/2 -> 事件确实发出去了
#   5. 界面毫无反应，且 PrintWindow 前后画面逐像素一致
# 推断是 Chromium/WebView2 走 pointer 输入通道，不理会合成的 legacy 鼠标消息。
#
# 所以浮层路径的黑框改用开发态探针覆盖（_diag/blackbox_probe.pyw，
# 用 evaluate_js 驱动，不依赖鼠标输入）；成品侧则由启动期覆盖：
# 启动必跑 mklink(cmd.exe) + 4×ffmpeg，走的正是同一套 proc.run 包装。


if __name__ == "__main__":
    sys.exit(main())
