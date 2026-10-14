# -*- coding: utf-8 -*-
r"""相机已在运行时点按钮能不能拉到前台（验收 3）。

    venv\Scripts\python.exe _diag\e2e_camera_focus.pyw

不驱动界面，直接走**产品代码的那条分支**：
  1. 起相机应用
  2. 把焦点抢到别处（模拟"相机被别的窗口盖住 / 最小化"）
  3. 调 camera_app.launch() —— 它会走 app_running() 为真的 already 分支
  4. 断言 GetForegroundWindow() == 相机窗口

**故意从一个后台脚本调**：这样比"用户点按钮"更难（用户点按钮时我们是前台
进程，有天然权限；后台脚本没有）。难的那条能成，容易的那条必然能成。

结果写 _diag\e2e_camera_focus_results.txt。
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
OUT = os.path.join(DIAG, "e2e_camera_focus_results.txt")
os.environ["VKB_NO_SINGLE_INSTANCE"] = "1"
os.environ.pop("VKB_FAKE", None)
T0 = time.monotonic()

sys.path.insert(0, os.path.join(ROOT, "src"))
import proc         # noqa: E402
import winapi       # noqa: E402
import camera_app   # noqa: E402

R = []


def log(m):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("t=%7.2f  %s\n" % (time.monotonic() - T0, m))


def chk(name, cond, extra=""):
    R.append({"name": name, "pass": bool(cond), "extra": str(extra)})
    log("%s  %-52s %s" % ("PASS" if cond else "FAIL", name, extra))


def kill_camera():
    """只杀相机应用（精确进程名，不是我们的目标程序）。"""
    proc.run(["taskkill", "/F", "/IM", "WindowsCamera.exe"],
             capture_output=True, timeout=30)
    time.sleep(2.0)


def main():
    if os.path.exists(OUT):
        os.remove(OUT)
    log("相机窗口标题候选 = %s" % (camera_app.CAMERA_TITLES,))

    kill_camera()

    # ---------------- 1. 起相机 ----------------
    res = camera_app.launch(timeout=15)
    log("首次 launch = %s" % res)
    chk("F1a ★ 相机应用起来了（走第 1 级）", res.get("ok") is True, res)
    chk("F1b 首次是 uri 方式", res.get("how") == "uri", res.get("how"))

    hwnd = camera_app.camera_window()
    log("相机窗口 hwnd = %s" % hwnd)
    chk("F2a ★ 能用「ApplicationFrameWindow + 标题」找到相机窗口", hwnd != 0, hwnd)

    # ---------------- 2. 把焦点抢走 ----------------
    try:
        shell = winapi.u32.GetShellWindow()
        winapi.u32.SetForegroundWindow(shell)
    except Exception as e:                              # noqa: BLE001
        log("抢焦点异常: %s" % e)
    time.sleep(0.8)
    fg = winapi.foreground()
    log("抢走之后前台 = %s（相机 = %s）" % (fg, hwnd))
    chk("F3a 焦点确实不在相机上了（前提成立才有意义）", fg != hwnd,
        "前台=%s 相机=%s" % (fg, hwnd))

    # ---------------- 3. 最小化它，模拟"在后台" ----------------
    try:
        winapi.u32.ShowWindow(hwnd, 6)                  # SW_MINIMIZE
        time.sleep(0.6)
    except Exception:                                   # noqa: BLE001
        pass
    log("已把相机窗口最小化，IsIconic=%s" % winapi.is_minimized(hwnd))

    # ---------------- 4. 走产品代码的 already 分支 ----------------
    t0 = time.monotonic()
    res2 = camera_app.launch(timeout=15)
    dt = time.monotonic() - t0
    log("第二次 launch = %s（耗时 %.2fs）" % (res2, dt))
    chk("F4a ★ 已经运行时走的是 already 分支", res2.get("how") == "already",
        res2.get("how"))
    chk("F4b ★ 报告拉前台成功（frontOk=True）", res2.get("frontOk") is True,
        res2.get("frontOk"))

    # ---------------- 5. 核实 ----------------
    time.sleep(0.4)
    fg2 = winapi.foreground()
    log("拉之后前台 = %s" % fg2)
    chk("F5a ★★ 相机窗口真的成了前台窗口", fg2 == hwnd,
        "前台=%s 相机=%s" % (fg2, hwnd))
    chk("F5b 从最小化恢复了（不再 IsIconic）", not winapi.is_minimized(hwnd),
        winapi.is_minimized(hwnd))

    # 时间线里要留下记录
    tl = camera_app.timeline()
    log("camera_app 时间线：")
    for row in tl:
        log("  +%7.3fs  %s" % (row["t"], row["msg"]))
    chk("F6a ★ 时间线里记了「已在运行 / 拉前台」这一笔",
        any("已在运行" in r["msg"] for r in tl), [r["msg"] for r in tl][-3:])

    kill_camera()
    log("---- 结果 ----")
    npass = sum(1 for x in R if x["pass"])
    log("合计 %d 通过 / %d 失败 / 共 %d" % (npass, len(R) - npass, len(R)))
    for x in R:
        if not x["pass"]:
            log("   失败: %s  %s" % (x["name"], x["extra"]))
    print(open(OUT, encoding="utf-8").read())
    return 0 if npass == len(R) else 1


if __name__ == "__main__":
    sys.exit(main())
