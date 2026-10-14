# -*- coding: utf-8 -*-
"""摄像头权限探针：查清 WebView2 里 getUserMedia 到底能不能用，**实测不猜**。

用法：
    pythonw _diag/probe_camera.pyw plain    # 基线：pywebview 原样（不订阅权限事件）
    pythonw _diag/probe_camera.pyw perm     # 订阅 CoreWebView2.PermissionRequested -> Allow

结果写 _diag/camera_probe_<mode>.txt。

为什么要探：
  pywebview 6.2.1 的 edgechromium.py **完全没有**订阅 PermissionRequested，
  而 WebView2 没有内置权限弹窗。默认是拒绝还是放行，必须实测。
"""

import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
MODE = (sys.argv[1] if len(sys.argv) > 1 else "plain").strip()
OUT = os.path.join(DIAG, "camera_probe_%s.txt" % MODE)
HTML = os.path.join(DIAG, "cam_probe.html")
T0 = time.monotonic()


def log(m):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("t=%6.2f  %s\n" % (time.monotonic() - T0, m))


# --------------------------------------------------------------------------
# 权限钩子
# --------------------------------------------------------------------------
def install_permission_hook():
    """给 EdgeChrome.on_webview_ready 包一层，订阅 PermissionRequested。

    这是**外部**打补丁（不改 venv 里的文件），应用里也会用同样的位置。
    """
    from webview.platforms import edgechromium
    from Microsoft.Web.WebView2.Core import (
        CoreWebView2PermissionKind, CoreWebView2PermissionState)

    kinds = {0: "Default", 1: "Camera", 2: "Microphone",
             3: "Geolocation", 4: "Notifications", 5: "OtherSensors",
             6: "ClipboardRead", 7: "MultipleAutomaticDownloads",
             8: "FileReadWrite", 9: "Autoplay",
             10: "LocalFonts", 11: "MidiSystemExclusive",
             12: "WindowManagement"}

    orig = edgechromium.EdgeChrome.on_webview_ready

    def patched(self, sender, args):
        orig(self, sender, args)
        if not args.IsSuccess:
            log("on_webview_ready 失败，跳过权限钩子")
            return
        try:
            def on_perm(s, a):
                try:
                    k = kinds.get(int(a.PermissionKind), a.PermissionKind)
                    log("★ PermissionRequested kind=%s uri=%s" % (k, a.Uri))
                    a.State = CoreWebView2PermissionState.Allow
                    a.Handled = True
                    log("   -> 已置 Allow + Handled")
                except Exception as e:                  # noqa: BLE001
                    log("   -> 处理失败: %s: %s" % (type(e).__name__, e))
            sender.CoreWebView2.PermissionRequested += on_perm
            log("已订阅 PermissionRequested")
        except Exception as e:                          # noqa: BLE001
            log("订阅 PermissionRequested 失败: %s: %s" % (type(e).__name__, e))

    edgechromium.EdgeChrome.on_webview_ready = patched
    log("已给 EdgeChrome.on_webview_ready 打补丁")


def driver():
    import webview

    while not webview.windows:
        time.sleep(0.05)
    w = webview.windows[0]
    log("窗口已创建")

    got = None
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            raw = w.evaluate_js("JSON.stringify(window.__CAM || null)")
        except Exception:
            raw = None
        if raw:
            try:
                got = json.loads(raw)
            except Exception:
                got = None
            if got and got.get("stage") not in (None, "boot", "ready"):
                break
        time.sleep(0.35)

    log("快照 = %s" % json.dumps(got, ensure_ascii=False))
    if got is None:
        log("判定: 界面没回话（页面没起来或 JS 异常）")
    elif got.get("stage") == "ok":
        log("判定: ★ getUserMedia 成功（%sx%s，音频轨 %s）" %
            (got.get("w"), got.get("h"), got.get("audioTracks")))
    elif got.get("stage") == "error":
        log("判定: 失败 name=%s msg=%s" % (got.get("name"), got.get("msg")))
    else:
        log("判定: 卡在 %s" % got.get("stage"))
    time.sleep(0.4)
    os._exit(0)


def main():
    if os.path.exists(OUT):
        os.remove(OUT)
    log("mode = %s" % MODE)
    log("html = %s 存在=%s" % (HTML, os.path.isfile(HTML)))

    if MODE == "perm":
        install_permission_hook()

    import webview
    webview.create_window("cam probe", url=HTML, width=520, height=420)
    threading.Thread(target=driver, daemon=True).start()
    try:
        webview.start(gui="edgechromium")
    except TypeError:
        webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
