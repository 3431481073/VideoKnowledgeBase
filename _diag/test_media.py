# -*- coding: utf-8 -*-
"""媒体联接单测：正常建立 + **悬空联接自愈**。

在**临时目录**里跑，不碰项目真实的 data/。

为什么单独有这一套：media.py 此前没有任何套件覆盖，而它是"视频能不能播"
的唯一开关 —— 联接一坏，所有视频、裁剪、合并全废。
"""

import os
import shutil
import subprocess
import sys
import tempfile

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)
os.environ.pop("VKB_FAKE", None)

import media         # noqa: E402

TMP = tempfile.mkdtemp(prefix="vkb_media_test_")

# 全部重定向到临时目录 —— 漏一个就会去动项目真实的 data/
media.DATA_DIR = os.path.join(TMP, "data")
media.MEDIA_DIR = os.path.join(media.DATA_DIR, "media")
media.LINK_PATH = os.path.join(TMP, "webui", "media")
os.makedirs(os.path.dirname(media.LINK_PATH), exist_ok=True)
os.makedirs(media.MEDIA_DIR, exist_ok=True)

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


def drop_link():
    """摘掉联接（只摘链接，不动目标）。"""
    if os.path.lexists(media.LINK_PATH):
        os.rmdir(media.LINK_PATH)


print("== 1. 正常建立 ==")
media.ensure_link()
chk("★ 联接建起来了", media.link_ok())
chk("★ 指向 data/media",
    os.path.realpath(media.LINK_PATH) == os.path.realpath(media.MEDIA_DIR),
    os.path.realpath(media.LINK_PATH))
with open(os.path.join(media.MEDIA_DIR, "a.mp4"), "wb") as f:
    f.write(b"x" * 10)
chk("list_media 能列出视频", [x["name"] for x in media.list_media()] == ["a.mp4"],
    media.list_media())
chk("非视频扩展名不列", media.list_media()[0]["url"] == "media/a.mp4",
    media.list_media()[0]["url"])
chk("link_ok() 为真", media.link_ok())

print("== 2. 悬空联接必须能自愈 ==")
# 造一个"链接在、目标没了"的悬空目录联接
drop_link()
ghost = os.path.join(TMP, "ghost_不存在")
subprocess.run(["cmd", "/c", "mklink", "/J", media.LINK_PATH, ghost],
               capture_output=True)
chk("造出悬空联接（lexists=True 而 exists=False）",
    os.path.lexists(media.LINK_PATH) and not os.path.exists(media.LINK_PATH),
    (os.path.lexists(media.LINK_PATH), os.path.exists(media.LINK_PATH)))
chk("悬空时 link_ok() 为 False（视频此时是放不了的）", not media.link_ok())

# 这一条是本次修的核心：以前这里会一路走到 mklink、撞名字失败，
# 于是应用**永久**挂不上媒体，只能人工删链接 —— 死路。
media.ensure_link()
chk("★★ 悬空联接能自愈，不再是死路", media.link_ok())
chk("★★ 自愈后指向正确的 data/media",
    os.path.realpath(media.LINK_PATH) == os.path.realpath(media.MEDIA_DIR),
    os.path.realpath(media.LINK_PATH))
chk("自愈没有牵连删掉目标目录", os.path.isdir(media.MEDIA_DIR))
chk("自愈后还能列出视频", [x["name"] for x in media.list_media()] == ["a.mp4"],
    media.list_media())

print("== 3. 反复调用是幂等的 ==")
for _ in range(3):
    media.ensure_link()
chk("连续 ensure_link 不报错、联接仍正确",
    media.link_ok() and os.path.realpath(media.LINK_PATH)
    == os.path.realpath(media.MEDIA_DIR))

# 收尾：先摘链接再删目录 —— 否则 rmtree 可能顺着联接穿到目标
drop_link()
shutil.rmtree(TMP, ignore_errors=True)

print("\n结果：%d 通过，%d 失败" % (ok, len(bad)))
if bad:
    print("失败项：" + ", ".join(bad))
sys.exit(1 if bad else 0)
