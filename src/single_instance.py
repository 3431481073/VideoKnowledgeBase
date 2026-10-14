# -*- coding: utf-8 -*-
"""单实例：不许同时开两个窗口。

【为什么需要】实测踩到的真事：用户 22:26 双击 .bat 起了一个实例，之后我
改了代码又起新实例跑测试 —— 用户点的是那个**跑着旧代码**的窗口，症状是
"点摄像头半天不出来"（那份代码里根本没有摄像头功能）。两个实例还会同时
写 data/workspace.json，互相覆盖。

【为什么是两道闸，不是一道】
  ① 按窗口标题找 —— 覆盖**陈旧实例**。旧代码在互斥量出现之前就启动了，
     它根本没有互斥量，只有"窗口标题"能认出它。
  ② 命名互斥量 —— 覆盖**同时启动**的两个新实例（那一刻窗口还没建出来）。
  单靠任一道都有漏。

【为什么用命名互斥量而不是锁文件】进程被强杀时，互斥量由内核自动释放，
  不会留下一个"僵尸锁文件"把用户永久挡在外面。锁文件做不到这一点。
"""

import os
import sys

import winapi

#: 窗口标题（与 app_web.APP_TITLE 一致）。故意不 import app_web：
#: 那会把 pywebview 整条链拉进来，启动期多几百毫秒。
APP_TITLE = "视频知识库 · 工作台"

#: 互斥量名。Local\ 前缀 = 只在当前登录会话内互斥 —— 多用户各开一个是合理的。
MUTEX_NAME = r"Local\VideoKnowledgeBase.Workbench"

#: 测试驱动设这个变量跳过单实例闸。
#: **只跳过这一道**，其它逻辑一律照跑。测试要能和你开着的实例并存。
SKIP_ENV = "VKB_NO_SINGLE_INSTANCE"

_handle = None          # 必须一直持有，否则互斥量被释放
_acquired = False

#: 可替换的实现 —— 测试用假件替掉它们，就能在**不建真窗口**的前提下
#: 把每一条分支都跑一遍（这条套件的存在意义就是不用真起 GUI）。
_find_window = winapi.find_window
_bring_to_front = winapi.bring_to_front
_acquire_mutex = winapi.acquire_mutex
_message_box = winapi.message_box


def _reset_for_test():
    """测试用：放掉互斥量句柄、恢复默认实现。"""
    global _handle, _acquired
    _handle = None
    _acquired = False


def skipped():
    return os.environ.get(SKIP_ENV, "").strip() == "1"


def acquire():
    """拿单实例权。返回 None = 可以继续；返回字符串 = 已经被占用（原因）。"""
    global _handle, _acquired

    if skipped():
        return None

    # ---- ① 已经有窗口了？（覆盖陈旧实例）----
    hwnd = _find_window(APP_TITLE)
    if hwnd:
        ok = _bring_to_front(hwnd)
        if not ok:
            return ("已经有一个「%s」在运行，但没能把它拉到前台。\n\n"
                    "请点任务栏上的那个窗口。" % APP_TITLE)
        return "already"        # 已前置，调用方直接退出

    # ---- ② 互斥量（覆盖并发启动）----
    _handle, exists = _acquire_mutex(MUTEX_NAME)
    _acquired = True
    if exists:
        # 互斥量在、窗口却找不到 —— 说明那个进程活着但窗口没了。
        # 这种必须**明确告诉用户怎么办**，不能静默退出（pythonw 没控制台）。
        hwnd = _find_window(APP_TITLE, timeout=3.0, poll=0.3)
        if hwnd:
            _bring_to_front(hwnd)
            return "already"
        _message_box(
            "已经有一个「%s」在运行，但找不到它的窗口"
            "（可能卡住了，或者窗口被关掉了）。\n\n"
            "请在任务管理器里结束它再重试。注意：进程名是 python.exe 或 "
            "pythonw.exe，你机器上还有别的程序也用这个名字，"
            "**请在任务管理器里打开「命令行」列**，找命令行里带 "
            "VideoKnowledgeBase\\src\\app_web.py 的那两个（一个是转发器、"
            "一个是真解释器）。\n\n"
            "本次启动已取消。" % APP_TITLE)
        return "no-window"

    return None


def held():
    """本进程是否持有互斥量（自检用）。"""
    return _acquired and _handle is not None
