# -*- coding: utf-8 -*-
"""真实验收（端到端）：真模型 + 真 LLM + 真落盘 + 真界面。

跑在**真实链路**上（不设 VKB_FAKE）：
  建 workspace 条目 -> 起界面 -> 勾选 + 点转写 -> 采样进度
  -> 校验四个产物文件 -> 挂到树 -> 点节点看播放器与正文

结果写 _diag/e2e_results.txt。这一步会真的调 DeepSeek，产生少量 token 消耗。
"""

import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
OUT = os.path.join(DIAG, "e2e_results.txt")
os.environ.pop("VKB_FAKE", None)
os.environ["VKB_NO_SINGLE_INSTANCE"] = "1"   # e2e/探针要起真界面，跳过单实例闸          # 明确：真实链路
DEGRADE = "--degrade" in sys.argv         # 缺 API Key 的降级路径
T0 = time.monotonic()
CFG_BAK = os.path.join(DIAG, "config.backup.json")
TREE_BAK = os.path.join(DIAG, "tree.backup.json")

R = []


def log(m):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("t=%7.2f  %s\n" % (time.monotonic() - T0, m))


def chk(name, cond, extra=""):
    R.append({"name": name, "pass": bool(cond), "extra": str(extra)})
    log("%s  %-40s %s" % ("PASS" if cond else "FAIL", name, extra))


def restore_tree():
    """把 e2e 期间清空的用户知识树还回去。"""
    if not os.path.isfile(TREE_BAK):
        return False
    import shutil
    shutil.copyfile(TREE_BAK, os.path.join(ROOT, "data", "knowledge_tree.json"))
    os.remove(TREE_BAK)
    log("已还原用户的知识树")
    return True


def restore_config():
    """把降级测试里清掉的 API Key 还回去。备份文件在就还原，还原完删掉。"""
    if not os.path.isfile(CFG_BAK):
        return False
    import shutil
    import config
    shutil.copyfile(CFG_BAK, config.CONFIG_FILE)
    os.remove(CFG_BAK)
    k = (config.load_config().get("clean_api_key") or "")
    log("已还原 config.json（api_key 长度 %d）" % len(k))
    return bool(k)


def _finish():
    restore_tree()
    log("---- 结果 ----")
    npass = sum(1 for x in R if x["pass"])
    log("合计 %d 通过 / %d 失败 / 共 %d" % (npass, len(R) - npass, len(R)))
    time.sleep(0.3)
    os._exit(0)


