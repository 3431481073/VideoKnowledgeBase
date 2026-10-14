# -*- coding: utf-8 -*-
"""临时探针：把相机监视主循环那一天的时间线打出来。

为什么需要它：K4v 那条（"进程退出后文件才出现，不许被重开宽限截胡"）**失败了**，
而我推的时间线说是 i=41 撞在一起 —— 说明我推的轮次不对。不许猜根因，
把每轮的 el / 有没有文件 / exit_seen 打出来看。
"""

import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import camera_app  # noqa: E402

D1 = "__d1__"
SCRIPT = [[]] * 40 + [["A.mp4"]] * 80
RUNNING = [True, True, False] + [False] * 200

idx = {"i": 0}
nrun = {"n": 0}
rows = []


def fake_snapshot():
    i = min(idx["i"], len(SCRIPT) - 1)
    files = SCRIPT[i]
    return {D1: {n: (5000, 1.0) for n in files}}


def fake_running():
    r = RUNNING[min(nrun["n"], len(RUNNING) - 1)]
    nrun["n"] += 1
    return r


camera_app.POLL_SEC = 0.05
camera_app.QUIET_SEC = 99.0
camera_app.REOPEN_GRACE_SEC = 5.0
camera_app.EXIT_STABLE_TICKS = 4
camera_app.STABLE_TICKS = 2

orig_s, orig_r = camera_app.snapshot, camera_app.app_running
camera_app.snapshot = fake_snapshot
camera_app.app_running = fake_running

# 每轮把想要的状态抄一份出来（主循环自己写 self.state，不动它，
# 另起一个钩子：包住 _set）
_orig_set = camera_app.Watch._set


def spy_set(self, **kw):
    _orig_set(self, **kw)


box = {}

try:
    w = camera_app.Watch(on_done=lambda r: box.update(r), timeout=20.0)
    w.before = {D1: {}}
    w.state["dirs"] = [D1]
    w.state["active"] = True

    # 包一层 snapshot，把每轮的轮号 + 文件名记下来
    def counting_snapshot():
        cur = fake_snapshot()
        names = sorted(cur[D1].keys())
        rows.append((idx["i"], names))
        idx["i"] += 1
        return cur

    camera_app.snapshot = counting_snapshot

    t = threading.Thread(target=w._loop, daemon=True)
    t.start()
    t.join(25)
finally:
    camera_app.snapshot = orig_s
    camera_app.app_running = orig_r

print("主循环轮次 = %d 次" % len(rows))
print("文件首次出现的轮号：", end="")
first = None
for i, names in rows:
    if names:
        first = i
        break
print(first if first is not None else "从未出现")
print("")
print("轮号   有没有文件")
for i, names in rows:
    if i >= 30:
        print("%4d   %s" % (i, ",".join(names) or "-"))
print("")
print("结果：", box)
