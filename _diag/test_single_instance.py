# -*- coding: utf-8 -*-
"""单实例闸单测：**不建真窗口**，把每条分支都走一遍。

为什么能不起窗口还测得准：single_instance 里的四个外部动作
（找窗口 / 拉前台 / 拿互斥量 / 弹框）都换成了可替换的实现，
测试塞假件进去记录"被调了什么、按什么顺序"。

除了假件，还有一条**真的**：在同一个进程里连拿两次命名互斥量，
第二次必须报 exists —— 这条验的是 winapi 那层真能用。
"""

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
os.environ.pop("VKB_FAKE", None)

TMP = tempfile.mkdtemp(prefix="vkb_single_test_")
os.environ["VKB_NO_SINGLE_INSTANCE"] = "0"      # 先确保闸是开的

import winapi            # noqa: E402
import single_instance as si   # noqa: E402

ok = 0
bad = []


def chk(name, cond, extra=""):
    global ok
    if cond:
        ok += 1
        print("  PASS  %s" % name)
    else:
        bad.append(name)
        print("  FAIL  %s  %s" % (name, extra))


def fake_env(find_results, bring_result=True, mutex_exists=False):
    """装一套假件，返回记录调用的 calls 列表。"""
    calls = []
    seq = {"i": 0}

    def f_find(title, klass=None, timeout=0.0, poll=0.25):
        calls.append(("find", title, timeout))
        i = min(seq["i"], len(find_results) - 1)
        seq["i"] += 1
        return find_results[i]

    def f_bring(hwnd):
        calls.append(("bring", hwnd))
        return bring_result if callable(bring_result) else bring_result

    def f_mutex(name):
        calls.append(("mutex", name))
        return (12345, mutex_exists)

    def f_box(text, title="", warn=True):
        calls.append(("box", text))
        return 1

    si._find_window = f_find
    si._bring_to_front = f_bring
    si._acquire_mutex = f_mutex
    si._message_box = f_box
    si._reset_for_test()
    return calls


def restore():
    si._find_window = winapi.find_window
    si._bring_to_front = winapi.bring_to_front
    si._acquire_mutex = winapi.acquire_mutex
    si._message_box = winapi.message_box
    si._reset_for_test()


def main():
    print("=" * 60)
    print("py-single：单实例闸（不建真窗口）")

    # ---------------- 0. 跳过开关 ----------------
    os.environ[si.SKIP_ENV] = "1"
    chk("S0a 设了 VKB_NO_SINGLE_INSTANCE=1 就算跳过", si.skipped() is True)
    calls = fake_env([0])
    chk("S0b ★ 跳过时 acquire() 直接放行，不找窗口、不拿互斥量",
        si.acquire() is None and calls == [], calls)
    os.environ[si.SKIP_ENV] = "0"
    chk("S0c 设成 0 就是不跳过", si.skipped() is False)
    os.environ.pop(si.SKIP_ENV, None)
    chk("S0d 没设这个变量默认不跳过", si.skipped() is False)

    # ---------------- 1. ①号闸：窗口已存在（覆盖陈旧实例）----------------
    calls = fake_env([0x1234])                      # 找到窗口
    r = si.acquire()
    chk("S1a ★ 已有窗口 -> 返回 already", r == "already", r)
    chk("S1b ★ 已把那个窗口拉到前台", ("bring", 0x1234) in calls, calls)
    chk("S1c ★ 走①号闸就不碰互斥量（陈旧实例根本没有互斥量）",
        not any(c[0] == "mutex" for c in calls), calls)

    # 找到窗口但拉不动 -> 要给出"点任务栏"的指引，不能静默
    calls = fake_env([0x1234], bring_result=False)
    r = si.acquire()
    chk("S1d ★ 找到窗口但拉不动 -> 明确提示（不静默退出）",
        r not in (None, "already") and "任务栏" in r, r)

    # ---------------- 2. ②号闸：互斥量被占（覆盖并发启动）----------------
    # 2a. 互斥量在，稍后窗口出来了 -> 拉前台
    calls = fake_env([0, 0x5678], mutex_exists=True)
    r = si.acquire()
    chk("S2a ★ 互斥量被占 + 窗口稍后出现 -> 拉前台", r == "already", r)
    chk("S2b 是**轮询**等的窗口（带了 timeout）",
        any(c[0] == "find" and c[2] and c[2] > 0 for c in calls), calls)

    # 2c. 互斥量在，窗口一直没有 -> 弹框给指引
    calls = fake_env([0, 0], mutex_exists=True)
    r = si.acquire()
    chk("S2c ★ 互斥量在但窗口找不到 -> 返回 no-window", r == "no-window", r)
    box = [c for c in calls if c[0] == "box"]
    chk("S2d ★ 弹了提示框（pythonw 没控制台，不弹等于没提示）", len(box) == 1, calls)
    if box:
        txt = box[0][1]
        chk("S2e ★ 提示里说清了去任务管理器", "任务管理器" in txt, txt[:60])
        chk("S2f ★ 提示里教了怎么区分（看命令行认 app_web.py）",
            "命令行" in txt and "app_web.py" in txt, txt[:120])
        chk("S2g ★ 提示里点了名「多个程序共用一个进程名」这个坑",
            "pythonw" in txt or "python" in txt, txt[:120])
    else:
        for n in ("S2e ★ 提示里说清了去任务管理器",
                  "S2f ★ 提示里教了怎么区分（看命令行认 app_web.py）",
                  "S2g ★ 提示里点了名「多个程序共用一个进程名」这个坑"):
            chk(n, False, "上一条已失败")

    # ---------------- 3. 正常放行 ----------------
    calls = fake_env([0], mutex_exists=False)
    r = si.acquire()
    chk("S3a ★ 没窗口 + 互斥量是新的 -> 放行（返回 None）", r is None, r)
    chk("S3b 拿过互斥量", any(c[0] == "mutex" for c in calls), calls)
    chk("S3c held() 为真（句柄要一直持有，否则闸失效）", si.held() is True)

    # ---------------- 4. 真互斥量（不走假件）----------------
    restore()
    h1, e1 = winapi.acquire_mutex(r"Local\VKB_SelfTest_Mutex_%d" % os.getpid())
    h2, e2 = winapi.acquire_mutex(r"Local\VKB_SelfTest_Mutex_%d" % os.getpid())
    chk("S4a ★ 真命名互斥量：第一次是新的", h1 and e1 is False, (h1, e1))
    chk("S4b ★ 真命名互斥量：同进程再拿一次会报 exists", h2 and e2 is True,
        (h2, e2))

    # ---------------- 5. winapi 的边界 ----------------
    chk("S5a 找不存在的标题返回 0", winapi.find_window("绝不可能存在的窗口标题_12345") == 0)
    chk("S5b 数不存在的标题返回 0", winapi.count_windows("绝不可能存在的窗口标题_12345") == 0)
    chk("S5c 对 hwnd=0 拉前台返回 False（不崩）",
        winapi.bring_to_front(0) is False)
    chk("S5d 对自己窗口标题能数出个数（0 或多个都合理）",
        isinstance(winapi.count_windows(si.APP_TITLE), int))

    print("-" * 60)
    print("py-single 合计 %d 通过 / %d 失败" % (ok, len(bad)))
    for x in bad:
        print("   失败: %s" % x)
    return 1 if bad else 0


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        restore()
        os.environ.pop(si.SKIP_ENV, None)
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
