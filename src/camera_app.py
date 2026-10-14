# -*- coding: utf-8 -*-
"""调起系统相机应用 + 监视录制产物 + 导入。

【为什么是"调起"而不是"自己访问摄像头"】
    用户明确要求：像调文件资源管理器那样 —— 调系统的东西，用户在里面操作，
    我们拿结果。所以这里不碰摄像头设备、不做 WebRTC、不做 ffmpeg dshow 录制
    （那条只在系统相机调不起来时降级用，见 camera.dshow_record）。

【目录：不猜，同时盯多个 —— 本机实测挖出来的坑，不是推测】
    SHGetKnownFolderPath(FOLDERID_CameraRoll) 给的是
        C:\\Users\\asus\\Pictures\\Camera Roll      ← 空的，0 个文件
    而真实录像是
        D:\\asus\\Pictures\\Camera Roll              ← 4 个文件，最近写到 2026/9/18
    两个目录**创建时间完全相同**（2023/9/3 20:08:17），D 盘那个带 desktop.ini
    （隐藏+系统属性），且 D:\\asus\\Pictures 被登记在图片库里。
    → **按常理硬编码 %USERPROFILE%\\Pictures\\Camera Roll，会盯一个永远不出现
    文件的空目录。** 所以候选目录运行时算出来、全部监视，谁出现新文件收谁。

【怎么知道录完了 —— 三条判据，谁先到算谁】
    A. 有稳定的文件，且所有候选项连续 QUIET_SEC 秒毫无变化（大小不变、也没有新文件）
    B. 相机进程已退出 —— **不再傻等宽限期**：立刻按 EXIT_POLL_SEC 复查文件，
       连着 EXIT_STABLE_TICKS 次大小不变就当场收工（见下面的常量说明）
    C. 超时（默认 10 分钟没有任何新文件）
    稳定的定义：大小连续 STABLE_TICKS 次轮询（≥3 秒）不变且 > 0。
"""

import ctypes
import ctypes.wintypes as wt
import os
import re
import stat
import sys
import threading
import time
import uuid

import proc
import store

#: 相机应用的 URI 协议（HKCU\Software\Classes 下已注册，实测可用）
CAMERA_URI = "microsoft.windows.camera:"
#: 兜底：直接按 AppUserModelId 起（实测可用，比 URI 慢约 0.8 秒）
CAMERA_APPSFOLDER = r"shell:AppsFolder\Microsoft.WindowsCamera_8wekyb3d8bbwe!App"
#: 进程名，用来判断"相机应用还开着吗"
CAMERA_EXE = "WindowsCamera.exe"

POLL_SEC = 1.0            # 轮询间隔
STABLE_TICKS = 3          # 大小连续几次不变算写完
QUIET_SEC = 8.0           # 全部静止多久算"用户录完了"
#: 相机进程退出后**改用这一套**（用户质疑"为什么要等 5 秒"之后改的）。
#:
#: 旧逻辑：进程没了也要再等 GRACE_SEC=5 秒才收工 —— 用户看到的就是
#: "我已经关掉相机了，它还在那儿傻等 5 秒"。实际上进程退出时文件**已经**落盘了。
#:
#: 新逻辑：进程一没 → 立刻按短轮询（EXIT_POLL_SEC）复查文件；
#: 大小连续 EXIT_STABLE_TICKS 次不变就算写完，**当场导入，不等 5 秒**。
#: 只有"文件还在长 / 还没出现"时才继续轮询 —— 这条同时兜住了
#: "相机应用正在重启、文件还在写"那种误判（进程回来 → exit_seen 清零，
#: 回到正常的 STABLE_TICKS 判据）。
EXIT_POLL_SEC = 0.25      # 进程退出后的复查间隔
EXIT_STABLE_TICKS = 2     # 退出后连续几次大小不变算写完（≈0.5 秒）
#: 退出后**不再设"到点强行收下"的兜底**。
#:
#: 试过一版：退出满 N 秒就把目录里 >0 的文件强行收走。实测它是**有害的** ——
#: 文件第一次露面时"上次大小"就是它自己，`prev == cur_size` 恒成立，
#: 于是**刚出现的文件会被立刻收走**，正是用户担心的那种误判（把"还在录"
#: 当成"录完了"）。现在的规则更简单：**进程没了就只等文件不再变大**，
#: 一直等不来的兜底是总的 10 分钟超时（DEFAULT_TIMEOUT）。
#
#: **一个文件都没收到**时，进程退出后还要等多久才放弃。
#:
#: 判据是「**相机进程消失** → 等这么久」，**不是**"点完按钮 N 秒就结束"：
#: 进程只要还在，监视就继续等（最长 DEFAULT_TIMEOUT）。
#: 进程忽隐忽现（UWP 挂起/重启）也没关系 —— 只要在这个窗口内回来，
#: exit_seen 就清零，继续等，不会因为一次抖动断掉。
#:
#: 5 秒是用户定的。真正会漏的场景：进程没了、5 秒内没回来、之后又开、
#: 且期间用户录了东西 —— 这种情况下用户再点一次「摄像头」就会重新起监视。
#: 收到文件之后不走这条 —— 那时候"关掉应用"才是明确的结束信号。
REOPEN_GRACE_SEC = 5.0
DEFAULT_TIMEOUT = 600.0   # 10 分钟没有任何新文件就结束

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv")
PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".heic", ".bmp", ".gif")


