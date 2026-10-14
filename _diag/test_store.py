# -*- coding: utf-8 -*-
"""持久层单测（真实链路，不需要 GPU / API Key）。

在**临时目录**里跑，不碰项目真实的 data/。
重点验：原子写、raw 不被清洗稿覆盖、持久 id 刷新后不变、导入去重。
"""

import json
import os
import shutil
import sys
import tempfile

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)
os.environ.pop("VKB_FAKE", None)          # 明确走真实链路

TMP = tempfile.mkdtemp(prefix="vkb_store_test_")

import config         # noqa: E402
import store          # noqa: E402
import web_state      # noqa: E402
from ui_model import UINode   # noqa: E402

store.BASE_DIR = TMP
store.DATA_DIR = os.path.join(TMP, "data")
store.MEDIA_DIR = os.path.join(store.DATA_DIR, "media")
store.RAW_DIR = os.path.join(store.DATA_DIR, "raw_transcripts")
store.AI_DIR = os.path.join(store.DATA_DIR, "ai_processed")
# 备份/归档目录同样是模块级全局，漏改会往真实的 data/ 下写
store.BACKUP_DIR = os.path.join(store.DATA_DIR, "backups")
store.STALE_DIR = os.path.join(store.DATA_DIR, "_stale")
store.WORKSPACE_FILE = os.path.join(store.DATA_DIR, "workspace.json")
store.TREE_FILE = os.path.join(store.DATA_DIR, "knowledge_tree.json")

# 【必须】config 的路径是 import 时算出来的，不重定向的话 save_settings 会写到
# **项目真实的 data/config.json**（第一版就踩了：把 clean_model 改成了 unit-test-model）。
config.DATA_DIR = store.DATA_DIR
config.CONFIG_FILE = os.path.join(store.DATA_DIR, "config.json")

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


def make_src(name, size=2048):
    """源文件要**保留原文件名** —— import_media 取 basename，加了前缀就测不到真名。"""
    d = os.path.join(TMP, "src")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(b"x" * size)
    return p


print("== 0. 隔离自检：所有写入都必须落在临时目录 ==")
REAL_DATA = os.path.join(os.path.dirname(SRC), "data")
for label, p in (("store.WORKSPACE_FILE", store.WORKSPACE_FILE),
                 ("store.MEDIA_DIR", store.MEDIA_DIR),
                 ("store.RAW_DIR", store.RAW_DIR),
                 ("store.AI_DIR", store.AI_DIR),
                 ("store.TREE_FILE", store.TREE_FILE),
                 ("config.CONFIG_FILE", config.CONFIG_FILE)):
    chk("%s 在临时目录" % label, os.path.abspath(p).startswith(TMP) and
        not os.path.abspath(p).startswith(REAL_DATA), p)

print("== 1. 导入：复制进 media，重名加序号 ==")
store.ensure_dirs()
a1 = store.import_media(make_src("片子.mp4"))
chk("导入返回文件名", a1 == "片子.mp4", a1)
chk("文件真的落盘", os.path.isfile(store.media_path(a1)))
a2 = store.import_media(make_src("片子.mp4"))
chk("重名自动加序号", a2 == "片子_2.mp4", a2)
chk("两个文件都在", os.path.isfile(store.media_path(a1)) and os.path.isfile(store.media_path(a2)))

print("== 2. 条目清单：落盘 / 读回 / id 不变 ==")
it = store.add_item(a1, make_src("片子.mp4"))
it2 = store.add_item(a2)
store.save_items([it, it2])
back = store.load_items()
chk("读回 2 条", len(back) == 2, len(back))
chk("id 保持不变", sorted(x.iid for x in back) == sorted([it.iid, it2.iid]),
    [x.iid for x in back])
chk("media 是相对 URL", back[0].media.startswith("media/"), back[0].media)
chk("title_stem 去扩展名", back[0].title_stem == "片子", back[0].title_stem)

print("== 3. 原始转写：只写一次，清洗稿不许覆盖它 ==")
segs = [{"start": 0.0, "end": 1.5, "text": "原始第一句"},
        {"start": 1.5, "end": 3.0, "text": "原始第二句"}]
