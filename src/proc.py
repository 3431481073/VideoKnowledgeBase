# -*- coding: utf-8 -*-
"""子进程收口：**所有** spawn 都从这里走，保证不弹黑框。

为什么需要这个模块（实测，不是推测）：
    本程序运行时是 GUI 子系统进程（开发期 pythonw.exe，打包后 --windowed 的
    exe），**本身没有控制台**。Windows 在这种情况下启动一个控制台子程序
    （cmd / ffmpeg / ffprobe / nvidia-smi …）时，会为它**新建**一个控制台
    窗口 —— 用户看到的就是一闪而过的黑框。

    A/B 对照（_diag/ab_test.pyw，pythonw 下）：
        裸 subprocess.run([ffprobe ...])           3/3 出现可见窗口，各约 110ms
        同调用 + CREATE_NO_WINDOW                  0/3，一个窗口都没有

    CREATE_NO_WINDOW 让子进程**不要**新建控制台（它仍然有 stdio，
    只是不配窗口）。相比 STARTUPINFO/SW_HIDE，它是内核级的，不依赖
    "窗口先创建再隐藏"的时序，没有闪一下的窗口。

注意：**不做静默降级**。如果拿不到 CREATE_NO_WINDOW（非 Windows），
    调用方自己决定怎么办；本模块只负责在支持的平台上把它加上。
"""

import subprocess
import sys

#: 0x08000000，CreateProcess 的 CREATE_NO_WINDOW
CREATE_NO_WINDOW = 0x08000000

_HAS_NO_WINDOW = sys.platform.startswith("win")


def hidden_flags():
    """给 subprocess 用的 creationflags。非 Windows 返回 0（无此概念）。"""
    return CREATE_NO_WINDOW if _HAS_NO_WINDOW else 0


def run(cmd, **kw):
    """subprocess.run 的安全替代：自动带上隐藏窗口标志。

    调用方仍可显式传 creationflags —— 会与隐藏标志按位或，不会被覆盖掉。
    """
    kw["creationflags"] = kw.get("creationflags", 0) | hidden_flags()
    return subprocess.run(cmd, **kw)


def check_output(cmd, **kw):
    """subprocess.check_output 的安全替代。"""
    kw["creationflags"] = kw.get("creationflags", 0) | hidden_flags()
    return subprocess.check_output(cmd, **kw)


def popen(cmd, **kw):
    """subprocess.Popen 的安全替代。"""
    kw["creationflags"] = kw.get("creationflags", 0) | hidden_flags()
    return subprocess.Popen(cmd, **kw)
