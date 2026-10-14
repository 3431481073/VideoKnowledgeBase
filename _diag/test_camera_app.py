# -*- coding: utf-8 -*-
"""camera_app 单测：**不真调起相机应用**，所以谁都能跑。

覆盖真正会出事的地方：
  1. 候选目录算得对不对（本机实测：系统 API 给 C 盘空目录，真实录像在 D 盘）
  2. 图片库 XML 解析
  3. 快照 diff：新增视频认得出、照片另算、删除也算"有变化"
  4. **停止判据**：文件稳定 + 静止 QUIET_SEC -> 收工；进程退出 + 宽限 -> 收工；
     超时 -> 明确报"没等到"
  5. 导入：复制进 media、ffprobe 复核、坏文件不收还报错

第 4 节把 snapshot / app_running 换成剧本，跑**真的** Watch 主循环，
所以验的是真停止逻辑，不是"函数被调用了"。
"""

import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
os.environ.pop("VKB_FAKE", None)

TMP = tempfile.mkdtemp(prefix="vkb_camapp_test_")

import config      # noqa: E402
import store       # noqa: E402

store.BASE_DIR = TMP
store.DATA_DIR = os.path.join(TMP, "data")
store.MEDIA_DIR = os.path.join(store.DATA_DIR, "media")
store.RAW_DIR = os.path.join(store.DATA_DIR, "raw_transcripts")
store.AI_DIR = os.path.join(store.DATA_DIR, "ai_processed")
store.BACKUP_DIR = os.path.join(store.DATA_DIR, "backups")
store.STALE_DIR = os.path.join(store.DATA_DIR, "_stale")
store.WORKSPACE_FILE = os.path.join(store.DATA_DIR, "workspace.json")
store.TREE_FILE = os.path.join(store.DATA_DIR, "knowledge_tree.json")
config.DATA_DIR = store.DATA_DIR
config.CONFIG_FILE = os.path.join(store.DATA_DIR, "config.json")

import camera_app   # noqa: E402
import video_ops    # noqa: E402

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


def make_video(path, secs=2):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cmd = [video_ops.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc=s=160x120:r=10:d=%d" % secs,
           "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % secs,
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "64k", "-t", str(secs), path]
    import proc
    r = proc.run(cmd, capture_output=True, text=True,
                 encoding="utf-8", errors="replace", timeout=120)
    if r.returncode != 0:
        raise SystemExit("造视频失败: %s" % r.stderr[:300])
    return path


