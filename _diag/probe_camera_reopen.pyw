# -*- coding: utf-8 -*-
r"""复现「打开 → 关闭 → 再打开」失败，拿日志定位断在哪一步。

    venv\Scripts\python.exe _diag\probe_camera_reopen.pyw

监控三样东西：
  1. **桥调用序列**（包一层 VKB.call 记下来）—— 看第二次点按钮到底有没有发请求
  2. **监视状态**（active / stage / note）—— 看旧的监视有没有退出
  3. **相机进程**（按命令行核实过的精确 PID）—— 看相机到底有没有起来

结果写 _diag\camera_reopen.txt。

**只查证，不改代码。**
"""

import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
OUT = os.path.join(DIAG, "camera_reopen.txt")
os.environ["VKB_NO_SINGLE_INSTANCE"] = "1"
os.environ.pop("VKB_FAKE", None)
T0 = time.monotonic()

sys.path.insert(0, os.path.join(ROOT, "src"))
import proc         # noqa: E402
import camera_app   # noqa: E402


def log(m):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("t=%7.2f  %s\n" % (time.monotonic() - T0, m))


def camera_pids():
    """按**进程名 + 命令行**核实过的相机进程 PID（不按名字盲杀）。"""
    return camera_app._pids_of(camera_app.CAMERA_EXE)


def close_camera():
    """关掉相机应用。**精确 PID**，且先核实映像名。"""
    pids = camera_pids()
    log("   关闭相机，候选 PID = %s" % pids)
    for pid in pids:
        # 再核实一次身份：映像名必须是 WindowsCamera.exe 才动手
        try:
            p = proc.run(["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"],
                         capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=20)
            line = (p.stdout or "").strip()
            if camera_app.CAMERA_EXE.lower() not in line.lower():
                log("   ★ PID %d 不是相机（%s），跳过" % (pid, line[:60]))
                continue
        except Exception as e:                          # noqa: BLE001
            log("   核实 PID %d 失败: %s，跳过" % (pid, e))
            continue
        proc.run(["taskkill", "/F", "/PID", str(pid)],
                 capture_output=True, timeout=20)
        log("   已关 PID %d" % pid)
    time.sleep(1.5)


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

    # 包一层记录桥调用
    js("""
    window.__calls = [];
    if (!window.__wrapped) {
      var orig = window.VKB.call;
      window.VKB.call = function (m) {
        window.__calls.push(m);
        return orig.apply(window.VKB, arguments);
      };
      window.__wrapped = true;
    }
    """)

    def calls():
        try:
            return json.loads(js("JSON.stringify(window.__calls||[])") or "[]")
        except Exception:
            return []

    def cam():
        try:
            return json.loads(js("JSON.stringify((VKBProcess.state()||{}).camera||{})")
                              or "{}")
        except Exception:
            return {}

    def camjs():
        try:
            return json.loads(js("JSON.stringify(window.VKBCamera.state())") or "{}")
        except Exception:
            return {}

    def click():
        js("(function(){var b=document.querySelector('#procCamera');if(b)b.click();})()")

    def wait_cam(sec):
        t0 = time.monotonic()
        while time.monotonic() - t0 < sec:
            if camera_pids():
                return time.monotonic() - t0
            time.sleep(0.3)
        return None

    close_camera()

    # ================= 第 1 次 =================
    log("")
    log("========== 第 1 次点「打开摄像头」==========")
    before = len(calls())
    t_click = time.monotonic()
    click()
    dt = wait_cam(20)
    time.sleep(1.5)
    log("  相机起来耗时 = %s" % ("%.2fs" % dt if dt else "★ 没起来"))
    log("  这期间新增桥调用 = %s" % calls()[before:])
    log("  VKBCamera.state = %s" % json.dumps(camjs(), ensure_ascii=False)[:260])
    log("  watch 状态 = %s" % json.dumps(
        {k: cam().get(k) for k in ("active", "stage", "note", "error")},
        ensure_ascii=False))

    # ================= 关闭相机 =================
    log("")
    log("========== 关闭相机应用 ==========")
    close_camera()
    for i in range(4):                       # 观察监视怎么反应
        time.sleep(1.0)
        c = cam()
        log("  +%ds  watch: active=%s stage=%s note=%s"
            % (i + 1, c.get("active"), c.get("stage"), (c.get("note") or "")[:40]))

    # ---- 第二层验证：绕过前端闩锁，直接问后端「现在能不能再开一次」----
    log("")
    log("---- 绕过前端，直接调桥 open_camera_app ----")
    # evaluate_js 不能 await promise，所以把结果落到全局变量上，下一轮再读
    js("window.__lastOpen = 'pending';"
       "window.VKB.call('open_camera_app')"
       ".then(function(x){ window.__lastOpen = JSON.stringify(x); })"
       ".catch(function(e){ window.__lastOpen = 'ERR ' + e.message; });")
    time.sleep(3.0)
    log("  ★ 后端直接返回 = %s" % js("window.__lastOpen"))
    log("  调用后 watch 状态 = %s" % json.dumps(
        {k: cam().get(k) for k in ("active", "stage", "note", "error")},
        ensure_ascii=False))
    log("  调用后相机进程 = %s" % camera_pids())

    # ================= 第 2 次 =================
    log("")
    log("========== 第 2 次点「打开摄像头」（紧接着）==========")
    before2 = len(calls())
    t2 = time.monotonic()
    click()
    dt2 = wait_cam(20)
    log("  相机起来耗时 = %s" % ("%.2fs" % dt2 if dt2 else "★★★ 打不开了"))
    log("  ★ 这期间新增桥调用 = %s" % calls()[before2:])
    time.sleep(1.0)
    log("  VKBCamera.state = %s" % json.dumps(camjs(), ensure_ascii=False)[:260])
    log("  watch 状态 = %s" % json.dumps(
        {k: cam().get(k) for k in ("active", "stage", "note", "error")},
        ensure_ascii=False))
    log("  #camStatus 文案 = %s" % js("document.querySelector('#camStatus').textContent"))
    log("  #camError  = %s / 显示=%s"
        % (js("document.querySelector('#camError').textContent"),
           js("!document.querySelector('#camError').classList.contains('hidden')")))

    # ================= 诊断 =================
    log("")
    log("========== 诊断 ==========")
    allcalls = calls()
    log("  桥调用总序列 = %s" % allcalls)
    log("  open_camera_app 被调了几次 = %d" % allcalls.count("open_camera_app"))
    log("  第 2 次点按钮有没有发 open_camera_app = %s"
        % ("是" if "open_camera_app" in allcalls[before2:] else "★ 没有（前端就没发）"))
    tl = (cam() or {}).get("timeline") or []
    log("  camera_app 时间线：")
    for row in tl:
        log("    +%7.3fs  %s" % (row["t"], row["msg"]))

    log("")
    log("监控结束")
    time.sleep(0.5)
    os._exit(0)


def main():
    f = open(os.path.join(DIAG, "camera_reopen_stderr.txt"), "w",
             encoding="utf-8", buffering=1)
    sys.stdout = f
    sys.stderr = f
    if os.path.exists(OUT):
        os.remove(OUT)

    import app_web
    threading.Thread(target=driver, daemon=True).start()
    try:
        app_web.main()
    finally:
        pass


if __name__ == "__main__":
    main()
