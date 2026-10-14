# -*- coding: utf-8 -*-
"""任务队列单测（不需要 GPU / API Key / 网络）。

把 transcriber 与 ai_processor 换成假的（只替掉那两个函数，队列本身是真的），
验证：串行顺序、五个阶段的推进、落盘、**取消**、以及三条失败/降级路径。
"""

import os
import shutil
import sys
import tempfile
import time

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)
os.environ.pop("VKB_FAKE", None)

TMP = tempfile.mkdtemp(prefix="vkb_jobs_test_")

import config        # noqa: E402
import store         # noqa: E402
import transcriber   # noqa: E402
import ai_processor  # noqa: E402

store.BASE_DIR = TMP
store.DATA_DIR = os.path.join(TMP, "data")
store.MEDIA_DIR = os.path.join(store.DATA_DIR, "media")
store.RAW_DIR = os.path.join(store.DATA_DIR, "raw_transcripts")
store.AI_DIR = os.path.join(store.DATA_DIR, "ai_processed")
# 【必须一起改】备份/归档目录也是 store 的模块级全局。漏改的话测试会往
# **真实的** data/backups 和 data/_stale 里写 —— 上次 test_store 写进真
# config.json 就是这么栽的。隔离自检断言在下面 I0。
store.BACKUP_DIR = os.path.join(store.DATA_DIR, "backups")
store.STALE_DIR = os.path.join(store.DATA_DIR, "_stale")
store.WORKSPACE_FILE = os.path.join(store.DATA_DIR, "workspace.json")
store.TREE_FILE = os.path.join(store.DATA_DIR, "knowledge_tree.json")
config.DATA_DIR = store.DATA_DIR
config.CONFIG_FILE = os.path.join(store.DATA_DIR, "config.json")

import jobs          # noqa: E402
import web_state     # noqa: E402

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


def wait_for(fn, sec, label=""):
    t0 = time.monotonic()
    while time.monotonic() - t0 < sec:
        if fn():
            return True
        time.sleep(0.02)
    print("    （等超时：%s）" % label)
    return False


# ---------------------------------------------------------------- 假转写器
CALLS = []          # 记录真实调用顺序，验证串行


def fake_iter(video_path, language="zh", on_progress=None, should_stop=None):
    name = os.path.basename(video_path)
    CALLS.append(("start", name))
    total = 10.0
    for i in range(4):
        if should_stop and should_stop():
            CALLS.append(("stopped", name))
            return
        # 第一段留长一点，让测试有机会采到 loading 阶段（模型加载期的替身）
        time.sleep(0.08 if i == 0 else 0.01)
        yield {"start": i * 2.5, "end": (i + 1) * 2.5, "text": "%s第%d句" % (name, i)}
        if on_progress:
            on_progress((i + 1) * 2.5, total)
    CALLS.append(("end", name))


def fake_iter_empty(video_path, language="zh", on_progress=None, should_stop=None):
    return iter([])


def fake_clean(segments, **kw):
    time.sleep(0.05)
    return {"title": "", "cleaned_text": "清洗稿：" + "".join(s["text"] for s in segments)}


transcriber.transcribe_video_iter = fake_iter
ai_processor.process_segments = fake_clean

print("== 0. 隔离自检 ==")
REAL_DATA = os.path.join(os.path.dirname(SRC), "data")
chk("store 写在临时目录", os.path.abspath(store.RAW_DIR).startswith(TMP))
chk("config 写在临时目录", os.path.abspath(config.CONFIG_FILE).startswith(TMP) and
    not os.path.abspath(config.CONFIG_FILE).startswith(REAL_DATA))

store.ensure_dirs()


def make_media(name):
    os.makedirs(store.MEDIA_DIR, exist_ok=True)
    p = store.media_path(name)
    with open(p, "wb") as f:
        f.write(b"x" * 1024)
    return p