store.write_raw(it.base, segs)
raw_before = store.read_raw(it.base)
chk("raw 文本已写", raw_before == "原始第一句原始第二句", repr(raw_before))
chk("segments 是合法 JSON", store.read_segments(it.base) == segs)
chk("has_raw 为真", store.has_raw(it.base) is True)
chk("此时 has_cleaned 为假（还没清洗）", store.has_cleaned(it.base) is False)

store.write_cleaned(it.base, "清洗后的正文",
                    store.make_meta(it.video_name, it.media_name, it.src or "",
                                    store.cleaned_path(it.base)))
raw_after = store.read_raw(it.base)
chk("★ 清洗之后 raw 一字未变（老程序就栽在这）", raw_after == raw_before, repr(raw_after))
chk("清洗稿写在另一个目录", store.read_cleaned(it.base) == "清洗后的正文")
chk("has_cleaned 为真", store.has_cleaned(it.base) is True)

print("== 4. meta 字段齐全 ==")
meta = store.read_meta(it.base)
for k in ("title", "video_path", "cleaned_file", "created_time", "modified_at"):
    chk("meta 有 %s" % k, k in meta, list(meta))

print("== 5. 状态从磁盘推导（不回写状态位） ==")
store.refresh_status(it)
chk("transcribed 由文件推导", it.transcribed is True)
chk("ai_processed 由文件推导", it.ai_processed is True)
it2.refresh_status = None
store.refresh_status(it2)
chk("没产物的条目状态为假", it2.transcribed is False and it2.ai_processed is False)

print("== 5b. 改名不断链（media_name 与显示名解耦）==")
r_ = store.load_items()[0]
before_base = r_.base
before_media = r_.media
r_.video_name = "改过名的标题.mp4"          # 模拟用户改名
chk("改名后 base 不变（产物还找得到）", r_.base == before_base,
    "%s -> %s" % (before_base, r_.base))
chk("改名后 media 不变（还能播）", r_.media == before_media,
    "%s -> %s" % (before_media, r_.media))
chk("改名后 title_stem 跟着变（导图/列表要显示新名）",
    r_.title_stem == "改过名的标题", r_.title_stem)
store.save_items([r_, it2])          # 两条都写回，别把片子_2 冲掉
back2 = [x for x in store.load_items() if x.iid == r_.iid][0]
chk("★ 落盘再读回：media_name 保住了", back2.base == before_base,
    "%s -> %s" % (before_base, back2.base))
chk("★ 落盘再读回：显示名也保住了", back2.video_name == "改过名的标题.mp4",
    back2.video_name)
chk("★ 读回后状态仍由产物推导（没掉回未处理）",
    back2.transcribed is True and back2.ai_processed is True,
    (back2.transcribed, back2.ai_processed))

print("== 5c. 老记录迁移：缺 media_name 时从 src 推 ==")
rec = {"id": "iold1", "name": "怪物和人类的十大发",
       "src": os.path.join(TMP, "src", "片子.mp4"), "created": "", "clips": []}
mn = store.resolve_media_name(rec)
chk("★ 显示名不是真文件时，从 src 的 basename 推出来", mn == "片子.mp4", mn)
# 改回原名，后面的用例依赖"片子.mp4"这条
r_.video_name = "片子.mp4"
store.save_items([r_, it2])
chk("改回原名后 base 依然是同一个",
    [x for x in store.load_items() if x.iid == r_.iid][0].base == before_base)

rec2 = {"id": "iold2", "name": "片子_2.mp4", "src": "", "created": "", "clips": []}
chk("显示名本身就是真文件 -> 用它", store.resolve_media_name(rec2) == "片子_2.mp4",
    store.resolve_media_name(rec2))
rec3 = {"id": "iold3", "name": "查无此片.mp4", "src": "D:\\不存在\\查无此片.mp4",
        "created": "", "clips": []}