# --------------------------------------------------------------------------
# 已知文件夹 / 图片库
# --------------------------------------------------------------------------
class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort),
                ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]


FOLDERID_CameraRoll = "{AB5FB87B-7CE2-4F83-915D-550846C9537B}"


def known_folder(guid):
    """SHGetKnownFolderPath。取不到返回 None（**不猜一个默认值顶上**）。"""
    if not sys.platform.startswith("win"):
        return None
    try:
        import uuid as _uuid
        g = _GUID.from_buffer_copy(_uuid.UUID(guid).bytes_le)
        p = ctypes.c_wchar_p()
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(g), 0, None, ctypes.byref(p))
        if hr != 0:
            return None
        path = p.value
        ctypes.windll.ole32.CoTaskMemFree(p)
        return path
    except Exception:                                   # noqa: BLE001
        return None


def pictures_library_file():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    p = os.path.join(appdata, "Microsoft", "Windows", "Libraries",
                     "Pictures.library-ms")
    return p if os.path.isfile(p) else None


_KNOWN_RE = re.compile(r"knownfolder:\{([0-9A-Fa-f-]{36})\}")


def library_folders(path=None):
    """解析图片库 XML 里的 <url> 节点 -> 真实目录列表。

    library-ms 就是普通 XML，`<url>knownfolder:{GUID}</url>` 或 `<url>D:\\...`。
    本机实测它列了 knownfolder:{33E28130...}（= C:\\Users\\asus\\Pictures）
    和 D:\\asus\\Pictures —— 后者正是真正在写录制的那个。
    """
    path = path or pictures_library_file()
    if not path:
        return []
    raw = b""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return []
    text = ""
    for enc in ("utf-8", "utf-16", "utf-16-le"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        return []
    out = []
    for m in re.finditer(r"<url>(.*?)</url>", text, re.S):
        u = m.group(1).strip()
        if not u:
            continue
        km = _KNOWN_RE.match(u)
        if km:
            p = known_folder("{%s}" % km.group(1))
        else:
            p = u
        if p and p not in out:
            out.append(p)
    return out


def candidate_dirs():
    """要盯的目录全集。**不猜**：把系统给的、图片库里的、约定的全放进去。"""
    out = []

    def add(p):
        if p and os.path.isdir(p) and p not in out:
            out.append(p)

    add(known_folder(FOLDERID_CameraRoll))
    for root in library_folders():
        add(root)
        add(os.path.join(root, "Camera Roll"))
    home = os.path.expanduser("~")
    add(os.path.join(home, "Pictures", "Camera Roll"))
    add(os.path.join(home, "Videos", "Captures"))
    return out


# --------------------------------------------------------------------------
# 快照 / 差分
# --------------------------------------------------------------------------
def snapshot():
    """{目录: {文件名: (大小, mtime)}}。"""
    snap = {}
    for d in candidate_dirs():
        entries = {}
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if n.startswith(".") or n.lower() == "desktop.ini":
                continue
            try:
                st = os.stat(os.path.join(d, n))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                entries[n] = (int(st.st_size), float(st.st_mtime))
        snap[d] = entries
    return snap


def diff(before, after):
    """找出新增 / 变大的文件。

    返回 {"videos": [(dir, name, size)], "photos": [(dir, name)],
          "changed": bool}
    """
    videos, photos = [], []
    changed = False
    for d, entries in (after or {}).items():
        old = (before or {}).get(d) or {}
        for n, (size, _mt) in entries.items():
            if n in old and old[n][0] == size:
                continue
            changed = True
            low = n.lower()
            if low.endswith(VIDEO_EXTS):
                videos.append((d, n, size))
            elif low.endswith(PHOTO_EXTS):
                photos.append((d, n))
    # 老文件被删掉也算"变了"（用户清空目录时不该误判成静止）
    for d, entries in (before or {}).items():
        if set(entries) - set((after or {}).get(d) or {}):
            changed = True
    return {"videos": videos, "photos": photos, "changed": changed}


# --------------------------------------------------------------------------
# 进程
# --------------------------------------------------------------------------
def _pids_of(exe_name):
    """枚举进程找 exe_name 的 pid。用 Win32 API，不 spawn（每秒一次不能起子进程）。"""
    if not sys.platform.startswith("win"):
        return []
    try:
        psapi = ctypes.windll.psapi
        k32 = ctypes.windll.kernel32
        count = 1024
        arr = (wt.DWORD * count)()
        used = wt.DWORD()
        if not psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr),
                                   ctypes.byref(used)):
            return []
        n = used.value // ctypes.sizeof(wt.DWORD)
        out = []
        for i in range(n):
            pid = int(arr[i])
            if pid <= 0:
                continue
            h = k32.OpenProcess(0x1000, False, pid)     # QUERY_LIMITED_INFORMATION
            if not h:
                continue
            try:
                buf = ctypes.create_unicode_buffer(1024)
                ln = ctypes.c_ulong(1024)
                if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(ln)):
                    if os.path.basename(buf.value).lower() == exe_name.lower():
                        out.append(pid)
            finally:
                k32.CloseHandle(h)
        return out
    except Exception:                                   # noqa: BLE001
        return []


