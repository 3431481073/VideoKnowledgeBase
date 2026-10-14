# -*- coding: utf-8 -*-
"""摄像头：(降级) dshow 录制。**WebRTC 那套已停用，见下方横幅。**

============================================================================
【已停用 · M10 一起清】WebRTC 录制链路（权限钩子 / rec_begin / rec_chunk /
rec_done / Recorder / _Registry）**不再被任何代码引用**。

为什么停用：用户明确要求"直接调起系统相机应用，不要自己实现摄像头访问"。
现在的正路是 src/camera_app.py（调起 Windows 相机应用 + 监视产物 + 导入）。

为什么留着不删：这套东西是实测有效的（探针证据在 _diag/camera_probe_*.txt、
_diag/record_probe_*.txt），万一以后要回到"app 内预览 + 录制"它能直接用。
按约定统一在 M10 清理，避免现在删了又后悔。

【仍然在用】本文件下半部分的 dshow_record —— 它是三级降级的最后一环：
    URI 调起系统相机 -> AppsFolder 调起 -> ffmpeg dshow 直录
============================================================================

原始说明如下（针对上面已停用的那套）：

摄像头：WebView2 权限放行 + 录制分片接收 + (降级) dshow 录制。

【权限必须自己放行 —— 实测，不是推测】
    pywebview 6.2.1 的 edgechromium.py 316 行里**没有一处** permission 相关代码，
    而 WebView2 没有浏览器那种权限弹窗 UI。实测裸跑 getUserMedia：
        stage 一直停在 ready，**既不 resolve 也不 reject**，25 秒后探针掐断。
    订阅 CoreWebView2.PermissionRequested 并置 Allow + Handled 之后：
        Camera / Microphone 各来一次事件，3.4 秒拿到 1280x720 + 1 路音频。
    证据：_diag/camera_probe_plain.txt / _diag/camera_probe_perm.txt

【为什么录 WebM 不录 MP4 —— 实测】
    请求 video/mp4 时 Chromium 产出的是 `video/mp4;codecs=vp9,opus`，
    **里面根本没有视频流**（ffprobe 只报出一条 opus），连 WebView2 自己都
    解不开（videoWidth=0）。video/webm 则是 vp8 1280x720 + opus 双流齐全。
    证据：_diag/record_probe_video_mp4.txt / record_probe_video_webm.txt

【为什么不用 ffmpeg dshow 直接录（那是降级路径）】
    UVC 摄像头在 Windows 上是**独占设备**：ffmpeg 占用时预览打不开，
    预览开着 ffmpeg 就 I/O error。而"点摄像头能看到画面"是硬要求，
    WebRTC 用同一个 stream 同时喂预览和录制，不存在争用。
"""

import base64
import os
import threading
import time

import store
import video_ops

#: MediaRecorder 只给这两种，其余一律拒绝（见模块头）
ALLOWED_MIME = ("video/webm",)


class CameraError(RuntimeError):
    """摄像头相关失败。**明确抛出，不静默降级**。"""


# --------------------------------------------------------------------------
# 权限放行  —— 【已停用 · M10 清】现在走系统相机应用，不经过 WebView2 权限
# --------------------------------------------------------------------------
def install_permission_hook():
    """给 pywebview 的 EdgeChrome 补上 PermissionRequested 处理。

    在 `webview.start()` **之前**调用。打的是外部补丁（不改 venv 里的文件）。
    幂等：重复调用只会装一次。
    """
    from webview.platforms import edgechromium

    if getattr(edgechromium.EdgeChrome, "_vkb_perm_patched", False):
        return True

    from Microsoft.Web.WebView2.Core import (
        CoreWebView2PermissionKind, CoreWebView2PermissionState)

    want = {int(CoreWebView2PermissionKind.Camera),
            int(CoreWebView2PermissionKind.Microphone)}
    orig = edgechromium.EdgeChrome.on_webview_ready

    def patched(self, sender, args):
        orig(self, sender, args)
        if not args.IsSuccess:
            return

        def on_perm(_s, a):
            try:
                if int(a.PermissionKind) in want:
                    a.State = CoreWebView2PermissionState.Allow
                    a.Handled = True
            except Exception:                           # noqa: BLE001
                # 处理不了也不能让控件崩 —— 保持未处理，浏览器会维持默认（悬挂）
                pass

        sender.CoreWebView2.PermissionRequested += on_perm

    edgechromium.EdgeChrome.on_webview_ready = patched
    edgechromium.EdgeChrome._vkb_perm_patched = True
    return True