print("== 1. 串行 FIFO：三条依次跑，不交错 ==")
CALLS.clear()
store.save_settings({"clean_api_key": "sk-fake"})
q = jobs.JobQueue()
q.start()
st = web_state.WebState()
st.jobs = q

items = []
for n in ("a.mp4", "b.mp4", "c.mp4"):
    make_media(n)
    it = store.add_item(n)
    st._items[it.iid] = it
    st.pending.append(it)
    items.append(it)

for it in items:
    st.start_processing(it.iid)

chk("提交后立刻是 queued", st.item(items[0].iid).stage == "queued")
chk("排队位次 1/2/3",
    [q.state_of(x.iid)["queued"] for x in items] == [1, 2, 3],
    [q.state_of(x.iid)["queued"] for x in items])

done = wait_for(lambda: all(store.has_cleaned(x.base) for x in items), 20, "三条跑完")
chk("三条都跑完", done)
starts = [c[1] for c in CALLS if c[0] == "start"]
ends = [c[1] for c in CALLS if c[0] == "end"]
chk("★ 严格串行：start 顺序与提交顺序一致", starts == ["a.mp4", "b.mp4", "c.mp4"], starts)
chk("★ 没有交错：每个 end 紧跟下一个 start",
    ends == ["a.mp4", "b.mp4", "c.mp4"], ends)
chk("队列空了", q.active_count() == 0, q.active_count())

print("== 2. 落盘：四个文件都对，raw 没被清洗稿覆盖 ==")
for it in items:
    chk("%s raw 存在" % it.video_name, store.has_raw(it.base))
    chk("%s cleaned 存在" % it.video_name, store.has_cleaned(it.base))
a = items[0]
raw = store.read_raw(a.base)
clean = store.read_cleaned(a.base)
chk("raw 是原始转写（含时间戳拼接的原句）", raw.startswith("a.mp4第0句"), repr(raw[:20]))
chk("清洗稿是另一份内容", clean.startswith("清洗稿："), repr(clean[:20]))
chk("★ raw != cleaned（老程序在这栽过）", raw != clean)
chk("segments 是 4 段", len(store.read_segments(a.base)) == 4,
    len(store.read_segments(a.base)))
meta = store.read_meta(a.base)
chk("meta 五字段齐全",
    all(k in meta for k in ("title", "video_path", "cleaned_file",
                            "created_time", "modified_at")), sorted(meta))

print("== 3. 阶段推进：loading -> transcribing -> cleaning -> done ==")
it = store.add_item("d.mp4")
make_media("d.mp4")
st._items[it.iid] = it
st.pending.append(it)
seen = set()
st.start_processing(it.iid)
t0 = time.monotonic()
while time.monotonic() - t0 < 20:
    s = q.state_of(it.iid)
    if s:
        seen.add(s["stage"])
        if s["stage"] in ("done", "error", "transcribed"):
            break
    time.sleep(0.02)
chk("出现过 loading", "loading" in seen, sorted(seen))
chk("出现过 transcribing", "transcribing" in seen, sorted(seen))
chk("出现过 cleaning", "cleaning" in seen, sorted(seen))
chk("最终 done", q.state_of(it.iid)["stage"] == "done", q.state_of(it.iid))
chk("transcribePct 到 100", q.state_of(it.iid)["pct"] == 100, q.state_of(it.iid)["pct"])
chk("cleanPct 到 100", q.state_of(it.iid)["cleanPct"] == 100, q.state_of(it.iid)["cleanPct"])

print("== 4. 进度是单调不减的，且出现多个不同值 ==")
it2 = store.add_item("e.mp4")
make_media("e.mp4")
st._items[it2.iid] = it2
st.pending.append(it2)
st.start_processing(it2.iid)
pcts = []
t0 = time.monotonic()
while time.monotonic() - t0 < 20:
    s = q.state_of(it2.iid)
    if s and s["stage"] == "transcribing":
        pcts.append(s["pct"])
    if s and s["stage"] in ("done", "error"):
        break
    time.sleep(0.01)
