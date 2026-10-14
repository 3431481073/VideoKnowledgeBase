# -*- coding: utf-8 -*-
"""查证：点「打开摄像头」到底动了什么、卡在哪、dshow 有没有被触发。

做法：**全进程生死监控** + 分级时间线。
  - 每 200ms 扫一遍所有进程，记录新增/消失（带进程名），形成时间线
  - 同时盯 ffmpeg.exe（dshow 降级的指纹）和 WindowsCamera.exe
  - 点按钮走真实链路，读 camera_app 的内部时间线（哪一级成功、各耗时）

结果写 _diag/camera_sidefx.txt。

**只查证，不改任何东西。** 不杀别人的进程，只记录。
"""

import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
OUT = os.path.join(DIAG, "camera_sidefx.txt")
os.environ.pop("VKB_FAKE", None)
os.environ["VKB_NO_SINGLE_INSTANCE"] = "1"   # e2e/探针要起真界面，跳过单实例闸
T0 = time.monotonic()
WATCH_SEC = 70

sys.path.insert(0, os.path.join(ROOT, "src"))
import proc  # noqa: E402

_loglock = threading.Lock()


def log(m):
    with _loglock:
        with open(OUT, "a", encoding="utf-8") as f:
            f.write("t=%7.3f  %s\n" % (time.monotonic() - T0, m))


# --------------------------------------------------------------------------
# 进程快照（用 tasklist，一次拿全，比 Get-Process 稳）
# --------------------------------------------------------------------------
def procs():
    try:
        r = proc.run(["tasklist", "/FO", "CSV", "/NH"],
                     capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=30)
    except Exception as e:                              # noqa: BLE001
        log("tasklist 失败: %s" % e)
        return {}
    out = {}
    for line in (r.stdout or "").splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) < 2:
            continue
        name, pid = parts[0].strip('"'), parts[1]
        try:
            out[int(pid)] = name
        except ValueError:
            continue
    return out


WATCH_NAMES = ("ffmpeg", "ffprobe", "WindowsCamera", "powershell", "explorer",
               "python", "pythonw", "audiodg", "tasklist")


def interesting(name):
    return any(w.lower() in (name or "").lower() for w in WATCH_NAMES)


def watcher(stop):
    prev = procs()
    log("起始进程数 = %d" % len(prev))
    while not stop.is_set():
        time.sleep(0.2)
        cur = procs()
        for pid, name in cur.items():
            if pid not in prev:
                if interesting(name):
                    log("  ＋进程 %-22s pid=%s" % (name, pid))
                    if name.lower().startswith("ffmpeg"):
                        log("     ★★★ 出现 ffmpeg —— dshow 降级的指纹！")
        for pid, name in prev.items():
            if pid not in cur:
                if interesting(name):
                    log("  －进程 %-22s pid=%s  【消失】" % (name, pid))
        prev = cur


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
    log("界面就绪")
    time.sleep(1.0)

    def js(code):
        try:
            return w.evaluate_js(code)
        except Exception as e:
            log("JS 失败: %s" % e)
            return None

    def cam_js():
        try:
            return json.loads(js("JSON.stringify((VKBProcess.state()||{}).camera||{})")
                              or "{}")
        except Exception:
            return {}

    # ---------------- 点之前 ----------------
    log("")
    log("===== 点「打开摄像头」之前 =====")
    t_click = time.monotonic()
    js("VKBProcess.open()")
    time.sleep(0.5)
    js("(function(){var b=document.querySelector('#procCamera');if(b)b.click();})()")
    log("已点 #procCamera")

    # ---------------- 盯着看 ----------------
    seen_ffmpeg = False
    t_cam_up = None
    t_done = None
    deadline = time.time() + WATCH_SEC
    while time.time() < deadline:
        cur = procs()
        if any(n.lower().startswith("ffmpeg") for n in cur.values()):
            seen_ffmpeg = True
        if t_cam_up is None and any(n == "WindowsCamera.exe" for n in cur.values()):
            t_cam_up = time.monotonic()
            log("相机进程出现，距点击 %.2fs" % (t_cam_up - t_click))
        cs = cam_js()
        if not cs.get("active") and cs.get("stage") not in (None, "idle", "launching"):
            t_done = time.monotonic()
            break
        time.sleep(0.3)

    log("")
    log("===== 结果 =====")
    log("点按钮 -> 相机进程出现: %s"
        % ("%.2fs" % (t_cam_up - t_click) if t_cam_up else "★ 没出现"))
    log("ffmpeg 全程出现过吗: %s" % ("是 ★★★ dshow 被触发了" if seen_ffmpeg
                                    else "没有 —— dshow 没被触发"))
    log("监视状态: %s" % json.dumps(cam_js(), ensure_ascii=False)[:300])

    # ---------------- 内部时间线 ----------------
    log("")
    log("===== camera_app 内部时间线（从进程启动算）=====")
    tl = (cam_js() or {}).get("timeline") or []
    if tl:
        for row in tl:
            log("  +%7.3fs  %s" % (row["t"], row["msg"]))
    else:
        log("  ★ 界面里没有时间线数据 —— 说明 open_camera_app 根本没被调到")

    log("")
    log("监控结束，共 %.1fs" % (time.monotonic() - T0))
    time.sleep(0.5)
    os._exit(0)


def main():
    f = open(os.path.join(DIAG, "camera_sidefx_stderr.txt"), "w",
             encoding="utf-8", buffering=1)
    sys.stdout = f
    sys.stderr = f
    if os.path.exists(OUT):
        os.remove(OUT)

    stop = threading.Event()
    threading.Thread(target=watcher, args=(stop,), daemon=True).start()
    threading.Thread(target=driver, daemon=True).start()

    import app_web
    try:
        app_web.main()
    finally:
        stop.set()


if __name__ == "__main__":
    main()
