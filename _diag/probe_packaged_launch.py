# -*- coding: utf-8 -*-
r"""打包版（onedir）启动验收。

    venv\Scripts\python.exe _diag\probe_packaged_launch.py

验六件事：
  P1  启动期 0 黑框 —— **带阳性对照**
  P2  exe 能启动、主窗口出来
  P3  窗口不最小化
  P4  _internal\webui\media 联接在 onedir 下建起来了
  P5  单实例闸生效（连点两次只有一个进程）
  P6  用户库完好（workspace.json + 真实媒体文件都在）

=== 为什么用 SetWinEventHook 而不是轮询 ===
  黑框一闪而过，轮询抓不住。EVENT_OBJECT_CREATE 是事件驱动的，
  窗口一被创建就回调，不存在漏检。

=== 两个实测踩出来的坑（都在这份代码里修掉了）===
  1) **回调实例必须存住。**
     写成 user32.SetWinEventHook(..., WinEventProc(on_event), ...) —— 内联创建的
     临时对象在调用返回后立刻被 GC，而 Windows 还攥着那个跳板指针。
     实测结果：事件一来就 call 到已释放内存 -> access violation
     (0xC000041D STATUS_FATAL_USER_CALLBACK_EXCEPTION)，进程直接死。
     所以下面用 _hook_cb 全局存住。
  2) **必须把所有 argtypes/restype 显式声明。**
     否则 64 位 HWND 会被 ctypes 当 c_int 截断成野句柄。

=== 黑框的窗口类不止一个（实测）===
  这台机器默认终端是 Windows Terminal，实测带控制台的 cmd 产生的窗口类是：
      CASCADIA_HOSTING_WINDOW_CLASS   <- Windows Terminal 宿主窗口
      PseudoConsoleWindow             <- ConPTY 宿主
  而**不是** ConsoleWindowClass。
  只认 ConsoleWindowClass 的话，真闪了黑框也会报 PASS —— 假阴性。
  所以下面认一整族。

结果写 _diag\probe_packaged_launch_results.txt
"""

import ctypes
import os
import stat
import subprocess
import sys
import threading
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
OUT = os.path.join(DIAG, "probe_packaged_launch_results.txt")
DIST = os.path.join(ROOT, "build", "dist_onedir", "VideoKnowledgeBase")
EXE = os.path.join(DIST, "VideoKnowledgeBase.exe")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

EVENT_OBJECT_CREATE = 0x8000
WINEVENT_OUTOFCONTEXT = 0x0000
WM_QUIT = 0x0012
CREATE_NEW_CONSOLE = 0x00000010
GA_ROOT = 2

#: 一整族「这就是个控制台窗口」的窗口类。少认一个就可能假阴性。
CONSOLE_CLASSES = (
    "ConsoleWindowClass",              # 传统 conhost
    "CASCADIA_HOSTING_WINDOW_CLASS",   # Windows Terminal 宿主
    "PseudoConsoleWindow",             # ConPTY
    "Windows Terminal",                # 前缀匹配，实测类名形如 "Windows Terminal <hash>"
)