chk("★ 推不出来时返回 None（不猜，调用方原样保留）",
    store.resolve_media_name(rec3) is None, store.resolve_media_name(rec3))

print("== 6. 知识树：隐形根（多根）+ 持久 nid 刷新后不变 ==")
root = store.load_tree()
chk("★★ 空树返回的是**隐形根**（多根容器）", root.virtual is True, root.name)
chk("隐形根名字为空（界面上不画它）", root.name == "", repr(root.name))
nid_root = root.nid
chk("根有持久 id", bool(nid_root) and nid_root.startswith("n"), nid_root)
top = store.UINode("交易体系")
root.add(top)                      # 加到隐形根下 = 成为一个**顶层节点**
top.add(store.UINode("断板反包"))
store.assign_missing_nids(root)
store.save_tree(root)
root2 = store.load_tree()
chk("★ 刷新后还是隐形根（virtual 标记写进文件又读回来）",
    root2.virtual is True)
chk("刷新后根 id 不变", root2.nid == nid_root, "%s -> %s" % (nid_root, root2.nid))
chk("★★ 顶层节点挂在隐形根下 —— 这就是「多根」",
    len(root2.children) == 1 and root2.children[0].name == "交易体系",
    [c.name for c in root2.children])
alln = list(root2.walk())
chk("节点数对", len(alln) == 3, len(alln))
chk("每个节点都有 id", all(n.nid for n in alln), [n.nid for n in alln])
chk("两次加载 id 完全一致",
    [n.nid for n in alln] == [n.nid for n in store.load_tree().walk()])

print("== 6b. 老文件迁移：单个真根 -> 降级为顶层节点，一个都不丢 ==")
# 老格式：文件根是**真节点**「个人空间」（没有 virtual 标记）
old = store.UINode("个人空间")
old.nid = store.new_nid()
old.add(store.UINode("乒乓球"))
store._atomic_write_json(store.TREE_FILE, store._node_to_dict(old))
mig = store.load_tree()
chk("★★ 读老文件 -> 套了一层隐形根", mig.virtual is True)
chk("★★ 老的根降级成**顶层节点**（没被丢掉）",
    len(mig.children) == 1 and mig.children[0].name == "个人空间",
    [c.name for c in mig.children])
chk("★ 它下面的东西原样还在",
    [c.name for c in mig.children[0].children] == ["乒乓球"],
    [c.name for c in mig.children[0].children])
chk("★ 迁移后 total = 3（隐形根 + 个人空间 + 乒乓球）",
    sum(1 for _ in mig.walk()) == 3, sum(1 for _ in mig.walk()))

print("== 7. 原子写：不留半截文件 ==")
leftovers = []
for d in (store.DATA_DIR, store.RAW_DIR, store.AI_DIR, store.MEDIA_DIR):
    for f in os.listdir(d):
        if f.startswith(".vkb-") or f.startswith(".import-"):
            leftovers.append(os.path.join(d, f))
chk("没有残留临时文件", not leftovers, leftovers)

print("== 8. WebState 真实模式：结构不变、数据来自磁盘 ==")
st = web_state.WebState()
chk("不是假链路", st.fake is False)
snap = st.snapshot()
for k in ("tree", "done", "pending", "settings"):
    chk("snapshot 有 %s" % k, k in snap)
chk("已完成 = 有清洗稿的那条", [x["title"] for x in snap["done"]] == ["片子.mp4"],
    [x["title"] for x in snap["done"]])
chk("待处理 = 没清洗稿的那条", [x["title"] for x in snap["pending"]] == ["片子_2.mp4"],
    [x["title"] for x in snap["pending"]])
d0 = snap["done"][0]
for k in ("id", "title", "titleStem", "media", "clips", "origin", "overwrite",
          "stage", "transcribePct", "cleanPct", "transcribed", "aiProcessed", "error"):
    chk("item_dict 有 %s" % k, k in d0, sorted(d0))
chk("inTree 由树推导（还没挂，应为 False）",
    st.item_dict(st.done[0], True)["inTree"] is False)

