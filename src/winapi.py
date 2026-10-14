# -*- coding: utf-8 -*-
"""win32 窗口操作：找窗口、拉前台、弹消息框。纯 ctypes，不引第三方依赖。

为什么自己写而不装 pywin32：这个项目所有子进程都要走 proc.py 保证不出黑框，
依赖越少越好；这几个函数用 ctypes 写出来也就几十行。

**本模块不做任何"杀进程"的事** —— 一个调用都没有，将来也不许加。
"""

import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

IS_WIN = sys.platform.startswith("win")

u32 = ctypes.windll.user32 if IS_WIN else None
k32 = ctypes.windll.kernel32 if IS_WIN else None

#: 枚举窗口的回调类型（必须在模块级持有引用，否则会被 GC 掉）
ENUMPROC = (ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            if IS_WIN else None)

SW_RESTORE = 9
SW_SHOW = 5
MB_OK = 0x0
MB_ICONWARNING = 0x30
MB_TOPMOST = 0x40000
MB_SETFOREGROUND = 0x10000

ERROR_ALREADY_EXISTS = 183


# --------------------------------------------------------------------------
# 找窗口
# --------------------------------------------------------------------------
def find_window(title, klass=None, timeout=0.0, poll=0.25):
    """按标题找顶层窗口，返回 hwnd；找不到返回 0。

    标题是**精确匹配**（GetWindowTextW 的结果 == title）。
    klass 给了就同时校验类名（如 UWP 的 "ApplicationFrameWindow"）。
    timeout > 0 时轮询等待（窗口可能是异步建出来的）。
    """
    if not IS_WIN:
        return 0
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        hit = _find_once(title, klass)
        if hit or time.monotonic() >= deadline:
            return hit
        time.sleep(poll)


def _find_once(title, klass=None):
    hits = []

    def cb(hwnd, _):
        t = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, t, 256)
        if t.value == title:
            if klass:
                c = ctypes.create_unicode_buffer(256)
                u32.GetClassNameW(hwnd, c, 256)
                if c.value != klass:
                    return True
            hits.append(int(hwnd))
            return False                    # 找到一个就够
        return True

    u32.EnumWindows(ENUMPROC(cb), None)
    return hits[0] if hits else 0


def find_titled_windows(titles, klass=None):
    """按**一组**可能标题找（本地化名字不同的场景，如「相机」/「Camera」）。"""
    if not IS_WIN:
        return []
    want = set(titles)
    hits = []

    def cb(hwnd, _):
        t = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, t, 256)
        if t.value in want:
            if klass:
                c = ctypes.create_unicode_buffer(256)
                u32.GetClassNameW(hwnd, c, 256)
                if c.value != klass:
                    return True
            hits.append(int(hwnd))
        return True

    u32.EnumWindows(ENUMPROC(cb), None)
    return hits


def count_windows(title):
    """标题匹配的顶层窗口个数（e2e 断言"只有一个实例窗口"用）。"""
    if not IS_WIN:
        return 0
    n = [0]

    def cb(hwnd, _):
        t = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, t, 256)
        if t.value == title:
            n[0] += 1
        return True

    u32.EnumWindows(ENUMPROC(cb), None)
    return n[0]


def is_minimized(hwnd):
    return bool(u32.IsIconic(hwnd)) if IS_WIN and hwnd else False


def foreground():
    return int(u32.GetForegroundWindow()) if IS_WIN else 0


# --------------------------------------------------------------------------
# 拉前台
# --------------------------------------------------------------------------
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002


def _alt_tap():
    """按一下再松开 Alt。

    为什么需要：Windows 的前台锁规定"只有当前前台进程、或最近收到过输入的
    进程"才能 SetForegroundWindow。一个刚被脚本/服务拉起来的进程两样都不是，
    于是怎么调都没用。发一次合成输入能让我们变成"最近有输入的进程"，
    从而拿到放行。实测：不起这一下，第二实例拉前台必失败。

    只在前面几级都失败后才走这里，而且只按 Alt（不影响别的键）。
    """
    try:
        u32.keybd_event(VK_MENU, 0, 0, 0)
        time.sleep(0.03)
        u32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception:                                   # noqa: BLE001
        return False


