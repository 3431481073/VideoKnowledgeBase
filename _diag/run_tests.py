# -*- coding: utf-8 -*-
"""测试总入口。**改哪儿跑哪儿**，别每次全量。

    python _diag/run_tests.py --list
    python _diag/run_tests.py --suite ui-core
    python _diag/run_tests.py --suite py-state py-store
    python _diag/run_tests.py                 # = --suite all
    python _diag/run_tests.py --suite all real

选套指南：
    改 UI 文案 / 元素位置 / 删元素      -> ui-core     (~4s)
    改处理浮层（列表 / 裁剪 / 合并）     -> ui-panel    (~8s)
    改导图 / 文章面板 / 条目 / 设置      -> ui-tree     (~6s)
    改数据层（WebState / item_dict）     -> py-state    (<1s)
    改持久层（store / workspace / 产物） -> py-store    (<1s)
    改媒体联接（media.py：视频能不能播） -> py-media    (<1s)
    改任务队列 / 转写 / 清洗             -> py-jobs     (~4s)
    改 ffmpeg 裁剪 / 合并 / 流探测       -> py-video    (~25s，真编码)
    改摄像头分片 / 权限钩子（已停用）    -> py-camera   (~5s，不碰真摄像头)
    改系统相机调起 / 目录监视 / 导入     -> py-camapp   (~8s，**不真调起相机**)
    改真实链路（模型 / LLM / 落盘）      -> real        (~15s，会花 token)
    整轮结束                            -> all         (~55s，不含 real)

真摄像头端到端**不在这里**，手动跑：_diag/e2e_camera.pyw
"""

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
PY = os.path.join(ROOT, "venv", "Scripts", "python.exe")
PYW = os.path.join(ROOT, "venv", "Scripts", "pythonw.exe")

#: name -> (类型, 脚本, 输出文件, 说明)
SUITES = {
    "ui-core":  ("js", "ui_core.js", "ui_core_results.txt", "布局/控制栏/音量/旋转/快捷键/右下外观"),
    "ui-panel": ("js", "ui_panel.js", "ui_panel_results.txt", "处理浮层三模式 + 选中规则"),
    "ui-tree":  ("js", "ui_tree.js", "ui_tree_results.txt", "导图交互/文章/条目/设置"),
    "py-state": ("py", "test_state.py", "", "数据层"),
    "py-store": ("py", "test_store.py", "", "持久层"),
    "py-media": ("py", "test_media.py", "", "媒体联接（建立/自愈）"),
    "py-jobs":  ("py", "test_jobs.py", "", "任务队列"),
    "py-video": ("py", "test_video_ops.py", "", "ffmpeg 裁剪/合并（真素材）"),
    "py-camera": ("py", "test_camera.py", "", "摄像头分片接收/校验/权限钩子（已停用那套）"),
    "py-camapp": ("py", "test_camera_app.py", "", "系统相机：目录解析/停止判据/导入"),
    "py-single": ("py", "test_single_instance.py", "", "单实例闸（不建真窗口）"),
    "real":     ("pyw", "e2e_real.pyw", "e2e_results.txt", "真 GPU + 真 LLM 端到端"),
}
ALL = ["ui-core", "ui-panel", "ui-tree", "py-state", "py-store", "py-media",
       "py-jobs", "py-video", "py-camera", "py-camapp", "py-single"]

#: 测试驱动一律跳过单实例闸 —— 否则用户自己开着一个实例，所有套件都起不来。
#: **只跳过这一道**，其它逻辑照跑（见 src/single_instance.py 的 SKIP_ENV）。
NO_SINGLE = "VKB_NO_SINGLE_INSTANCE"


