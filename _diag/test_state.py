# -*- coding: utf-8 -*-
"""数据层单测：裁剪 / 合并的新字段与新方法。不依赖界面。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
os.environ.setdefault("VKB_FAKE", "1")     # 数据层单测只针对假链路

import web_state  # noqa: E402
import store  # noqa: E402

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


def _tree_sig(root):
    """树结构的指纹：(名字, 层级) 列表 —— 用来断言"结构一点没变"。"""
    out = []

    def w(n, dep):
        out.append((n.name, dep))
        for c in n.children:
            w(c, dep + 1)

    w(root, 0)
    return out


s = web_state.WebState()
p0 = s.pending[0]
iid = p0.iid
src_media = p0.media

print("== 1. 条目默认字段 ==")
d = s.item_dict(p0)
chk("origin 默认 source", d["origin"] == "source", d["origin"])
chk("overwrite 默认 False", d["overwrite"] is False, d["overwrite"])
chk("clips 默认空", d["clips"] == [], d["clips"])

print("== 2. 保存为新片段 ==")
n_before = len(s.pending)
nid, created = s.save_clip(iid, 1.5, 4.5, overwrite=False)
chk("返回了新 id", nid is not None and nid != iid, nid)
chk("created=True", created is True, created)
chk("pending 多了一条", len(s.pending) == n_before + 1, len(s.pending))
new = s.item(nid)
chk("origin=clip", new.origin == "clip", new.origin)
chk("名字带 _clip", "_clip" in new.title, new.title)
chk("clips 正确", new.clips == [{"media": src_media, "start": 1.5, "end": 4.5}], new.clips)
orig = s.item(iid)
chk("原条目不动", orig.clips == [] and orig.overwrite is False, (orig.clips, orig.overwrite))

print("== 3. 覆盖原视频 ==")
n_before = len(s.pending)
oid, created2 = s.save_clip(iid, 2.0, 6.0, overwrite=True)
chk("返回原 id", oid == iid, oid)
chk("created=False", created2 is False, created2)
chk("pending 数量不变", len(s.pending) == n_before, len(s.pending))
chk("overwrite=True", orig.overwrite is True, orig.overwrite)
chk("clips 被写上", orig.clips == [{"media": src_media, "start": 2.0, "end": 6.0}], orig.clips)

print("== 4. 非法裁剪被拒 ==")
chk("end<=start 拒绝", s.save_clip(iid, 5.0, 5.0)[0] is None)
chk("负数拒绝", s.save_clip(iid, -1.0, 3.0)[0] is None)

print("== 5. 合并导出 ==")
segs = [
    {"media": "media/sample_01.mp4", "start": 0, "end": 3},
    {"media": "media/sample_02.mp4", "start": 1, "end": 4},
    {"media": "media/sample_03.mp4", "start": 2, "end": 8},
]
n_before = len(s.pending)
mid = s.make_merge(segs)
chk("返回 id", mid is not None, mid)
chk("pending 多了一条", len(s.pending) == n_before + 1, len(s.pending))
mi = s.item(mid)
chk("origin=merge", mi.origin == "merge", mi.origin)
chk("名字带 合并_", mi.title.startswith("合并_"), mi.title)
chk("有序片段原样保留", mi.clips == [dict(x, start=float(x["start"]), end=float(x["end"])) for x in segs], mi.clips)

print("== 6. 合并片段不足被拒 ==")
chk("1 段拒绝", s.make_merge(segs[:1]) is None)

print("== 7. 同名加序号 ==")
a = s.save_clip(nid, 0.5, 1.5, overwrite=False)[0]
b = s.save_clip(nid, 0.6, 1.6, overwrite=False)[0]
titles = [s.item(a).title, s.item(b).title]
chk("两条标题不同", titles[0] != titles[1], titles)

print("== 8. 合并产物不进树（inTree=False）==")
chk("inTree 为 False", s.item_dict(mi, True)["inTree"] is False)

print("== 9. 快照带新字段 ==")
snap = s.snapshot()
chk("pending 条目都有 origin", all("origin" in x and "overwrite" in x for x in snap["pending"]))
chk("done 条目都有 origin", all("origin" in x for x in snap["done"]))

print("== 10. 桥接层：失败要说清原因 + 写盘失败必须可见 ==")
import web_bridge                                   # noqa: E402
br = web_bridge.WebBridge(s)

r = br.add_content_node(s.tree.nid, "i根本不存在")
chk("★ 加不存在的条目 -> ok=False", r["ok"] is False)
chk("★ 原因区分出来了 reason=item-missing", r.get("reason") == "item-missing",
    r.get("reason"))
chk("★ 文案说的是真原因，不是「已经在树里了」",
    "找不到" in (r.get("error") or ""), r.get("error"))

free = [i for i in (list(s.done) + list(s.pending))
        if s.find_node_by_item(i.iid) is None]
chk("假数据里有可加的条目（否则下面两条测不到）", bool(free), len(free))
if free:
    r2 = br.add_content_node(s.tree.nid, free[0].iid)
    chk("★ 正常加节点 -> ok=True 且带回 newId",
        r2["ok"] is True and bool(r2.get("newId")))
    r3 = br.add_content_node(s.tree.nid, free[0].iid)
    chk("★ 重复加 -> reason=already（这一种才该说「已经在树里了」）",
        r3["ok"] is False and r3.get("reason") == "already", r3.get("reason"))

# 写盘失败：必须 ok=False + 带原因。以前 persist_all() 一抛异常就直接冒出去，
# 前端 .then 链没有 catch，会被静默吞掉 —— 用户以为改动生效了。
_orig = s.persist_all


def _boom():
    raise RuntimeError("模拟磁盘写不进去")


s.persist_all = _boom
r4 = br._wrap(True)
chk("★★ 写盘失败 -> ok=False（不许装作成功）", r4["ok"] is False)
chk("★★ 写盘失败 -> reason=save-failed",
    r4.get("reason") == "save-failed", r4.get("reason"))
chk("★★ 写盘失败 -> 文案带上真实异常（用户看得见为什么）",
    "模拟磁盘写不进去" in (r4.get("error") or ""), r4.get("error"))
s.persist_all = _orig
chk("恢复后 -> ok=True（确认上面没把状态弄坏）", br._wrap(True)["ok"] is True)

print("== 11. 删除条目：记录 / 导图节点 / 内存态 一起清 ==")
# 假链路**不碰磁盘**（归档那步被 self.fake 挡掉），所以这套不用重定向 store
# 路径也能安全跑 —— 它不会去动项目真实的 data/。
target = s.done[0] if s.done else None
chk("假数据里有一条可删的 done 条目", target is not None, len(s.done))
if target:
    br.add_content_node(s.tree.nid, target.iid)
    node = s.find_node_by_item(target.iid)
    chk("先把它挂到树上（前置）", node is not None)
    nid = node.nid if node is not None else None
    n_done = len(s.done)

    moved = s.delete_item(target.iid)
    chk("★ 假链路不碰磁盘：归档数 = 0", moved == 0, moved)
    chk("★ 条目从 _items 里没了", s.item(target.iid) is None)
    chk("★ 条目从 done 里没了", len(s.done) == n_done - 1,
        (n_done, len(s.done)))
    chk("★★ 导图上挂着它的那个节点也一起摘掉了",
        s.find_node_by_item(target.iid) is None)
    if nid:
        chk("★★ 那颗节点的 nid 也从索引里清了（不留幽灵）",
            s.node(nid) is None)
    chk("★ 再删一次 -> None（已经没了，不报错）",
        s.delete_item(target.iid) is None)
    chk("压根不存在的 iid -> None", s.delete_item("i根本不存在") is None)

r = br.delete_item("i根本不存在")
chk("★ 桥接 delete_item 找不到条目 -> ok=False", r["ok"] is False)
chk("★ 理由说清了 reason=item-missing",
    r.get("reason") == "item-missing", r.get("reason"))
chk("★ 文案不是「该条目已经在树里了」那种误导话",
    "找不到" in (r.get("error") or ""), r.get("error"))

print("== 12. 脱离父节点 ==")
# 脱离 = 从当前父节点摘出来挂到**根**下（成为顶层）。子节点跟着走。
deep = None
for n in s.tree.walk():
    if n.parent is not None and n.parent is not s.tree and n.children:
        deep = n
        break
if deep is None:
    for n in s.tree.walk():
        if n.parent is not None and n.parent is not s.tree:
            deep = n
            break
chk("★ 假数据里有嵌套节点可测（带子节点的优先）",
    deep is not None and bool(deep.children),
    deep.name if deep else None)

if deep:
    old_parent = deep.parent
    kids = list(deep.children)
    total_before = sum(1 for _ in s.tree.walk())
    r = br.detach_node(deep.nid)
    chk("★ 脱离 -> ok=True", r["ok"] is True, r.get("error"))
    chk("★ moved=True（这次是真移动了）", r.get("moved") is True, r.get("moved"))
    chk("★★ 它现在挂在根节点下", deep.parent is s.tree)
    chk("★ 从原父的 children 里摘掉了", deep not in old_parent.children)
    chk("★★ 子节点跟着一起走（还是它的孩子、父指针没断）",
        deep.children == kids and all(c.parent is deep for c in kids),
        "%d 个子节点" % len(kids))
    chk("★★ 整棵树节点总数不变（一个都没丢）",
        sum(1 for _ in s.tree.walk()) == total_before, total_before)
    # 再脱离一次：它现在**已经是根的直接子节点**了。
    # 语义：允许、算成功、结构不变、moved=False —— 不报错、也不假装动了。
    sig_before = _tree_sig(s.tree)
    r2 = br.detach_node(deep.nid)
    chk("★★ 已经是顶层再脱离 -> 仍然 ok=True（允许，不报错）",
        r2["ok"] is True, r2.get("error"))
    chk("★★ 但 moved=False（告诉前端这次什么都没变）",
        r2.get("moved") is False, r2.get("moved"))
    chk("★★ 树结构一点没变（真 no-op）",
        _tree_sig(s.tree) == sig_before, sig_before)
    chk("★ 它还是根的直接子节点", deep.parent is s.tree)

chk("★ 根节点 -> reason=is-root",
    br.detach_node(s.tree.nid).get("reason") == "is-root")
chk("★ 不存在的 nid -> reason=node-missing",
    br.detach_node("n根本不存在").get("reason") == "node-missing")

print("== 13. 待处理列表顺序：按导入时间倒序（最新在最上面）==")
# 判据 = **created 倒序**，同一分钟再按"清单里的先后"倒序。
order = s.snapshot()["pending"]
want = sorted(range(len(s.pending)),
              key=lambda i: (s.pending[i].created or "", i), reverse=True)
chk("★ 快照里的 pending = 按 created 倒序",
    [x["id"] for x in order] == [s.pending[i].iid for i in want],
    [x["id"] for x in order][:4])
chk("★ 顺序确实是降序的（逐个比 created）",
    all((order[i]["created"] or "") >= (order[i + 1]["created"] or "")
        for i in range(len(order) - 1)),
    [x["created"] for x in order[:4]])
chk("★ light() 与 snapshot() 顺序一致（两条出口不许各说各话）",
    [x["id"] for x in s.light()["pending"]] == [x["id"] for x in order])

# 真导入一条 -> 出现在**最上面**
_mark = len(s.pending)
_new = store.add_item("排序探针_新导入.mp4", "", created="2027-01-01 00:00")
s._items[_new.iid] = _new
s.pending.append(_new)
after = s.snapshot()["pending"]
chk("★ 新导入的排在最上面（不是最底下）",
    after and after[0]["id"] == _new.iid, after[0]["id"] if after else None)
chk("★ 它确实是最后 append 的那条（前置条件对）",
    s.pending[-1] is _new and len(s.pending) == _mark + 1, len(s.pending))
s.pending.remove(_new)
s._items.pop(_new.iid, None)

# ★★ 判别性用例：**清单里的先后 ≠ 导入时间**。
# 用户那份数据真有这种条目 —— 掉过产物的条目会在「已完成/待处理」两块之间
# 搬家，搬一次位置就变了。实测：一条 created=2026-10-12 20:56 的录制
# 排在 pending 的**第一个**。
# 形状必须是「**块首 + 时间最新**」才分得出胜负：
#   倒排清单顺序 -> 块首那条被甩到最底下（最新反倒沉底）；
#   按 created 排  -> 它就该在最上面。
_front = store.add_item("排序探针_排在块首但时间最新.mp4", "",
                        created="2099-01-01 00:00")
s._items[_front.iid] = _front
s.pending.insert(0, _front)            # 故意塞在**块首**
o3 = [x["id"] for x in s.snapshot()["pending"]]
chk("★★ 排在块首、但 created 最新 -> 仍然排最上面",
    o3 and o3[0] == _front.iid,
    "它在第 %d 位（共 %d 条）" % (o3.index(_front.iid) + 1, len(o3)))
chk("★★ 同一条：倒排清单顺序会把它甩到最底下 —— 这条能把那版揪出来",
    o3 and o3[-1] != _front.iid, o3[-1])
s.pending.remove(_front)
s._items.pop(_front.iid, None)

print("== 14. 预处理队列：✕ = 只出队，别的什么都不动 ==")
# 这个列表是**收件箱**，不是条目库。用户在这儿点 ✕ 的意思是"暂时不处理它了"。
# 第一版接到了 delete_item 上 —— 用户在列表里点一下，**导图上对应的节点跟着
# 没了**（实测丢了一个节点）。这一节就是钉死"两个动作不能再串线"。
q0 = s.queue()
n_all_pending = len(s.pending)
chk("★ 队列里的每一条都满足：在台账里 + 没进导图 + 没出队",
    all((x in s.pending) and (x.iid not in s.tree_item_ids())
        and not x.dequeued for x in q0), len(q0))
chk("★ 没人出队、也没人进导图时，队列 == 全部待处理",
    len(q0) == n_all_pending, "%d vs %d" % (len(q0), n_all_pending))

victim = q0[0]
tree_sig_before = _tree_sig(s.tree)
nodes_before = sum(1 for _ in s.tree.walk())
chk("★ dequeue_item 返回 True", s.dequeue_item(victim.iid) is True)
chk("★★ 出队后它不在队列里了", victim.iid not in [x.iid for x in s.queue()])
chk("★★ 记录还在（_items 里查得到）", s.item(victim.iid) is victim)
chk("★★★ 它仍在 self.pending 里 —— 落盘走的就是这个列表，"
    "在这儿筛掉一条 = 下次保存就把它丢了",
    victim in s.pending, len(s.pending))
chk("★★★ 导图一个节点都没动（出队 ≠ 删树）",
    _tree_sig(s.tree) == tree_sig_before
    and sum(1 for _ in s.tree.walk()) == nodes_before, nodes_before)
chk("★ 出队位是真的置上了（不是悄悄 no-op）", victim.dequeued is True)

# 反过来钉一次：真正的删除**会**动树 —— 两个动作必须能区分开
_pair = [x for x in s.pending if x.iid not in s.tree_item_ids()
         and not x.dequeued][0]
_pn = s.add_content_node(s.tree.nid, _pair.iid)
chk("★ 先把一条挂上导图（前置）", bool(_pn) and _pair.iid in s.tree_item_ids())
chk("★★ 进了导图 -> **自动**不在队列里（用户要的就是这条）",
    _pair.iid not in [x.iid for x in s.queue()])
chk("★ 但它还是一条正常条目（记录没动）", s.item(_pair.iid) is _pair)
nodes_with_pair = sum(1 for _ in s.tree.walk())
s.delete_item(_pair.iid)
chk("★ 对照：delete_item 才会摘掉导图节点（比出队少 1 个节点）",
    sum(1 for _ in s.tree.walk()) == nodes_with_pair - 1,
    "%d -> %d" % (nodes_with_pair, sum(1 for _ in s.tree.walk())))

# 可逆。（上面那个对照实验真删了一条，所以这里不能再拿 n_all_pending 比 ——
#   拿"放回前"的长度比才对。）
n_before_requeue = len(s.queue())
chk("★ requeue_item 放回去", s.requeue_item(victim.iid) is True)
chk("★★ 放回后又在队列里了（出队是可逆的）",
    victim.iid in [x.iid for x in s.queue()])
chk("★ 队列长度正好 +1（没多没少）",
    len(s.queue()) == n_before_requeue + 1,
    "%d -> %d" % (n_before_requeue, len(s.queue())))
chk("不存在的 iid -> None", s.dequeue_item("i根本不存在") is None)
chk("桥接层 dequeue 找不到条目 -> ok=False",
    br.dequeue_item("i根本不存在").get("reason") == "item-missing")

print("\n结果：%d 通过，%d 失败" % (ok, len(bad)))
if bad:
    print("失败项：" + ", ".join(bad))
sys.exit(1 if bad else 0)
