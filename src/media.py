# -*- coding: utf-8 -*-
"""媒体目录：把 data/media 通过**目录联接**挂进 webui，让内置 HTTP 服务器能供视频。

为什么必须这么做（都是实测结论）：
  1. pywebview 的页面来源是 http://127.0.0.1:<随机端口>/，**不是 file://**
  2. 从这个页面加载 file:///D:/....mp4 会被 WebView2 拒绝：
     MEDIA_ELEMENT_ERROR: Media load rejected by URL safety check
  3. 同源 HTTP 可以，而且 Range 也通（206 / accept-ranges / seeked 全部实测通过）
  4. 但那个内置服务器只供窗口 URL 所在的目录（webui/）

  所以用目录联接把 data/media 挂到 webui/media 下 —— 视频同源可播，
  bottle 的 static_file 原生处理 Range，我们一行服务器代码都不用写。

  联接在**运行时创建**、不提交进仓库：否则 PyInstaller 的
  --add-data webui;webui 会把整个媒体目录打进 exe。
"""

import os
import sys

import proc

#: 四段样片。testsrc 自带帧计数，hue 让四段颜色不同。
SAMPLES = [
    ("sample_01.mp4", 0,   "样片 01"),
    ("sample_02.mp4", 90,  "样片 02"),
    ("sample_03.mp4", 180, "样片 03"),
    ("sample_04.mp4", 270, "样片 04"),
]
SAMPLE_SECONDS = 8


class MediaLinkError(RuntimeError):
    """媒体目录挂载失败。**明确抛出，不做静默降级**。"""


# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
def app_root():
    """数据目录的锚点：打包后是 exe 所在目录，开发时是项目根。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundle_root():
    """只读资源（webui / 内置文件）的锚点：打包后是 _MEIPASS。"""
    return getattr(sys, "_MEIPASS", None) or app_root()


DATA_DIR = os.path.join(app_root(), "data")
MEDIA_DIR = os.path.join(DATA_DIR, "media")
#: webui/media —— 由 ensure_link() 在运行时创建的目录联接
LINK_PATH = os.path.join(bundle_root(), "webui", "media")


def media_url(filename):
    """给前端的相对 URL（同源，直接 <video src>）。"""
    return f"media/{filename}"


# --------------------------------------------------------------------------
# 挂载
# --------------------------------------------------------------------------
def link_ok():
    return os.path.exists(LINK_PATH)


def _is_dangling_link(path):
    """存在一个链接项、但**目标已经不在了**（悬空的目录联接/符号链接）。"""
    if not os.path.lexists(path):
        return False
    if os.path.exists(path):        # 目标还在 -> 不是悬空
        return False
    try:
        import stat
        attrs = os.lstat(path).st_file_attributes
        return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return False


def ensure_link():
    """确保 webui/media 存在并指向 data/media。

    失败就抛 MediaLinkError，**绝不静默降级**（不复制文件、不改路径）。
    Windows 的目录联接（mklink /J）不需要管理员权限。
    """
    os.makedirs(MEDIA_DIR, exist_ok=True)

    if os.path.exists(LINK_PATH):
        return True

    # 【自愈】LINK_PATH 存在、但目标没了（悬空联接）：
    #   os.path.exists 对悬空联接返回 **False**，于是会一路走到下面的 mklink；
    #   而 mklink 撞上已存在的名字直接失败 —— 应用就**永久**挂不上媒体
    #   （所有视频放不了、裁剪合并全废），**只能人工删掉那个链接才能恢复**。
    #   实测踩过：一个旁路实例建的联接指向了后来被删掉的目录。
    # 这里：是悬空的目录联接就先摘掉（os.rmdir 对联接**只摘链接、不动目标**），
    # 让它走下面的正常重建。
    if _is_dangling_link(LINK_PATH):
        try:
            os.rmdir(LINK_PATH)
        except OSError as e:
            raise MediaLinkError(
                "媒体联接已悬空（目标 %s 不存在），且摘除失败：%s\n"
                "请手动删掉这个链接再重开：%s" % (MEDIA_DIR, e, LINK_PATH)) from e

    if not sys.platform.startswith("win"):
        raise MediaLinkError(
            f"媒体目录 {LINK_PATH} 不存在，且当前平台不支持目录联接。"
            f"请手动把 {MEDIA_DIR} 链接到该路径。")

    try:
        # 走 proc.run：cmd.exe 是控制台程序，裸调会在用户屏幕上弹一个黑框
        r = proc.run(["cmd", "/c", "mklink", "/J", LINK_PATH, MEDIA_DIR],
                     capture_output=True, text=True, timeout=20)
    except Exception as e:
        raise MediaLinkError(f"执行 mklink 失败：{e}") from e

    if r.returncode != 0 or not os.path.exists(LINK_PATH):
        raise MediaLinkError(
            "创建媒体目录联接失败，视频将无法播放。\n"
            f"  目标：{LINK_PATH}\n  来源：{MEDIA_DIR}\n"
            f"  mklink 退出码 {r.returncode}\n"
            f"  stdout: {(r.stdout or '').strip()}\n"
            f"  stderr: {(r.stderr or '').strip()}")
    return True


# --------------------------------------------------------------------------
# 样片
# --------------------------------------------------------------------------
def find_ffmpeg():
    """找一个能用的 ffmpeg。找不到返回 None。"""
    import shutil
    cands = [
        os.path.join(app_root(), "tools", "ffmpeg.exe"),
        os.path.join(bundle_root(), "tools", "ffmpeg.exe"),
        r"D:\MyProject\_tools\ffmpeg\bin\ffmpeg.exe",
        r"D:\ffmpeg\bin\ffmpeg.exe",
        r"D:\MyProject\catcher\backend\tools\ffmpeg.exe",
    ]
    for c in cands:
        if os.path.isfile(c):
            return c
    return shutil.which("ffmpeg")


def ensure_samples(force=False):
    """生成样片（只在缺失时）。返回 (已存在数, 新生成数, 错误信息或 None)。

    样片只是给假数据用的测试素材，画面带帧计数，便于肉眼验证裁剪是否生效。
    """
    os.makedirs(MEDIA_DIR, exist_ok=True)
    missing = [(n, h, t) for n, h, t in SAMPLES
               if force or not os.path.exists(os.path.join(MEDIA_DIR, n))]
    if not missing:
        return len(SAMPLES), 0, None

    ff = find_ffmpeg()
    if not ff:
        return len(SAMPLES) - len(missing), 0, (
            f"缺少 {len(missing)} 段样片，且找不到 ffmpeg，无法生成。"
            f"请把 ffmpeg.exe 放到 {os.path.join(app_root(), 'tools')} 或加入 PATH。")

    made = 0
    for name, hue, _label in missing:
        out = os.path.join(MEDIA_DIR, name)
        cmd = [
            ff, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=s=640x360:r=25:d={SAMPLE_SECONDS}",
            "-vf", f"hue=h={hue}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            "-t", str(SAMPLE_SECONDS), out,
        ]
        try:
            r = proc.run(cmd, capture_output=True, text=True, timeout=120)
        except Exception as e:
            return made, made, f"生成 {name} 失败：{e}"
        if r.returncode != 0 or not os.path.exists(out):
            return made, made, f"生成 {name} 失败：{(r.stderr or '').strip()[:300]}"
        made += 1
    return len(SAMPLES), made, None


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------
def list_media():
    """列出可用媒体（给前端）。"""
    out = []
    if os.path.isdir(MEDIA_DIR):
        for n in sorted(os.listdir(MEDIA_DIR)):
            if n.lower().endswith((".mp4", ".webm", ".mkv", ".mov", ".avi")):
                p = os.path.join(MEDIA_DIR, n)
                out.append({
                    "name": n,
                    "url": media_url(n),
                    "size": os.path.getsize(p),
                })
    return out


def probe_duration(path):
    """用 ffprobe 读时长（秒）。失败返回 None。"""
    ff = find_ffmpeg()
    if not ff:
        return None
    # 只在**同目录**里找 ffprobe —— 不能用字符串替换，
    # 路径里本身就有 "ffmpeg" 这个目录名，链式 replace 会把它也换掉。
    probe = os.path.join(os.path.dirname(ff), "ffprobe.exe")
    if not os.path.isfile(probe):
        import shutil
        probe = shutil.which("ffprobe")
    if not probe:
        return None
    try:
        r = proc.run(
            [probe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20)
        return float(r.stdout.strip())
    except Exception:
        return None