def run_js(suite):
    kind, script, out, _desc = SUITES[suite]
    outpath = os.path.join(DIAG, out)
    env = dict(os.environ)
    env["VKB_TESTS"] = script
    env["VKB_OUT"] = out
    env["VKB_FAKE"] = "1"
    env[NO_SINGLE] = "1"
    t0 = time.monotonic()
    p = subprocess.run([PYW, os.path.join(DIAG, "ui_run.pyw")], cwd=ROOT,
                       env=env, capture_output=True, timeout=900,
                       encoding="utf-8", errors="replace")
    secs = time.monotonic() - t0
    npass = nfail = 0
    fails = []
    if os.path.isfile(outpath):
        # 结果行的格式是 "t=  4.42  PASS  5a  ..."，有前缀，不能用 startswith
        for line in open(outpath, encoding="utf-8"):
            s = line.strip()
            if " FAIL " in s:
                nfail += 1
                fails.append(s.split("FAIL", 1)[1].strip())
            elif " PASS " in s:
                npass += 1
    return npass, nfail, secs, fails, p.returncode


def run_py(suite):
    kind, script, out, _desc = SUITES[suite]
    outpath = os.path.join(DIAG, out) if out else ""
    if outpath and os.path.exists(outpath):
        os.remove(outpath)
    env = dict(os.environ)
    if kind == "pyw":
        env.pop("VKB_FAKE", None)      # real 走真实链路
        env[NO_SINGLE] = "1"           # e2e 要起真界面，别被单实例闸挡住
    # py 套件各自在文件里设 VKB_FAKE，这里不干预
    t0 = time.monotonic()
    exe = PYW if kind == "pyw" else PY
    args = [exe, os.path.join(DIAG, script)]
    # 必须显式 utf-8：Windows 默认 GBK，中文输出会直接解码炸掉，
    # 表现为"套件跑了但 0 通过 0 失败"（第一版就栽在这）
    p = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, timeout=1800,
                       encoding="utf-8", errors="replace")
    secs = time.monotonic() - t0
    text = ""
    if outpath and os.path.isfile(outpath):
        text = open(outpath, encoding="utf-8").read()
    if not text:
        text = (p.stdout or "") + "\n" + (p.stderr or "")
    npass = nfail = 0
    fails = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("FAIL") or " FAIL " in s:
            nfail += 1
            fails.append(s[:120])
        elif s.startswith("PASS") or " PASS " in s:
            npass += 1
    return npass, nfail, secs, fails, p.returncode


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--suite", nargs="*", default=None)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list:
        print("可选套件：")
        for k, v in SUITES.items():
            print("  %-9s %-6s %s" % (k, "%.0fs" % 0, v[3]))
        print("  all      ~24s   除 real 外全部")
        return 0

    names = a.suite if a.suite else ["all"]
    if "all" in names:
        names = list(ALL)

    print("=" * 64)
    total_pass = total_fail = 0
    rows = []
    all_fails = []
    for name in names:
        if name not in SUITES:
            print("未知套件：%s" % name)
            continue
        kind = SUITES[name][0]
        sys.stdout.write("  %-9s 跑…" % name)
        sys.stdout.flush()
        if kind == "js":
            npass, nfail, secs, fails, rc = run_js(name)
        else:
            npass, nfail, secs, fails, rc = run_py(name)
        total_pass += npass
        total_fail += nfail
        rows.append((name, npass, nfail, secs, rc))
        all_fails.extend((name, f) for f in fails)
        print("\r  %-9s %5.1fs  %d 通过 / %d 失败%s"
              % (name, secs, npass, nfail, "" if not nfail else "   <-- 有失败"))

    print("-" * 64)
    for name, npass, nfail, secs, rc in rows:
        print("  %-9s %6.1fs  %4d 通过  %3d 失败  %s"
              % (name, secs, npass, nfail, SUITES[name][3]))
    print("-" * 64)
    print("  合计      %6.1fs  %4d 通过  %3d 失败"
          % (sum(r[3] for r in rows), total_pass, total_fail))
    if all_fails:
        print("\n失败明细：")
        for suite, f in all_fails[:40]:
            print("  [%s] %s" % (suite, f))
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
