# -*- coding: utf-8 -*-
"""验证打包后的 exe 真的起得来、窗口真的显示出来、画面真的渲染了内容。

不看"进程还在"就算过 —— 那只能证明没崩，证明不了界面出来了。
这里做三件事：
  1. 找到窗口，读 IsWindowVisible / IsIconic / 位置 / 尺寸
  2. PrintWindow 抓一张图，数不同颜色数与非白像素占比
     （空白窗口只有一种颜色；渲染出界面必然几百种颜色）
  3. 报告溢出屏幕的量（四格必须完整可见）
"""

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import proc  # noqa: E402

EXE = os.path.join(ROOT, "build", "dist_onefile", "VideoKnowledgeBase.exe")
TITLE = "视频知识库 · 工作台"

u32 = ctypes.windll.user32
g32 = ctypes.windll.gdi32

PW_RENDERFULLCONTENT = 0x00000002
SPI_GETWORKAREA = 0x0030


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def find_window(title, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = u32.FindWindowW(None, title)
        if h:
            return h
        time.sleep(0.25)
    return 0


def grab(hwnd):
    r = wt.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None, 0, 0
    hdc = u32.GetDC(hwnd)
    mem = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    g32.SelectObject(mem, bmp)
    u32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)

    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h          # 负数 = 自上而下
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)

    g32.DeleteObject(bmp)
    g32.DeleteDC(mem)
    u32.ReleaseDC(hwnd, hdc)
    return buf.raw, w, h


def analyze(raw, w, h):
    colors = set()
    nonwhite = 0
    step = 4
    n = 0
    for y in range(0, h, 3):
        for x in range(0, w, step):
            i = (y * w + x) * 4
            b, g, r = raw[i], raw[i + 1], raw[i + 2]
            colors.add((r >> 3, g >> 3, b >> 3))
            if not (r > 250 and g > 250 and b > 250):
                nonwhite += 1
            n += 1
    return len(colors), (nonwhite / max(1, n))


def main():
    if not os.path.isfile(EXE):
        print("找不到 exe: %s" % EXE)
        return 2
    print("exe: %s  %.1f MB" % (EXE, os.path.getsize(EXE) / 1024 / 1024))

    p = proc.popen([EXE], cwd=os.path.dirname(EXE))
    try:
        hwnd = find_window(TITLE)
        if not hwnd:
            print("FAIL 等不到窗口")
            return 3
        time.sleep(3.0)                      # 等 WebView2 把界面画出来

        style = u32.GetWindowLongW(hwnd, -16) & 0xFFFFFFFF
        r = wt.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        area = wt.RECT()
        u32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(area), 0)

        print("窗口句柄   : %d" % hwnd)
        print("可见        : %s" % bool(u32.IsWindowVisible(hwnd)))
        print("最小化      : %s" % bool(u32.IsIconic(hwnd)))
        print("位置尺寸    : (%d,%d) %dx%d" % (r.left, r.top, r.right - r.left, r.bottom - r.top))
        print("工作区      : (%d,%d)-(%d,%d)" % (area.left, area.top, area.right, area.bottom))
        print("溢出右/下   : %d / %d" % (r.right - area.right, r.bottom - area.bottom))
        print("可拉伸      : %s" % bool(style & 0x00040000))
        print("最大化按钮  : %s" % bool(style & 0x00010000))

        raw, w, h = grab(hwnd)
        if raw:
            nc, ratio = analyze(raw, w, h)
            print("抓图        : %dx%d  不同颜色 %d 种  非白像素 %.1f%%" % (w, h, nc, ratio * 100))
            print("判定        : %s" % ("渲染了真实界面" if nc > 60 and ratio > 0.03 else "疑似空白窗口"))
        else:
            print("抓图失败（尺寸为 0）")
        return 0
    finally:
        try:
            p.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
