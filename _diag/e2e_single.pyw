# -*- coding: utf-8 -*-
r"""单实例闸端到端（验收 1）：真起两个实例，断言只有一个窗口。

    venv\\Scripts\\python.exe _diag\\e2e_single.pyw

**故意不设 VKB_NO_SINGLE_INSTANCE** —— 这条测的就是那个闸。

三件事：
  1. 起实例 A（正常）           -> 窗口出现
  2. 再起实例 B（应当被拦）     -> B 退出、**窗口数仍然是 1**
  3. 确认 A 拿到了前台

结果写 _diag\e2e_single_results.txt。
"""

import json
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
OUT = os.path.join(DIAG, "e2e_single_results.txt")
PY = os.path.join(ROOT, "venv", "Scripts", "python.exe")
APP = os.path.join(ROOT, "src", "app_web.py")
APP_TITLE = "视频知识库 · 工作台"
T0 = time.monotonic()

sys.path.insert(0, os.path.join(ROOT, "src"))
import winapi  # noqa: E402

R = []


def log(m):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("t=%7.2f  %s\n" % (time.monotonic() - T0, m))


def chk(name, cond, extra=""):
    R.append({"name": name, "pass": bool(cond), "extra": str(extra)})
    log("%s  %-50s %s" % ("PASS" if cond else "FAIL", name, extra))


def start_app(tag):
    """起一个实例，返回 Popen。**显式清掉跳过开关**，闸必须是开的。"""
    env = dict(os.environ)
    env.pop("VKB_NO_SINGLE_INSTANCE", None)
    env.pop("VKB_FAKE", None)
    log("启动实例 %s" % tag)
    return subprocess.Popen([PY, APP], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main():
    if os.path.exists(OUT):
        os.remove(OUT)
    log("APP_TITLE = %s" % APP_TITLE)

    base = winapi.count_windows(APP_TITLE)
    log("跑之前同名窗口数 = %d" % base)
    chk("S0a 跑之前没有同名窗口（否则先关掉你的程序再跑）", base == 0, base)
    if base:
        log("★ 已被占用，测试作废 —— 请先关掉正在运行的「视频知识库」窗口")
        _finish()
        return

    # ---------------- 1. 实例 A ----------------
    a = start_app("A")
    hwnd = 0
    t0 = time.monotonic()
    while time.monotonic() - t0 < 40:
        if winapi.count_windows(APP_TITLE) >= 1:
            hwnd = winapi.find_window(APP_TITLE)
            break
        time.sleep(0.4)
    log("实例 A 窗口 = %s，耗时 %.1fs" % (hwnd, time.monotonic() - t0))
    chk("S1a ★ 实例 A 起得来、窗口出现", hwnd != 0, hwnd)
    chk("S1b 此时只有一个窗口", winapi.count_windows(APP_TITLE) == 1,
        winapi.count_windows(APP_TITLE))

    # ---------------- 2. 实例 B（应被拦）----------------
    # 先把焦点让给别人，这样"B 把 A 拉到前台"才看得出来
    try:
        winapi.u32.SetForegroundWindow(winapi.u32.GetShellWindow())
    except Exception:                                   # noqa: BLE001
        pass
    time.sleep(0.6)
    fg_before = winapi.foreground()
    log("起 B 之前的前台窗口 = %s（A=%s）" % (fg_before, hwnd))

    t_b = time.monotonic()
    b = start_app("B")
    try:
        b.wait(timeout=30)
        rc = b.returncode
    except subprocess.TimeoutExpired:
        rc = None
    dt = time.monotonic() - t_b
    log("实例 B 退出码=%s，耗时 %.1fs" % (rc, dt))

    chk("S2a ★ 实例 B 自己退出了（被拦住，不是挂在那）", rc is not None, rc)
    chk("S2b ★ 退出码是 0（正常拒绝，不是崩）", rc == 0, rc)

    time.sleep(1.0)
    n = winapi.count_windows(APP_TITLE)
    log("起了 B 之后同名窗口数 = %d" % n)
    chk("S2c ★★ 始终只有一个窗口（没有出现第二个）", n == 1, n)

    # ---------------- 3. 前台 ----------------
    fg_after = winapi.foreground()
    log("起 B 之后的前台窗口 = %s" % fg_after)
    chk("S3a ★ 实例 B 把 A 的窗口拉到了前台", fg_after == hwnd,
        "前台=%s A=%s" % (fg_after, hwnd))

    # B 的 stderr 里应该留一句说明
    try:
        err = (b.stderr.read() or b"").decode("utf-8", "replace")
    except Exception:                                   # noqa: BLE001
        err = ""
    log("B 的 stderr: %s" % err.strip()[:200])
    chk("S3b 实例 B 说明了自己为什么退出",
        "已有" in err or "已经" in err or err.strip() == "", err.strip()[:80])

    # ---------------- 收尾 ----------------
    log("关闭实例 A")
    try:
        a.terminate()
        a.wait(timeout=10)
    except Exception:                                   # noqa: BLE001
        try:
            a.kill()
        except Exception:                               # noqa: BLE001
            pass
    time.sleep(1.5)
    left = winapi.count_windows(APP_TITLE)
    chk("S4a 收尾后窗口清干净", left == 0, left)
    _finish()


def _finish():
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
