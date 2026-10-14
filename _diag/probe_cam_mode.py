# -*- coding: utf-8 -*-
"""探针：相机应用能不能**直接以视频模式**打开（免得用户自己切一下）。

做法：换几种调起方式各来一次，每次把相机窗口截下来存 PNG，肉眼看差异。
只截**相机应用窗口**，不截整个屏幕。

用法：venv\\Scripts\\python.exe _diag\\probe_cam_mode.py
出图：_diag\\cam_shot_<方式>.png
"""

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
sys.path.insert(0, os.path.join(ROOT, "src"))
import proc  # noqa: E402

u32 = ctypes.windll.user32
g32 = ctypes.windll.gdi32
ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
PW_RENDERFULLCONTENT = 0x00000002


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


def find_camera_window():
    """找标题是「相机」/「Camera」的 ApplicationFrameWindow。"""
    hits = []

    def cb(hwnd, _):
        b = ctypes.create_unicode_buffer(256)
        u32.GetClassNameW(hwnd, b, 256)
        if b.value == "ApplicationFrameWindow":
            t = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(hwnd, t, 256)
            if t.value.strip() in ("相机", "Camera"):
                hits.append((int(hwnd), t.value))
        return True

    u32.EnumWindows(ENUMPROC(cb), None)
    return hits


def grab(hwnd, path):
    r = RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None
    hdc = u32.GetWindowDC(hwnd)
    mem = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    g32.SelectObject(mem, bmp)
    ok = u32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)
    if not ok:
        ok = u32.PrintWindow(hwnd, mem, 0)
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth, bi.biHeight = w, -h
    bi.biPlanes, bi.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mem)
    u32.ReleaseDC(hwnd, hdc)
    # 手写 BMP（32bpp，不压缩），不引第三方库
    hdr = ctypes.create_string_buffer(14 + 40)
    hdr[0:2] = b"BM"
    size = 14 + 40 + len(buf)
    hdr[2:6] = size.to_bytes(4, "little")
    hdr[10:14] = (14 + 40).to_bytes(4, "little")
    hdr[14:18] = (40).to_bytes(4, "little")
    hdr[18:22] = w.to_bytes(4, "little")
    hdr[22:26] = (-h).to_bytes(4, "little", signed=True)
    hdr[26:28] = (1).to_bytes(2, "little")
    hdr[28:30] = (32).to_bytes(2, "little")
    with open(path, "wb") as f:
        f.write(hdr)
        f.write(buf)
    return path


def kill_camera():
    proc.run(["taskkill", "/F", "/IM", "WindowsCamera.exe"],
             capture_output=True, timeout=30)
    time.sleep(2.5)


def shot(tag, launch):
    kill_camera()
    launch()
    hwnd = None
    t0 = time.monotonic()
    while time.monotonic() - t0 < 20:
        hits = find_camera_window()
        if hits:
            hwnd = hits[0][0]
            break
        time.sleep(0.4)
    if not hwnd:
        print("  [%s] 没等到相机窗口" % tag)
        return None
    time.sleep(4.5)                    # 等它把预览渲染出来
    out = os.path.join(DIAG, "cam_shot_%s.bmp" % tag)
    grab(hwnd, out)
    print("  [%s] 已截图 -> %s" % (tag, os.path.basename(out)))
    kill_camera()
    return out


def main():
    print("相机窗口模式探针")
    shot("default", lambda: os.startfile("microsoft.windows.camera:"))
    shot("mode_video", lambda: os.startfile("microsoft.windows.camera:?mode=video"))
    shot("mode_pro", lambda: os.startfile("microsoft.windows.camera:?mode=pro"))
    print("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
