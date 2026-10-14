# -*- coding: utf-8 -*-
"""启动耗时打点。**默认完全关闭**：只有设了 VKB_TIMING=1 才写日志。

为什么要有：用户反馈"打包版打开时加载数据很慢"，但"慢"必须落到**每一步几毫秒**
上才能改。本模块就是那把尺子。

用：
    set VKB_TIMING=1
    VideoKnowledgeBase.exe          （或 venv\\Scripts\\python.exe src\\app_web.py）

日志：<app_root>\\data\\logs\\startup_timing.log
     每行 = t=进程内相对秒数 · wall=绝对时间戳（用来跟外部记录的拉起时刻对齐）
     · 事件名 · 附带的键值

关闭时：`mark()` 直接 return，`span` 不取时间 —— 只有一次 os.environ 查询的开销。
"""

import os
import sys
import time

#: 开关。读到就固定，运行期不再查环境变量。
ON = os.environ.get("VKB_TIMING", "").strip() == "1"

_T0 = time.perf_counter()


def _root():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log_path():
    return os.path.join(_root(), "data", "logs", "startup_timing.log")


def mark(name, **extra):
    """记一条。关闭时什么都不做。"""
    if not ON:
        return
    try:
        p = log_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        line = "t=%8.3f  wall=%.3f  pid=%d  %s" % (
            time.perf_counter() - _T0, time.time(), os.getpid(), name)
        for k, v in extra.items():
            line += "  %s=%s" % (k, v)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:                                     # noqa: BLE001
        pass                    # 打点绝不许把程序搞崩


class span:
    """with timing.span("WebState 构建") as s: ... —— 退出时记一条带耗时的行。

    slow_ms 给了就"只在超阈值时记"，另外**前 5 次无论如何都记** ——
    poll() 每 120ms 一次，全记会把日志刷爆，但前几次要看基线。
    """

    _seen = {}

    def __init__(self, name, slow_ms=None):
        self.name = name
        self.slow_ms = slow_ms
        self.t = None
        self.extra = {}

    def __enter__(self):
        if ON:
            self.t = time.perf_counter()
        return self

    def __exit__(self, *exc):
        if not ON or self.t is None:
            return False
        ms = (time.perf_counter() - self.t) * 1000.0
        n = span._seen.get(self.name, 0) + 1
        span._seen[self.name] = n
        if self.slow_ms is None or ms >= self.slow_ms or n <= 5:
            mark("%s  %.1f ms" % (self.name, ms), call=n, **self.extra)
        return False