print("== 9. 正文：有清洗稿用清洗稿 ==")
st2 = web_state.WebState()
body = st2.node_body(store.UINode("x", "video", item_id=st2.done[0].iid))
chk("内容节点正文 = 清洗稿", body == "清洗后的正文", repr(body))

print("== 10. 设置读写走真 config.json（合并写） ==")
s = store.load_settings()
chk("默认值齐全", all(k in s for k in ("whisper_model", "clean_url", "clean_model",
                                       "clean_prompt", "clean_api_key")), sorted(s))
saved = store.save_settings({"clean_model": "unit-test-model"})
chk("写入生效", saved["clean_model"] == "unit-test-model")
chk("其它键没被清掉（合并写）", bool(saved["clean_url"]) and bool(saved["clean_prompt"]))
chk("文件真的写了", os.path.isfile(os.path.join(TMP, "data", "config.json")))

print("== 11. 备份与归档（「覆盖原视频」的两道保险） ==")
os.makedirs(store.MEDIA_DIR, exist_ok=True)
with open(store.media_path("orig.mp4"), "wb") as f:
    f.write(b"ORIGINAL-BYTES" * 100)
bk = store.backup_media("orig.mp4")
chk("备份文件建出来了", os.path.isfile(bk), bk)
chk("★ 备份落 data/backups/ 下", os.path.dirname(bk) == store.BACKUP_DIR, bk)
chk("★ 备份内容与原文件逐字节一致",
    open(bk, "rb").read() == open(store.media_path("orig.mp4"), "rb").read())
chk("原文件没被动过（备份不是搬走）",
    os.path.isfile(store.media_path("orig.mp4")))
bk2 = store.backup_media("orig.mp4")
chk("★ 同一秒内连备两次不会互相覆盖", bk2 != bk and os.path.isfile(bk2),
    (os.path.basename(bk), os.path.basename(bk2)))

try:
    store.backup_media("根本不存在.mp4")
    chk("★ 备份失败必须抛（不能静默返回，那样会继续去覆盖原文件）", False, "没抛")
except FileNotFoundError as e:
    chk("★ 备份失败必须抛（不能静默返回，那样会继续去覆盖原文件）",
        "不存在" in str(e), str(e)[:60])

# 归档：产物挪走而不是删掉，状态自然回到"未处理"
store.write_raw("orig", [{"start": 0, "end": 1, "text": "旧转写"}])
store.write_cleaned("orig", "旧清洗稿", {"title": "orig"})
chk("归档前：产物都在", store.has_raw("orig") and store.has_cleaned("orig"))
n_moved = store.archive_artifacts("orig")
chk("★ 归档挪走了 4 个产物文件", n_moved == 4, n_moved)
chk("★ 归档后状态自然回到未处理",
    not store.has_raw("orig") and not store.has_cleaned("orig"))
stale = sorted(os.listdir(store.STALE_DIR))
chk("★ 是挪走不是删除（_stale 里找得到 4 个）", len(stale) == 4, stale)
chk("归档的文件名带时间戳（可回溯是哪一次覆盖）",
    all("." in f for f in stale), stale)
chk("对没有产物的条目归档不报错", store.archive_artifacts("没有产物") == 0)

print("== 12. 写盘轮转（每次覆盖前把上一版留成 .bak） ==")
# 起点必须干净：**基础文件和 .bak 都要清掉**。
# 前面小节已经写过 workspace.json，不清的话"第一次写"也会轮转出 .bak，
# 断言就不确定了（第一版就是这么挂的）。
for f in os.listdir(store.DATA_DIR):
    if ".bak-" in f or f in ("workspace.json", "knowledge_tree.json"):
        os.remove(os.path.join(store.DATA_DIR, f))

store.save_items([store.add_item("轮转A.mp4"), store.add_item("轮转B.mp4")])
chk("第一次写：本来没有上一版，不产生 .bak",
    not [f for f in os.listdir(store.DATA_DIR)
         if f.startswith("workspace.json.bak-")])

store.save_items([store.add_item("轮转C.mp4")])
baks = sorted(f for f in os.listdir(store.DATA_DIR)
              if f.startswith("workspace.json.bak-"))
