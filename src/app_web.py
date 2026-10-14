# -*- coding: utf-8 -*-
"""视频知识库 · Web 界面入口（pywebview + HTML/CSS/JS）。

单进程、无本地服务器、无端口：pywebview 在同一个进程里开一个 WebView2
窗口加载本地 HTML，Python 与 JS 通过 js_api 直接调用。

跑：venv\\Scripts\\python.exe src\\app_web.py
    venv\\Scripts\\python.exe src\\app_web.py --debug   （打开 DevTools）
或双击 启动视频知识库.bat
"""

import ctypes
import os
import sys
import time
from ctypes import wintypes

import webview

import jobs
import media
from web_bridge import WebBridge
from web_state import WebState

APP_TITLE = "视频知识库 · 工作台"

# 期望尺寸（会被屏幕工作区收敛）
WANT_W, WANT_H = 1440, 920
MIN_W, MIN_H = 960, 640
MARGIN_W, MARGIN_H = 40, 40          # 初始尺寸与工作区之间留的边
MIN_MARGIN_W, MIN_MARGIN_H = 100, 100

SPI_GETWORKAREA = 0x0030


def work_area():
    """取屏幕工作区（去掉任务栏），返回 (x, y, w, h)。

    实测本机返回 (0, 0, 1280, 752)，与 pywebview 的 width/height/x/y 是同一套单位。
    取不到就返回 None，调用方退回原始尺寸与默认位置。
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        rect = wintypes.RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
        if ok:
            w = int(rect.right - rect.left)
            h = int(rect.bottom - rect.top)
            if w > 200 and h > 200:
                return int(rect.left), int(rect.top), w, h
    except Exception as e:
        print(f"[app_web] 读取屏幕工作区失败，使用默认尺寸：{e}", file=sys.stderr)
    return None


def place(area, win_w, win_h):
    """在工作区内居中。返回 (x, y)；取不到工作区就返回 (None, None)。

    必须显式定位：实测 pywebview 自己会把窗口放在 (201,236)（物理像素），
    不管申请的尺寸是多少 —— 位置固定不动，所以"申请小一点"救不了，
    窗口右/下会一直顶出屏幕外。显式给 x/y 才能保证四格完整可见。
    """
    if not area:
        return None, None
    ax, ay, aw, ah = area
    x = ax + max(0, (aw - win_w) // 2)
    y = ay + max(0, (ah - win_h) // 2)
    return x, y


def fit(want_w, want_h, area, margin_w, margin_h):
    """把尺寸收敛到工作区内。

    为什么必须做：本机物理屏 1920x1200、缩放 150% -> 工作区逻辑 1280x752。
    之前申请 1440x920 比工作区还大，Windows 只钳尺寸不钳位置，
    窗口被放到 (201,236)，右边 137 CSS px、底部 139 CSS px 直接被推出屏幕外。
    """
    if not area:
        return want_w, want_h
    _ax, _ay, aw, ah = area
    return min(want_w, aw - margin_w), min(want_h, ah - margin_h)


def resource_path(*parts):
    """打包后资源在 sys._MEIPASS；开发时在项目根目录。"""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def icon_path():
    """窗口/任务栏图标文件。找不到返回空串（调用方跳过，不报错）。"""
    for c in (
        resource_path("vkb.ico"),                 # 打包后：--add-data 放进 _MEIPASS 根
        resource_path("build", "vkb.ico"),        # 开发时：项目根\build\vkb.ico
    ):
        if os.path.isfile(c):
            return c
    return ""


def main():
    debug = "--debug" in sys.argv
    import timing
    timing.mark("main 进入", debug=debug,
                frozen=bool(getattr(sys, "frozen", False)),
                exe=sys.executable)

    # 【第一件事】单实例闸。为什么放在最前面：两个实例会同时写
    # data/workspace.json 互相覆盖；而且用户很容易点到**跑着旧代码**的那个
    # 窗口（实测踩过：用户点「摄像头」半天没反应，因为他开的是改动之前的实例）。
    # 测试驱动靠 VKB_NO_SINGLE_INSTANCE=1 跳过这一道。
    import single_instance
    with timing.span("① 单实例闸"):
        why = single_instance.acquire()
    if why is not None:
        if why == "already":
            print("[app_web] 已有一个实例在运行，已把它拉到前台，本次退出",
                  file=sys.stderr)
        # "no-window" 的情况 single_instance 已经弹框说清楚了，这里不再重复
        return 0

    area = work_area()
    win_w, win_h = fit(WANT_W, WANT_H, area, MARGIN_W, MARGIN_H)
    min_w, min_h = fit(MIN_W, MIN_H, area, MIN_MARGIN_W, MIN_MARGIN_H)
    pos_x, pos_y = place(area, win_w, win_h)
    print(f"[app_web] 工作区={area}  窗口={win_w}x{win_h}@{pos_x},{pos_y}"
          f"  最小={min_w}x{min_h}", file=sys.stderr)

    with timing.span("② WebState 构建（读 workspace/tree/settings）") as _s2:
        state = WebState()
    _s2.extra["fake"] = state.fake
    _s2.extra["条目"] = len(state.done) + len(state.pending)
    if not state.fake:
        # 真实链路：起一个串行任务队列。daemon 线程，关窗即随进程退出。
        with timing.span("③ 任务队列启动"):
            queue_ = jobs.JobQueue()
            queue_.start()
        state.jobs = queue_
    holder = {}
    bridge = WebBridge(state, window_provider=lambda: holder.get("win"))

    # 媒体挂载：失败**明确报错**，不静默降级（不复制文件、不改路径）。
    # 失败也不阻止程序启动 —— 前端会显示醒目错误条，用户能看见原因。
    media_error = None
    try:
        with timing.span("④ 媒体联接 ensure_link") as _s4:
            media.ensure_link()
        _s4.extra["已存在"] = media.link_ok()
        with timing.span("⑤ 样片 ensure_samples") as _s5:
            _total, _made, sample_err = media.ensure_samples()
        _s5.extra["新生成"] = _made
        if sample_err:
            media_error = sample_err
            print(f"[app_web] 样片: {sample_err}", file=sys.stderr)
    except media.MediaLinkError as e:
        media_error = str(e)
        print(f"[app_web] 媒体挂载失败：\n{e}", file=sys.stderr)
    bridge.set_media_error(media_error)

    index = resource_path("webui", "index.html")
    if not os.path.isfile(index):
        print(f"[app_web] 找不到界面文件：{index}", file=sys.stderr)
        return 2
    # 把**实际加载的界面路径**打出来。排查"改了前端没生效"时第一眼看这行：
    # 如果这里指向 build\...\_internal\webui\，就说明跑的是构建产物而不是源码。
    print(f"[app_web] 界面文件={index}  _MEIPASS={getattr(sys, '_MEIPASS', None)}",
          file=sys.stderr)

    # 【已停用 · M10 清】这里原来装摄像头权限钩子（订阅 WebView2 的
    # PermissionRequested，给 getUserMedia 放行）。
    # 现在摄像头走**系统相机应用**（src/camera_app.py），页面里不再调
    # getUserMedia，WebView2 权限这一环整个用不上了，所以不再安装。
    # 钩子代码保留在 src/camera.py 里（实测有效，M10 一起清）。

    with timing.span("⑥ create_window"):
        window = webview.create_window(
            APP_TITLE,
            url=index,
            js_api=bridge,
            width=win_w,
            height=win_h,
            min_size=(min_w, min_h),
            resizable=False,      # 规格：窗口固定大小，不支持拉伸
            background_color="#f6f7f9",
        )
    holder["win"] = window
    timing.mark("⑥b create_window 返回（下面进 webview.start）")

    def on_start():
        """窗口起来后统一做三件事：确保显示、取消最小化、移到算好的位置。

        为什么不在 create_window 里给 x/y：
          实测（本机 Win11 + pywebview 6.2.1）传 x/y 会让窗口**最小化启动**；
          不传时窗口默认停在 (51,51)，右边会顶出屏幕。
          所以位置只能在窗口创建之后给。

        为什么要重试几轮：
          从后台进程拉起 GUI 时 Windows 会给窗口一个"最小化"提示，而这个提示
          可能**晚于** start 回调到达 —— 只调一次 restore() 会被随后的提示盖掉。
          实测：单次调用后窗口仍是 min=True；这里在头两秒内反复 show+restore
          直到窗口真正显示出来。
        """
        moved = False
        timing.mark("⑦ on_start 回调进入（窗口已建，等显示）")

        # 【窗口图标】pywebview 的 create_window(icon=...) 在 Windows 上**无效**
        # （它文档里写着 Supported only on GTK/QT），只能自己 WM_SETICON。
        # exe 自己的文件图标由 PyInstaller --icon 管，两者是**两回事**：
        #   · exe 图标 -> 文件管理器、任务栏按钮的默认来源
        #   · 窗口图标 -> 标题栏左上角、Alt+Tab（覆盖掉 exe 的默认值）
        # 这里在做，是因为此时窗口才真的存在、能按标题找到它的 hwnd。
        try:
            import winapi
            hwnd = winapi.find_window(APP_TITLE, timeout=3.0)
            ico = icon_path()
            if hwnd and ico:
                if winapi.set_window_icon(hwnd, ico):
                    timing.mark("⑦b 窗口图标已设", hwnd=hwnd, ico=os.path.basename(ico))
                else:
                    timing.mark("★ 窗口图标设置失败（LoadImage/SendMessage 没成）", hwnd=hwnd)
            else:
                timing.mark("★ 没找到窗口句柄或图标文件，跳过设图标",
                            hwnd=hwnd, ico=ico)
        except Exception as e:                          # noqa: BLE001
            print(f"[app_web] 设置窗口图标失败：{e}", file=sys.stderr)

        for _ in range(8):
            time.sleep(0.25)
            for name in ("show", "restore"):
                fn = getattr(window, name, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass
            if pos_x is not None and not moved:
                try:
                    window.move(pos_x, pos_y)
                    moved = True
                except Exception:
                    pass
        if pos_x is not None and not moved:
            print("[app_web] 窗口定位失败，使用系统默认位置", file=sys.stderr)
        timing.mark("⑧ on_start 收尾（显示/前置循环走完）")

    # 【WebView2 配置目录】不给的话**每次启动都是冷启动**（实测根因）：
    #   pywebview 的 private_mode 默认是 True（webview\__init__.py:173），
    #   winforms.init_storage() 于是走 else 分支把 cache_dir 设成
    #   tempfile.TemporaryDirectory().name（winforms.py:757）——
    #   每一次启动都拿到一个全新的随机临时目录：
    #     · 缓存完全复用不了（无 HTTP/代码/GPU 着色器缓存）
    #     · 浏览器是 InPrivate（实测窗口标题里就有 "[InPrivate]"）
    #     · 那些目录**从不清理**（实测 TEMP 里堆了 6 个 / 73.5 MB）
    # 现在：private_mode=False + 固定 storage_path。
    #   为什么不只给 private_mode=False：那样 cache_dir 会落到
    #   %APPDATA%\pywebview —— 那是**全机器所有 pywebview 应用共用**的目录，
    #   而 WebView2 会独占锁 UserDataFolder，两个应用同时开就打架；
    #   而且它在 C 盘 Roaming 里。固定到自己的 data\webview 更干净。
    wv_profile = os.path.join(media.app_root(), "data", "webview")
    try:
        os.makedirs(wv_profile, exist_ok=True)
    except Exception as e:                              # noqa: BLE001
        print(f"[app_web] 建 WebView 配置目录失败：{e}", file=sys.stderr)
    timing.mark("⑪ WebView 配置目录", 路径=wv_profile,
                可写=os.access(wv_profile, os.W_OK))

    # 【可钉端口】VKB_HTTP_PORT 给了就用它，否则让 pywebview 自己挑。
    # 为什么需要：pywebview 挑的"随机"端口在 Windows 上可能和**另一个正在跑的
    # 实例**撞在一起 —— 两边的 socket 都能 bind，请求被谁接走不确定。
    # 实测踩过：ui 套件的页面被**打包版**的服务器接走了，于是测的是构建产物
    # 里的旧前端，而不是源码里刚改的那份，断言假失败/假通过都出现过。
    # 测试驱动靠这个环境变量钉一个确认没人占用的端口。
    _port = os.environ.get("VKB_HTTP_PORT", "").strip()
    http_port = int(_port) if _port.isdigit() else None

    try:
        webview.start(on_start, gui="edgechromium", debug=debug,
                      private_mode=False, storage_path=wv_profile,
                      http_port=http_port)
    except TypeError:
        # 老版本 pywebview 没有 gui= 参数。**private_mode / storage_path 必须保留**
        # —— 丢了就退回"每次新建随机临时目录"的老毛病。
        webview.start(on_start, debug=debug,
                      private_mode=False, storage_path=wv_profile)
    return 0


if __name__ == "__main__":
    sys.exit(main())
