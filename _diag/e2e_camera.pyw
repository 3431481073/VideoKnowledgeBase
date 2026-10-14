# -*- coding: utf-8 -*-
"""真摄像头端到端（验收 1~5）。**手动跑，不进 all** —— 需要人真的去录一段。

    venv\\Scripts\\pythonw.exe _diag\\e2e_camera.pyw

跑真实链路：真调起 Windows 相机应用 -> **停下来等你录** -> 检测文件 ->
导入 data/media/ -> 弹命名框。

结果写 _diag/e2e_camera_results.txt（边跑边写，可以 tail 着看）。

【要你做什么】跑起来之后：
    1. 会自动弹出 Windows 相机应用
    2. 在里面**切到「视频」模式**（默认是拍照），录 10 秒左右
    3. 关掉相机应用窗口（或者停录后等 8 秒静止）
脚本检测到文件就自动往下走。

【关于你的数据】
  - 你在相机应用里录的那份**原文件不动**，留在相机胶卷里
  - 脚本只把它**复制**一份进 data/media/，跑完会把自己复制的那份和
    workspace 条目清掉，恢复原状
"""

import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG = os.path.join(ROOT, "_diag")
OUT = os.path.join(DIAG, "e2e_camera_results.txt")
os.environ.pop("VKB_FAKE", None)
os.environ["VKB_NO_SINGLE_INSTANCE"] = "1"   # e2e/探针要起真界面，跳过单实例闸
T0 = time.monotonic()
WAIT_SEC = 600           # 最多等你 10 分钟

R = []


def log(m):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("t=%7.2f  %s\n" % (time.monotonic() - T0, m))


def chk(name, cond, extra=""):
    R.append({"name": name, "pass": bool(cond), "extra": str(extra)})
    log("%s  %-46s %s" % ("PASS" if cond else "FAIL", name, extra))