def app_running():
    return bool(_pids_of(CAMERA_EXE))


# --------------------------------------------------------------------------
# 调起
# --------------------------------------------------------------------------
def launch(timeout=10.0):
    """调起系统相机应用。三级：URI -> AppsFolder -> 失败。

    **不走 cmd**：os.startfile 走 ShellExecute，explorer.exe 是 GUI 程序，
    两条都不会弹黑框。实测 URI 方式 1.0 秒起来，AppsFolder 1.8 秒。
    """
    _t("launch() 开始；当前 app_running=%s" % app_running())
    if app_running():
        # 已经在跑就必须**把它拉到前台**，否则用户点完按钮什么变化都看不到
        # （UWP 窗口可能最小化、也可能被别的窗口盖住），看起来就是"没反应"。
        front = raise_camera_window()
        _t("相机应用已在运行 -> 复用；拉前台=%s" % front)
        return {"ok": True, "how": "already", "pids": _pids_of(CAMERA_EXE),
                "frontOk": front}

    errors = []
    if not sys.platform.startswith("win"):
        return {"ok": False, "error": "只支持 Windows"}

    t0 = time.monotonic()
    try:
        _t("第 1 级：os.startfile(%s)" % CAMERA_URI)
        os.startfile(CAMERA_URI)                        # noqa: S606
        if _wait_start(timeout):
            _t("第 1 级成功，进程出现，耗时 %.2fs" % (time.monotonic() - t0))
            return {"ok": True, "how": "uri", "pids": _pids_of(CAMERA_EXE)}
        errors.append("URI 方式 %gs 内没等到进程" % timeout)
        _t("第 1 级失败：%gs 内没等到进程" % timeout)
    except Exception as e:                              # noqa: BLE001
        errors.append("URI 方式失败：%s: %s" % (type(e).__name__, e))
        _t("第 1 级抛异常：%s: %s" % (type(e).__name__, e))

    t1 = time.monotonic()
    try:
        _t("第 2 级：explorer.exe %s" % CAMERA_APPSFOLDER)
        proc.run(["explorer.exe", CAMERA_APPSFOLDER],
                 capture_output=True, timeout=30)
        if _wait_start(timeout):
            _t("第 2 级成功，进程出现，耗时 %.2fs" % (time.monotonic() - t1))
            return {"ok": True, "how": "appsFolder", "pids": _pids_of(CAMERA_EXE)}
        errors.append("AppsFolder 方式 %gs 内没等到进程" % timeout)
        _t("第 2 级失败：%gs 内没等到进程" % timeout)
    except Exception as e:                              # noqa: BLE001
        errors.append("AppsFolder 方式失败：%s: %s" % (type(e).__name__, e))
        _t("第 2 级抛异常：%s: %s" % (type(e).__name__, e))

    _t("★ 前两级都失败，总共耗时 %.2fs —— 交给前端决定是否用 dshow 降级（本函数不自动跑）"
       % (time.monotonic() - t0))
    return {"ok": False, "error": "；".join(errors)}