chk("★ 第二次写：上一版被留成 .bak", len(baks) == 1, baks)

with open(os.path.join(store.DATA_DIR, baks[-1]), encoding="utf-8") as f:
    prev = json.load(f)
chk("★★ .bak 里保住了这次写丢掉的条目（这就是「一键回退」）",
    {i["name"] for i in prev["items"]} >= {"轮转A.mp4", "轮转B.mp4"},
    [i["name"] for i in prev["items"]])

root = UINode("根")
root.add(UINode("甲", "topic"))
store.save_tree(root)
store.save_tree(UINode("根"))                  # 这一写把「甲」丢了
tbaks = sorted(f for f in os.listdir(store.DATA_DIR)
               if f.startswith("knowledge_tree.json.bak-"))
chk("★ 树覆盖前也留上一版", len(tbaks) >= 1, tbaks)
with open(os.path.join(store.DATA_DIR, tbaks[-1]), encoding="utf-8") as f:
    tprev = f.read()
chk("★★ 树 .bak 里还找得到被这次写丢掉的节点「甲」",
    "甲" in tprev)

for _ in range(store.BACKUP_KEEP + 4):
    store.save_tree(root)
tbaks = [f for f in os.listdir(store.DATA_DIR)
         if f.startswith("knowledge_tree.json.bak-")]
chk("★ 只保留最近 %d 份，不会无限涨" % store.BACKUP_KEEP,
    len(tbaks) <= store.BACKUP_KEEP, len(tbaks))

print("== 13. 转写产物覆盖前也要留上一版 ==")
# 这一节盯的是**真正丢过的那类文件**：raw_transcripts/*.txt、*_segments.json、
# ai_processed/*_cleaned.txt、*_meta.json。
# 它们以前是**唯一一份**：重转写 / 重跑清洗会直接盖掉上一稿，没有任何回溯。
store.write_raw("轮转转写", [{"start": 0, "end": 1, "text": "第一次转写"}])
chk("第一次写 raw：本来没有上一版，不产生 .bak",
    not [f for f in os.listdir(store.RAW_DIR)
         if f.startswith("轮转转写") and ".bak-" in f],
    os.listdir(store.RAW_DIR))

store.write_raw("轮转转写", [{"start": 0, "end": 1, "text": "第二次转写"}])
rb_txt = [f for f in os.listdir(store.RAW_DIR)
          if f.startswith("轮转转写.txt.bak-")]
rb_seg = [f for f in os.listdir(store.RAW_DIR)
          if f.startswith("轮转转写_segments.json.bak-")]
chk("★ 第二次写 raw：txt 与 segments 各留一份 .bak",
    len(rb_txt) == 1 and len(rb_seg) == 1, (rb_txt, rb_seg))
with open(os.path.join(store.RAW_DIR, rb_txt[0]), encoding="utf-8") as f:
    prev = f.read()
chk("★★ .bak 里是**第一次**的稿子（重转写没把上一次吃掉）",
    "第一次转写" in prev and "第二次转写" not in prev, prev[:40])
chk("当前稿是第二次的", "第二次转写" in store.read_raw("轮转转写"))

store.write_cleaned("轮转转写", "第一次清洗稿", {"title": "轮转转写"})
store.write_cleaned("轮转转写", "第二次清洗稿", {"title": "轮转转写"})
cb = [f for f in os.listdir(store.AI_DIR)
      if f.startswith("轮转转写_cleaned.txt.bak-")]
mb = [f for f in os.listdir(store.AI_DIR)
      if f.startswith("轮转转写_meta.json.bak-")]
chk("★ 清洗稿覆盖前也留上一版（cleaned + meta 各一份）",
    len(cb) == 1 and len(mb) == 1, (cb, mb))
with open(os.path.join(store.AI_DIR, cb[0]), encoding="utf-8") as f:
    cprev = f.read()
chk("★★ 上一版清洗稿内容完整（可一键回退）",
    cprev == "第一次清洗稿", cprev[:40])