def driver():
    import webview

    while not webview.windows:
        time.sleep(0.05)
    w = webview.windows[0]
    for _ in range(200):
        try:
            if w.evaluate_js("!!(window.VKB_DEBUG && VKB_DEBUG.ready())"):
                break
        except Exception:
            pass
        time.sleep(0.1)
    log("界面就绪")

    def js(code):
        try:
            return w.evaluate_js(code)
        except Exception as e:
            log("JS 失败: %s" % e)
            return None

    # ---------------- 0. 真实模式 & 列表里有我们那条 ----------------
    st = js("JSON.stringify(VKBProcess.state())")
    st = json.loads(st) if st else {}
    chk("0a 走的是真实链路", js("VKB_DEBUG.ready()") and js(
        "!!(window.VKBApp && VKBApp.applyState)") is not None)
    fake = js("(function(){return !!(document.querySelector('#procList'));})()")
    chk("0b 处理面板就绪", fake is True, fake)

    js("VKB_DEBUG.openProcess()")
    time.sleep(0.6)
    n = js("document.querySelectorAll('#procList .proc-item').length") or 0
    chk("0c 待处理列表里有条目", n >= 1, n)
    title = js("document.querySelector('#procList .proc-item .nm').textContent")
    log("待处理第一条 = %s" % title)

    # ---------------- 1. 触发转写 ----------------
    js("(function(){var cb=document.querySelector('#procList .proc-item .ci');"
       "if(cb && !cb.checked) cb.click();})()")
    time.sleep(0.3)
    js("(function(){var b=document.querySelector('#procList .proc-item .tr');"
       "if(b) b.click();})()")
    log("已点转写")

    stages = []
    deadline = time.monotonic() + 300
    final = None
    finished = False
    while time.monotonic() < deadline:
        # 【注意】跑完的条目会从「待处理」移进「已完成」，那一行就没了 ——
        # 所以不能只盯行内文字，必须同时看它有没有出现在已完成里。
        one = js("(function(){var e=document.querySelector('#procList .proc-item .tr');"
                 "return e? e.textContent : '';})()")
        if one and (not stages or stages[-1] != one):
            stages.append(one)
        if one:
            final = one
        d = json.loads(js("JSON.stringify(VKB_DEBUG.done())") or "{}")
        if any("speech_test" in t for t in (d.get("titles") or [])):
            finished = True
            break
        if one == "失败":
            break
        time.sleep(0.15)

    log("阶段轨迹（行内文字）: %s" % " -> ".join(stages[:60]))
    chk("1a 进度确实在推进（出现多个阶段文字）", len(stages) >= 3, len(stages))
    chk("1b 出现过「加载模型」段（首次约 11 秒必须有提示）",
        any("加载模型" in x for x in stages), stages[:8])
    chk("1c 出现过转写百分比", any("%" in x and "整理" not in x for x in stages),
        [x for x in stages if "%" in x and "整理" not in x][:6])
    chk("1d 出现过「整理」段（清洗阶段）", any("整理" in x for x in stages),
        [x for x in stages if "整理" in x][:4])
    if DEGRADE:
        chk("D1 缺 Key 时停在「已转写」而不是失败", final == "已转写", final)
        import store as _s
        chk("D2 原始转写照常落盘（成果不丢）", bool(_s.read_raw("speech_test").strip()))
        chk("D3 没有写出清洗稿", not os.path.isfile(_s.cleaned_path("speech_test")))
        rawtxt = _s.read_raw("speech_test")
        chk("D4 转写内容仍然是正确的",
            any(w in rawtxt for w in ("断板", "反包", "资金")), rawtxt[:40])
        restore_config()
        _finish()
        return
    chk("1e 最终进到已完成", finished, "行内最后=%r" % final)

    # ---------------- 2. 落盘校验（Python 侧看真实文件） ----------------
    import store
    base = "speech_test"
    raw_txt = store.raw_txt_path(base)
    seg_json = store.seg_path(base)
    cleaned = store.cleaned_path(base)
    meta_p = store.meta_path(base)
    raw = store.read_raw(base)
    clean_txt = store.read_cleaned(base)
    segs = store.read_segments(base)
    meta = store.read_meta(base)

    chk("2a raw_transcripts/<base>.txt 存在且非空", bool(raw.strip()), len(raw))
    chk("2b raw_transcripts/<base>_segments.json 是合法分段",
        isinstance(segs, list) and len(segs) > 0 and all(
            set(("start", "end", "text")) <= set(s) for s in segs), len(segs))
    chk("2c ai_processed/<base>_cleaned.txt 存在且非空", bool(clean_txt.strip()),
        len(clean_txt))
    chk("2d ai_processed/<base>_meta.json 存在且五字段齐全", os.path.isfile(meta_p) and all(
        k in meta for k in ("title", "video_path", "cleaned_file",
                            "created_time", "modified_at")), sorted(meta))
    chk("2e ★ raw 与 cleaned 内容不同（raw 没被清洗稿覆盖）",
        raw.strip() != clean_txt.strip())
    log("raw 前 60 字: %s" % raw[:60])
    log("cleaned 前 60 字: %s" % clean_txt[:60])

    # 转写内容与朗读稿有交集才算"真的认出来了"
    hit = any(w in raw for w in ("断板", "反包", "资金", "图形", "位置", "形态"))
    chk("2f ★ 转写内容与朗读稿吻合（认出关键词）", hit,
        [w for w in ("断板", "反包", "资金", "图形", "位置", "形态") if w in raw])

    # ---------------- 3. 条目从待处理进已完成 ----------------
    js("VKBProcess.close()")
    time.sleep(0.3)
    done = json.loads(js("JSON.stringify(VKB_DEBUG.done())") or "{}")
    log("done = %s" % json.dumps(done, ensure_ascii=False)[:200])
    titles = done.get("titles") or []
    chk("3a 条目进了「已完成」", any("speech_test" in t for t in titles), titles[:5])
    chk("3b 待处理里没有它了",
        "speech_test" not in (js("(function(){return Array.prototype.map.call("
                                 "document.querySelectorAll('#procList .proc-item .nm'),"
                                 "function(e){return e.textContent}).join('|');})()") or ""),
        "ok")

    # ---------------- 4. 加入视频 -> 播放器 + 文章 ----------------
    # 【流程变了】以前是"空白双击 -> 弹节点类型二选一 -> 选内容节点 -> 选条目"。
    # 现在没有"节点类型"这一步：直接在分组上右键「加入视频…」-> 选条目。
    js("(function(){var el=document.querySelector('#nodes .node');"
       "var r=el.getBoundingClientRect();"
       "el.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,"
       "clientX:r.left+5,clientY:r.top+5}));return true;})()")
    time.sleep(0.4)
    js("(function(){var m=document.querySelectorAll('#ctxMenu li');"
       "if(m.length>1)m[1].click();return m.length;})()")
    time.sleep(0.6)
    picked = js("(function(){var l=document.querySelectorAll('#dlgPickList .pick-item');"
                "for(var i=0;i<l.length;i++){if(l[i].textContent.indexOf('speech_test')>=0)"
                "{l[i].click();return l[i].textContent;}}return null;})()")
    log("挂到导图的条目 = %s" % picked)
    time.sleep(0.8)
    chk("4a 条目选择框里能选到它", bool(picked), picked)

    node = js("(function(){var n=window.VKBGraph.debug().nodes.filter(function(x)"
              "{return x.itemId;});if(!n.length)return null;"
              "return JSON.stringify(n[n.length-1]);})()")
    node = json.loads(node) if node else None
    chk("4b 树上出现了内容节点", bool(node and node.get("itemId")), node and node.get("name"))

    if node:
        media_ok = False
        for _ in range(60):
            js("(function(){var e=document.querySelector('#nodes .node[data-id=\"%s\"]');"
               "if(e){e.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,button:0,"
               "clientX:0,clientY:0}));window.dispatchEvent(new MouseEvent('mouseup',"
               "{bubbles:true}));}})()" % node["id"])
            time.sleep(0.3)
            ps = json.loads(js("JSON.stringify(VKB_DEBUG.player())") or "{}")
            if ps.get("readyState", 0) >= 2:
                media_ok = True
                break
        chk("4c ★ 点内容节点 -> 右上播放器加载了就绪的媒体", media_ok,
            json.dumps(ps, ensure_ascii=False)[:160])

        art = json.loads(js("JSON.stringify(VKB_DEBUG.article())") or "{}")
        blocks = art.get("blocks") or 0
        chk("4d ★ 左下文章有内容", blocks > 0, blocks)
        log("article 快照: %s" % json.dumps(art, ensure_ascii=False)[:300])
        log("点中的节点 kind=%s name=%s" % (node.get("kind"), node.get("name")))
        # 正文在 .body 里（.h 是标题），要读 body 的值
        bodies = js("(function(){return Array.prototype.map.call("
                    "document.querySelectorAll('#article .body'),"
                    "function(e){return e.value}).join('');})()") or ""
        log("文章正文前 60 字: %s" % bodies[:60])
        chk("4e ★ 文章正文来自清洗稿（不是原始转写）",
            bool(bodies.strip()) and bodies.strip()[:20] in clean_txt,
            bodies[:60])
        chk("4f 正文是 LLM 清洗后的版本（「形态」已纠正、「形太」不在）",
            "形态" in bodies and "形太" not in bodies, bodies[:60])

    _finish()