def _wait_start(timeout):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if app_running():
            return True
        time.sleep(0.25)
    return False


#: UWP 的窗口挂在 ApplicationFrameHost 上，类名是 ApplicationFrameWindow。
#: 标题本地化：中文系统是「相机」，英文是「Camera」。
CAMERA_TITLES = ("相机", "Camera")
CAMERA_WINDOW_CLASS = "ApplicationFrameWindow"


def camera_window():
    """找相机应用的顶层窗口，返回 hwnd（找不到 0）。"""
    import winapi
    hits = winapi.find_titled_windows(CAMERA_TITLES, CAMERA_WINDOW_CLASS)
    return hits[0] if hits else 0


def raise_camera_window(timeout=3.0):
    """把相机应用窗口拉到前台。返回是否**确实**成了前台窗口。

    找不到窗口时短轮询再试（UWP 进程起来了、窗口可能还没建好）。
    **不假装成功** —— 拉不动就返回 False，界面如实提示"在后台，请点任务栏"。
    """
    import winapi
    t0 = time.monotonic()
    while True:
        hwnd = camera_window()
        if hwnd and winapi.bring_to_front(hwnd):
            return True
        if time.monotonic() - t0 >= timeout:
            _t("拉前台失败：窗口=%s（%s）" % (hwnd or "没找到",
                                            "已找到但抢不到前台" if hwnd else "还没建出来"))
            return False
        time.sleep(0.3)


# --------------------------------------------------------------------------
# 时间线（查"点一下到底走了哪一级、卡在哪一步"用）
# --------------------------------------------------------------------------
_T0 = time.monotonic()
_timeline = []


def _t(text):
    _timeline.append((round(time.monotonic() - _T0, 3), str(text)[:160]))
    del _timeline[:-80]


def timeline():
    return [{"t": t, "msg": m} for t, m in _timeline]


# --------------------------------------------------------------------------
# 视频模式
# --------------------------------------------------------------------------
#: 实测结论（三条，都是量出来的，不是猜的）：
#:   1. 相机应用**记住上次用的模式**。本机控件树里那个按钮叫「切换到 照片 模式」，
#:      说明当前就在视频模式 —— 因为上次录的就是视频。
#:   2. `microsoft.windows.camera:?mode=video` / `:?mode=pro` 这类启动参数
#:      **被完全忽略**：三个变体的控件树一模一样（对比见 _diag/probe_cam_mode.py、
#:      _diag/probe_cam_uia.ps1）。所以没法"直接以视频模式打开"。
#:   3. 唯一可行的办法是打开之后用 UI Automation 读按钮名，必要时点一下。
#:      按钮名是**动作式**的：「切换到 X 模式」里的 X 是"目标模式"，
#:      所以出现「切换到 视频 模式」就表示现在是照片模式。
#:
#: 这件事是**尽力而为**：切不了就保持现状，由界面提示用户手动切，绝不报错中断。
_PS_MODE = r'''
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$C = [System.Windows.Automation.Condition]::TrueCondition
$TS = [System.Windows.Automation.TreeScope]
$root = $null
$deadline = (Get-Date).AddSeconds(18)
while ((Get-Date) -lt $deadline) {
  foreach ($e in [System.Windows.Automation.AutomationElement]::RootElement.FindAll($TS::Children, $C)) {
    try { if ($e.Current.ClassName -eq 'ApplicationFrameWindow' -and
              ($e.Current.Name -eq [string][char]0x76F8 + [char]0x673A -or $e.Current.Name -eq 'Camera')) {
            $root = $e; break } } catch {}
  }
  if ($root) { break }
  Start-Sleep -Milliseconds 500
}
if (-not $root) { Write-Output 'no-window'; exit 0 }
Start-Sleep -Seconds 3
$btns = $root.FindAll($TS::Descendants, $C)
$switched = $false
$found = $false
foreach ($b in $btns) {
  $n = ''
  try { $n = $b.Current.Name } catch { continue }
  if (-not $n) { continue }
  $isSwitch = ($n -like '*Switch*' -or $n -like '*' + [char]0x5207 + [char]0x6362 + '*')
  $isVideo  = ($n -like '*Video*'  -or $n -like '*' + [char]0x89C6 + [char]0x9891 + '*')
  if ($isSwitch) {
    $found = $true
    if ($isVideo) {
      try {
        $b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
        $switched = $true
      } catch {}
    }
  }
}
if (-not $found) { Write-Output 'unknown' }
elseif ($switched) { Write-Output 'switched' }
else { Write-Output 'already-video' }
'''


