# -*- coding: utf-8 -*-
"""查证：venv 的 python.exe / pythonw.exe 会不会再 spawn 一个子进程跑同一份脚本。

为什么要查：单实例互斥量如果在"转发器"和"真解释器"里各建一次，
子进程会看到 ALREADY_EXISTS 直接退出 —— 那程序就起不来了。
不猜，实测。
"""
import os
import sys
import time

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pidtest.txt")
with open(out, "a", encoding="utf-8") as f:
    f.write("pid=%d ppid=%d exe=%s argv=%s\n"
            % (os.getpid(), os.getppid(), sys.executable, sys.argv))
time.sleep(6)
