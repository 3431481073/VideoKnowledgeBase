# -*- coding: utf-8 -*-
"""摄像头模块单测：**不碰真摄像头**，所以没有摄像头的机器也能跑。

覆盖的是这几件真正会出事的事：
  1. 分片**乱序到达**能不能按序拼回去（js_api 每个调用一个线程，顺序不保证）
  2. 收尾的**字节数/片数校验**会不会真的拦住丢数据的情况（不许静默通过）
  3. 格式白名单（MP4 那一路上游就坏了，见 camera.py 模块头）
  4. 权限钩子能装上、且幂等

第 5 节拿**真的 MediaRecorder 产物**（_diag/fixtures/rec_nodur.webm）走一遍
完整链路：切片 -> base64 -> rec_chunk -> rec_done -> 无损重封装 -> 落盘，
验证产出的文件真的是可用的 WebM（有视频有音频有时长）。
"""

import base64
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
DIAG = os.path.join(ROOT, "_diag")
sys.path.insert(0, SRC)
os.environ.pop("VKB_FAKE", None)

TMP = tempfile.mkdtemp(prefix="vkb_cam_test_")

import config      # noqa: E402
import store       # noqa: E402

store.BASE_DIR = TMP
store.DATA_DIR = os.path.join(TMP, "data")
store.MEDIA_DIR = os.path.join(store.DATA_DIR, "media")
store.RAW_DIR = os.path.join(store.DATA_DIR, "raw_transcripts")
store.AI_DIR = os.path.join(store.DATA_DIR, "ai_processed")
store.BACKUP_DIR = os.path.join(store.DATA_DIR, "backups")
store.STALE_DIR = os.path.join(store.DATA_DIR, "_stale")
store.WORKSPACE_FILE = os.path.join(store.DATA_DIR, "workspace.json")
store.TREE_FILE = os.path.join(store.DATA_DIR, "knowledge_tree.json")
config.DATA_DIR = store.DATA_DIR
config.CONFIG_FILE = os.path.join(store.DATA_DIR, "config.json")

import camera        # noqa: E402
import video_ops     # noqa: E402

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