def media_files():
    d = os.path.join(ROOT, "data", "media")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def cleanup(made, names):
    """清掉我复制进来的产物和 workspace 条目。用户相机胶卷里的原文件不动。"""
    import store
    items = store.load_items()
    keep = [it for it in items if it.media_name not in made
            and (it.video_name or "") not in names]
    if len(keep) != len(items):
        store.save_items(keep)
    for n in made:
        p = store.media_path(n)
        if os.path.isfile(p):
            os.remove(p)
    left = [n for n in made if os.path.isfile(store.media_path(n))]
    still = [it.video_name for it in store.load_items()
             if it.media_name in made or (it.video_name or "") in names]
    log("清理：文件残留=%s 条目残留=%s" % (left, still))
    return not left and not still


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

    def cam_state():
        try:
            st = js("JSON.stringify((VKB_DEBUG.process()||{}).camera||{})")
            return json.loads(st) if st else {}
        except Exception:
            return {}

    before_media = set(media_files())
    import store
    before_names = {it.video_name for it in store.load_items()}
    log("跑之前 media 文件数=%d，workspace 条目数=%d"
        % (len(before_media), len(before_names)))

    # ---------------- 1. 调起系统相机应用 ----------------
    js("VKBProcess.open()")
    time.sleep(0.4)
    js("(function(){var b=document.querySelector('#procCamera');if(b)b.click();})()")

    launched = False
    deadline = time.time() + 25
    while time.time() < deadline:
        cs = cam_state()
        if cs.get("dirs"):
            launched = True
            break
        if cs.get("error"):
            break
        time.sleep(0.5)

    cs = cam_state()
    log("摄像头状态 = %s" % json.dumps(cs, ensure_ascii=False)[:400])
    chk("A1 ★ 点「打开摄像头」-> 提示浮层打开",
        js("window.VKBCamera.state().overlayVisible") is True)
    chk("A2 ★ 系统相机应用被调起（监视已开始）", launched is True,
        cs.get("error") or cs.get("note"))
    dirs = cs.get("dirs") or []
    log("监视中的候选目录：")
    for d in dirs:
        log("    %s" % d)
    chk("A3 候选目录非空", len(dirs) >= 1, len(dirs))

    # 真的起进程了吗 —— 直接问系统
    import camera_app
    chk("A4 ★ WindowsCamera.exe 真的在跑", camera_app.app_running() is True,
        camera_app._pids_of(camera_app.CAMERA_EXE))

    # 提示用户去录
    log("")
    log("=" * 62)
    log("  请在系统相机应用窗口里：")
    log("    1) 点底部那个**红色圆点**开始录制（不是白色快门）")
    log("    2) 录 5 秒左右，再点一次同一个圆点停止")
    log("    3) 关掉相机应用窗口")
    log("  脚本最多等你 %d 秒" % WAIT_SEC)
    log("=" * 62)
    log("")
    SIM = "--simulate" in sys.argv
    simfile = None
    if SIM:
        log("--simulate 模式：不用你录，我自己往相机胶卷里放一个文件")
        simfile = place_fake_recording()
        if simfile is not None:
            # 关掉相机应用，免得它还开着；监视会走"文件静止"那条路收工
            import proc
            proc.run(["taskkill", "/F", "/IM", "WindowsCamera.exe"],
                     capture_output=True, timeout=30)
            log("--simulate：已关掉相机应用，等监视检测到文件")
        if simfile is None:
            log("放不进去，改用人工模式")
            SIM = False
    else:
        js("VKBApp.toast('请在相机应用里按红色圆点开始录制，录 5 秒后再按一次停止，"
           "然后关掉相机应用')")

    # ---------------- 2~3. 等你录 + 自动导入 ----------------
    seen_dirs = set()
    last_note = ""
    deadline = time.time() + WAIT_SEC
    final = {}
    while time.time() < deadline:
        cs = cam_state()
        for f in (cs.get("found") or []):
            if f.get("dir"):
                seen_dirs.add(f["dir"])
        if cs.get("note") and cs["note"] != last_note:
            last_note = cs["note"]
            log("  状态：%s" % last_note)
        if not cs.get("active") and cs.get("stage") not in (None, "idle", "launching"):
            final = cs
            break
        time.sleep(0.6)

    chk("A5 ★ 监视跑到了结论（不是一直挂着）", bool(final),
        final.get("stage"))
    log("最终状态 = %s" % json.dumps(final, ensure_ascii=False)[:500])

    # ---------------- 4. 导入结果 ----------------
    added = final.get("imported") or []
    imported = [it["mediaName"] for it in added]
    log("导入的产物 = %s" % imported)
    log("")
    log("【谜底】新文件出现在哪个候选目录：%s"
        % ("  ".join(sorted(seen_dirs)) if seen_dirs else "（没有检测到新文件）"))

    chk("A6 ★ 检测到录制并自动导入", bool(imported), final.get("note"))
    if imported:
        import video_ops
        okall = True
        details = []
        for nm in imported:
            p = store.media_path(nm)
            exists = os.path.isfile(p) and os.path.getsize(p) > 0
            st = video_ops.probe(p) or {}
            dur = st.get("duration") or 0
            vid = bool(st.get("video"))
            details.append("%s 存在=%s %.1fs 视频流=%s"
                           % (nm, exists, dur, vid))
            if not (exists and vid and dur > 0.5):
                okall = False
        for d in details:
            log("    %s" % d)
        chk("A7 ★ 录制的文件真的进了 data/media/ 且能播（有时长+视频流）",
            okall, details[:2])
        # 是不是"复制"而不是"搬家"：相机胶卷里的原文件必须还在
        srcs = [os.path.join(f["dir"], f["name"])
                for f in (final.get("found") or []) if f.get("dir")]
        chk("A8 ★ 是复制进来的（相机胶卷里的原文件一个都没少）",
            bool(srcs) and all(os.path.isfile(s) for s in srcs),
            srcs[:3])

        # ---------------- 5. 命名框 ----------------
        js("window.VKBCamera.open()")
        time.sleep(0.4)
        dlg = js("!!document.querySelector('#dlgText') && "
                 "document.querySelector('#dlgText').open")
        chk("A9 ★ 导入后弹出命名框", dlg is True, dlg)
        if dlg:
            NEW = "e2e摄像头录制"
            js("(function(){var i=document.querySelector('#dlgTextInput');"
               "i.value=%s;})()" % json.dumps(NEW))
            js("(function(){var b=document.querySelector('#dlgTextOk');"
               "if(b)b.click();})()")
            time.sleep(1.5)
            names = {it.video_name for it in store.load_items()}
            chk("A10 ★ 命名生效（列表里出现了这个名字）",
                any(NEW in (n or "") for n in names - before_names),
                sorted(names - before_names))
        else:
            chk("A10 ★ 命名生效", False, "命名框没出来")

    # ---------------- 收尾 ----------------
    now = set(media_files())
    orphan = now - before_media - set(imported)
    chk("A11 除录制产物外没多出别的文件", not orphan, sorted(orphan))

    new_names = {it.video_name for it in store.load_items()} - before_names
    okc = cleanup(set(imported), new_names)
    if simfile and os.path.isfile(simfile):
        os.remove(simfile)
        log("--simulate：已删掉我放进相机胶卷的那份 %s" % os.path.basename(simfile))
        okc = okc and not os.path.isfile(simfile)
    chk("A12 ★ 测试产物已清理（用户数据恢复原状）", okc)
    chk("A13 跑完后 media 文件数与跑之前一致",
        set(media_files()) == before_media,
        sorted(set(media_files()) ^ before_media))
    log("注意：你在相机胶卷里录的那份**原文件没有动**")

    log("---- 结果 ----")
    npass = sum(1 for x in R if x["pass"])
    log("合计 %d 通过 / %d 失败 / 共 %d" % (npass, len(R) - npass, len(R)))
    for x in R:
        if not x["pass"]:
            log("   失败: %s  %s" % (x["name"], x["extra"]))
    time.sleep(0.3)
    os._exit(0)


