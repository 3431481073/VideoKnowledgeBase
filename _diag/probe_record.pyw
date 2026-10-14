# -*- coding: utf-8 -*-
"""录制链路探针：摄像头 -> MediaRecorder -> js_api 分片传 -> 落盘 -> ffprobe 校验。

用法：
    pythonw _diag/probe_record.pyw video/mp4
    pythonw _diag/probe_record.pyw video/webm;codecs=vp8,opus
    pythonw _diag/probe_record.pyw ""            # 用引擎默认

一次把四件事问清楚：
  1. 这个容器到底能不能录（isTypeSupported 说 true 不等于能出合法文件）
  2. 分片走 js_api（base64）在真实体积下通不通、每次多大、多久
  3. ffprobe 认不认这个文件（下游裁剪/合并全靠它）
  4. 录完之后 WebView2 自己还能不能解码播放

结果写 _diag/record_probe_<slug>.txt，视频留在 _diag/rec_out/。
"""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
OUTDIR = os.path.join(DIAG, "rec_out")
HTML = os.path.join(DIAG, "cam_rec.html")
sys.path.insert(0, os.path.join(ROOT, "src"))

MIME = (sys.argv[1] if len(sys.argv) > 1 else "video/mp4").strip()
SLUG = re.sub(r"[^0-9a-zA-Z]+", "_", MIME) or "default"
OUT = os.path.join(DIAG, "record_probe_%s.txt" % SLUG)
SECONDS = 6
T0 = time.monotonic()

_stats = {"chunks": 0, "bytes": 0, "max_msg": 0, "t_first": None, "t_last": None}
ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
_part = os.path.join(OUTDIR, "p1.part")
_final = None


def log(m):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("t=%6.2f  %s\n" % (time.monotonic() - T0, m))


# --------------------------------------------------------------------------
# 权限钩子（已在 probe_camera 里验证有效，这里照搬）
# --------------------------------------------------------------------------
def install_permission_hook():
    from webview.platforms import edgechromium
    from Microsoft.Web.WebView2.Core import (
        CoreWebView2PermissionKind, CoreWebView2PermissionState)

    orig = edgechromium.EdgeChrome.on_webview_ready

    def patched(self, sender, args):
        orig(self, sender, args)
        if not args.IsSuccess:
            return

        def on_perm(s, a):
            log("★ PermissionRequested kind=%s" % a.PermissionKind)
            a.State = CoreWebView2PermissionState.Allow
            a.Handled = True

        sender.CoreWebView2.PermissionRequested += on_perm
    edgechromium.EdgeChrome.on_webview_ready = patched


# --------------------------------------------------------------------------
# js_api：分片接收
# --------------------------------------------------------------------------
class RecApi:
    def rec_chunk(self, rec_id, seq, b64):
        t = time.monotonic()
        if not isinstance(b64, str):
            log("分片 %s ★ 参数类型不是 str 而是 %s" % (seq, type(b64).__name__))
            return False
        if seq < 2:                                     # 只对头两片做诊断
            bad = {}
            for ch in b64:
                if ch not in ALPHABET:
                    bad[ch] = bad.get(ch, 0) + 1
            log("分片 %s 诊断: len=%d 头=%r 尾=%r" % (seq, len(b64), b64[:40], b64[-40:]))
            log("        非法字符: %s" % sorted((repr(k), v) for k, v in bad.items()))
            pos = b64.find("=")
            log("        第一个 '=' 出现在下标 %s（长度 %d）" % (pos, len(b64)))
        try:
            raw = base64.b64decode(b64)
        except Exception as e:                          # noqa: BLE001
            log("分片 %s 解码失败: %s" % (seq, e))
            return False
        with open(_part, "ab") as f:
            f.write(raw)
        _stats["chunks"] += 1
        _stats["bytes"] += len(raw)
        _stats["max_msg"] = max(_stats["max_msg"], len(b64))
        if _stats["t_first"] is None:
            _stats["t_first"] = t
        _stats["t_last"] = t
        return seq

    def rec_done(self, rec_id, total, mime):
        global _final
        ext = ".mp4" if "mp4" in mime else ".webm"
        _final = os.path.join(OUTDIR, "rec" + ext)
        log("rec_done 进入: _part=%r 存在=%s 大小=%s  pid=%d" %
            (_part, os.path.exists(_part),
             os.path.getsize(_part) if os.path.exists(_part) else -1,
             os.getpid()))
        log("  目录内容: %s" % [f for f in os.listdir(OUTDIR)])
        if os.path.exists(_final):
            os.remove(_final)
        os.replace(_part, _final)
        log("落盘完成 %s  size=%d (JS 报 %s) mime=%s" %
            (os.path.basename(_final), os.path.getsize(_final), total, mime))
        return {"path": _final, "size": os.path.getsize(_final)}


