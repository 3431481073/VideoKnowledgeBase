# -*- coding: utf-8 -*-
"""ClientToScreen 在这个环境下到底返回什么 —— 单独测，别猜。"""
import ctypes
import ctypes.wintypes as wt

u32 = ctypes.windll.user32
TITLE = "视频知识库 · 工作台"

print("wintypes.POINT =", wt.POINT, "fields =", wt.POINT._fields_)
print("sizeof(POINT) =", ctypes.sizeof(wt.POINT))

hwnd = u32.FindWindowW(None, TITLE)
print("hwnd =", hwnd)
if not hwnd:
    raise SystemExit("窗口没找到")

r = wt.RECT()
u32.GetWindowRect(hwnd, ctypes.byref(r))
print("GetWindowRect =", (r.left, r.top, r.right, r.bottom))

# 方式 A：不声明 argtypes（当前写法）
ptA = wt.POINT(0, 0)
okA = u32.ClientToScreen(hwnd, ctypes.byref(ptA))
print("A 无 argtypes : ok=%s  pt=(%d,%d)" % (okA, ptA.x, ptA.y))

# 方式 B：显式声明 argtypes / restype
u32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
u32.ClientToScreen.restype = wt.BOOL
ptB = wt.POINT(0, 0)
okB = u32.ClientToScreen(hwnd, ctypes.byref(ptB))
print("B 有 argtypes : ok=%s  pt=(%d,%d)" % (okB, ptB.x, ptB.y))

# 方式 C：用 GetClientRect + ClientToScreen 交叉验证
cr = wt.RECT()
u32.GetClientRect(hwnd, ctypes.byref(cr))
print("GetClientRect =", (cr.left, cr.top, cr.right, cr.bottom))
ptC = wt.POINT(0, 0)
u32.ClientToScreen(hwnd, ctypes.byref(ptC))
print("C 客户区左上角屏幕坐标 = (%d,%d); 窗口右下 = (%d,%d)"
      % (ptC.x, ptC.y, ptC.x + cr.right, ptC.y + cr.bottom))