def _run_ps(script, timeout=60):
    """跑一段 PowerShell（写成带 BOM 的临时文件 —— 不带 BOM 的话 PS5.1 会按
    GBK 读，脚本里的中文全乱、直接语法错。这个坑踩过不止一次）。"""
    import tempfile
    d = tempfile.mkdtemp(prefix="vkb-cammode-")
    p = os.path.join(d, "mode.ps1")
    try:
        with open(p, "w", encoding="utf-8-sig") as f:
            f.write(script)
        r = proc.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                      "-File", p],
                     capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=timeout)
        return (r.stdout or "").strip()
    except Exception as e:                              # noqa: BLE001
        return "error: %s: %s" % (type(e).__name__, e)
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


_mode_info = {"state": "unknown", "note": "未知"}


def video_mode_info():
    return dict(_mode_info)


def ensure_video_mode_async():
    """后台尽力把相机切到视频模式。**绝不影响调起主流程**。"""
    def work():
        global _mode_info
        out = _run_ps(_PS_MODE)
        last = out.splitlines()[-1] if out else "unknown"
        mapping = {
            "already-video": ("video", "已是视频模式（相机记住了上次的选择）"),
            "switched": ("video", "原来是照片模式，已自动切到视频"),
            "unknown": ("unknown", "没能确认模式，若不是视频请手动切一下"),
            "no-window": ("unknown", "没找到相机窗口，请确认模式"),
        }
        state, note = mapping.get(last, ("unknown", "模式探测异常：%s" % last))
        _mode_info = {"state": state, "note": note, "raw": last}
    t = threading.Thread(target=work, name="vkb-cammode", daemon=True)
    t.start()
    return t


