# -*- coding: utf-8 -*-
"""界面验收驱动：跑真实应用 + 注入 _diag/ui_tests.js，把结果写成日志。

为什么要 pythonw：和打包后的 --windowed exe 同为 GUI 子系统，
窗口样式（resizable）与黑框行为才与用户看到的一致。
"""

import ctypes
import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
#: 界面断言跑在假数据回退链路上 —— 不需要 GPU、不需要 API Key，结果可复现。
#: 传 VKB_FAKE=0 可切到真实数据（真实模式下只有数据无关的子集能跑）。
os.environ.setdefault("VKB_FAKE", "1")
# 测试驱动一律跳过单实例闸，否则用户自己开着程序时这些套件全起不来。
# 只跳过这一道，其它逻辑照跑。
os.environ["VKB_NO_SINGLE_INSTANCE"] = "1"
#: 用环境变量切换跑哪一套（默认新验收；回归套件传 VKB_TESTS=regress_tests.js）
TESTS = os.environ.get("VKB_TESTS", "ui_tests.js")
OUT = os.path.join(DIAG, os.environ.get("VKB_OUT", "ui_results.txt"))
T0 = time.monotonic()


def log(msg):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("t=%6.2f  %s\n" % (time.monotonic() - T0, msg))


u32 = ctypes.windll.user32
GWL_STYLE = -16
WS_THICKFRAME = 0x00040000      # 可拉伸边框
WS_MAXIMIZEBOX = 0x00010000     # 最大化按钮
WS_MINIMIZEBOX = 0x00020000

TITLE = "视频知识库 · 工作台"


def window_style_report():
    hwnd = u32.FindWindowW(None, TITLE)
    if not hwnd:
        return {"found": False}
    style = u32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF
    return {
        "found": True,
        "hwnd": hwnd,
        "resizable": bool(style & WS_THICKFRAME),
        "maximizeBox": bool(style & WS_MAXIMIZEBOX),
        "minimizeBox": bool(style & WS_MINIMIZEBOX),
        "style": hex(style),
    }


def driver():
    import webview

    while not webview.windows:
        time.sleep(0.05)
    w = webview.windows[0]

    ready = False
    for _ in range(200):
        try:
            if w.evaluate_js("!!(window.VKB_DEBUG && VKB_DEBUG.ready())"):
                ready = True
                break
        except Exception:
            pass
        time.sleep(0.1)
    if not ready:
        log("界面没就绪，放弃")
        os._exit(3)
    log("界面就绪")

    # ---- 8. 窗口固定大小：读真实窗口样式位 ----
    time.sleep(0.6)
    st = window_style_report()
    log("窗口样式: " + json.dumps(st, ensure_ascii=False))

    # 把窗口提到前台：Chromium 对被完全遮挡的窗口会暂停 rAF，
    # 循环播放的判定会因此假失败。这条纯属测试环境保障，不改被测代码。
    hwnd = u32.FindWindowW(None, TITLE)
    if hwnd:
        for fn in ("ShowWindow", "SetForegroundWindow", "BringWindowToTop"):
            try:
                if fn == "ShowWindow":
                    u32.ShowWindow(hwnd, 5)
                else:
                    getattr(u32, fn)(hwnd)
            except Exception:
                pass
        time.sleep(0.5)
        log("已把窗口提到前台")

    # 注入"源码真值"（磁盘上这几个文件有多少字符）。
    # 防的是：pywebview 挑的端口撞上另一个正在跑的实例，页面被**那个实例**的
    # 服务器供走 —— 于是套件测的是构建产物里的旧前端，而不是源码里刚改的那份。
    # 实测踩过：E2 假失败，查了半天才发现页面来自打包版的 42001 端口。
    import json as _json
    _src = {}
    for _rel in ("js/app.js", "style.css"):
        try:
            with open(os.path.join(ROOT, "webui", _rel.replace("/", os.sep)),
                      encoding="utf-8") as _f:
                _src[_rel] = len(_f.read())
        except OSError:
            _src[_rel] = -1
    w.evaluate_js("window.__SRC_LEN = %s" % _json.dumps(_src))
    log("源码真值 = " + _json.dumps(_src))

    js = open(os.path.join(DIAG, TESTS), encoding="utf-8").read()
    log("注入测试脚本 %d 字节" % len(js))
    w.evaluate_js(js)

    done = False
    for _ in range(1200):                    # 最多 4 分钟
        time.sleep(0.2)
        try:
            if w.evaluate_js("!!window.__DONE"):
                done = True
                break
        except Exception:
            pass
    if not done:
        log("测试超时（__DONE 未置位）")

    try:
        res = w.evaluate_js("JSON.stringify(window.__RESULTS || [])")
        results = json.loads(res) if res else []
    except Exception as e:
        log("取结果失败: %s" % e)
        results = []

    npass = sum(1 for r in results if r.get("pass"))
    log("---- 结果 ----")
    for r in results:
        log("%s  %-46s %s" % ("PASS" if r.get("pass") else "FAIL", r.get("name"), r.get("extra", "")))
    log("合计 %d 通过 / %d 失败 / 共 %d" % (npass, len(results) - npass, len(results)))

    time.sleep(0.3)
    os._exit(0)


def main():
    f = open(os.path.join(DIAG, "ui_app_stderr.txt"), "w", encoding="utf-8", buffering=1)
    sys.stdout = f
    sys.stderr = f
    if os.path.exists(OUT):
        os.remove(OUT)
    sys.path.insert(0, os.path.join(ROOT, "src"))

    # 【必须】钉一个确认没人占用的端口再启动。
    # 为什么不靠 pywebview 自己挑：它挑的"随机"端口在 Windows 上和**另一个正在
    # 跑的实例**撞了也能 bind（两边都能绑，请求被谁接走不确定）。实测踩过：
    # 套件的页面被打包版的服务器接走，测的是构建产物里的旧前端 —— 断言会假失败。
    # 这里用 SO_EXCLUSIVEADDRUSE 探一个真的没人在听的端口，钉给应用。
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1", 0))
        os.environ["VKB_HTTP_PORT"] = str(s.getsockname()[1])
    finally:
        s.close()
    sys.stderr.write("测试用 HTTP 端口 = %s\n" % os.environ.get("VKB_HTTP_PORT"))

    import app_web
    threading.Thread(target=driver, daemon=True).start()
    app_web.main()


if __name__ == "__main__":
    main()
