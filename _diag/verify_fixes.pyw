# -*- coding: utf-8 -*-
"""对着**用户真实数据**验收这一轮的修复。

会触发一次迁移写入（workspace.json 补 media_name）—— 这是本轮批准的改动。
其余一律只读。
"""

import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
OUT = os.path.join(DIAG, "verify_results.txt")
os.environ.pop("VKB_FAKE", None)
os.environ["VKB_NO_SINGLE_INSTANCE"] = "1"   # e2e/探针要起真界面，跳过单实例闸
T0 = time.monotonic()
R = []


def log(m):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("t=%6.2f  %s\n" % (time.monotonic() - T0, m))


def chk(name, cond, extra=""):
    R.append({"name": name, "pass": bool(cond)})
    log("%s  %-46s %s" % ("PASS" if cond else "FAIL", name, extra))


def read_ws():
    p = os.path.join(ROOT, "data", "workspace.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


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
    time.sleep(1.0)

    def js(code):
        try:
            return w.evaluate_js(code)
        except Exception as e:
            log("JS 失败 %s" % e)
            return None

    # ---------------- 迁移结果 ----------------
    ws = read_ws()
    rec = None
    for r in ws["items"]:
        if r.get("name") == "怪物和人类的十大发":
            rec = r
            break
    chk("M1 找到用户那条改过名的记录", rec is not None)
    if rec:
        chk("M2 ★ 已补出 media_name 并接回真实文件",
            rec.get("media_name") == "VID20260731063231.mp4", rec.get("media_name"))
        chk("M3 显示名没被动过", rec.get("name") == "怪物和人类的十大发", rec.get("name"))
    withm = sum(1 for r in ws["items"] if r.get("media_name"))
    chk("M4 所有记录都带上了 media_name", withm == len(ws["items"]),
        "%d/%d" % (withm, len(ws["items"])))

    # ---------------- 条目状态恢复 ----------------
    done = json.loads(js("JSON.stringify(VKB_DEBUG.done())") or "{}")
    log("done = %s" % json.dumps(done, ensure_ascii=False)[:300])
    chk("M5 ★ 那条改名条目回到了「已完成」（产物重新找得到）",
        any("怪物和人类" in t for t in (done.get("titles") or [])),
        done.get("titles"))

    # ---------------- BUG2：点根节点，正文要出来 ----------------
    g = json.loads(js("JSON.stringify(VKB_DEBUG.graph())") or "{}")
    for n in g.get("nodes", []):
        log("  树: depth=%s kind=%s name=%s" % (n.get("depth"), n.get("kind"), n.get("name")))
    root = [n for n in g.get("nodes", []) if n.get("depth") == 0]
    if root:
        js("(function(){var e=document.querySelector('#nodes .node[data-id=\"%s\"]');"
           "if(e){e.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,button:0,"
           "clientX:0,clientY:0}));window.dispatchEvent(new MouseEvent('mouseup',"
           "{bubbles:true}));}})()" % root[0]["id"])
        time.sleep(0.6)
    bodies = js("(function(){return Array.prototype.map.call("
                "document.querySelectorAll('#article .body'),"
                "function(e){return e.value}).join(' | ');})()") or ""
    log("根节点文章正文 = %r" % bodies[:120])
    chk("B1 ★ 点根节点 -> 有正文（不再是光秃秃一个标题）", len(bodies.strip()) > 0,
        len(bodies))
    chk("B2 ★ 用户手打的「士大夫」看得见了", "士大夫" in bodies, bodies[:60])

    # ---------------- BUG1：点条目 -> 全文 ----------------
    js("document.querySelector('#article').innerHTML=''")
    row = js("(function(){var r=document.querySelector('#doneList .row-item');"
             "if(!r)return null;r.click();return r.children[0].textContent;})()")
    got = False
    for _ in range(30):
        got = bool(js("(function(){var e=document.querySelector('#article .body.ro');"
                      "return e && e.textContent.length>20;})()"))
        if got:
            break
        time.sleep(0.2)
    txt = js("(function(){var e=document.querySelector('#article .body.ro');"
             "return e? e.textContent.slice(0,60):'';})()") or ""
    log("点条目 %s 后正文 = %r" % (row, txt))
    chk("B3 ★ 点右下条目 -> 左下显示清洗稿全文", got, txt[:40])
    chk("B4 显示了来源标注",
        bool(js("!!document.querySelector('#article .ro-meta')")))
    chk("B5 条目行高亮选中", js("document.querySelectorAll('#doneList .row-item.sel').length") == 1)

    # ---------------- 摄像头 ----------------
    js("VKB_DEBUG.openProcess()")
    time.sleep(0.5)
    js("(function(){var b=document.querySelector('#procCamera');if(b)b.click();})()")
    time.sleep(0.4)
    toast = js("!document.querySelector('#toast').classList.contains('hidden')")
    st = js("document.querySelector('#procStatus').textContent")
    chk("B6 ★ 点摄像头 -> 弹居中提示", toast is True)
    chk("B7 点摄像头 -> 状态行也有文字", "摄像头" in (st or ""), st)

    log("---- 结果 ----")
    npass = sum(1 for x in R if x["pass"])
    log("合计 %d 通过 / %d 失败 / 共 %d" % (npass, len(R) - npass, len(R)))
    time.sleep(0.3)
    os._exit(0)


def main():
    f = open(os.path.join(DIAG, "verify_stderr.txt"), "w", encoding="utf-8", buffering=1)
    sys.stdout = f
    sys.stderr = f
    if os.path.exists(OUT):
        os.remove(OUT)
    sys.path.insert(0, os.path.join(ROOT, "src"))

    # 看一眼迁移前的样子
    before = read_ws()
    missing = [r["name"] for r in before["items"] if not r.get("media_name")]
    log("迁移前缺 media_name 的记录 %d 条：%s" % (len(missing), missing))

    import app_web
    threading.Thread(target=driver, daemon=True).start()
    app_web.main()


if __name__ == "__main__":
    main()