# --------------------------------------------------------------------------
# 监视
# --------------------------------------------------------------------------
class Watch:
    """一次"等用户录完"的会话。线程只写 self.state，界面靠 status() 读。

    **绝不从工作线程调 evaluate_js** —— pywebview 的 WebView2 有 COM 线程
    亲和性，跨线程调用必炸（这个坑在 jobs.py 里已经记过一次）。
    """

    def __init__(self, on_done=None, timeout=DEFAULT_TIMEOUT):
        self.id = uuid.uuid4().hex[:8]
        self.timeout = float(timeout)
        self.on_done = on_done
        self._lock = threading.Lock()
        self._stop = False
        self.before = {}
        self.state = {
            "active": False, "stage": "starting", "found": [],
            "photos": 0, "elapsed": 0.0, "note": "正在打开系统相机应用…",
            "error": None, "dirs": [], "elapsedSinceNew": 0.0,
        }
        self._thread = None

    # ---------------------------------------------------------------- 控制
    def start(self):
        self.before = snapshot()
        self.state["dirs"] = candidate_dirs()
        self.state["active"] = True
        self._thread = threading.Thread(target=self._loop, name="vkb-camwatch",
                                        daemon=True)
        self._thread.start()
        return True

    def cancel(self):
        with self._lock:
            self._stop = True
        return True

    def status(self):
        with self._lock:
            st = dict(self.state)
        st["dirs"] = list(self.state.get("dirs") or [])
        return st

    def _set(self, **kw):
        with self._lock:
            self.state.update(kw)

    # ---------------------------------------------------------------- 主循环
    def _loop(self):
        t0 = time.monotonic()
        stable = {}          # (dir,name) -> (size, 连续不变的次数)
        collected = []       # 已收下的稳定文件 [(dir, name, size)]
        photos = set()
        last_change = t0
        exit_seen = None
        try:
            while True:
                if self._stop:
                    self._set(active=False, stage="cancelled", note="已取消")
                    return
                now = time.monotonic()
                el = now - t0

                if el > self.timeout:
                    break

                cur = snapshot()
                d = diff(self.before, cur)
                if d["changed"]:
                    last_change = now
                if d["videos"] or d["photos"]:
                    self.before = cur

                # 进程在不在 —— 要在"数稳定次数"之前算：退出后判据会放宽，
                # 靠的就是这个 running/exit_seen。
                running = app_running()
                if running:
                    exit_seen = None
                elif exit_seen is None and el > 1.0:
                    exit_seen = now                        # 第一次发现它不在了
                exited = exit_seen is not None
                # 退出后：轮询加快、判"写完"的次数放宽（文件和进程是一起没的，
                # 再多等几秒只是让用户干等）
                need_ticks = EXIT_STABLE_TICKS if exited else STABLE_TICKS

                # 新增的视频 -> 进稳定观察队列
                for (dirp, name, size) in d["videos"]:
                    stable[(dirp, name)] = (size, 0)
                for (_dirp, name) in d["photos"]:
                    photos.add(name)

                # 大小连续不变 = 写完了
                grown = []
                for key, (prev, ticks) in list(stable.items()):
                    dirp, name = key
                    cur_size = (cur.get(dirp) or {}).get(name, (None, None))[0]
                    if cur_size is None:
                        del stable[key]
                        continue
                    if cur_size == prev and cur_size > 0:
                        stable[key] = (prev, ticks + 1)
                    else:
                        stable[key] = (cur_size, 0)      # 还在长，重新数
                    # 判据只有一条：**见过这么多回都没再变大**。
                    # 不设"到点强行收"——那会把刚开始写的文件当成写完的。
                    if stable[key][1] >= need_ticks:
                        if not any(c[1] == name and c[0] == dirp for c in collected):
                            collected.append((dirp, name, cur_size))
                            grown.append(os.path.join(dirp, name))

                n_photos = len(photos)
                self._set(
                    active=True, stage="waiting",
                    found=[{"dir": c[0], "name": c[1], "size": c[2]} for c in collected],
                    photos=n_photos, elapsed=el,
                    elapsedSinceNew=now - last_change,
                    note=self._note(collected, n_photos, running))

                if collected and grown:
                    pass                                   # 已记录，继续等更多段

                # ---- 停止判据 ----
                if collected:
                    quiet = (now - last_change) >= QUIET_SEC
                    # 进程退出 = 明确的结束信号。到这里 collected 里的文件
                    # 已经按"退出后的放宽判据"确认过大小不再变，直接收工。
                    if quiet or exited:
                        self._finish(collected, n_photos,
                                     "文件已稳定" if quiet else "相机应用已关闭")
                        return
                # 一个文件都没收到时，进程退出**不算**结束信号 —— 只等一小段
                # 看它会不会回来。回来就把计时清零，继续等。
                #
                # `not stable` 不能省：**目录里已经冒出候选文件**就不许走这条。
                # 否则"进程先没、文件后到（差一点点赶在宽限到点前）"会被这条
                # 截胡 —— 已经录好的那一段当场丢掉。实测就是这么丢的：
                # 文件第 40 轮露面、宽限第 41 轮到点、判据要看到第 43 轮，
                # 少了 `not stable` 就是 41 轮直接 break，收工结果 files=[]。
                if (not collected and not stable and exit_seen is not None
                        and (now - exit_seen) >= REOPEN_GRACE_SEC):
                    break
                # 进程不在了就快点复查 —— 这是"关掉相机立刻导入"的关键
                time.sleep(EXIT_POLL_SEC if exited else POLL_SEC)

            # 走到这里只有两种可能：真超时，或者相机应用关了却什么都没录。
            # **必须分开说** —— 明明是因为应用被关掉结束的，却告诉用户
            # "10 分钟内没等到录制"，那是假信息（实测踩到过）。
            if collected:
                self._finish(collected, len(photos), "超时前已收到文件")
            else:
                closed = exit_seen is not None
                if closed:
                    note = "相机应用已关闭，但没有检测到新录制的视频"
                    reason = "closed"
                else:
                    note = ("没等到录制（%d 分钟内相机目录里没有出现新视频）"
                            % int(self.timeout // 60))
                    reason = "timeout"
                self._set(active=False, stage=reason, error=None, note=note)
                if self.on_done:
                    self.on_done({"ok": False, "reason": reason, "files": []})
        except Exception as e:                              # noqa: BLE001
            self._set(active=False, stage="error",
                      error="%s: %s" % (type(e).__name__, e), note="监视出错")
            if self.on_done:
                self.on_done({"ok": False, "reason": "error", "files": [],
                              "error": str(e)})

    def _note(self, collected, n_photos, running):
        parts = []
        if collected:
            parts.append("已检测到 %d 段录制" % len(collected))
        elif running:
            parts.append("等待录制…（相机应用运行中）")
        else:
            # 没录到 + 应用不在 —— 说清"还在等"，别让人以为已经结束了。
            # 应用可能只是被挂起或用户要重开，我们会再等一段时间。
            parts.append("相机应用当前没在运行，仍在等待…"
                         "（按红色圆点开始录制；不想录了可以点「取消等待」）")
        if n_photos:
            parts.append("另有 %d 张照片（本程序只导入视频）" % n_photos)
        return " · ".join(parts)

    def _finish(self, collected, n_photos, why):
        self._set(active=False, stage="finishing", note="正在导入…",
                  photos=n_photos)
        if self.on_done:
            self.on_done({"ok": True, "files": list(collected),
                          "photos": n_photos, "reason": why})


# --------------------------------------------------------------------------
# 单例
# --------------------------------------------------------------------------
_watch = None
_watch_lock = threading.Lock()
_last_result = None


def start_watch(on_done=None, timeout=DEFAULT_TIMEOUT):
    global _watch
    with _watch_lock:
        if _watch is not None and _watch.status().get("active"):
            return None                       # 已经有一个在跑
        _watch = Watch(on_done=on_done, timeout=timeout)
        _watch.start()
        return _watch


def current():
    return _watch


def status():
    global _last_result
    w = _watch
    if w is None:
        return {"active": False, "stage": "idle", "note": "", "found": [],
                "photos": 0, "elapsed": 0.0, "error": None, "result": _last_result}
    st = w.status()
    st["result"] = _last_result
    st["mode"] = video_mode_info()
    st["timeline"] = timeline()
    return st


def set_result(r):
    global _last_result
    _last_result = r


def cancel():
    w = _watch
    if w is not None:
        return w.cancel()
    return False


# --------------------------------------------------------------------------
# 导入（watcher 的 on_done 里调，跑在工作线程）
# --------------------------------------------------------------------------
def import_recordings(files, on_progress=None):
    """把录到的文件复制进 data/media/ 并登记成条目。

    **沿用导入视频那套**：store.import_media —— 复制（不是软链）、
    临时文件 + os.replace 原子落地、重名自动加序号。
    复制完用 ffprobe 复核一次，复核不过就报错，**不静默收下一个坏文件**。
    """
    import video_ops

    added, failed = [], []
    total = len(files) or 1
    for i, (dirp, name, _size) in enumerate(files):
        src = os.path.join(dirp, name)
        if not os.path.isfile(src):
            failed.append((name, "文件不见了"))
            continue

        def prog(f, _i=i):
            if on_progress:
                on_progress((_i + f) / total, name)

        try:
            media_name = store.import_media(src, on_progress=prog)
        except Exception as e:                          # noqa: BLE001
            failed.append((name, "%s: %s" % (type(e).__name__, e)))
            continue

        st = video_ops.probe(store.media_path(media_name))
        if not st or not st.get("video"):
            failed.append((name, "ffprobe 读不出视频流（文件可能不完整）"))
            continue

        it = store.add_item(media_name, "", origin="record",
                            media_name=media_name)
        # 把条目对象本身带回去：调用方（WebState）要把它并进内存列表并落盘。
        # store.add_item 只造对象不写盘（这是它的既定约定），
        # 谁调用谁负责持久化 —— 所以这里也**不**替调用方写。
        added.append({"iid": it.iid, "mediaName": media_name, "item": it,
                      "seconds": st.get("duration"),
                      "width": (st.get("video") or {}).get("width"),
                      "height": (st.get("video") or {}).get("height"),
                      "sourceDir": dirp})
    return {"added": added, "failed": failed}