chk("采集到多个进度值", len(set(pcts)) >= 3, sorted(set(pcts)))
chk("单调不减", all(pcts[i] <= pcts[i + 1] for i in range(len(pcts) - 1)), pcts[:20])

print("== 5. 降级：缺 API Key -> 转写照做、raw 落盘、不清洗、不崩 ==")
store.save_settings({"clean_api_key": ""})
it3 = store.add_item("f.mp4")
make_media("f.mp4")
st._items[it3.iid] = it3
st.pending.append(it3)
st.start_processing(it3.iid)
ok5 = wait_for(lambda: (q.state_of(it3.iid) or {}).get("stage") in
               ("transcribed", "error", "done"), 20, "缺 Key")
s = q.state_of(it3.iid) or {}
chk("停在 transcribed", s.get("stage") == "transcribed", s)
chk("raw 已落盘", store.has_raw(it3.base))
chk("cleaned 没落盘", store.has_cleaned(it3.base) is False)
chk("error 说明缺 Key", "API Key" in (s.get("error") or ""), s.get("error"))

print("== 6. VAD 全过滤 -> 明确报错，不当成功 ==")
transcriber.transcribe_video_iter = fake_iter_empty
it4 = store.add_item("g.mp4")
make_media("g.mp4")
st._items[it4.iid] = it4
st.pending.append(it4)
st.start_processing(it4.iid)
wait_for(lambda: (q.state_of(it4.iid) or {}).get("stage") in ("error", "done"), 20, "空分段")
s4 = q.state_of(it4.iid) or {}
chk("stage=error", s4.get("stage") == "error", s4)
chk("错误说明是未识别到语音", "未识别到语音" in (s4.get("error") or ""), s4.get("error"))
chk("没有写出空 raw", store.has_raw(it4.base) is False)
transcriber.transcribe_video_iter = fake_iter

print("== 7. 清洗抛异常 -> stage=error，原因带出来 ==")
store.save_settings({"clean_api_key": "sk-fake"})


def boom(*a, **kw):
    raise ValueError("模拟清洗服务 500")


ai_processor.process_segments = boom
it5 = store.add_item("h.mp4")
make_media("h.mp4")
st._items[it5.iid] = it5
st.pending.append(it5)
st.start_processing(it5.iid)
wait_for(lambda: (q.state_of(it5.iid) or {}).get("stage") in ("error", "done"), 20, "清洗失败")
s5 = q.state_of(it5.iid) or {}
chk("stage=error", s5.get("stage") == "error", s5)
chk("原因里带异常类型", "模拟清洗服务 500" in (s5.get("error") or ""), s5.get("error"))
chk("raw 仍然保留（转写成果不丢）", store.has_raw(it5.base))
chk("cleaned 没有", store.has_cleaned(it5.base) is False)
ai_processor.process_segments = fake_clean

print("== 8. 取消：排队中的能取消，进行中的能叫停 ==")
it6 = store.add_item("i.mp4")
make_media("i.mp4")
it7 = store.add_item("j.mp4")
make_media("j.mp4")
for x in (it6, it7):
    st._items[x.iid] = x
    st.pending.append(x)
st.start_processing(it6.iid)
st.start_processing(it7.iid)
q.cancel(it7.iid)
chk("被取消的离开排队列表", it7.iid not in q._order, q._order)
wait_for(lambda: (q.state_of(it7.iid) or {}).get("stage") in ("idle",), 10, "取消生效")
chk("取消后回到 idle（不是 error）", q.state_of(it7.iid)["stage"] == "idle",
    q.state_of(it7.iid))
chk("取消的那条没有产物", store.has_raw(it7.base) is False)
wait_for(lambda: store.has_cleaned(it6.iid and it6.base), 20, "前一条照常跑完")
chk("没被取消的那条正常完成", store.has_cleaned(it6.base))

