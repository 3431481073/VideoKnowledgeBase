# -*- coding: utf-8 -*-
r"""摄像头连续打开 3 次（验收 2、3）。

    venv\Scripts\python.exe _diag\e2e_camera_reopen.pyw

复现用户报的场景并断言修好了：
    点「打开摄像头」-> 相机起来 -> 关掉它 -> **紧接着再点** -> 应当又起来
    连做 3 轮。

为什么"紧接着"很关键：老代码里两道闩锁都只在**紧接着**重开时才暴露 ——
  · 前端 `C.launched` 置 true 后不再发请求
  · 后端旧监视在相机关闭后还要等 60s 宽限，这期间一律回「已经在等录制了」

结果写 _diag\e2e_camera_reopen_results.txt。
"""

import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
OUT = os.path.join(DIAG, "e2e_camera_reopen_results.txt")
os.environ["VKB_NO_SINGLE_INSTANCE"] = "1"
os.environ.pop("VKB_FAKE", None)
T0 = time.monotonic()
ROUNDS = 3

sys.path.insert(0, os.path.join(ROOT, "src"))
import proc         # noqa: E402
import camera_app   # noqa: E402

R = []


def log(m):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("t=%7.2f  %s\n" % (time.monotonic() - T0, m))


def chk(name, cond, extra=""):
    R.append({"name": name, "pass": bool(cond), "extra": str(extra)})
    log("%s  %-50s %s" % ("PASS" if cond else "FAIL", name, extra))


def camera_pids():
    return camera_app._pids_of(camera_app.CAMERA_EXE)


def close_camera():
    """关相机。**精确 PID + 先核实映像名**（不按名字盲杀）。"""
    for pid in camera_pids():
        try:
            p = proc.run(["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"],
                         capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=20)
            if camera_app.CAMERA_EXE.lower() not in (p.stdout or "").lower():
                log("   PID %d 不是相机，跳过" % pid)
                continue
        except Exception as e:                          # noqa: BLE001
            log("   核实 PID %d 失败: %s，跳过" % (pid, e))
            continue
        proc.run(["taskkill", "/F", "/PID", str(pid)],
                 capture_output=True, timeout=20)
        log("   已关相机 PID %d" % pid)
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

    # 记录桥调用（看第 N 次点击到底有没有发请求）
    js("window.__calls=[];if(!window.__w){var o=window.VKB.call;"
       "window.VKB.call=function(m){window.__calls.push(m);"
       "return o.apply(window.VKB,arguments)};window.__w=1;}")

    def calls():
        try:
            return json.loads(js("JSON.stringify(window.__calls||[])") or "[]")
        except Exception:
            return []

    def click():
        js("(function(){var b=document.querySelector('#procCamera');if(b)b.click();})()")

    def wait_cam(sec):
        t0 = time.monotonic()
        while time.monotonic() - t0 < sec:
            if camera_pids():
                return time.monotonic() - t0
            time.sleep(0.25)
        return None

    chk("R0a ★ 界面上没有中间浮层（DOM 里不存在 #camOverlay）",
        js("!document.querySelector('#camOverlay')") is True)
    chk("R0b ★ 「取消等待」按钮已经删掉（DOM 里不存在）",
        js("!document.querySelector('#camCancel')") is True)

    close_camera()

    for i in range(1, ROUNDS + 1):
        log("")
        log("========== 第 %d 轮：点「打开摄像头」==========" % i)
        n0 = len(calls())
        t = time.monotonic()
        click()
        dt = wait_cam(25)
        used = time.monotonic() - t
        new = calls()[n0:]
        log("  新增桥调用 = %s" % new)
        log("  相机起来耗时 = %s" % ("%.2fs" % dt if dt else "★ 没起来"))

        chk("R%da ★ 第 %d 次点击发出了 open_camera_app" % (i, i),
            "open_camera_app" in new, new[:5])
        chk("R%db ★★ 第 %d 次相机真的起来了" % (i, i), dt is not None,
            "%.2fs" % used if dt else "25 秒内没等到相机进程")
        chk("R%dc 相机起来够快（< 8 秒）" % i, dt is not None and dt < 8,
            "%.2fs" % dt if dt else None)

        # 确认相机窗口真的出来了（进程在 ≠ 窗口在）
        hwnd = 0
        t2 = time.monotonic()
        while time.monotonic() - t2 < 8:
            hwnd = camera_app.camera_window()
            if hwnd:
                break
            time.sleep(0.3)
        chk("R%dd ★ 相机窗口出现了（不只是进程）" % i, hwnd != 0, hwnd)

        if i < ROUNDS:
            log("  ---- 关掉相机，紧接着准备下一轮 ----")
            close_camera()
            log("  关闭后相机进程 = %s（应当为空）" % camera_pids())
            chk("R%de 关闭后相机进程确实没了" % i, not camera_pids())

    # 这里**不**断言"只有一个程序窗口"：本 e2e 按设计设了
    # VKB_NO_SINGLE_INSTANCE=1（否则你自己开着程序时它根本起不来），
    # 闸被跳过时这个断言必然不成立 —— 那是断言写错了，不是产品错了。
    # 单实例闸由 _diag\e2e_single.pyw 专门验（那边闸是开的，断言窗口数==1）。

    # 时间线里每次 launch 都该有记录
    tl = camera_app.timeline()
    log("")
    log("camera_app 时间线：")
    for row in tl:
        log("  +%7.3fs  %s" % (row["t"], row["msg"]))
    n_launch = sum(1 for r in tl if "launch() 开始" in r["msg"])
    chk("R9b ★ 时间线里记录到 3 次 launch（每次都真调了）", n_launch >= ROUNDS,
        n_launch)

    close_camera()
    log("")
    log("---- 结果 ----")
    npass = sum(1 for x in R if x["pass"])
    log("合计 %d 通过 / %d 失败 / 共 %d" % (npass, len(R) - npass, len(R)))
    for x in R:
        if not x["pass"]:
            log("   失败: %s  %s" % (x["name"], x["extra"]))
    time.sleep(0.3)
    os._exit(0)


def main():
    f = open(os.path.join(DIAG, "e2e_camera_reopen_stderr.txt"), "w",
             encoding="utf-8", buffering=1)
    sys.stdout = f
    sys.stderr = f
    if os.path.exists(OUT):
        os.remove(OUT)

    import app_web
    threading.Thread(target=driver, daemon=True).start()
    try:
        app_web.main()
    except Exception:                                   # noqa: BLE001
        import traceback
        log("主循环异常：%s" % traceback.format_exc())


if __name__ == "__main__":
    main()