def main():
    print("=" * 60)
    print("py-camapp：调起/目录解析/停止判据/导入（不碰真相机应用）")

    # ---------------- 0. 隔离 ----------------
    chk("K0a ★ 落盘目录隔离在临时目录",
        os.path.abspath(store.MEDIA_DIR).startswith(os.path.abspath(TMP)),
        store.MEDIA_DIR)

    # ---------------- 1. 候选目录 ----------------
    dirs = camera_app.candidate_dirs()
    print("        候选目录：")
    for d in dirs:
        print("          %s" % d)
    chk("K1a 候选目录非空", len(dirs) >= 2, dirs)
    chk("K1b 全部真实存在（不返回不存在的路径）",
        all(os.path.isdir(d) for d in dirs), dirs)
    chk("K1c 没有重复项", len(set(dirs)) == len(dirs), dirs)
    kf = camera_app.known_folder("{AB5FB87B-7CE2-4F83-915D-550846C9537B}")
    chk("K1d SHGetKnownFolderPath 能取到相机胶卷", bool(kf), kf)
    # 本机实测的关键一条：系统 API 给的目录**不是**真正在写录制的那个，
    # 所以必须靠图片库/兜底把 D 盘那个也覆盖进来
    lib = camera_app.library_folders()
    print("        图片库目录：%s" % lib)
    chk("K1e ★ 图片库解析出条目", len(lib) >= 1, lib)
    if os.path.isdir(r"D:\asus\Pictures"):
        chk("K1f ★ 图片库里的 D 盘目录被解析出来",
            any(os.path.abspath(p).lower().startswith(r"d:\asus\pictures")
                for p in lib), lib)
        chk("K1g ★ 候选目录覆盖了真实录像所在的 D 盘相机胶卷",
            any(os.path.abspath(d).lower() == r"d:\asus\pictures\camera roll"
                for d in dirs), dirs)
    else:
        chk("K1f ★ 图片库里的 D 盘目录被解析出来", True, "本机无 D:\\asus\\Pictures，跳过")
        chk("K1g ★ 候选目录覆盖真实录像目录", True, "跳过")

    # 已知文件夹解析不出来时要返回 None，而不是编一个默认路径顶上
    chk("K1h 取不到的 GUID 返回 None（不猜默认值）",
        camera_app.known_folder("{00000000-0000-0000-0000-000000000000}") is None)

    # ---------------- 2. 快照 / 差分 ----------------
    d1 = os.path.join(TMP, "camdir")
    os.makedirs(d1, exist_ok=True)
    camera_app.candidate_dirs = lambda: [d1]          # 只盯这一个
    with open(os.path.join(d1, "old.mp4"), "wb") as f:
        f.write(b"x" * 100)
    with open(os.path.join(d1, "desktop.ini"), "wb") as f:
        f.write(b"[.ShellClassInfo]")
    s0 = camera_app.snapshot()
    chk("K2a 快照收到了已有文件", "old.mp4" in s0[d1], list(s0[d1]))
    chk("K2b desktop.ini 被排除（不是录制产物）",
        "desktop.ini" not in s0[d1], list(s0[d1]))

    with open(os.path.join(d1, "WIN_20260927_10_00_00_Pro.mp4"), "wb") as f:
        f.write(b"y" * 5000)
    with open(os.path.join(d1, "WIN_20260927_10_00_05.jpg"), "wb") as f:
        f.write(b"z" * 800)
    s1 = camera_app.snapshot()
    dd = camera_app.diff(s0, s1)
    chk("K2c ★ 新增视频被认出来",
        [v[1] for v in dd["videos"]] == ["WIN_20260927_10_00_00_Pro.mp4"], dd["videos"])
    chk("K2d 新增照片单独归类（不当视频收）",
        [p[1] for p in dd["photos"]] == ["WIN_20260927_10_00_05.jpg"], dd["photos"])
    chk("K2e 标了 changed", dd["changed"] is True)

    # 文件变大也算变化
    with open(os.path.join(d1, "WIN_20260927_10_00_00_Pro.mp4"), "ab") as f:
        f.write(b"y" * 3000)
    s2 = camera_app.snapshot()
    chk("K2f ★ 文件变大被认出来（录制中要能看见它在长）",
        camera_app.diff(s1, s2)["changed"] is True)
    chk("K2g 完全没变 -> changed=False",
        camera_app.diff(s2, camera_app.snapshot())["changed"] is False)

    # 删除也算变化（用户清空目录时不能误判成"静止了"）
    os.remove(os.path.join(d1, "WIN_20260927_10_00_05.jpg"))
    chk("K2h ★ 文件被删也算有变化", camera_app.diff(s2, camera_app.snapshot())["changed"])

    # ---------------- 3. 进程枚举 ----------------
    pids = camera_app._pids_of("WindowsCamera.exe")
    chk("K3a 进程枚举能跑通（相机没开时应为空）", isinstance(pids, list), pids)
    chk("K3b ★ 相机没开时 app_running()=False（不误判）",
        camera_app.app_running() is False, pids)
    chk("K3c 不存在的进程名返回空", camera_app._pids_of("绝对没有这个.exe") == [])

    # ---------------- 4. 停止判据（跑真的主循环，喂剧本） ----------------
    # 用户定的：一个文件都没收到时，相机进程消失后 **5 秒** 就结束监视
    chk("K4p ★ 默认重开宽限就是 5.0 秒",
        camera_app.REOPEN_GRACE_SEC == 5.0, camera_app.REOPEN_GRACE_SEC)
    # 退出后的"立刻收工"那一套（用户质疑"为什么要等 5 秒"之后加的）
    chk("K4p2 ★ 退出后短轮询 0.25 秒", camera_app.EXIT_POLL_SEC == 0.25,
        camera_app.EXIT_POLL_SEC)
    chk("K4p3 ★ 退出后 2 次不变就算写完", camera_app.EXIT_STABLE_TICKS == 2,
        camera_app.EXIT_STABLE_TICKS)
    chk("K4p4 退出后的判据比平时的更宽松（「立刻」才有意义）",
        camera_app.EXIT_STABLE_TICKS < camera_app.STABLE_TICKS,
        "%d vs %d" % (camera_app.EXIT_STABLE_TICKS, camera_app.STABLE_TICKS))
    chk("K4p5 ★ 没有「到点强行收下」那种兜底（那会把刚出现的文件收走）",
        not hasattr(camera_app, "EXIT_SETTLE_MAX_SEC"),
        getattr(camera_app, "EXIT_SETTLE_MAX_SEC", "没有"))

    # 缩短节奏，免得测试等半天。EXIT_POLL_SEC 用产品默认值不覆盖 ——
    # 下面那条"真实计时"要量的就是它。
    camera_app.POLL_SEC = 0.05
    camera_app.STABLE_TICKS = 2
    camera_app.QUIET_SEC = 0.3

    def run_watch(script, timeout=5.0, running_script=None, quiet=None,
                  grace=None):
        """script: [[文件名, ...], ...] 每次 snapshot 返回的当前文件集合。

        每一项必须是**列表**。写成 ["A.mp4", ...] 会被当成遍历字符串的字符，
        目录里就会出现叫 'A'、'.'、'm' 的"文件" —— 这个坑我踩过一次。
        """
        box = {}
        idx = {"i": 0}

        def fake_snapshot():
            i = min(idx["i"], len(script) - 1)
            files = script[i]
            idx["i"] += 1
            return {d1: {n: (5000, 1.0) for n in files}}

        run = {"n": 0}

        def fake_running():
            if running_script is None:
                return True
            r = running_script[min(run["n"], len(running_script) - 1)]
            run["n"] += 1
            return r

        orig_s, orig_r = camera_app.snapshot, camera_app.app_running
        orig_q = camera_app.QUIET_SEC
        orig_g = camera_app.REOPEN_GRACE_SEC
        camera_app.snapshot = fake_snapshot
        camera_app.app_running = fake_running
        # 缩短"重开宽限"，测试要跑得快；grace 给了就用给的（真实计时那条要真 5 秒）
        camera_app.REOPEN_GRACE_SEC = 0.4 if grace is None else grace
        if quiet is not None:
            # 把"静止"判据推远，好把"进程退出"这条路径单独隔离出来测。
            # 不隔离的话静止总是先到（它不需要等进程），退出那条永远轮不到。
            camera_app.QUIET_SEC = quiet
        try:
            w = camera_app.Watch(on_done=lambda r: box.update(r), timeout=timeout)
            w.before = {d1: {}}
            w.state["dirs"] = [d1]
            w.state["active"] = True
            import threading
            t = threading.Thread(target=w._loop, daemon=True)
            t.start()
            t.join(timeout + 5)
            return box, w.status()
        finally:
            camera_app.snapshot = orig_s
            camera_app.app_running = orig_r
            camera_app.QUIET_SEC = orig_q
            camera_app.REOPEN_GRACE_SEC = orig_g

    # 4a. 文件出现 -> 长完 -> 静止 -> 收工
    box, st = run_watch([["A.mp4"]] * 12, timeout=4.0)
    chk("K4a ★ 静止够久 -> 收工并报成功", box.get("ok") is True, box)
    chk("K4b ★ 收工理由说清了（文件已稳定）",
        "稳定" in (box.get("reason") or ""), box.get("reason"))
    chk("K4c 收到的文件就是那一段",
        [f[1] for f in (box.get("files") or [])] == ["A.mp4"], box.get("files"))
    chk("K4d 状态里记着它在哪个目录（e2e 靠这个报告新文件出现在哪）",
        (box.get("files") or [[None]])[0][0] == d1, box.get("files"))

    # 4b. 录两段，一起收
    box2, _ = run_watch([["A.mp4"]] * 3 + [["A.mp4", "B.mp4"]] * 9, timeout=4.0)
    got2 = sorted(f[1] for f in (box2.get("files") or []))
    chk("K4b ★ 连录两段 -> 两段都收（不丢）", got2 == ["A.mp4", "B.mp4"], got2)

    # 4c. 相机进程退出 -> 宽限后收工（不用等静止）
    box3, _ = run_watch([["A.mp4"]] * 20, timeout=4.0, quiet=99.0,
                        running_script=[True, True, False, False, False,
                                        False, False, False])
    chk("K4c ★ 相机应用关闭 -> 也能收工（不必等静止判据）",
        box3.get("ok") is True, box3)
    chk("K4d 理由说的是应用已关闭",
        "关闭" in (box3.get("reason") or ""), box3.get("reason"))

    # 4d. 什么都没录（目录一直是空的）-> 超时必须明确报，不能装作成功
    box4, st4 = run_watch([[]] * 40, timeout=0.6)
    chk("K4e ★ 一直没文件 -> 超时，不报成功",
        box4.get("ok") is False and box4.get("reason") == "timeout", box4)
    chk("K4f ★ 超时的说明写的是没等到录制（不静默）",
        "没等到" in (st4.get("note") or ""), st4.get("note"))

    # 4e. 相机应用关了但什么都没录 -> 文案不能说成"超时没等到"
    box5, st5 = run_watch([[]] * 90, timeout=6.0, quiet=99.0,
                          running_script=[True, True, False] + [False] * 30)
    chk("K4g ★ 关掉应用却没录 -> 不报成功", box5.get("ok") is False, box5)
    chk("K4h ★ 结束理由说的是「应用已关闭」而不是「超时」",
        box5.get("reason") == "closed", box5.get("reason"))
    chk("K4i ★ 提示文案不许出现「没等到录制（N 分钟内…）」这种假信息",
        "分钟" not in (st5.get("note") or ""), st5.get("note"))

    # 4f. 应用关一下又回来、然后才录 —— 不许早早收工
    box6, _ = run_watch([[]] * 4 + [["A.mp4"]] * 30, timeout=6.0,
                        running_script=[True, True, False, False, True] + [True] * 30)
    chk("K4j ★ 应用闪退又回来、之后才录 -> 仍然等到了（不早退）",
        box6.get("ok") is True and [f[1] for f in (box6.get("files") or [])] == ["A.mp4"],
        box6)

    # 4g. **真实计时**：用产品默认的 5.0 秒宽限，量真的墙钟时间。
    # 前面几条用的是缩短常量（验逻辑），这条验"常量 + 主循环"合起来是对的。
    t0 = time.monotonic()
    box7, st7 = run_watch([[]] * 400, timeout=30.0, quiet=99.0, grace=5.0,
                          running_script=[True] + [False] * 400)
    dt = time.monotonic() - t0
    log_line = "      真实计时：相机消失后 %.2fs 结束监视" % dt
    print(log_line)
    chk("K4q ★★ 真按产品默认 5 秒宽限结束（墙钟 4~10 秒）",
        4.0 <= dt <= 10.0, "%.2fs" % dt)
    chk("K4r 结束理由仍是「应用已关闭」", box7.get("reason") == "closed",
        box7.get("reason"))

    # 4h. **用户质疑「为什么要等 5 秒」之后改的**：文件已经稳定，进程一退就收工。
    #     跑**真的**主循环 + 真的墙钟 —— 旧逻辑这里要等满 5 秒才结束。
    t1 = time.monotonic()
    box8, _ = run_watch([["A.mp4"]] * 400, timeout=30.0, quiet=99.0, grace=5.0,
                        running_script=[True, True, True] + [False] * 400)
    dt2 = time.monotonic() - t1
    print("      真实计时：文件已稳定，进程消失后 %.2fs 就收工（旧逻辑要等满 5 秒）" % dt2)
    chk("K4s ★★ 文件已稳定 -> 进程一退立刻收工，不再等 5 秒（墙钟 < 3 秒）",
        dt2 < 3.0, "%.2fs" % dt2)
    chk("K4t 照样收下了那一段",
        [f[1] for f in (box8.get("files") or [])] == ["A.mp4"], box8.get("files"))
    chk("K4u 结束理由说的是「应用已关闭」", "关闭" in (box8.get("reason") or ""),
        box8.get("reason"))

    # 4i. **不许误判**：进程早就没了，文件**晚一步**才出现 —— 不能因为
    #     "重开宽限到点了"就把这段丢掉。放开的只有"一个文件都没收到"那条路。
    #
    #     时间线（EXIT_POLL_SEC=0.25、REOPEN_GRACE_SEC=5.0）：
    #       i=21  el=1.05  发现进程不在了
    #       i=40  el=5.80  文件才出现（exited 状态，还只见过一次）
    #       i=41  el=6.05  ★ 宽限到点 —— 「一个文件都没收到」那条路若不加
    #                      `not stable`，就在这里 break，这段录像当场丢掉
    #       i=43  el=6.55  看够 EXIT_STABLE_TICKS 次没再变大 -> 收下
    #
    #     把"看几次"临时调到 4，好让"还没确认完"和"宽限到点"撞在同一轮 ——
    #     不然 i=41 那一轮就已经确认完、威胁根本没机会出现（测不到就是白测）。
    _et = camera_app.EXIT_STABLE_TICKS
    camera_app.EXIT_STABLE_TICKS = 4
    try:
        box9, st9 = run_watch([[]] * 40 + [["A.mp4"]] * 80, timeout=20.0,
                              quiet=99.0, grace=5.0,
                              running_script=[True, True, False] + [False] * 200)
    finally:
        camera_app.EXIT_STABLE_TICKS = _et
    chk("K4v ★★ 进程退出后才出现的录制，仍然收下（不被重开宽限截胡）",
        [f[1] for f in (box9.get("files") or [])] == ["A.mp4"], box9)
    chk("K4w 收工理由说的是应用已关闭", "关闭" in (box9.get("reason") or ""),
        box9.get("reason"))
    chk("K4x 没把它误报成「没检测到新录制的视频」",
        "没有检测到" not in (st9.get("note") or ""), st9.get("note"))

    # ---------------- 5. 导入 ----------------
    srcdir = os.path.join(TMP, "rec")
    a = make_video(os.path.join(srcdir, "WIN_20260927_11_00_00_Pro.mp4"), 2)
    b = make_video(os.path.join(srcdir, "WIN_20260927_11_00_30_Pro.mp4"), 3)
    with open(os.path.join(srcdir, "坏的.mp4"), "wb") as f:
        f.write(b"not a video at all")

    prog = []
    res = camera_app.import_recordings(
        [(srcdir, "WIN_20260927_11_00_00_Pro.mp4", os.path.getsize(a)),
         (srcdir, "WIN_20260927_11_00_30_Pro.mp4", os.path.getsize(b))],
        on_progress=lambda f, n: prog.append((round(f, 2), n)))

    chk("K5a ★ 两个真实录制都导入成功", len(res["added"]) == 2, res["failed"])
    chk("K5b 没有失败项", not res["failed"], res["failed"])
    if res["added"]:
        names = [x["mediaName"] for x in res["added"]]
        chk("K5c ★ 文件真的复制进 data/media/",
            all(os.path.isfile(store.media_path(n)) for n in names), names)
        chk("K5d 复制不是原地引用（源和产物是两个文件）",
            all(os.path.abspath(store.media_path(n)) != os.path.abspath(a)
                for n in names))
        chk("K5e 内容逐字节一致",
            open(store.media_path(names[0]), "rb").read() == open(a, "rb").read())
        chk("K5f ★ 条目带上了时长和分辨率",
            res["added"][0].get("seconds") and res["added"][0].get("width") == 160,
            res["added"][0])
        chk("K5g ★ 记下了来源目录（e2e 要用它报告存哪）",
            res["added"][0].get("sourceDir") == srcdir, res["added"][0].get("sourceDir"))
        item0 = res["added"][0].get("item")
        chk("K5h ★ 条目带 origin=record 且指向真实文件名",
            item0 is not None and item0.origin == "record"
            and item0.media_name == names[0]
            and item0.base == os.path.splitext(names[0])[0],
            item0 and (item0.origin, item0.media_name, item0.base))
        chk("K5i 进度回调在推进", len(prog) >= 2 and prog[-1][0] >= 0.9, prog[-3:])

    # 坏文件要**明确报错**并跳过，不能静默收下
    res2 = camera_app.import_recordings(
        [(srcdir, "坏的.mp4", os.path.getsize(os.path.join(srcdir, "坏的.mp4")))])
    chk("K5j ★ 不是视频的文件被拒（不静默收下）",
        not res2["added"] and len(res2["failed"]) == 1, res2)
    chk("K5k 拒绝原因说得清（读不出视频流）",
        "视频流" in (res2["failed"][0][1] if res2["failed"] else ""), res2["failed"])

    res3 = camera_app.import_recordings([(srcdir, "根本没有.mp4", 0)])
    chk("K5l 源文件不见了也报错不崩",
        not res3["added"] and res3["failed"], res3)

    # 重名：同一个源导入两次不许互相覆盖
    res4 = camera_app.import_recordings(
        [(srcdir, "WIN_20260927_11_00_00_Pro.mp4", os.path.getsize(a))])
    if res4["added"]:
        n1 = res["added"][0]["mediaName"]
        n2 = res4["added"][0]["mediaName"]
        chk("K5m ★ 重名自动加序号，不覆盖之前那份", n1 != n2, (n1, n2))
        chk("K5n 两份都在", os.path.isfile(store.media_path(n1))
            and os.path.isfile(store.media_path(n2)))
    else:
        chk("K5m ★ 重名自动加序号，不覆盖之前那份", False, res4)
        chk("K5n 两份都在", False, "上一条已失败")

    print("-" * 60)
    print("py-camapp 合计 %d 通过 / %d 失败" % (ok, len(bad)))
    for x in bad:
        print("   失败: %s" % x)
    return 1 if bad else 0


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