it8 = store.add_item("k.mp4")
make_media("k.mp4")
st._items[it8.iid] = it8
st.pending.append(it8)
st.start_processing(it8.iid)
time.sleep(0.03)
q.cancel(it8.iid)
wait_for(lambda: (q.state_of(it8.iid) or {}).get("stage") == "idle", 15, "进行中取消")
chk("进行中的也能叫停", q.state_of(it8.iid)["stage"] == "idle", q.state_of(it8.iid))

print("== 9. WebState 读取：状态与进度来自队列 ==")
st2 = web_state.WebState()
st2.jobs = q
it9 = store.add_item("m.mp4")
make_media("m.mp4")
st2._items[it9.iid] = it9
st2.pending.append(it9)
st2.start_processing(it9.iid)
chk("WebState 提交后 stage=queued", st2.item(it9.iid).stage == "queued")
st2.tick()
chk("tick 后仍是真实状态", st2.item(it9.iid).stage in
    ("queued", "loading", "transcribing"), st2.item(it9.iid).stage)


def pumped_done():
    # WebState 只在 tick()/poll() 时刷新 —— 这正是界面的节奏，
    # 所以等待循环里必须跟着 tick，否则等的是个永远不更新的快照。
    st2.tick()
    return st2.item(it9.iid).stage == "done"


chk("轮询驱动下最终 done", wait_for(pumped_done, 20, "跑完"), st2.item(it9.iid).stage)
chk("★ 清洗完成后从待处理移到已完成", it9.iid in [x.iid for x in st2.done],
    [x.title for x in st2.done])
chk("不在待处理里了", it9.iid not in [x.iid for x in st2.pending])

# ============================================================ 10~12 真生成
# 前面几节的素材是 1KB 的假文件（转写不需要真视频）。裁剪/合并要真 ffmpeg，
# 所以这里现造几段小视频 —— 160x120、2 秒，编得很快。
import video_ops     # noqa: E402
import proc          # noqa: E402


def make_video(name, secs=3, hue=0):
    out = store.media_path(name)
    cmd = [video_ops.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc=s=160x120:r=10:d=%d" % secs,
           "-f", "lavfi", "-i", "sine=frequency=%d:duration=%d" % (300 + hue, secs),
           "-vf", "hue=h=%d" % hue, "-c:v", "libx264", "-preset", "ultrafast",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
           "-t", str(secs), out]
    r = proc.run(cmd, capture_output=True, text=True,
                 encoding="utf-8", errors="replace", timeout=120)
    if r.returncode != 0:
        raise SystemExit("造视频失败 %s: %s" % (name, r.stderr[:300]))
    return out


def pump(cond, sec, label):
    """等后台任务跑完 —— 必须**跟着 tick**，和界面的节奏一致。"""
    t0 = time.monotonic()
    while time.monotonic() - t0 < sec:
        st2.tick()
        if cond():
            return True
        time.sleep(0.05)
    print("    （等超时：%s）" % label)
    return False


print("== 10. 裁剪任务（保存为新片段）：真出文件 ==")
make_video("src1.mp4", 3, 0)
it10 = store.add_item("src1.mp4", "", media_name="src1.mp4")
it10.iid = store.new_iid()
st2._items[it10.iid] = it10
st2.pending.append(it10)

chk("提交裁剪返回成功", st2.submit_clip(it10.iid, 0.5, 1.5, False))
chk("提交后 stage=queued", it10.stage == "queued", it10.stage)


def clip_appeared():
    return any(x.origin == "clip" for x in st2.pending)


chk("★ 裁剪跑完，列表里出现 origin=clip 的新条目",
    pump(clip_appeared, 60, "裁剪"), [x.title for x in st2.pending])
