# -*- coding: utf-8 -*-
"""对着**用户的真实数据**只读排查三个 bug：文章面板 / 点条目 / 摄像头反馈。

严格只读：不重置树、不删产物、不触发任何变更类 js_api。
"""

import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
OUT = os.path.join(DIAG, "probe_results.txt")
os.environ.pop("VKB_FAKE", None)
T0 = time.monotonic()


def log(m):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("t=%6.2f  %s\n" % (time.monotonic() - T0, m))


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

    log("=== 树的形状 ===")
    g = json.loads(js("JSON.stringify(VKB_DEBUG.graph())") or "{}")
    for n in g.get("nodes", []):
        log("  depth=%d kind=%-6s itemId=%-12s name=%s"
            % (n.get("depth", -1), n.get("kind"), n.get("itemId"), n.get("name")))

    log("=== 右下条目 ===")
    log("  " + (js("JSON.stringify(VKB_DEBUG.done())") or ""))

    def click_node(nid):
        js("(function(){var e=document.querySelector('#nodes .node[data-id=\"%s\"]');"
           "if(!e)return;e.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,"
           "button:0,clientX:0,clientY:0}));window.dispatchEvent("
           "new MouseEvent('mouseup',{bubbles:true}));})()" % nid)
        time.sleep(0.5)

    log("=== BUG2: 点根节点后的文章面板 ===")
    root = [n for n in g.get("nodes", []) if n.get("depth") == 0]
    if root:
        click_node(root[0]["id"])
        art = json.loads(js("JSON.stringify(VKB_DEBUG.article())") or "{}")
        log("  blocks=%s bodies=%s" % (art.get("blocks"), art.get("bodies")))
        log("  标题们 = %s" % json.dumps(art.get("titles"), ensure_ascii=False))
        bodies = js("(function(){return Array.prototype.map.call("
                    "document.querySelectorAll('#article .body'),"
                    "function(e){return (e.value||'').slice(0,40)}).join(' || ');})()")
        log("  正文们 = %s" % bodies)
        log("  hint = %s" % js("document.querySelector('#contentHint').textContent"))

    log("=== 点内容子节点后的文章面板（对照）===")
    child = [n for n in g.get("nodes", []) if n.get("itemId")]
    if child:
        click_node(child[0]["id"])
        art = json.loads(js("JSON.stringify(VKB_DEBUG.article())") or "{}")
        log("  blocks=%s bodies=%s" % (art.get("blocks"), art.get("bodies")))
        bodies = js("(function(){return Array.prototype.map.call("
                    "document.querySelectorAll('#article .body'),"
                    "function(e){return (e.value||'').slice(0,50)}).join(' || ');})()")
        log("  正文 = %s" % bodies)

    log("=== BUG1: 点右下已完成的条目 ===")
    before = js("document.querySelector('#article').textContent.slice(0,40)")
    row = js("(function(){var r=document.querySelector('#doneList .row-item');"
             "if(!r)return null;r.click();return r.children[0].textContent;})()")
    time.sleep(0.6)
    after = js("document.querySelector('#article').textContent.slice(0,40)")
    log("  点到的条目 = %s" % row)
    log("  点之前文章开头 = %r" % before)
    log("  点之后文章开头 = %r" % after)
    log("  文章变了吗 = %s" % (before != after))
    log("  条目有没有 click 监听（看 title/class 变化）= %s"
        % js("document.querySelector('#doneList .row-item').className"))

    log("=== BUG3: 点「打开摄像头」 ===")
    js("VKB_DEBUG.openProcess()")
    time.sleep(0.6)
    st_before = js("document.querySelector('#procStatus').textContent")
    js("(function(){var b=document.querySelector('#procCamera');if(b)b.click();})()")
    time.sleep(0.3)
    st_now = js("document.querySelector('#procStatus').textContent")
    time.sleep(1.5)
    st_after = js("document.querySelector('#procStatus').textContent")
    log("  点之前 status = %r" % st_before)
    log("  点完立刻 status = %r" % st_now)
    log("  1.5 秒后 status = %r（被轮询覆盖？）" % st_after)
    log("  status 元素可见 = %s"
        % js("(function(){var e=document.querySelector('#procStatus');"
             "var r=e.getBoundingClientRect();return r.width+'x'+r.height+' at '+"
             "Math.round(r.left)+','+Math.round(r.top);})()"))

    log("=== BUG4: 导入接口现在的返回 ===")
    log("  pick_videos 是弹系统框，无法自动点；只看 start_import 的进度字段是否在 poll 里")
    log("  poll 载荷里有 import 字段 = %s"
        % js("(function(){return typeof VKBProcess.setImportStatus === 'function';})()"))

    log("=== 结束（全程只读，未改任何数据）===")
    time.sleep(0.3)
    os._exit(0)


def main():
    f = open(os.path.join(DIAG, "probe_stderr.txt"), "w", encoding="utf-8", buffering=1)
    sys.stdout = f
    sys.stderr = f
    if os.path.exists(OUT):
        os.remove(OUT)
    sys.path.insert(0, os.path.join(ROOT, "src"))
    import app_web
    threading.Thread(target=driver, daemon=True).start()
    app_web.main()


if __name__ == "__main__":
    main()
