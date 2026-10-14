# -*- coding: utf-8 -*-
"""规格 20 验收：双击 .vbs 启动，全程不许出现任何控制台窗口。

沿用黑框探针那套：5ms 轮询所有控制台类顶层窗口，跟踪可见性跳变。
带**阳性对照**（借 pythonw 裸调一次 cmd）—— 对照为 0 就说明探针没分辨力，
那么"应用 0 个"也不可信。
"""

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
VBS = os.path.join(ROOT, "启动视频知识库.vbs")
OUT = os.path.join(DIAG, "vbs_check.txt")
os.environ.setdefault("VKB_FAKE", "1")   # 只看窗口，不需要真实链路

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
CONSOLE_CLASSES = ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS")

hits = []
_stop = False
TITLE = "视频知识库 · 工作台"


def log(m):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(m + "\n")


def pname(pid):
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return "?"
    try:
        b = ctypes.create_unicode_buffer(1024)
        n = ctypes.c_ulong(1024)
        return os.path.basename(b.value) if k32.QueryFullProcessImageNameW(
            h, 0, b, ctypes.byref(n)) else "?"
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
            new = hwnd not in seen
            became = (hwnd in seen and vis and not seen[hwnd][1])
            if vis and (new or became):
                hits.append((tag, pname(pid)))
                log("   ★ 控制台窗口出现 [%s] 进程=%s" % (tag, pname(pid)))
        seen = cur


def main():
    if os.path.exists(OUT):
        os.remove(OUT)
    log("vbs = %s  存在=%s" % (VBS, os.path.isfile(VBS)))

    threading.Thread(target=watcher, args=("对照",), daemon=True).start()
    time.sleep(0.4)

    pyw = os.path.join(ROOT, "venv", "Scripts", "pythonw.exe")
    log("-- 阳性对照：借 pythonw 起一个 cmd（应当 1 个控制台窗口）--")
    subprocess.run([pyw, "-c",
                    "import subprocess;subprocess.run(['cmd','/c','echo','x'],timeout=10)"],
                   timeout=60)
    time.sleep(1.2)
    n_control = len(hits)
    log("对照窗口数 = %d" % n_control)

    log("-- 正式：双击 .vbs --")
    t0 = len(hits)
    # wscript 跑 .vbs 就是"双击"的等效方式
    ws = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "wscript.exe")
    subprocess.run([ws, VBS], timeout=60)

    found = False
    deadline = time.time() + 40
    while time.time() < deadline:
        if u32.FindWindowW(None, TITLE):
            found = True
            break
        time.sleep(0.3)
    time.sleep(6.0)                      # 给启动期留出足够窗口
    n_app = len(hits) - t0
    log("应用窗口出现 = %s" % found)
    log("vbs 启动期控制台窗口数 = %d" % n_app)

    _stop = True
    ok = (n_control >= 1) and (n_app == 0) and found
    log("")
    log("阳性对照 %d 个（必须 >=1）" % n_control)
    log("vbs 启动控制台窗口 %d 个（必须 0）" % n_app)
    log("判定: %s" % ("通过" if ok else "不通过"))
    print(open(OUT, encoding="utf-8").read())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