newc = [x for x in st2.pending if x.origin == "clip"][0] if clip_appeared() else None
if newc:
    p = store.media_path(newc.media_name)
    chk("★ 裁剪产物真的落盘了", os.path.isfile(p) and os.path.getsize(p) > 0, p)
    cst = video_ops.probe(p) or {}
    cdur = cst.get("duration") or 0
    chk("★ 裁剪时长准（1.0s ±0.25）", abs(cdur - 1.0) <= 0.25, cdur)
    chk("产物有视频流", bool(cst.get("video")), cst.get("video"))
    chk("区间记在了条目上（合并要复用）",
        newc.clips and abs(newc.clips[0]["start"] - 0.5) < 0.01
        and abs(newc.clips[0]["end"] - 1.5) < 0.01, newc.clips)
    chk("任务跑完条目回到 idle（不是永远 done）", it10.stage == "idle", it10.stage)
    chk("合并时能看见「刚做完」事件",
        bool(st2.last_event and "片段" in st2.last_event["text"]),
        st2.last_event)
else:
    for n in ("★ 裁剪产物真的落盘了", "★ 裁剪时长准（1.0s ±0.25）",
              "产物有视频流", "区间记在了条目上（合并要复用）",
              "任务跑完条目回到 idle（不是永远 done）"):
        chk(n, False, "上一条已失败")

print("== 11. 覆盖原视频：先备份、再替换、旧产物归档 ==")
make_video("src2.mp4", 3, 90)
it11 = store.add_item("src2.mp4", "", media_name="src2.mp4")
it11.iid = store.new_iid()
st2._items[it11.iid] = it11
# 造一份"已完成"的样子：raw + cleaned 都在
store.write_raw(it11.base, [{"start": 0, "end": 1, "text": "旧内容"}])
store.write_cleaned(it11.base, "旧的清洗稿", store.make_meta("src2.mp4", "src2.mp4", "", ""))
store.refresh_status(it11)
st2.done.append(it11)
orig_size = os.path.getsize(store.media_path("src2.mp4"))

chk("提交覆盖返回成功", st2.submit_clip(it11.iid, 0.5, 1.5, True))
chk("★ 覆盖后被移回待处理", pump(lambda: it11 in st2.pending, 60, "覆盖"),
    [x.title for x in st2.pending])


def backups():
    d = store.BACKUP_DIR
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


chk("★ 原文件已备份到 data/backups/", any(f.startswith("src2.") for f in backups()),
    backups())
bk = [f for f in backups() if f.startswith("src2.")]
if bk:
    chk("★ 备份大小和原文件一致",
        os.path.getsize(os.path.join(store.BACKUP_DIR, bk[0])) == orig_size,
        "%s vs %s" % (os.path.getsize(os.path.join(store.BACKUP_DIR, bk[0])),
                      orig_size))
now_dur = video_ops.duration_of(store.media_path("src2.mp4"))
chk("★ 原文件已被替换成裁剪结果（1.0s ±0.25，原为 3s）",
    abs(now_dur - 1.0) <= 0.25, now_dur)
chk("★ 旧的转写产物已挪进 _stale（状态自然回到未处理）",
    not store.has_raw(it11.base) and not store.has_cleaned(it11.base),
    (store.has_raw(it11.base), store.has_cleaned(it11.base)))
stale = os.listdir(store.STALE_DIR) if os.path.isdir(store.STALE_DIR) else []
chk("★ 归档不是删除（_stale 里找得到）", len(stale) >= 3, stale)
chk("条目回到未处理状态", it11.transcribed is False and it11.ai_processed is False)
chk("overwrite 标记已复位", it11.overwrite is False)

print("== 12. 合并任务：真出文件 ==")
make_video("m1.mp4", 2, 0)
make_video("m2.mp4", 2, 120)
iid12 = st2.submit_merge([
    {"media": "media/m1.mp4", "start": 0.0, "end": 2.0},
    {"media": "media/m2.mp4", "start": 0.0, "end": 2.0},
])
chk("提交合并返回了新条目 id", bool(iid12), iid12)
it12 = st2.item(iid12) if iid12 else None
chk("占位条目立刻就在列表里（看得见进度）",
    it12 is not None and it12 in st2.pending, it12 and it12.title)