def bring_to_front(hwnd):
    """把窗口恢复并拉到前台。返回是否**确实**成了前台窗口。

    为什么不只调 SetForegroundWindow：Windows 有前台锁，后台进程直接调会被
    无视。这里按"从轻到重"来，每一级都用 GetForegroundWindow **核实**
    （SetForegroundWindow 的返回值不可靠，不能当成功）：
      1. ShowWindow(RESTORE) + SetForegroundWindow
         —— 用户刚点过我们界面时我们就是前台进程，这级通常就够
      2. AttachThreadInput 挂到当前前台线程的输入队列
      3. SetWindowPos TOPMOST/NOTOPMOST（改 Z 序，不改前台）
      4. 合成 Alt 输入解锁前台锁，再 SetForegroundWindow
      5. SwitchToThisWindow（老 API，对 UWP 窗口更管用）
    全失败就如实返回 False，让调用方提示用户去点任务栏 —— **不假装成功**。
    """
    if not IS_WIN or not hwnd:
        return False
    if not u32.IsWindow(hwnd):
        return False

    try:
        if u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, SW_RESTORE)
        else:
            u32.ShowWindow(hwnd, SW_SHOW)
    except Exception:                                   # noqa: BLE001
        pass

    def fg_ok():
        return foreground() == hwnd

    # 1 级
    try:
        u32.SetForegroundWindow(hwnd)
    except Exception:                                   # noqa: BLE001
        pass
    if fg_ok():
        return True

    # 2 级
    try:
        fg = u32.GetForegroundWindow()
        tid_fg = u32.GetWindowThreadProcessId(fg, None)
        tid_me = k32.GetCurrentThreadId()
        if tid_fg and tid_fg != tid_me:
            u32.AttachThreadInput(tid_fg, tid_me, True)
            u32.BringWindowToTop(hwnd)
            u32.SetForegroundWindow(hwnd)
            u32.AttachThreadInput(tid_fg, tid_me, False)
    except Exception:                                   # noqa: BLE001
        pass
    if fg_ok():
        return True

    # 3 级：改 Z 序
    try:
        u32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        u32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    except Exception:                                   # noqa: BLE001
        pass

    # 4 级：合成 Alt 解锁
    for _ in range(2):
        _alt_tap()
        try:
            u32.SetForegroundWindow(hwnd)
        except Exception:                               # noqa: BLE001
            pass
        if fg_ok():
            return True
        time.sleep(0.12)

    # 5 级
    try:
        u32.SwitchToThisWindow(hwnd, True)
    except Exception:                                   # noqa: BLE001
        pass
    return fg_ok()


# --------------------------------------------------------------------------
# 消息框
# --------------------------------------------------------------------------
def message_box(text, title="视频知识库", warn=True):
    """弹一个系统消息框。pythonw 没有控制台，这是唯一能让用户看见的通道。"""
    if not IS_WIN:
        return 0
    flags = MB_OK | MB_SETFOREGROUND
    if warn:
        flags |= MB_ICONWARNING
    return u32.MessageBoxW(None, text, title, flags)


# --------------------------------------------------------------------------
# 窗口图标
# --------------------------------------------------------------------------
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
WM_SETICON = 0x0080
ICON_SMALL = 0       # 标题栏左上角 / 任务栏小图标
ICON_BIG = 1         # Alt+Tab / 任务栏大图标


def set_window_icon(hwnd, ico_path):
    """给窗口设标题栏与任务栏图标。返回是否两个尺寸都设上了。

    **为什么必须自己调 WM_SETICON**：
      pywebview 的 `create_window(icon=...)` 文档里明写
      "Supported only on GTK/QT" —— Windows 后端（winforms）直接忽略这个参数，
      传了也白传。

    加载出来的 HICON **故意不销毁**：Windows 会一直引用它，销毁了图标会变空。
    本函数只在启动时调一次，泄漏一个图标句柄可以接受。
    """
    if not IS_WIN or not hwnd or not ico_path or not os.path.isfile(ico_path):
        return False
    # LoadImageW 返回的是句柄（指针）。不显式声明 restype 会被当成 c_int
    # **截断成 32 位**，拿到的就是野句柄。
    u32.LoadImageW.restype = ctypes.c_void_p
    u32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                               ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    ok = 0
    for which, cx in ((ICON_BIG, 32), (ICON_SMALL, 16)):
        h = u32.LoadImageW(None, str(ico_path), IMAGE_ICON, cx, cx, LR_LOADFROMFILE)
        if h:
            u32.SendMessageW(hwnd, WM_SETICON, which, h)
            ok += 1
    return ok == 2


# --------------------------------------------------------------------------
# 单实例互斥量
# --------------------------------------------------------------------------
def acquire_mutex(name):
    """建/打开一个命名互斥量。返回 (handle, already_exists)。

    handle 必须**一直持有**到进程结束，否则互斥量会被释放、第二道闸失效。
    调用方把它存进模块级变量。
    """
    if not IS_WIN:
        return None, False
    k32.SetLastError(0)
    h = k32.CreateMutexW(None, False, name)
    err = k32.GetLastError()
    if not h:
        return None, False
    return h, (err == ERROR_ALREADY_EXISTS)