# --------------------------------------------------------------------------
# 分片接收  —— 【已停用 · M10 清】
# --------------------------------------------------------------------------
class Recorder:
    """一次录制的落盘会话。

    【坑 1】分片**必须按序号拼**：js_api 每个调用都跑在**独立线程**里
    （pywebview 的 js_bridge_call 就是这么干的），而 JS 侧每个分片各自走一次
    异步 FileReader，**到达顺序不保证**。所以这里按 seq 排序后顺序落盘。

    【坑 2】收尾必须**校验**：JS 报的总字节/片数要和实收对得上。对不上就是
    丢了数据，必须报错 —— 一个截断的视频文件比一个明确的错误坏得多。
    """

    def __init__(self, rec_id, tmp_path):
        self.rec_id = rec_id
        self.tmp_path = tmp_path
        self._lock = threading.Lock()
        self._buf = {}          # seq -> bytes（先到但还不能写的）
        self._next = 0          # 下一个该写的序号
        self._chunks = 0
        self._bytes = 0
        self._f = open(tmp_path, "wb")
        self.closed = False

    def chunk(self, seq, raw):
        """收一片。返回当前已按序落盘的片数。"""
        with self._lock:
            if self.closed:
                return self._chunks
            self._buf[int(seq)] = raw
            while self._next in self._buf:
                data = self._buf.pop(self._next)
                self._f.write(data)
                self._bytes += len(data)
                self._chunks += 1
                self._next += 1
            return self._chunks

    def finish(self, total_bytes, chunk_count, mime):
        """收尾：校验 -> 关文件。返回 (tmp_path, 实收字节)。"""
        with self._lock:
            self._f.flush()
            os.fsync(self._f.fileno())
            self._f.close()
            self.closed = True
            got_bytes, got_chunks = self._bytes, self._chunks
            pend = sorted(self._buf)

        if mime and not any(mime.startswith(m) for m in ALLOWED_MIME):
            raise CameraError("不支持的录制格式：%s" % mime)
        if pend:
            raise CameraError(
                "分片序号有缺口，缺 %d 片（已按序写入 %d 片）"
                % (len(pend), got_chunks))
        if chunk_count and got_chunks != int(chunk_count):
            raise CameraError("分片数对不上：JS 报 %s，实收 %d"
                              % (chunk_count, got_chunks))
        if total_bytes and got_bytes != int(total_bytes):
            raise CameraError("字节数对不上：JS 报 %s，实收 %d"
                              % (total_bytes, got_bytes))
        if got_bytes <= 0 or not os.path.isfile(self.tmp_path):
            raise CameraError("录制没有收到任何数据")
        return self.tmp_path, got_bytes

    def abort(self):
        with self._lock:
            if not self.closed:
                try:
                    self._f.close()
                except Exception:
                    pass
                self.closed = True
            try:
                if os.path.isfile(self.tmp_path):
                    os.remove(self.tmp_path)
            except OSError:
                pass


class _Registry:
    def __init__(self):
        self._lock = threading.Lock()
        self._by_id = {}

    def begin(self, rec_id):
        store.ensure_dirs()
        rec_id = str(rec_id or "r1")
        tmp = os.path.join(store.MEDIA_DIR, ".rec-%s.webm" % rec_id)
        with self._lock:
            old = self._by_id.pop(rec_id, None)
            if old is not None:
                old.abort()
            r = Recorder(rec_id, tmp)
            self._by_id[rec_id] = r
        return r

    def get(self, rec_id):
        with self._lock:
            return self._by_id.get(str(rec_id))

    def pop(self, rec_id):
        with self._lock:
            return self._by_id.pop(str(rec_id), None)


_registry = _Registry()


# --------------------------------------------------------------------------
# 对外（web_bridge 调）
# --------------------------------------------------------------------------
def rec_begin(rec_id="r1"):
    _registry.begin(rec_id)
    return {"ok": True, "recId": str(rec_id)}


