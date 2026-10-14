# -*- coding: utf-8 -*-
"""黑框端到端验证 —— 带**阳性对照**，防止"看不见"其实是探针坏了。

为什么必须用 pythonw.exe 跑：
    用 python.exe 时父进程自带控制台，子进程会**继承**它，Windows 不会新建
    控制台窗口 —— 现象根本不复现。打包后的 exe 是 --windowed（GUI 子系统，
    无控制台），与 pythonw 同类。验证同层，所以必须跑在 GUI 子系统解释器上。

四个阶段：
    0  阳性对照：故意裸调一次 ffprobe（不加 CREATE_NO_WINDOW）
                  -> 必须恰好出现 1 个可见黑框，否则说明探针没有分辨力，
                     后面所有的 0 都不可信
    1  启动期   ：mklink(cmd.exe) + ffmpeg    -> 期望 0
    2  打开处理浮层                            -> 期望 0
    3  逐条「勾选 + 进裁剪」（每条触发一次 ffprobe）-> 期望 0

可见性判定必须**跟踪跳变**：控制台窗口总是先以不可见创建、随后才转可见，
只在创建那一瞬间采一次样永远看不到它"可见过"。
"""

import ctypes
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
LOG = os.path.join(DIAG, "blackbox.log")
os.environ.setdefault("VKB_FAKE", "1")     # 浮层探针要有一条固定的列表可点
os.makedirs(DIAG, exist_ok=True)

T0 = time.monotonic()
_lock = threading.Lock()
_stop = False


def log(kind, msg):
    with _lock:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("t=%7.3f  %-9s %s\n" % (time.monotonic() - T0, kind, msg))


u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
CONSOLE_CLASSES = ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS")


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
        buf = ctypes.create_unicode_buffer(256)
        u32.GetClassNameW(hwnd, buf, 256)
        if buf.value in CONSOLE_CLASSES:
            pid = ctypes.c_ulong()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            t = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(hwnd, t, 256)
            out[int(hwnd)] = (pid.value, bool(u32.IsWindowVisible(hwnd)), t.value)
        return True

    u32.EnumWindows(ENUMPROC(cb), None)
    return out


def watcher():
    seen = scan()
    log("WATCH", "基线 %d 个控制台窗口" % len(seen))
    while not _stop:
        time.sleep(0.005)
        cur = scan()
        for hwnd, v in cur.items():
            pid, vis, title = v
            if hwnd not in seen:
                log("WATCH", "新建 hwnd=%d 进程=%s visible=%s" % (hwnd, proc_name(pid), vis))
            elif vis != seen[hwnd][1]:
                if vis:
                    log("BLACKBOX", "★ 黑框出现 hwnd=%d 进程=%s 标题=%r"
                        % (hwnd, proc_name(pid), title[:50]))
                else:
                    log("WATCH", "黑框隐去 hwnd=%d 进程=%s" % (hwnd, proc_name(pid)))
        for hwnd in seen:
            if hwnd not in cur:
                log("WATCH", "销毁 hwnd=%d 进程=%s" % (hwnd, proc_name(seen[hwnd][0])))
        seen = cur


FFPROBE = None
SAMPLE = None


def control():
    """阳性对照：与修复前的调用完全一致（不加 creationflags）。"""
    time.sleep(0.4)
    log("MARK", "==== 阶段 0：阳性对照（裸调 ffprobe，应当出现 1 个黑框）====")
    subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nw=1:nk=1", SAMPLE],
                   capture_output=True, text=True, timeout=20)
    time.sleep(1.0)


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
    log("MARK", "==== 阶段 1 结束（启动期已过）界面就绪 ====")
    time.sleep(1.0)

    log("MARK", "==== 阶段 2：点「处理视频…」==== ")
    try:
        w.evaluate_js("VKB_DEBUG.openProcess()")
    except Exception as e:
        log("MARK", "驱动失败 %s" % e)
    time.sleep(2.5)

    log("MARK", "==== 阶段 3：逐条「勾选 -> 进裁剪」（每条触发一次 ffprobe）====")
    try:
        n = int(w.evaluate_js("document.querySelectorAll('#procList .proc-item').length") or 0)
    except Exception:
        n = 0
    log("MARK", "列表 %d 条" % n)
    for i in range(n):
        log("MARK", "---- 第 %d 条：勾选 + 进裁剪 ----" % (i + 1))
        try:
            # 新结构：点行只预览（不触发任何子进程）；要点勾选框 + 「裁剪」才走 ffprobe
            w.evaluate_js(
                "(function(){var r=document.querySelectorAll('#procList .proc-item')[%d];"
                "if(!r)return;var cb=r.querySelector('.ci');"
                "if(!cb.checked)cb.click();})()" % i)
        except Exception as e:
            log("MARK", "勾选失败 %s" % e)
        time.sleep(0.5)
        try:
            w.evaluate_js("(function(){var b=document.querySelector('#btnCropMode');"
                          "if(b && !b.disabled)b.click();})()")
        except Exception as e:
            log("MARK", "进裁剪失败 %s" % e)
        time.sleep(1.6)
        try:
            w.evaluate_js("(function(){var b=document.querySelector('#trimBack');"
                          "if(b)b.click();"
                          "var r=document.querySelectorAll('#procList .proc-item')[%d];"
                          "if(r){var cb=r.querySelector('.ci');if(cb.checked)cb.click();}})()" % i)
        except Exception:
            pass
        time.sleep(0.7)

    log("MARK", "==== 结束 ====")
    time.sleep(0.6)
    global _stop
    _stop = True
    os._exit(0)


def main():
    global FFPROBE, SAMPLE
    f = open(os.path.join(DIAG, "app_stderr.txt"), "w", encoding="utf-8", buffering=1)
    sys.stdout = f
    sys.stderr = f
    if os.path.exists(LOG):
        os.remove(LOG)

    sys.path.insert(0, os.path.join(ROOT, "src"))
    import media
    FFPROBE = os.path.join(os.path.dirname(media.find_ffmpeg() or "?"), "ffprobe.exe")
    SAMPLE = os.path.join(media.MEDIA_DIR, "sample_01.mp4")

    log("WATCH", "解释器=%s GUI子系统=%s"
        % (os.path.basename(sys.executable), sys.executable.lower().endswith("pythonw.exe")))
    log("WATCH", "ffprobe=%s 存在=%s  素材存在=%s"
        % (FFPROBE, os.path.isfile(FFPROBE), os.path.isfile(SAMPLE)))

    threading.Thread(target=watcher, daemon=True).start()
    # 对照**同步**跑完再启动应用：两件事在时间上完全分开，
    # 日志里哪个黑框属于对照、哪个属于应用，不会有歧义。
    control()
    threading.Thread(target=driver, daemon=True).start()

    import app_web
    app_web.main()


if __name__ == "__main__":
    main()
