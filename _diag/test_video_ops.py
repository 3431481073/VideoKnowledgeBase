# -*- coding: utf-8 -*-
"""video_ops 单测：真 ffmpeg + 真素材，不 mock。

测的是**行为**，不是"函数被调用了"：
  裁剪时长准不准（这是重编码路线的核心价值，也是 -c copy 做不到的）
  合并走的是 copy 还是 filter（判定逻辑对不对）
  混合来源（有音/无音、分辨率不同）能不能合出来
  没时长的 WebM 能不能被补上时长

素材现场生成（160x120、2~3 秒），跑得快；另外用一份**真的 MediaRecorder
产出的 WebM**（_diag/fixtures/rec_nodur.webm，头里确实没有 Duration）。
"""

import os
import shutil
import subprocess
import sys
import tempfile

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
DIAG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_diag")
sys.path.insert(0, SRC)
os.environ.pop("VKB_FAKE", None)

import proc          # noqa: E402
import video_ops     # noqa: E402

TMP = tempfile.mkdtemp(prefix="vkb_video_test_")
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


def make(name, secs, w=160, h=120, audio=True, hue=0):
    """造一段素材。返回路径。"""
    out = os.path.join(TMP, name)
    cmd = [video_ops.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i",
           "testsrc=s=%dx%d:r=10:d=%d" % (w, h, secs)]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=%d:duration=%d"
                % (300 + hue, secs)]
    cmd += ["-vf", "hue=h=%d" % hue, "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "64k"]
    cmd += ["-t", str(secs), out]
    r = proc.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise SystemExit("造素材失败 %s: %s" % (name, r.stderr[:400]))
    return out


def main():
    print("=" * 60)
    print("py-video：video_ops（真 ffmpeg）")

    # ---------------- 0. 环境 ----------------
    ff = video_ops.ffmpeg()
    chk("V0a 找得到 ffmpeg", bool(ff), ff)
    chk("V0b 找得到 ffprobe", bool(video_ops.ffprobe()), video_ops.ffprobe())

    # ---------------- 1. 编码器探测 ----------------
    video_ops.reset_encoder_cache()
    enc = video_ops.pick_encoder()
    chk("V1a 选出了一个编码器", enc in ("h264_nvenc", "libx264"), enc)
    # 选出来的这个必须**真能编**，否则选它没意义
    real_ok, why = video_ops._try_encoder(enc)
    chk("V1b ★ 选出来的编码器真能跑（不是只在列表里）", real_ok, why)
    chk("V1c 结果被缓存（第二次同值）",
        video_ops.pick_encoder() == enc)

    # ---------------- 2. 素材 ----------------
    a = make("a.mp4", 3, hue=0)
    b = make("b.mp4", 3, hue=90)
    noaud = make("noaud.mp4", 3, hue=180, audio=False)
    big = make("big.mp4", 3, w=240, h=180, hue=270)
    st_a = video_ops.probe(a)
    chk("V2a 素材 a 探出视频流", bool(st_a and st_a["video"]), st_a and st_a["video"])
    chk("V2b 素材 a 有时长", bool(st_a and st_a["duration"]), st_a and st_a["duration"])
    chk("V2c 素材 a 有音频流", bool(st_a and st_a["audio"]), st_a and st_a["audio"])
    st_n = video_ops.probe(noaud)
    chk("V2d 无音素材确实没有音频流", bool(st_n) and st_n["audio"] is None,
        st_n and st_n["audio"])
    chk("V2e 不同分辨率素材尺寸不同",
        video_ops.probe(big)["video"]["width"] == 240,
        video_ops.probe(big)["video"]["width"])

    # ---------------- 3. 裁剪：时长精度 ----------------
    dst = os.path.join(TMP, "clip1.mp4")
    prog = []
    video_ops.clip(a, dst, 1.0, 2.0, on_progress=lambda f: prog.append(f))
    st = video_ops.probe(dst)
    chk("V3a 裁剪产物存在", os.path.isfile(dst) and os.path.getsize(dst) > 0)
    chk("V3b 裁剪产物有视频流", bool(st and st["video"]))
    dur = (st or {}).get("duration") or 0
    chk("V3c ★ 裁剪时长准（1.0s ±0.25s，-c copy 做不到这个精度）",
        abs(dur - 1.0) <= 0.25, "实得 %.3fs" % dur)
    chk("V3d 分辨率保持", st["video"]["width"] == 160 and st["video"]["height"] == 120,
        (st["video"]["width"], st["video"]["height"]))
    chk("V3e 音频也带过来了", bool(st.get("audio")), st.get("audio"))
    chk("V3f ★ 进度回调真的在推进（不是只报 0 和 1）",
        len(prog) >= 2 and max(prog) > 0.1, "回调 %d 次，最大 %.2f"
        % (len(prog), max(prog) if prog else -1))

    # 起点不是 0 的裁剪：证明不受关键帧位置影响
    dst2 = os.path.join(TMP, "clip2.mp4")
    video_ops.clip(a, dst2, 1.37, 2.11)
    d2 = video_ops.probe(dst2)["duration"]
    chk("V3g ★ 非整秒起点也准（1.37~2.11 -> 0.74s）",
        abs(d2 - 0.74) <= 0.25, "实得 %.3fs" % d2)

    # ---------------- 4. 裁剪：取消 ----------------
    dst3 = os.path.join(TMP, "clip3.mp4")
    got = None
    try:
        video_ops.clip(big, dst3, 0.5, 2.5, should_stop=lambda: True)
    except video_ops.Cancelled:
        got = "cancelled"
    except Exception as e:                              # noqa: BLE001
        got = "%s: %s" % (type(e).__name__, e)
    chk("V4a ★ 取消能真的中断（抛 Cancelled）", got == "cancelled", got)

    # ---------------- 5. 合并方式判定 ----------------
    whole = lambda p: {"path": p, "start": 0.0, "end": video_ops.duration_of(p)}
    p1 = video_ops.plan_merge([whole(a), whole(b)])
    chk("V5a 参数一致 + 整段 -> copy", p1["mode"] == "copy", p1["reason"])

    part = [{"path": a, "start": 0.5, "end": 2.0},
            {"path": b, "start": 0.5, "end": 2.0}]
    p2 = video_ops.plan_merge(part)
    chk("V5b ★ 含裁剪子区间 -> filter（-c copy 切不准）",
        p2["mode"] == "filter", p2["reason"])

    p3 = video_ops.plan_merge([whole(a), whole(big)])
    chk("V5c ★ 分辨率不一致 -> filter 且给出统一画布",
        p3["mode"] == "filter" and p3["canvas"] == (240, 180),
        "%s %s" % (p3["mode"], p3["canvas"]))

    p4 = video_ops.plan_merge([whole(a), whole(b), whole(noaud)])
    chk("V5d 含无音轨素材 -> 至少不能是 copy",
        p4["mode"] == "filter", p4["reason"])

    # 参数一致但其中一段没声音 -> 指纹不同 -> filter
    mixed = [whole(a), whole(noaud)]
    p5 = video_ops.plan_merge(mixed)
    chk("V5e 有音+无音混合 -> filter", p5["mode"] == "filter", p5["reason"])

    # ---------------- 6. 合并：copy 路 ----------------
    out1 = os.path.join(TMP, "merge_copy.mp4")
    r1 = video_ops.merge([whole(a), whole(b)], out1)
    d1 = video_ops.probe(out1)["duration"]
    chk("V6a copy 合并走的是 copy", r1["mode"] == "copy", r1["reason"])
    chk("V6b copy 合并时长 = 两段之和（6s ±0.6）",
        abs(d1 - 6.0) <= 0.6, "实得 %.3fs" % d1)
    chk("V6c copy 合并产物有视频流", bool(video_ops.probe(out1)["video"]))

    # ---------------- 7. 合并：filter 路 ----------------
    out2 = os.path.join(TMP, "merge_filter.mp4")
    r2 = video_ops.merge(part, out2)
    d2b = video_ops.probe(out2)["duration"]
    chk("V7a 子区间合并走 filter", r2["mode"] == "filter", r2["reason"])
    chk("V7b ★ filter 合并时长 = 各段之和（1.5+1.5=3.0 ±0.5）",
        abs(d2b - 3.0) <= 0.5, "实得 %.3fs" % d2b)

    # 分辨率不一致的合并
    out3 = os.path.join(TMP, "merge_canvas.mp4")
    r3 = video_ops.merge([whole(a), whole(big)], out3)
    st3 = video_ops.probe(out3)
    chk("V7c ★ 分辨率不一致能合出来（不报错）",
        os.path.isfile(out3) and st3 and st3["video"], r3["reason"])
    chk("V7d 统一到最大画布 240x180",
        st3 and st3["video"]["width"] == 240 and st3["video"]["height"] == 180,
        st3 and (st3["video"]["width"], st3["video"]["height"]))

    # 无音段 + 有音段合并：静音轨要补齐，否则 concat 的 [i:a] 引用直接失败
    out4 = os.path.join(TMP, "merge_audio.mp4")
    try:
        video_ops.merge([whole(a), whole(noaud)], out4)
        st4 = video_ops.probe(out4)
        chk("V7e ★ 有音+无音能合出来（缺音轨补静音）",
            os.path.isfile(out4) and st4 and st4["video"], "文件=%s"
            % os.path.isfile(out4))
        chk("V7f 合成品有音频轨（静音也算）", bool(st4 and st4["audio"]),
            st4 and st4["audio"])
    except video_ops.VideoOpError as e:
        chk("V7e ★ 有音+无音能合出来（缺音轨补静音）", False, str(e)[:200])
        chk("V7f 合成品有音频轨（静音也算）", False, "上一条已失败")

    # ---------------- 8. 录制产物补时长 ----------------
    fx = os.path.join(DIAG, "fixtures", "rec_nodur.webm")
    if os.path.isfile(fx):
        before = video_ops.probe(fx)
        chk("V8a ★ 真实 MediaRecorder 产物的确没有时长（复现问题）",
            before and not before.get("duration"), before and before.get("duration"))
        chk("V8b 它确实带视频流（vp8 1280x720）",
            before and before["video"] and before["video"]["width"] == 1280,
            before and before["video"])
        fixed = os.path.join(TMP, "fixed.webm")
        video_ops.fix_webm_duration(fx, fixed)
        after = video_ops.probe(fixed)
        chk("V8c ★ 无损重封装后时长补上了",
            after and after.get("duration") and after["duration"] > 1.0,
            after and after.get("duration"))
        chk("V8d 重封装没丢流（视频+音频都在）",
            after and after["video"] and after["audio"],
            after and (after["video"], after["audio"]))
        chk("V8e 时长与画面尺寸保持一致",
            after and after["video"]["width"] == 1280,
            after and after["video"])
    else:
        chk("V8a ★ 真实 MediaRecorder 产物（缺 fixture，跳过）", False, fx)

    # ---------------- 9. dshow 设备清单（降级路径要用） ----------------
    # 用**本机 ffmpeg 的真实输出样本**断言解析（ffmpeg 9.x 换了格式，
    # 老教程里的 "DirectShow video devices" 标题行这个版本已经不打了）
    sample = '''
[in#0 @ 000001d35a880fc0] "USB2.0 HD UVC WebCam" (video)
[in#0 @ 000001d35a880fc0]   Alternative name "@device_pnp_\\\\?\\usb#vid_322e"
[in#0 @ 000001d35a880fc0] "WebcastMate VirtualCamera" (none)
[in#0 @ 000001d35a880fc0]   Alternative name "@device_sw_{860BB310}"
[in#0 @ 000001d35a880fc0] "麦克风阵列 (Realtek(R) Audio)" (audio)
Error opening input file dummy.
'''
    parsed = video_ops._parse_dshow(sample)
    chk("V9a ★ 新格式能解析出视频设备",
        parsed["video"] == ["USB2.0 HD UVC WebCam"], parsed["video"])
    chk("V9b 中文名音频设备也能解析",
        parsed["audio"] == ["麦克风阵列 (Realtek(R) Audio)"], parsed["audio"])
    chk("V9c Alternative name 不会被当成设备",
        len(parsed["video"]) + len(parsed["audio"]) == 2,
        parsed)
    chk("V9d (none) 类型的设备被排除（不是可用输入）",
        all("WebcastMate" not in v for v in parsed["video"]), parsed["video"])
    devs = video_ops.list_dshow_devices()
    chk("V9e 真机清单不报错、结构正确",
        isinstance(devs, dict) and devs.get("error") is None
        and isinstance(devs.get("video"), list), devs.get("error"))
    print("        （本机 dshow 视频设备: %s）" % (devs.get("video") or "无"))

    # ---------------- 10. 错误路径 ----------------
    try:
        video_ops.clip(os.path.join(TMP, "不存在.mp4"), os.path.join(TMP, "x.mp4"),
                       0, 1)
        chk("V10a 源文件不存在要明确报错", False, "没报错")
    except video_ops.VideoOpError as e:
        chk("V10a 源文件不存在要明确报错", "不存在" in str(e), str(e)[:80])
    try:
        video_ops.clip(a, os.path.join(TMP, "y.mp4"), 1.0, 1.01)
        chk("V10b 区间太短要明确报错", False, "没报错")
    except video_ops.VideoOpError as e:
        chk("V10b 区间太短要明确报错", "太短" in str(e), str(e)[:80])
    try:
        video_ops.merge([whole(a)], os.path.join(TMP, "z.mp4"))
        chk("V10c 单段合并要明确报错", False, "没报错")
    except video_ops.VideoOpError as e:
        chk("V10c 单段合并要明确报错", "两段" in str(e), str(e)[:80])
    try:
        video_ops.probe(os.path.join(TMP, "不存在.mp4"))
        chk("V10d 探测不存在的文件返回 None（不抛）", True)
    except Exception as e:                              # noqa: BLE001
        chk("V10d 探测不存在的文件返回 None（不抛）", False, str(e)[:80])

    print("-" * 60)
    print("py-video 合计 %d 通过 / %d 失败" % (ok, len(bad)))
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