WinEventProc = ctypes.WINFUNCTYPE(
    None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
    wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

# ---- 全部显式声明（见文件头坑 2）----
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.SetWinEventHook.argtypes = [
    wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WinEventProc,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

T0 = time.monotonic()
R = []
_events = []
_lock = threading.Lock()
_hook = None
_hook_cb = None          # ★ 存住回调实例，否则被 GC（见文件头坑 1）
_hook_tid = 0

# 类名/标题的 buffer 必须**线程私有**：回调跑在钩子线程上，而 ctypes 调
# foreign function 时会放开 GIL —— 两个线程共用同一个 buffer 会互相搅烂读到的
# 类名，那可能把"黑框"读成别的类，造成假阴性。所以走 threading.local。
_tls = threading.local()


def log(m):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("t=%7.2f  %s\n" % (time.monotonic() - T0, m))


def chk(name, cond, extra=""):
    R.append({"name": name, "pass": bool(cond), "extra": str(extra)})
    log("%s  %-54s %s" % ("PASS" if cond else "FAIL", name, extra))


def is_console_class(cls):
    return any(cls == c or cls.startswith(c) for c in CONSOLE_CLASSES)


# ---------------------------------------------------------------- 窗口工具

def class_of(hwnd):
    if not hwnd:
        return ""
    buf = getattr(_tls, "cls", None)
    if buf is None:
        buf = _tls.cls = ctypes.create_unicode_buffer(512)
    return buf.value if user32.GetClassNameW(hwnd, buf, 512) else ""


def title_of(hwnd):
    if not hwnd:
        return ""
    buf = getattr(_tls, "txt", None)
    if buf is None:
        buf = _tls.txt = ctypes.create_unicode_buffer(512)
    return buf.value if user32.GetWindowTextW(hwnd, buf, 512) else ""


def pid_of(hwnd):
    p = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def is_toplevel(hwnd):
    return bool(hwnd) and int(user32.GetAncestor(hwnd, GA_ROOT) or 0) == int(hwnd)


# ---------------------------------------------------------------- 事件钩子

def _on_event(_h, _ev, hwnd, idobj, _idchild, _tid, _tm):
    try:
        cls = class_of(hwnd)
        if not cls:
            return
        rec = {"cls": cls, "title": title_of(hwnd), "pid": pid_of(hwnd),
               "top": is_toplevel(hwnd), "t": time.monotonic() - T0}

    except Exception as e:                                # noqa: BLE001
        rec = {"cls": "<回调异常: %s>" % e, "title": "", "pid": 0,
               "top": False, "t": time.monotonic() - T0}
    with _lock:
        _events.append(rec)


def hook_start():
    global _hook, _hook_cb, _hook_tid
    _hook_tid = kernel32.GetCurrentThreadId()
    _hook_cb = WinEventProc(_on_event)          # ★ 存住
    _hook = user32.SetWinEventHook(
        EVENT_OBJECT_CREATE, EVENT_OBJECT_CREATE, None,
        _hook_cb, 0, 0, WINEVENT_OUTOFCONTEXT)
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def hook_stop():
    if _hook_tid:
        user32.PostThreadMessageW(_hook_tid, WM_QUIT, 0, 0)


def events():
    with _lock:
        return list(_events)


def clear_events():
    with _lock:
        _events.clear()


# ---------------------------------------------------------------- 进程工具

def running_pids():
    p = subprocess.run(["tasklist", "/FI", "IMAGENAME eq VideoKnowledgeBase.exe",
                        "/FO", "CSV", "/NH"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=20)
    pids = []
    for line in (p.stdout or "").splitlines():
        parts = [x.strip('"') for x in line.split('","')]
        if len(parts) >= 2 and parts[0].lower().startswith("videoknowledgebase"):
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


def is_junction(p):
    try:
        return bool(os.lstat(p).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except Exception:                                     # noqa: BLE001
        return False


#: 主窗口标题特征。**不能**只按"有标题的顶层窗口"找 —— 实测会先撞上
#: GDI+ Hook Window / OleMainThreadWndName 这类辅助窗口，那是探针选错了窗口，
#: 不是产品的问题。必须认标题。
MAIN_TITLE_KEY = "视频知识库"


def is_main_window(pid, rec):
    return (rec["pid"] == pid and rec["top"]
            and MAIN_TITLE_KEY in rec["title"])


def wait_main_window(pid, sec):
    t = time.monotonic()
    while time.monotonic() - t < sec:
        for rec in events():
            if is_main_window(pid, rec):
                return rec
        time.sleep(0.15)
    return None


def norm_path(p):
    r"""剥掉 Windows 扩展长度前缀再比对。

    os.readlink 对目录联接返回的是 \\?\D:\... 形式，直接比会假失败。
    """
    p = os.path.abspath(p)
    for pre in ("\\\\?\\", "\\??\\"):
        if p.startswith(pre):
            p = p[len(pre):]
            break
    return os.path.normcase(p)


def main():
    os.makedirs(DIAG, exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)

    log("exe = %s" % EXE)
    chk("P0a exe 存在", os.path.isfile(EXE), EXE)

    threading.Thread(target=hook_start, daemon=True).start()
    time.sleep(1.0)
    chk("P0b 事件钩子装上了（回调实例已存住）", bool(_hook), _hook)

    # ---------------- P1 阳性对照 ----------------
    log("")
    log("========== P1 阳性对照（必须抓到黑框）==========")
    clear_events()
    ctrl = subprocess.Popen(["cmd.exe", "/c", "ping -n 3 127.0.0.1 >nul"],
                            creationflags=CREATE_NEW_CONSOLE)
    ctrl.wait(timeout=30)
    time.sleep(1.2)

    ev = events()
    cons = [e for e in ev if is_console_class(e["cls"])]
    log("  阳性对照期共 %d 条事件，其中控制台类 %d 条：" % (len(ev), len(cons)))
    for e in ev:
        tag = "★黑框" if is_console_class(e["cls"]) else "     "
        log("    %s pid=%-7d cls=%-34s title=%s" % (tag, e["pid"], e["cls"], e["title"]))
    chk("P1a ★ 阳性对照：探针抓得到黑框", len(cons) >= 1,
        "抓到 %d 个：%s" % (len(cons), sorted({e["cls"] for e in cons})))

    # ---------------- P2/P3 起打包版 ----------------
    log("")
    log("========== 起打包版 ==========")
    clear_events()
    t0 = time.monotonic()
    launch_off = t0 - T0          # ★ 事件时间戳是「相对 T0」，要换算成「相对拉起」
    proc = subprocess.Popen([EXE], cwd=DIST)
    log("  已起 exe，PID=%d" % proc.pid)

    first = wait_main_window(proc.pid, 45)
    startup = (first["t"] - launch_off) if first else None
    if first:
        log("  ★ 启动耗时 %.2fs（从拉起进程到主窗口出现）cls=%s title=%s"
            % (startup, first["cls"], first["title"]))
    else:
        log("  ★ 45 秒内没记录到主窗口")

    chk("P2a ★ exe 起来了（有主窗口事件）", first is not None,
        first["title"] if first else "45s 内没有窗口事件")
    chk("P2b ★ 启动到主窗口 < 20s", startup is not None and startup < 20,
        "%.2fs" % startup if startup is not None else None)

    time.sleep(2.0)
    hwnd_main = 0

    def _cb(h, _l):
        nonlocal hwnd_main
        if pid_of(h) == proc.pid and MAIN_TITLE_KEY in title_of(h):
            hwnd_main = h
            return False
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)

    if hwnd_main:
        iconic = user32.IsIconic(hwnd_main)
        vis = user32.IsWindowVisible(hwnd_main)
        log("  主窗口 hwnd=%d cls=%s title=%s iconic=%s visible=%s"
            % (hwnd_main, class_of(hwnd_main), title_of(hwnd_main), iconic, vis))
        chk("P3a ★ 窗口不是最小化状态", not iconic, "IsIconic=%s" % iconic)
        chk("P3b ★ 窗口可见", bool(vis), "IsWindowVisible=%s" % vis)
    else:
        chk("P3a ★ 窗口不是最小化状态", False, "没找到主窗口句柄")
        chk("P3b ★ 窗口可见", False, "没找到主窗口句柄")

    # ---------------- P4 媒体联接 ----------------
    log("")
    link = os.path.join(DIST, "_internal", "webui", "media")
    data_media = os.path.join(DIST, "data", "media")
    for _ in range(40):
        if os.path.exists(link):
            break
        time.sleep(0.5)
    try:
        tgt = os.readlink(link) if os.path.exists(link) else ""
    except Exception as e:                                # noqa: BLE001
        tgt = "<读不出: %s>" % e
    log("  _internal\\webui\\media 存在=%s junction=%s"
        % (os.path.exists(link), is_junction(link)))
    log("  联接指向 = %s" % tgt)
    log("  期望指向 = %s" % data_media)
    chk("P4a ★ _internal\\webui\\media 是联接", is_junction(link), link)
    chk("P4b ★ 联接指向 dist 下的 data\\media",
        is_junction(link) and norm_path(tgt) == norm_path(data_media), tgt)

    # ---------------- P1 第二次：启动全程黑框 ----------------
    log("")
    log("========== P1 启动期黑框 ==========")
    ev = events()
    cons = [e for e in ev if is_console_class(e["cls"])]
    mine = [e for e in ev if e["pid"] == proc.pid]
    log("  启动全程钩子记到 %d 条事件：" % len(ev))
    for e in ev:
        tag = "★黑框" if is_console_class(e["cls"]) else "     "
        log("    %s pid=%-7d top=%-5s cls=%-34s title=%s"
            % (tag, e["pid"], e["top"], e["cls"], e["title"]))
    chk("P1b 钩子在启动期是活的（记到了它自己的窗口）", len(mine) >= 1,
        "本进程窗口事件 %d 条" % len(mine))
    chk("P1c ★★ 启动期 0 黑框", len(cons) == 0,
        "抓到 %d 个：%s" % (len(cons), [(e["cls"], e["title"]) for e in cons]))

    # ---------------- P5 单实例 ----------------
    log("")
    log("========== P5 单实例闸 ==========")
    pids1 = running_pids()
    log("  第一次启动后的进程 = %s" % pids1)
    proc2 = subprocess.Popen([EXE], cwd=DIST)
    time.sleep(6.0)
    pids2 = running_pids()
    rc2 = proc2.poll()
    log("  再点一次后的进程 = %s" % pids2)
    log("  第二个进程退出码 = %s（None=还活着）" % rc2)
    chk("P5a ★ 连点两次仍然只有一个应用进程", len(pids2) == 1,
        "%d 个：%s" % (len(pids2), pids2))
    chk("P5b ★ 第二个进程自己退了（闸拦住并让位）", rc2 is not None,
        "exit=%s" % rc2)

    # ---------------- P6 用户数据完好 ----------------
    # 【为什么反过来了】这个探针最早验的是"打包版起一个干净空库"。
    # 现在打包版的 data\ 里就是**用户的真实库**，所以断言反过来：
    # 必须看得见 workspace.json 和真实的媒体文件 —— 一条都不许少。
    log("")
    data_dir = os.path.join(DIST, "data")
    files = []
    for dp, _dn, fn in os.walk(data_dir):
        for f in fn:
            files.append(os.path.relpath(os.path.join(dp, f), DIST))
    media = [f for f in files if os.sep + "media" + os.sep in f]
    log("  dist\\data 共 %d 个文件，其中 media %d 个" % (len(files), len(media)))
    chk("P6a ★ 用户库在（workspace.json + 真实媒体文件都看得见）",
        any(f.endswith("workspace.json") for f in files) and len(media) >= 5,
        "media=%d 个" % len(media))

    # ---------------- 收尾：按精确 PID 关掉自己起的进程 ----------------
    log("")
    for p in (proc, proc2):
        try:
            if p.poll() is None:
                log("  关闭自己起的 PID %d" % p.pid)
                subprocess.run(["taskkill", "/F", "/PID", str(p.pid)],
                               capture_output=True, timeout=20)
        except Exception as e:                            # noqa: BLE001
            log("  关 PID %s 失败: %s" % (getattr(p, "pid", "?"), e))
    time.sleep(2.0)
    log("  收尾后残留 = %s" % running_pids())

    hook_stop()
    time.sleep(0.5)

    log("")
    log("---- 结果 ----")
    npass = sum(1 for x in R if x["pass"])
    log("合计 %d 通过 / %d 失败 / 共 %d" % (npass, len(R) - npass, len(R)))
    for x in R:
        if not x["pass"]:
            log("   失败: %s  %s" % (x["name"], x["extra"]))


if __name__ == "__main__":
    try:
        main()
    except Exception:                                     # noqa: BLE001
        import traceback
        log("探针异常：%s" % traceback.format_exc())
    sys.stdout.flush()
