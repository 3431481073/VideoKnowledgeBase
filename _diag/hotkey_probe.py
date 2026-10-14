# -*- coding: utf-8 -*-
"""Ctrl+Alt+空格 到底被谁占了？—— 用 RegisterHotKey 证伪，不猜。

原理：全局热键在系统里是**独占**的。如果一个组合已被某个进程注册，
别的进程再注册同一个组合会失败，错误码 1409 (ERROR_HOTKEY_ALREADY_REGISTERED)。
所以：
    注册成功        -> 全系统没有任何进程占着它，我们的程序也不可能"被它呼出"
    注册失败 1409   -> 确实有进程占着；再用 MOD_NOREPEAT 逐个试，
                       把范围缩到"哪个修饰键组合被占"
"""

import ctypes

u32 = ctypes.windll.user32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

VK_SPACE = 0x20

CASES = [
    ("Ctrl+Alt+Space", MOD_CONTROL | MOD_ALT),
    ("Ctrl+Space    ", MOD_CONTROL),
    ("Alt+Space     ", MOD_ALT),
    ("Ctrl+Shift+Space", MOD_CONTROL | MOD_SHIFT),
    ("Ctrl+Alt+Shift+Space", MOD_CONTROL | MOD_ALT | MOD_SHIFT),
    ("Win+Space     ", MOD_WIN),
]

print("=== RegisterHotKey 占用检查（每项注册后立刻注销）===")
next_id = 0xB000
for name, mods in CASES:
    next_id += 1
    ok = u32.RegisterHotKey(None, next_id, mods | MOD_NOREPEAT, VK_SPACE)
    if ok:
        u32.UnregisterHotKey(None, next_id)
        print("  %-22s 注册成功  -> 无人占用" % name)
    else:
        err = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
        code = ctypes.windll.kernel32.GetLastError()
        tag = "已被占用" if code == ERROR_HOTKEY_ALREADY_REGISTERED else "失败"
        print("  %-22s %s  错误码=%d%s" % (
            name, tag, code,
            " (ERROR_HOTKEY_ALREADY_REGISTERED)" if code == ERROR_HOTKEY_ALREADY_REGISTERED else ""))