# --------------------------------------------------------------------------
def ffprobe_report(path):
    import media
    ff = media.find_ffmpeg()
    if not ff:
        log("找不到 ffmpeg，跳过 ffprobe")
        return
    probe = os.path.join(os.path.dirname(ff), "ffprobe.exe")
    if not os.path.isfile(probe):
        probe = shutil.which("ffprobe")
    if not probe:
        log("找不到 ffprobe")
        return
    import proc
    r = proc.run([probe, "-v", "error", "-show_format", "-show_streams",
                  "-of", "json", path], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        log("★ ffprobe 失败 rc=%s stderr=%s" % (r.returncode, (r.stderr or "")[:400]))
        return
    try:
        d = json.loads(r.stdout)
    except Exception as e:                              # noqa: BLE001
        log("ffprobe 输出解析失败: %s" % e)
        return
    fmt = d.get("format") or {}
    log("★ ffprobe 认了：format=%s duration=%s size=%s" %
        (fmt.get("format_name"), fmt.get("duration"), fmt.get("size")))
    for s in d.get("streams") or []:
        log("   stream %s: %s %sx%s rate=%s" %
            (s.get("index"), s.get("codec_name"), s.get("width"),
             s.get("height"), s.get("avg_frame_rate")))


def driver():
    import webview

    while not webview.windows:
        time.sleep(0.05)
    w = webview.windows[0]

    for _ in range(60):
        try:
            if w.evaluate_js("!!(window.__REC && window.__REC.stage==='ready')"):
                break
        except Exception:
            pass
        time.sleep(0.15)
    log("页面就绪")

    w.evaluate_js("window.__startRec(%s, %d)" % (json.dumps(MIME), SECONDS))
    log("已开始录制 %d 秒，mime=%r" % (SECONDS, MIME))

    snap = None
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            raw = w.evaluate_js("JSON.stringify(window.__REC)")
            snap = json.loads(raw) if raw else None
        except Exception:
            snap = None
        if snap and snap.get("stage") in ("verified", "playfail", "error"):
            break
        time.sleep(0.4)

    log("最终快照 = %s" % json.dumps(snap, ensure_ascii=False))
    log("分片统计: 次数=%d 总字节=%d 单条最大(base64)=%d" %
        (_stats["chunks"], _stats["bytes"], _stats["max_msg"]))
    if _stats["t_first"] and _stats["t_last"]:
        log("传输耗时 = %.2fs" % (_stats["t_last"] - _stats["t_first"]))
    if _final and os.path.isfile(_final):
        ffprobe_report(_final)
    time.sleep(0.3)
    os._exit(0)


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    if os.path.exists(_part):
        os.remove(_part)
    log("mime 请求 = %r" % MIME)
    install_permission_hook()

    import webview
    webview.create_window("rec probe", url=HTML, js_api=RecApi(),
                          width=560, height=420)
    threading.Thread(target=driver, daemon=True).start()
    try:
        webview.start(gui="edgechromium")
    except TypeError:
        webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