def rec_chunk(rec_id, seq, b64):
    """收一片 base64。返回 {ok, got}。

    **不要把异常吞成 ok**：前端要靠这个判断"分片传输这一环通不通"，
    而"通不通"正是 dshow 降级路径的触发条件。
    """
    r = _registry.get(rec_id)
    if r is None:
        return {"ok": False, "error": "没有这个录制会话（rec_begin 没调？）"}
    if not isinstance(b64, str):
        return {"ok": False, "error": "分片不是字符串（收到 %s）"
                % type(b64).__name__}
    try:
        raw = base64.b64decode(b64)
    except Exception as e:                              # noqa: BLE001
        return {"ok": False, "error": "base64 解码失败：%s: %s"
                % (type(e).__name__, e)}
    got = r.chunk(seq, raw)
    return {"ok": True, "got": got}


def rec_done(rec_id, total_bytes, chunk_count, mime):
    """收尾：校验 + 无损重封装补时长 + 落到 data/media/。

    返回 {ok, mediaName, seconds, size} —— 前端拿 mediaName 去弹命名框。
    """
    r = _registry.pop(rec_id)
    if r is None:
        return {"ok": False, "error": "没有这个录制会话"}
    try:
        tmp, size = r.finish(total_bytes, chunk_count, mime)
    except CameraError as e:
        r.abort()
        return {"ok": False, "error": str(e)}
    except Exception as e:                              # noqa: BLE001
        r.abort()
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    name = "录制_%s.webm" % time.strftime("%Y%m%d_%H%M%S")
    name = store.unique_media_name(name)
    dst = store.media_path(name)
    try:
        # MediaRecorder 写的 WebM 头里没有时长（实测 duration=None），
        # 裁剪页的时间轴就画不出来。`-c copy` 重封装不重编码、毫秒级，
        # ffmpeg 会按实际数据把时长算出来写进去。
        video_ops.fix_webm_duration(tmp, dst)
    except Exception as e:                              # noqa: BLE001
        try:
            os.remove(tmp)
        except OSError:
            pass
        return {"ok": False, "error": "重封装失败：%s" % e}
    finally:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass

    st = video_ops.probe(dst) or {}
    return {"ok": True, "mediaName": name, "size": os.path.getsize(dst),
            "seconds": st.get("duration"),
            "width": (st.get("video") or {}).get("width"),
            "height": (st.get("video") or {}).get("height")}


def rec_abort(rec_id):
    r = _registry.pop(rec_id)
    if r is not None:
        r.abort()
    return {"ok": True}


def devices():
    """给界面选设备用。取不到就如实返回空。"""
    d = video_ops.list_dshow_devices()
    return {"ok": True, "video": d.get("video") or [], "audio": d.get("audio") or [],
            "error": d.get("error")}


# --------------------------------------------------------------------------
# 降级路径：ffmpeg dshow 直接录
# --------------------------------------------------------------------------
def dshow_record(seconds, device=None, on_progress=None, should_stop=None):
    """**降级路径**：不用浏览器，直接让 ffmpeg 抓摄像头。

    触发条件写死（前端判断）：分片传到 Python 这一环失败 ——
    `/rec_chunk` 返回 ok=false，或 /rec_done 报字节数对不上。
    代价是录制期间预览必须停掉（UVC 摄像头独占）。
    """
    secs = max(1.0, float(seconds or 0))
    devs = video_ops.list_dshow_devices()
    vdev = device or (devs.get("video") or [None])[0]
    if not vdev:
        raise CameraError("找不到可用的摄像头设备（ffmpeg dshow 没列出任何视频设备）")
    adev = (devs.get("audio") or [None])[0]

    spec = "video=%s" % vdev
    if adev:
        spec += ":audio=%s" % adev

    name = store.unique_media_name("录制_%s.mp4" % time.strftime("%Y%m%d_%H%M%S"))
    dst = store.media_path(name)
    cmd = [video_ops.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
           "-nostats", "-progress", "pipe:1",
           "-f", "dshow", "-i", spec, "-t", "%.3f" % secs,
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    if adev:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    cmd += ["-movflags", "+faststart", dst]

    video_ops.run_with_progress(cmd, secs, on_progress, should_stop,
                                timeout=int(secs) + 120)
    return {"ok": True, "mediaName": name, "seconds": secs, "device": vdev}
