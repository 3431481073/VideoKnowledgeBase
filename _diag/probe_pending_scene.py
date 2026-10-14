# -*- coding: utf-8 -*-
"""只读探针：待处理列表里现在到底有哪些东西。

回答一个具体问题 —— 用户说「已经被选中的（已处理完的）不要再出现在这个列表里」，
他看到的到底是哪种场景？**只打计数和状态名，不打标题、不打正文。**

⚠ 必须选对数据目录。本机有两个（第一版探针就栽在这儿，结论直接是错的）：
    · 项目根 data\\                                   —— **开发用的旧数据**（09-28 之后没动）
    · build\\dist_onedir\\VideoKnowledgeBase\\data\\      —— **用户真正在用的那份**

  `store.py` 的 BASE_DIR 是 `dirname(dirname(store.py))`，**不看 sys.executable** ——
  所以想在探针里 import store 就指向打包数据是**做不到的**（试过一次，骗到了
  media.DATA_DIR，store 照样读根上那份）。这里干脆不 import，直接按 store 的
  规则（raw=<base>.txt + <base>_segments.json，cleaned=<base>_cleaned.txt + <base>_meta.json）
  自己判，**只读**。

    venv\\Scripts\\python.exe _diag\\probe_pending_scene.py "build\\dist_onedir\\VideoKnowledgeBase\\data"
"""

import json
import os
import sys

if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(2)

DATA = os.path.abspath(sys.argv[1])
RAW = os.path.join(DATA, "raw_transcripts")
AI = os.path.join(DATA, "ai_processed")


def has_raw(base):
    return (os.path.isfile(os.path.join(RAW, base + ".txt"))
            and os.path.isfile(os.path.join(RAW, base + "_segments.json")))


def has_cleaned(base):
    return (os.path.isfile(os.path.join(AI, base + "_cleaned.txt"))
            and os.path.isfile(os.path.join(AI, base + "_meta.json")))


def tree_item_ids():
    p = os.path.join(DATA, "knowledge_tree.json")
    if not os.path.isfile(p):
        return set()
    with open(p, "r", encoding="utf-8") as f:
        root = json.load(f)
    out = set()

    def walk(n):
        if not isinstance(n, dict):
            return
        iid = n.get("itemId") or n.get("item_id")
        if iid:
            out.add(iid)
        for c in (n.get("children") or []):
            walk(c)

    walk(root)
    return out


def main():
    print("数据目录： %s" % DATA)
    with open(os.path.join(DATA, "workspace.json"), "r", encoding="utf-8") as f:
        recs = (json.load(f) or {}).get("items") or []

    in_tree = tree_item_ids()
    rows = []
    for r in recs:
        stem = os.path.splitext(r.get("media_name") or r.get("name") or "")[0]
        rows.append({
            "id": r.get("id"),
            "base": stem,
            "cleaned": has_cleaned(stem),
            "raw": has_raw(stem),
            "media_ok": os.path.isfile(os.path.join(DATA, "media",
                                                   r.get("media_name") or "")),
        })

    done = [x for x in rows if x["cleaned"]]
    pend = [x for x in rows if not x["cleaned"]]

    print("总条目              %d   （workspace.json 里的记录数）" % len(rows))
    print("  已清洗(=已完成)     %d   <- 按定义**不在**待处理列表里" % len(done))
    print("  未清洗(=待处理)     %d   <- 处理浮层左列表里看到的就是这些" % len(pend))
    print("")
    print("待处理里各状态：")
    print("  已转写、未清洗       %d   （列表里显示「已转写」）"
          % len([x for x in pend if x["raw"]]))
    print("  一个字都没有         %d   （列表里显示「转写」）"
          % len([x for x in pend if not x["raw"]]))
    print("")
    print("待处理里**已经挂到导图上**的： %d" % len([x for x in pend if x["id"] in in_tree]))
    print("  （挂没挂导图不参与「待处理/已完成」的划分 —— 只看清洗稿在不在）")
    print("")
    print("待处理里视频文件缺失的： %d" % len([x for x in pend if not x["media_ok"]]))
    print("")
    ids = {x["id"] for x in rows}
    print("树里被引用的 itemId 数： %d" % len(in_tree))
    print("  引用了不存在的条目(悬空)： %d" % len([i for i in in_tree if i not in ids]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
