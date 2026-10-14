# -*- coding: utf-8 -*-
r"""把 vkb.svg 转成多尺寸 vkb.ico（给 PyInstaller --icon 和窗口图标用）。

    venv\Scripts\python.exe build\make_ico.py

为什么要走 Edge 无头：
  本机**没有** Pillow、没有 cairosvg、没有 ImageMagick / inkscape（实测）。
  但有 Edge。用真浏览器引擎渲染 = 出来的图标和工作台里显示的**像素一致**，
  比自己手写一个光栅化器可靠。

为什么要自己写 ICO 容器：
  ICO 就是个很简单的容器（头 + 每张图的目录项 + 图片数据），
  Vista 以后允许每项直接放 PNG。用标准库 zlib/struct 写二十行就够，
  不值得为它装一个图像库（引入新依赖要走审批）。

尺寸取 16/24/32/48/64/128/256 —— Windows 各场景用不同尺寸：
  16/24 列表与标题栏 · 32 任务栏 · 48/64 中等图标 · 256 大图标/预览。
"""

import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG = os.path.join(ROOT, "build", "vkb.svg")
OUT_ICO = os.path.join(ROOT, "build", "vkb.ico")
TMP = os.path.join(ROOT, "build", "_ico_tmp")

SIZES = [16, 24, 32, 48, 64, 128, 256]

EDGE_CANDS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_edge():
    for c in EDGE_CANDS:
        if os.path.isfile(c):
            return c
    raise SystemExit("找不到 msedge.exe，无法渲染 SVG")


def html_for(svg_text, size):
    """把 SVG 内联进一个透明背景的页面，尺寸钉死为 size×size。"""
    svg = svg_text.replace("<svg ", '<svg width="%d" height="%d" ' % (size, size), 1)
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<style>html,body{margin:0;padding:0;background:transparent;"
        "overflow:hidden}svg{display:block}</style>" + svg
    )


def render(edge, svg_text, size, out_png):
    html_path = os.path.join(TMP, "icon_%d.html" % size)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_for(svg_text, size))
    if os.path.exists(out_png):
        os.remove(out_png)
    cmd = [
        edge, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--default-background-color=00000000",
        "--window-size=%d,%d" % (size, size),
        "--screenshot=" + out_png,
        "file:///" + html_path.replace("\\", "/"),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if not os.path.isfile(out_png):
        raise SystemExit("Edge 没产出 %s（exit=%s）\n%s"
                         % (out_png, r.returncode,
                            (r.stderr or b"")[-800:].decode("utf-8", "replace")))


def png_info(data):
    """读 PNG 的 IHDR：返回 (宽, 高, 位深, 颜色类型)。顺带确认它是真 PNG。"""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是 PNG")
    w, h, depth, ctype = struct.unpack(">IIBB", data[16:26])
    return w, h, depth, ctype


def build_ico(pngs, out_path):
    """pngs = [(size, bytes)]，按 ICO 格式打包。每项直接内嵌 PNG。"""
    n = len(pngs)
    header = struct.pack("<HHH", 0, 1, n)
    offset = 6 + 16 * n
    entries, blobs = b"", b""
    for size, data in pngs:
        dim = 0 if size >= 256 else size          # ICO 里 0 表示 256
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                               len(data), offset)
        blobs += data
        offset += len(data)
    with open(out_path, "wb") as f:
        f.write(header + entries + blobs)


def main():
    if not os.path.isfile(SVG):
        raise SystemExit("找不到 %s" % SVG)
    with open(SVG, "r", encoding="utf-8") as f:
        svg_text = f.read()
    edge = find_edge()
    print("Edge = %s" % edge)
    os.makedirs(TMP, exist_ok=True)

    pngs = []
    for size in SIZES:
        out = os.path.join(TMP, "icon_%d.png" % size)
        render(edge, svg_text, size, out)
        data = open(out, "rb").read()
        w, h, depth, ctype = png_info(data)
        print("  %3d -> %-28s  %dx%d  depth=%d color=%d  %d B"
              % (size, os.path.basename(out), w, h, depth, ctype, len(data)))
        if (w, h) != (size, size):
            raise SystemExit("★ %d 渲染出来是 %dx%d，尺寸不对" % (size, w, h))
        pngs.append((size, data))

    build_ico(pngs, OUT_ICO)
    print("")
    print("写出 %s  (%d B)" % (OUT_ICO, os.path.getsize(OUT_ICO)))

    # 回读校验：目录项数量、每项尺寸、每项是不是完整 PNG
    raw = open(OUT_ICO, "rb").read()
    _res, typ, cnt = struct.unpack("<HHH", raw[:6])
    print("回读: type=%d count=%d" % (typ, cnt))
    assert typ == 1 and cnt == len(SIZES), "ICO 头不对"
    for i in range(cnt):
        off = 6 + 16 * i
        w, h, _c, _r, _p, _b, nbytes, dataoff = struct.unpack("<BBBBHHII",
                                                              raw[off:off + 16])
        blob = raw[dataoff:dataoff + nbytes]
        pw, ph, _d, _t = png_info(blob)
        want = w or 256
        assert (pw, ph) == (want, want), "第 %d 项尺寸不对" % i
        print("  项 %d: 声明 %dx%d  实际 %dx%d  %d B  OK" % (i, w, h, pw, ph, nbytes))
    print("校验通过")


if __name__ == "__main__":
    main()