chk("清洗覆盖后 raw 没被动过（两条硬规矩之一）",
    "第二次转写" in store.read_raw("轮转转写"))

print("== 14. 「出队」标记能落盘、能读回（预处理队列用）==")
# 「出队」= 用户在预处理列表里点 ✕（只出队，什么都不删）。
# 这个位**必须持久** —— 不落盘的话，重启一次它自己就回队列了，
# 用户会觉得"我移除过的东西又冒出来了"。
_dq = store.add_item("出队探针.mp4")
store.save_items([_dq])
_b1 = store.load_items()
chk("★ 新条目默认没出队（老记录也一样 —— 缺键就是 False）",
    _b1 and _b1[0].dequeued is False, _b1[0].dequeued if _b1 else None)
_dq.dequeued = True
store.save_items([_dq])
_b2 = store.load_items()
chk("★★ 出队位落盘后读回来还是 True", _b2 and _b2[0].dequeued is True,
    _b2[0].dequeued if _b2 else None)
chk("★ 出队不影响别的字段（名字/真实文件名都没动）",
    _b2 and _b2[0].video_name == "出队探针.mp4"
    and _b2[0].media_name == _dq.media_name,
    (_b2[0].video_name, _b2[0].media_name) if _b2 else None)
with open(store.WORKSPACE_FILE, encoding="utf-8") as _f:
    _raw = json.load(_f)
chk("★ 落盘的是显式布尔值（不是「没出队就不写」）",
    all("dequeued" in r and isinstance(r["dequeued"], bool)
        for r in _raw["items"]),
    [r.get("dequeued") for r in _raw["items"]])

print("== 15. 导入：每次状态变化都要**主动**打 changed ==")
# 导入**不是队列任务**（只写 import_status，一个字节的队列状态都没动）。
# 以前靠"轮询恰好撞上它 active 的那一小段"来让界面刷新 —— 复制比两次轮询
# （120ms）还快、或者文件对话框把 UI 线程堵住让轮询积压，就会一次都没撞上，
# 前端整包收不到（用户看到："导入一个不显示，再导一个一起冒出来"）。
# 现在在**每次状态变化**处主动打一下 jobs.touch()。
import threading                                             # noqa: E402
import time                                                  # noqa: E402


class _FakeJobs:
    """只数 touch 次数。changed() 恒 False —— 模拟"队列侧一点变化都没有"。"""

    def __init__(self):
        self.n = 0
        self._lk = threading.Lock()

    def touch(self):
        with self._lk:
            self.n += 1

    def changed(self):
        return False

    def state_of(self, iid):
        return None

    def active_count(self):
        return 0


_st = web_state.WebState()
_st.jobs = _FakeJobs()
_before = len(_st.pending)
_src = make_src("导入探针.mp4")
chk("start_import 接下了这个活", _st.start_import([_src]) is True)
for _ in range(200):                       # 最多等 10 秒
    if not _st.import_status.get("active"):
        break
    time.sleep(0.05)
chk("★ 导入跑完（active 回到 False）", _st.import_status.get("active") is False)
chk("★★ 全程主动打了 changed —— 不再依赖「恰好被轮询撞上」",
    _st.jobs.n >= 3, "touch 了 %d 次" % _st.jobs.n)
chk("★ 没报错", not _st.import_status.get("error"), _st.import_status.get("error"))
chk("★ 新条目进了台账", len(_st.pending) == _before + 1,
    "%d -> %d" % (_before, len(_st.pending)))
_newit = _st.pending[-1]
chk("★ 视频真复制进了 media（不是原地引用）",
    os.path.isfile(store.media_path(_newit.media_name)), _newit.media_name)
chk("★ 复制内容逐字节一致",
    open(store.media_path(_newit.media_name), "rb").read() == open(_src, "rb").read())

shutil.rmtree(TMP, ignore_errors=True)
print("\n结果：%d 通过，%d 失败" % (ok, len(bad)))
if bad:
    print("失败项：" + ", ".join(bad))
sys.exit(1 if bad else 0)