def merge_done():
    return bool(it12 and it12.media_name
                and os.path.isfile(store.media_path(it12.media_name))
                and it12.stage == "idle")


chk("★ 合并跑完，产物落盘", pump(merge_done, 90, "合并"),
    it12 and it12.title)
if it12:
    mp = store.media_path(it12.media_name)
    chk("★ 合并产物真的存在", os.path.isfile(mp) and os.path.getsize(mp) > 0, mp)
    mst = video_ops.probe(mp) or {}
    mdur = mst.get("duration") or 0
    chk("★ 合并时长 = 两段之和（4.0s ±0.8）", abs(mdur - 4.0) <= 0.8, mdur)
    chk("产物有视频流", bool(mst.get("video")), mst.get("video"))
    chk("占位条目被正名（media_name 指向真产物）",
        it12.media_name.endswith(".mp4") and os.path.isfile(mp), it12.media_name)
    chk("区间链记在条目上", len(it12.clips) == 2, it12.clips)
    chk("合并事件带段数", bool(st2.last_event
                              and "合并" in st2.last_event["text"]),
        st2.last_event)
else:
    for n in ("★ 合并产物真的存在", "★ 合并时长 = 两段之和（4.0s ±0.8）"):
        chk(n, False, "上一条已失败")

print("== 13. 失败要落到 error，且不留半截产物 ==")
it13 = store.add_item("没有这个文件.mp4", "", media_name="没有这个文件.mp4")
it13.iid = store.new_iid()
st2._items[it13.iid] = it13
st2.pending.append(it13)
chk("提交会失败的任务", st2.submit_clip(it13.iid, 0, 1, False))


def clip_failed():
    s = q.state_of(it13.iid)
    return bool(s) and s.get("stage") == "error"


chk("★ 失败落到 error", pump(clip_failed, 30, "失败"), q.state_of(it13.iid))
chk("错误原因带出来了",
    "VideoOpError" in ((q.state_of(it13.iid) or {}).get("error") or ""),
    (q.state_of(it13.iid) or {}).get("error"))
chk("待处理列表里没有被误加成新条目",
    not any(x.origin == "clip" and "没有这个文件" in x.title for x in st2.pending))

print("== 14. 事件必须让 poll() 报 changed（摄像头那次的坑）==")
# 摄像头导入是在**监视线程**里完成的，它只写 WebState 的字段、没碰队列。
# 结果 poll() 永远报 changed=False，前端拿不到结果 —— e2e 一直等到超时，
# 而文件其实早就导进来了。所以 _emit 必须敲一下队列。
q.changed()                                   # 先把脏位清掉
st2._emit("测试事件：已导入 1 段录制",
          imported=[{"iid": "x", "mediaName": "y.mp4"}])
chk("★ _emit 之后 poll() 会报 changed=True（否则前端收不到结果）",
    q.changed() is True)
ev1 = dict(st2.last_event)
chk("★ 事件里带了 imported（前端靠它排队弹命名框）",
    isinstance(ev1.get("imported"), list) and ev1["imported"]
    and ev1["imported"][0]["mediaName"] == "y.mp4", ev1)
chk("事件带 seq 和 text", bool(ev1.get("seq")) and bool(ev1.get("text")), ev1)
st2._emit("第二条")
chk("连发两次事件也照样报 changed", q.changed() is True)
chk("seq 是递增的（前端靠它判新旧）",
    st2.last_event["seq"] > ev1["seq"], (ev1["seq"], st2.last_event["seq"]))

q.stop()
shutil.rmtree(TMP, ignore_errors=True)
print("\n结果：%d 通过，%d 失败" % (ok, len(bad)))
if bad:
    print("失败项：" + ", ".join(bad))
sys.exit(1 if bad else 0)
