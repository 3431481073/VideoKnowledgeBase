# -*- coding: utf-8 -*-
"""补回 2026-10-13 那次误删从导图上带走的那**一个节点**。

【事故】
  处理视频浮层的 ✕ 当时接到了 `delete_item` 上（删记录 + 删导图节点 + 归档产物）。
  用户在**预处理列表**里连点了 5 下（15:33:27 → 15:33:37），其中一条
  `ie50691a606`（10-12 20:56 那条录制）挂在导图上 —— 它的节点被一起删了。
  另外 4 条本来就不在导图上，只丢了记录。

【裁定】用户说：**只补回树节点那一条**（另外 4 条保持删除）。

【做法】
  1. 从 `knowledge_tree.json.bak-20261013-153329` 里按 **itemId** 找出当前树缺的那个
     节点（**不认名字** —— 名字可能被改过，id 不会）
  2. 顺着它的父链，在当前树里按 (名字, 类型) 找回同一个父节点，**插回原来的位置**
  3. 从 `workspace.json.bak-20261013-153329` 取回那条记录，追加进当前条目清单
     （没有它，节点上的 itemId 就是悬空的 —— 点那个节点什么都读不出来）
  4. 写之前两份文件各轮一份带时间戳的 .bak（走 store 自己的轮转，和平时一致）
  5. 写完自查：节点 +1、条目 +1、**无悬空 itemId**

⚠ 必须在**应用关闭**时跑 —— 应用在跑会拿内存态把文件覆盖回去。
⚠ 默认 **--dry-run**：只看不写。真要写必须显式加 `--yes`。

    venv\\Scripts\\python.exe _diag\\restore_tree_node.py [--data <目录>] [--yes]
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

TARGET_ITEM = "ie50691a606"
STAMP = "20261013-153329"          # 首次删除**之前**那一刻的备份
DEF_DATA = os.path.join(ROOT, "build", "dist_onedir", "VideoKnowledgeBase", "data")

import store  # noqa: E402


def path_of(root, node):
    """从 root 的**孩子**到 node 的 (名字, 类型) 链 —— 用来在另一棵树里找回同一位置。"""
    chain = []
    cur = node
    while cur is not None and cur is not root:
        chain.append((cur.name, cur.kind))
        cur = cur.parent
    chain.reverse()
    return chain


def find_child(parent, name, kind):
    for c in parent.children:
        if c.name == name and c.kind == kind:
            return c
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEF_DATA)
    ap.add_argument("--yes", action="store_true", help="真写；不给就只报告")
    ap.add_argument("--target", default=TARGET_ITEM)
    a = ap.parse_args()

    data = os.path.abspath(a.data)
    store.BASE_DIR = os.path.dirname(data)
    store.DATA_DIR = data
    store.MEDIA_DIR = os.path.join(data, "media")
    store.RAW_DIR = os.path.join(data, "raw_transcripts")
    store.AI_DIR = os.path.join(data, "ai_processed")
    store.BACKUP_DIR = os.path.join(data, "backups")
    store.STALE_DIR = os.path.join(data, "_stale")
    store.WORKSPACE_FILE = os.path.join(data, "workspace.json")
    store.TREE_FILE = os.path.join(data, "knowledge_tree.json")

    bak_tree = store.TREE_FILE + ".bak-" + STAMP
    bak_ws = store.WORKSPACE_FILE + ".bak-" + STAMP
    print("数据目录 : %s" % data)
    for p in (bak_tree, bak_ws):
        if not os.path.isfile(p):
            print("★ 缺少备份：%s" % p)
            return 2

    # ---- 1. 备份树里的那个节点 ----
    with open(bak_tree, encoding="utf-8") as f:
        bak_root = store._node_from_dict(json.load(f))
    want = [n for n in bak_root.walk() if n.item_id == a.target]
    if len(want) != 1:
        print("★ 备份树里按 itemId=%s 找不着唯一节点（找到 %d 个）" % (a.target, len(want)))
        return 2
    want = want[0]
    chain = path_of(bak_root, want)
    parent_chain, leaf = chain[:-1], chain[-1]
    print("要补回的节点：第 %d 层 / %s / 名字长度 %d 字"
          % (len(chain) - 1, want.kind, len(want.name)))
    print("  父链：%s" % " > ".join("(第%d层 %s)" % (i, k) for i, (_n, k)
                                    in enumerate(parent_chain)))

    # ---- 2. 当前树里找回同一个父 + 同一个位置 ----
    cur = store.load_tree()
    if any(n.item_id == a.target for n in cur.walk()):
        print("★ 当前树里已经有这个节点了 —— 不用补，什么都不做")
        return 0
    parent = cur
    for (name, kind) in parent_chain:
        nxt = find_child(parent, name, kind)
        if nxt is None:
            print("★ 当前树里找不到父节点「%s」(第…层 %s) —— 不敢瞎插，中止"
                  % ("<略>", kind))
            return 3
        parent = nxt
    # 在原父的 children 里的位次（按备份树里它前面的兄弟名字对）
    bak_brothers = [c.name for c in want.parent.children]
    idx = bak_brothers.index(want.name)
    same = [i for i, c in enumerate(parent.children) if c.name == want.name]
    if same:
        idx = same[0]
    else:
        idx = min(idx, len(parent.children))
    print("插入位置：父节点下第 %d 个孩子（共 %d 个）" % (idx + 1, len(parent.children)))

    # ---- 3. 备份 workspace 里的那条记录 ----
    with open(bak_ws, encoding="utf-8") as f:
        bak_items = (json.load(f) or {}).get("items") or []
    rec = [r for r in bak_items if r.get("id") == a.target]
    if len(rec) != 1:
        print("★ 备份清单里按 id 找不着唯一记录（找到 %d 条）" % len(rec))
        return 2
    rec = rec[0]
    cur_items = store.load_items()
    if any(x.iid == a.target for x in cur_items):
        print("★ 当前清单里已经有这条记录了 —— 只补树节点，不动清单")
        rec = None
    else:
        print("要补回的记录：origin=%s / created=%s / 有 media_name=%s"
              % (rec.get("origin"), rec.get("created"), bool(rec.get("media_name"))))

    n_before = sum(1 for _ in cur.walk())
    n_items_before = len(cur_items)
    print("")
    print("预期结果：树节点 %d -> %d；条目 %d -> %d"
          % (n_before, n_before + 1, n_items_before,
             n_items_before + (1 if rec else 0)))

    if not a.yes:
        print("")
        print("[dry-run] 什么都没写。要真写：加 --yes（且应用必须已关闭）")
        return 0

    # ---- 4. 写 ----
    want.parent = parent
    parent.children.insert(idx, want)
    store.save_tree(cur)                       # 内部会先轮一份 .bak
    print("已写回树：%s" % store.TREE_FILE)

    if rec is not None:
        it = store._item_from_record(rec)
        store.save_items(cur_items + [it])
        print("已写回清单：%s" % store.WORKSPACE_FILE)

    # ---- 5. 自查 ----
    t2 = store.load_tree()
    i2 = store.load_items()
    ids = {x.iid for x in i2}
    on_tree = {n.item_id for n in t2.walk() if n.kind == "video" and n.item_id}
    dangling = sorted(on_tree - ids)
    n2 = sum(1 for _ in t2.walk())
    print("")
    print("自查：树节点 %d（应 %d）· 条目 %d（应 %d）· 悬空 itemId %d 个"
          % (n2, n_before + 1, len(i2), n_items_before + (1 if rec else 0),
             len(dangling)))
    ok = (n2 == n_before + 1
          and len(i2) == n_items_before + (1 if rec else 0)
          and not dangling
          and any(n.item_id == a.target for n in t2.walk()))
    print("结论：%s" % ("补回成功" if ok else "★ 有地方不对，看上面数字"))
    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(main())
