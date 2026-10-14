# -*- coding: utf-8 -*-
"""js_api 桥的**大字符串**传输探针：隔离测，不用摄像头。

起因：录制探针里三片 base64 全部 b64decode 失败（Incorrect padding），
可能是桥对大字符串做了手脚，也可能是别的原因。这里用**合成载荷**把桥
单独拎出来，量清楚它到底送过来什么。

结果写 _diag/bridge_probe.txt。
"""

import base64
import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
HTML = os.path.join(DIAG, "bridge_probe.html")
OUT = os.path.join(DIAG, "bridge_probe.txt")
T0 = time.monotonic()

ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")

SIZES = [1024, 64 * 1024, 200 * 1024, 1024 * 1024, 4 * 1024 * 1024]


def log(m):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("t=%6.2f  %s\n" % (time.monotonic() - T0, m))


class Api:
    def echo_bridge(self, n, s):
        if not isinstance(s, str):
            log("n=%d ★ 参数类型不是 str 而是 %s" % (n, type(s).__name__))
            return {"ok": False, "type": type(s).__name__}
        bad = {}
        for ch in s:
            if ch not in ALPHABET:
                bad[ch] = bad.get(ch, 0) + 1
        try:
            raw = base64.b64decode(s)
            dec_ok, dec_len, err = True, len(raw), None
        except Exception as e:                          # noqa: BLE001
            dec_ok, dec_len, err = False, None, "%s: %s" % (type(e).__name__, e)
        log("n=%-8d 期望长度约=%-8d 实收长度=%-8d 头=%r 尾=%r"
            % (n, (n + 2) // 3 * 4, len(s), s[:24], s[-24:]))
        if bad:
            log("         ★ 非法字符: %s" % sorted(
                (repr(k), v) for k, v in bad.items()))
        log("         解码 %s  %s" % ("成功 len=%s" % dec_len if dec_ok else "失败 " + str(err), ""))
        return {"ok": dec_ok, "len": len(s), "bad": sorted(bad.keys()),
                "decoded": dec_len, "err": err}

    def echo_plain(self, n, s):
        """对照组：不带 base64 语义的同样长度字符串，只看桥会不会改内容。"""
        if not isinstance(s, str):
            return {"ok": False, "type": type(s).__name__}
        return {"ok": True, "len": len(s), "head": s[:16], "tail": s[-16:]}


def driver():
    import webview

    while not webview.windows:
        time.sleep(0.05)
    w = webview.windows[0]
    for _ in range(60):
        try:
            if w.evaluate_js("!!(window.__BR && window.__BR.stage==='ready')"):
                break
        except Exception:
            pass
        time.sleep(0.15)
    log("页面就绪，开始 %s" % SIZES)
    w.evaluate_js("window.__runBridge(%s)" % json.dumps(SIZES))

    snap = None
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            raw = w.evaluate_js("JSON.stringify(window.__BR)")
            snap = json.loads(raw) if raw else None
        except Exception:
            snap = None
        if snap and snap.get("stage") == "done":
            break
        time.sleep(0.3)

    if snap and snap.get("stage") == "done":
        for r in snap.get("results") or []:
            log("JS 侧回报: %s" % json.dumps(r, ensure_ascii=False))
    else:
        log("★ 没跑完，快照=%s" % json.dumps(snap, ensure_ascii=False))
    time.sleep(0.3)
    os._exit(0)


def main():
    if os.path.exists(OUT):
        os.remove(OUT)
    import webview
    webview.create_window("bridge probe", url=HTML, js_api=Api(),
                          width=520, height=320)
    threading.Thread(target=driver, daemon=True).start()
    try:
        webview.start(gui="edgechromium")
    except TypeError:
        webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