def main():
    print("=" * 60)
    print("py-camera：摄像头分片接收 / 校验 / 权限钩子")

    # ---------------- 0. 隔离自检 ----------------
    chk("C0a ★ 落盘目录被隔离到临时目录（不会写用户真实数据）",
        os.path.abspath(store.MEDIA_DIR).startswith(os.path.abspath(TMP))
        and os.path.abspath(store.BACKUP_DIR).startswith(os.path.abspath(TMP))
        and os.path.abspath(store.STALE_DIR).startswith(os.path.abspath(TMP)),
        store.MEDIA_DIR)

    # ---------------- 1. 分片乱序 ----------------
    r = camera._registry.begin("t1")
    parts = [b"AAAA", b"BBBB", b"CCCC", b"DDDD"]
    got = []
    for seq in (2, 0, 3, 1):                 # 故意乱序到达
        got.append(camera.rec_chunk("t1", seq, base64.b64encode(parts[seq]).decode()))
    chk("C1a 每片都收下了", all(g.get("ok") for g in got), got)
    last = got[-1]
    chk("C1b ★ 按序拼齐后已落盘片数 = 4（乱序也不乱）",
        last.get("got") == 4, last)
    # 必须 finish 之后再读：Recorder 内部是带缓冲的文件句柄，收尾才 flush+fsync
    tmp_path, written = r.finish(len(b"".join(parts)), 4, "video/webm")
    with open(tmp_path, "rb") as f:
        data = f.read()
    chk("C1c ★ 拼出来的字节序完全正确", data == b"".join(parts), data)
    chk("C1d 收尾返回的字节数也对", written == len(b"".join(parts)), written)
    # finish() 只负责 flush+校验，**不删临时文件**（删是 rec_done / abort 的活，
    # 因为 rec_done 还要拿它去重封装）。这里手工收尾，免得留给后面的断言。
    os.remove(tmp_path)

    # ---------------- 2. 收尾校验（不许静默通过） ----------------
    def run_case(rec_id, chunks, total, count, mime="video/webm"):
        camera._registry.begin(rec_id)
        for seq, payload in chunks:
            camera.rec_chunk(rec_id, seq, base64.b64encode(payload).decode())
        return camera.rec_done(rec_id, total, count, mime)

    # 实收 2 片共 4 字节，但 JS 报 99 字节 —— 就是"丢了数据"的情形
    r2 = run_case("t2", [(0, b"XX"), (1, b"YY")], 99, 2)
    chk("C2a ★ 字节数对不上 -> 明确报错（不产出坏文件）",
        not r2.get("ok") and "字节数对不上" in (r2.get("error") or ""),
        r2.get("error"))

    r3 = run_case("t3", [(0, b"XX"), (2, b"YY")], 4, 2)
    chk("C2b ★ 分片有缺口 -> 明确报错", not r3.get("ok")
        and "缺口" in (r3.get("error") or ""), r3.get("error"))

    r4 = run_case("t4", [(0, b"XX")], 3, 2)
    chk("C2c ★ 片数对不上 -> 明确报错", not r4.get("ok")
        and "片数对不上" in (r4.get("error") or ""), r4.get("error"))

    r5 = run_case("t5", [(0, b"")], 0, 0)
    chk("C2d 一片数据都没有 -> 明确报错", not r5.get("ok"), r5.get("error"))

    # 报错之后临时文件要清掉，不许留半截文件在 media/ 里冒充成品
    leftovers = [f for f in os.listdir(store.MEDIA_DIR)
                 if f.startswith(".rec-")]
    chk("C2e ★ 校验失败后不留下半截临时文件", not leftovers, leftovers)

    # ---------------- 3. 格式白名单 ----------------
    r6 = run_case("t6", [(0, b"ZZ")], 2, 1, mime="video/mp4;codecs=vp9,opus")
    chk("C3a ★ MP4 被拒（实测那一路根本没有视频流）",
        not r6.get("ok") and "不支持的录制格式" in (r6.get("error") or ""),
        r6.get("error"))

    # ---------------- 4. 异常输入 ----------------
    camera._registry.begin("t7")
    bad1 = camera.rec_chunk("t7", 0, "opus;base64")     # 就是实测踩到的那个串
    chk("C4a ★ 非 base64 的片被拦住并说明原因",
        not bad1.get("ok") and "base64" in (bad1.get("error") or ""),
        bad1.get("error"))
    bad2 = camera.rec_chunk("没有这个会话", 0, "AAAA")
    chk("C4b 对不存在的会话报错（不静默）",
        not bad2.get("ok") and "录制会话" in (bad2.get("error") or ""),
        bad2.get("error"))
    bad3 = camera.rec_chunk("t7", 0, 12345)
    chk("C4c 分片不是字符串时明确报错",
        not bad3.get("ok") and "字符串" in (bad3.get("error") or ""),
        bad3.get("error"))
    camera.rec_abort("t7")

    # ---------------- 5. 真实产物走一遍全链路 ----------------
    fx = os.path.join(DIAG, "fixtures", "rec_nodur.webm")
    if os.path.isfile(fx):
        with open(fx, "rb") as f:
            raw = f.read()
        n = 5
        step = (len(raw) + n - 1) // n
        pieces = [raw[i:i + step] for i in range(0, len(raw), step)]
        camera._registry.begin("real1")
        for seq in reversed(range(len(pieces))):        # 再乱序一遍
            camera.rec_chunk("real1", seq,
                             base64.b64encode(pieces[seq]).decode())
        res = camera.rec_done("real1", len(raw), len(pieces), "video/webm")
        chk("C5a ★ 真实录制产物分片回传 + 收尾成功", res.get("ok"), res.get("error"))
        if res.get("ok"):
            name = res["mediaName"]
            chk("C5b 落在 media/ 下且非空",
                os.path.isfile(store.media_path(name))
                and os.path.getsize(store.media_path(name)) > 0, name)
            st = video_ops.probe(store.media_path(name)) or {}
            chk("C5c ★ 产物有时长（重封装补上了 MediaRecorder 缺的那个）",
                bool(st.get("duration")) and st["duration"] > 1.0,
                st.get("duration"))
            chk("C5d 视频流在（vp8 1280x720）",
                bool(st.get("video")) and st["video"]["width"] == 1280,
                st.get("video"))
            chk("C5e 音频流在", bool(st.get("audio")), st.get("audio"))
            chk("C5f 没有留下 .rec- 临时文件",
                not [f for f in os.listdir(store.MEDIA_DIR)
                     if f.startswith(".rec-")],
                os.listdir(store.MEDIA_DIR))
            chk("C5g 返回里带了分辨率给人看",
                res.get("width") == 1280 and res.get("height") == 720,
                (res.get("width"), res.get("height")))
    else:
        chk("C5a 真实录制产物 fixture 存在", False, fx)

    # ---------------- 6. 权限钩子 ----------------
    try:
        import webview  # noqa: F401
        from webview.platforms import edgechromium
        camera.install_permission_hook()
        first = edgechromium.EdgeChrome.on_webview_ready
        chk("C6a ★ 权限钩子装上了（替换了 on_webview_ready）",
            getattr(edgechromium.EdgeChrome, "_vkb_perm_patched", False))
        camera.install_permission_hook()                 # 幂等
        chk("C6b 重复安装是幂等的（不会套两层）",
            edgechromium.EdgeChrome.on_webview_ready is first)
    except Exception as e:                               # noqa: BLE001
        chk("C6a ★ 权限钩子装上了（替换了 on_webview_ready）", False,
            "%s: %s" % (type(e).__name__, e))
        chk("C6b 重复安装是幂等的（不会套两层）", False, "上一条已失败")

    # ---------------- 7. dshow 降级路径的守门 ----------------
    devs = camera.devices()
    chk("C7a 设备清单接口结构正确",
        isinstance(devs, dict) and "video" in devs, devs)
    print("        （本机 dshow 视频设备: %s）" % (devs.get("video") or "无"))

    print("-" * 60)
    print("py-camera 合计 %d 通过 / %d 失败" % (ok, len(bad)))
    for b in bad:
        print("   失败: %s" % b)
    return 1 if bad else 0


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
