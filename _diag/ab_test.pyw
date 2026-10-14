# -*- coding: utf-8 -*-
"""黑框 A/B 对照实验：同一调用，唯一变量 = 有没有 CREATE_NO_WINDOW。

必须用 pythonw.exe 跑（GUI 子系统、无控制台）—— 与打包后的 --windowed exe 同层。

阶段 A：subprocess.run([ffprobe ...])                      —— 裸调用
阶段 B：subprocess.run([ffprobe ...], creationflags=CREATE_NO_WINDOW)

每个阶段各 3 次。观察者线程 5ms 轮询，对每个控制台窗口记录
**可见性跳变**（不可见 -> 可见）与窗口矩形，而不是只采一次样。
这样能区分"窗口存在但始终不可见"与"窗口真的闪了一下"。

证伪标准（实验前写死）：
    若 A 阶段出现「不可见 -> 可见」的跳变、B 阶段一次都没有  -> 机制成立
    若 A、B 都没有可见跳变                                  -> 用户看到的黑框不是这个机制，另找
"""

import ctypes
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
LOG = os.path.join(DIAG, "ab_test.log")
os.makedirs(DIAG, exist_ok=True)

T0 = time.monotonic()
_lock = threading.Lock()
stop = False


def log(kind, msg):
    with _lock:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("t=%7.3f  %-6s %s\n" % (time.monotonic() - T0, kind, msg))


u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
CONSOLE_CLASSES = ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS")


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


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
    """返回 {hwnd: (pid, visible, rect)}"""
    out = {}

    def cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        u32.GetClassNameW(hwnd, buf, 256)
        if buf.value in CONSOLE_CLASSES:
            pid = ctypes.c_ulong()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            r = RECT()
            u32.GetWindowRect(hwnd, ctypes.byref(r))
            out[int(hwnd)] = (pid.value, bool(u32.IsWindowVisible(hwnd)),
                              (r.right - r.left, r.bottom - r.top))
        return True

    u32.EnumWindows(ENUMPROC(cb), None)
    return out


def watcher():
    seen = scan()
    log("WATCH", "基线 %d 个控制台窗口" % len(seen))
    while not stop:
        time.sleep(0.005)
        cur = scan()
        for hwnd, (pid, vis, rect) in cur.items():
            if hwnd not in seen:
                log("WATCH", "新建 hwnd=%d 进程=%s visible=%s rect=%s"
                    % (hwnd, proc_name(pid), vis, rect))
            elif vis != seen[hwnd][1]:
                log("VISIBLE" if vis else "HIDDEN",
                    "hwnd=%d 进程=%s %s -> %s rect=%s"
                    % (hwnd, proc_name(pid), seen[hwnd][1], vis, rect))
        for hwnd in seen:
            if hwnd not in cur:
                log("WATCH", "销毁 hwnd=%d 进程=%s"
                    % (hwnd, proc_name(seen[hwnd][0])))
        seen = cur


CREATE_NO_WINDOW = 0x08000000


def main():
    if os.path.exists(LOG):
        os.remove(LOG)
    log("WATCH", "解释器=%s GUI子系统=%s" % (
        os.path.basename(sys.executable), sys.executable.lower().endswith("pythonw.exe")))

    threading.Thread(target=watcher, daemon=True).start()
    time.sleep(0.3)

    ff = r"D:\MyProject\_tools\ffmpeg\bin\ffprobe.exe"
    sample = os.path.join(ROOT, "data", "media", "sample_01.mp4")
    args = [ff, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", sample]
    log("MARK", "ffprobe 存在=%s  素材存在=%s" % (os.path.isfile(ff), os.path.isfile(sample)))

    log("MARK", "======== 阶段 A：裸调用（无 creationflags）========")
    for i in range(3):
        log("MARK", "A%d 调用前" % (i + 1))
        r = subprocess.run(args, capture_output=True, text=True, timeout=20)
        log("MARK", "A%d 返回 时长=%r" % (i + 1, r.stdout.strip()))
        time.sleep(0.7)

    time.sleep(0.5)
    log("MARK", "======== 阶段 B：CREATE_NO_WINDOW ========")
    for i in range(3):
        log("MARK", "B%d 调用前" % (i + 1))
        r = subprocess.run(args, capture_output=True, text=True, timeout=20,
                           creationflags=CREATE_NO_WINDOW)
        log("MARK", "B%d 返回 时长=%r" % (i + 1, r.stdout.strip()))
        time.sleep(0.7)

    log("MARK", "======== 结束 ========")
    time.sleep(0.5)
    stop = True
    os._exit(0)


if __name__ == "__main__":
    main()