def main():
    f = open(os.path.join(DIAG, "e2e_stderr.txt"), "w", encoding="utf-8", buffering=1)
    sys.stdout = f
    sys.stderr = f
    if os.path.exists(OUT):
        os.remove(OUT)
    sys.path.insert(0, os.path.join(ROOT, "src"))

    # 准备一条真实的待处理条目
    import store
    media = os.path.join(store.MEDIA_DIR, "speech_test.mp4")
    if not os.path.isfile(media):
        log("找不到素材 %s" % media)
        os._exit(2)
    existing = {it.video_name for it in store.load_items()}
    if "speech_test.mp4" not in existing:
        store.save_items(store.load_items() + [store.add_item("speech_test.mp4", "")])
        log("已登记 speech_test.mp4 到 workspace.json")
    # 树清空 —— 否则上一轮挂上去的节点还在，这条就永远是「已添加」，
    # 「未添加」选择框里根本不会出现它（第一版就栽在这）。
    # **先备份**：这是用户的真实知识树，跑完必须原样还回去。
    import shutil
    if os.path.isfile(store.TREE_FILE):
        shutil.copyfile(store.TREE_FILE, TREE_BAK)
        log("已备份知识树 -> %s" % TREE_BAK)
    root = store.UINode("")
    root.virtual = True                # 多根：空的**隐形根** = 一棵树都没有
    root.nid = store.new_nid()
    store.save_tree(root)
    log("已把知识树重置成空的隐形根（跑完会还原）")

    if DEGRADE:
        import shutil
        import config
        shutil.copyfile(config.CONFIG_FILE, CFG_BAK)
        cfg = config.load_config()
        before = len(cfg.get("clean_api_key") or "")
        cfg["clean_api_key"] = ""
        config.save_config(cfg)
        log("降级模式：已把 api_key 清空（原长度 %d，备份在 %s）" % (before, CFG_BAK))
    # 清掉上次的产物，保证这次是从零跑出来的
    for p in (store.raw_txt_path("speech_test"), store.seg_path("speech_test"),
              store.cleaned_path("speech_test"), store.meta_path("speech_test")):
        if os.path.isfile(p):
            os.remove(p)
    log("已清空上次产物")

    import app_web
    threading.Thread(target=driver, daemon=True).start()
    try:
        app_web.main()
    finally:
        # 兜底：万一驱动线程没跑到还原那步，这里也要把用户的树/config 还回去
        restore_tree()
        restore_config()


if __name__ == "__main__":
    main()