def place_fake_recording():
    """--simulate：往**真实的**相机胶卷里放一个"刚录好"的文件。

    为什么要这个开关：验收 2（用户去录）需要人手按相机按钮，卡住就验不下去。
    这条通道把"相机应用写出文件"这一步换成"我放一个进去"，其余**全部是真的** ——
    真目录、真监视、真检测、真复制、真 ffprobe、真命名框。
    放进去的那份跑完会删掉（只删我自己放的，名字带 _VKBSIM 前缀绝不会认错）。
    """
    import camera_app
    src = None
    for d in camera_app.candidate_dirs():
        for n in sorted(os.listdir(d), reverse=True):
            if n.upper().startswith("WIN_") and n.lower().endswith(".mp4"):
                src = os.path.join(d, n)
                break
        if src:
            break
    if not src:
        log("--simulate：相机胶卷里没有现成的 WIN_*.mp4 可借用")
        return None
    dst_dir = os.path.dirname(src)
    dst = os.path.join(dst_dir, "WIN_SIM_VKBSIM_%s.mp4"
                       % time.strftime("%Y%m%d_%H%M%S"))
    import shutil
    shutil.copyfile(src, dst)
    log("--simulate：已放入 %s（借自 %s，%d 字节）"
        % (dst, os.path.basename(src), os.path.getsize(dst)))
    return dst


def main():
    f = open(os.path.join(DIAG, "e2e_camera_stderr.txt"), "w",
             encoding="utf-8", buffering=1)
    sys.stdout = f
    sys.stderr = f
    if os.path.exists(OUT):
        os.remove(OUT)
    sys.path.insert(0, os.path.join(ROOT, "src"))

    import app_web
    threading.Thread(target=driver, daemon=True).start()
    try:
        app_web.main()
    except Exception:                                   # noqa: BLE001
        import traceback
        log("主循环异常：%s" % traceback.format_exc())


if __name__ == "__main__":
    main()
