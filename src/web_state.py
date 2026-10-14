# -*- coding: utf-8 -*-
"""界面内存态：知识树 / 条目 / 设置，以及"假处理"的推进。

本模块**不依赖 Qt、不依赖 pywebview** —— 可以脱离界面单独跑测试。
数据来自 mock_data（本轮假数据）；下一轮换成 knowledge_tree + 真实条目时，
只要保持 snapshot() 的输出结构不变，前端一行不用改。

假处理的推进方式：**按时间推导**，不起线程、不起定时器。
点"处理"时记下开始时刻，之后每次 tick() 用 now-start 算出当前阶段与百分比。
这样没有状态机、没有并发，问一次就得到确定值。
"""

import os
import sys
import threading
import time
from datetime import datetime

import mock_data
import store

#: 假处理的时长（秒）
TRANSCRIBE_SEC = 1.6
CLEAN_SEC = 1.1


class WebState:
    def __init__(self, clock=time.monotonic):
        import timing                       # 打点（默认关闭，零开销）
        self._clock = clock
        self._seq = 0

        #: True = VKB_FAKE=1 的假数据回退链路；False = 真实数据（默认）
        self.fake = store.fake_mode()
        #: 真实模式下的串行任务队列，由 app_web 注入
        self.jobs = None

        if self.fake:
            self.tree = mock_data.build_tree()
            self.done = mock_data.build_done_items()
            self.pending = mock_data.build_pending_items()
            self.settings = dict(mock_data.DEFAULT_SETTINGS)
        else:
            with timing.span("   ②a 读 knowledge_tree.json"):
                self.tree = store.load_tree()
            # 老文件第一次被新界面打开时没有持久 id，补上并落盘；
            # 没补说明不用写，避免每次启动都白写一次磁盘
            if store.assign_missing_nids(self.tree):
                store.save_tree(self.tree)
            with timing.span("   ②b 读 config.json"):
                self.settings = store.load_settings()
            with timing.span("   ②c 读 workspace.json") as _si:
                items = store.load_items()
            _si.extra["条数"] = len(items)
            # 老记录缺 media_name（改名断链的受害者）—— 补出来了就立刻写回，
            # 否则每次启动都要重推一遍
            if store.needs_migration():
                self._pending_migration = True
            # 真实链路下：清洗完的算「已完成」，其余算「待处理」
            self.done = [it for it in items if it.ai_processed]
            self.pending = [it for it in items if not it.ai_processed]

        self._processing = {}      # iid -> 开始时刻（仅假链路用）
        self._body_cache = {}
        #: 导入（复制大文件）的进度。放进 light() 让 poll() 带出去。
        self.import_status = {"active": False, "total": 0, "done": 0,
                              "pct": 0.0, "name": "", "error": None}
        #: 最近一次后台操作的结果（裁剪/合并完成）。前端靠 seq 判断新旧。
        self.last_event = None
        self._event_seq = 0
        #: 系统相机应用的监视/导入状态。放进 light() 让 poll() 带出去。
        self.camera_status = {"active": False, "stage": "idle", "note": "",
                              "found": [], "photos": 0, "error": None,
                              "pct": 0.0, "name": "", "dirs": [],
                              "imported": [], "failed": []}
        self._import_thread = None
        self._import_was_active = False
        with timing.span("   ②d _reindex"):
            self._reindex()
        if getattr(self, "_pending_migration", False):
            self._pending_migration = False
            self._persist()          # 把补出来的 media_name 落盘
        if self.fake:
            # 真实数据的关联关系已经写在知识树文件里，不需要再按名字猜
            self._seed_tree_links()

    def _seed_tree_links(self):
        """把树里已有的视频节点挂到同名条目上。

        **只在初始假数据上做这一次**。运行期的「已添加/未添加」一律走 item_id，
        不再按名字 —— 名字会因去 .mp4 后缀、条目改名而变，id 不会。
        """
        by_stem = {it.title_stem: it.iid for it in self.done}
        for n in self.tree.walk():
            if n.is_video() and n.item_id is None:
                iid = by_stem.get(n.name)
                if iid:
                    n.item_id = iid

    # ------------------------------------------------------------------ 索引
    def _new_id(self, prefix):
        # 真实链路要**持久 id**：刷新/重启后不能变，否则「已添加/未添加」会断
        if not self.fake:
            return store.new_nid() if prefix == "n" else store.new_iid()
        self._seq += 1
        return f"{prefix}{self._seq}"

    def _persist(self):
        """把条目清单写回磁盘（真实链路才写）。"""
        if not self.fake:
            store.save_items(list(self.done) + list(self.pending))

    def _persist_tree(self):
        if not self.fake:
            store.save_tree(self.tree)

    def persist_all(self):
        """把条目清单和知识树都写回磁盘。

        由桥接层在**每次变更之后**统一调用 —— 放在一个地方就不会漏；
        每次多写几 KB JSON，代价可以忽略。
        """
        if self.fake:
            return
        self._persist()
        self._persist_tree()

    def _reindex(self):
        self._nodes = {}
        for n in self.tree.walk():
            if getattr(n, "nid", None) is None:
                n.nid = self._new_id("n")
            self._nodes[n.nid] = n
        self._items = {}
        for it in list(self.done) + list(self.pending):
            if getattr(it, "iid", None) is None:
                it.iid = self._new_id("i")
            self._items[it.iid] = it

    def node(self, nid):
        return self._nodes.get(nid)

    def item(self, iid):
        return self._items.get(iid)

    # ------------------------------------------------------------------ 序列化
    def node_media(self, n):
        """视频节点对应的媒体相对 URL；没有就返回空串。"""
        if not n.is_video() or not n.item_id:
            return ""
        it = self._items.get(n.item_id)
        return it.media if it else ""

    def node_body(self, n):
        """节点正文。

        **优先返回节点自己的 body** —— 那是用户在文章里打的字（可编辑、会落盘）。
        只有它为空时才回落到条目的转写产物。

        反过来（先读产物）会把用户打的字吞掉：真实数据里就有这么一条，
        节点上存着用户写的「士大夫」，界面上却是空白 —— 因为产物文件没找到，
        而节点自己的 body 被完全忽略了。
        """
        if n.body and n.body.strip():
            return n.body
        if self.fake or not n.item_id:
            return n.body or ""
        it = self._items.get(n.item_id)
        if it is None:
            return ""
        return store.read_body(it)

    def node_dict(self, n):
        return {
            "id": n.nid,
            "name": n.name,
            "kind": n.kind,
            "collapsed": bool(n.collapsed),
            "body": self.node_body(n),
            "itemId": n.item_id,          # 内容节点才有；文字/主题节点为 None
            "media": self.node_media(n),  # 播放器用
            "children": [self.node_dict(c) for c in n.children],
        }

    def item_dict(self, it, with_tree_flag=False):
        d = {
            "id": it.iid,
            "title": it.title,
            "titleStem": it.title_stem,
            "created": it.created,
            "summary": it.summary,
            "media": it.media,
            "clips": [dict(c) for c in it.clips],
            "origin": it.origin,             # source | clip | merge
            "overwrite": bool(it.overwrite),
            "stage": it.stage,
            #: 进行中的一句话说明（「裁剪 42%」/「合并 3/7 段」）。
            #: 裁剪/合并复用 pct 字段，靠 note 区分它们在干什么
            "note": getattr(it, "note", "") or "",
            "transcribePct": it.transcribe_pct,
            "cleanPct": it.clean_pct,
            "queuedPos": int(getattr(it, "queued_pos", 0) or 0),
            # 真实链路：从磁盘推导，不重复存
            "transcribed": bool(getattr(it, "transcribed", False)),
            "aiProcessed": bool(getattr(it, "ai_processed", False)),
            "error": getattr(it, "error", None),
            "warning": getattr(it, "warning", None),
        }
        if with_tree_flag:
            d["inTree"] = self.is_in_tree(it)
        return d

    def is_in_tree(self, item):
        """条目是否已添加到导图。

        按 **item_id** 推导（树是唯一真值源）：删掉节点就自动回到「未添加」，
        改名不会影响归属，不需要额外维护标记。
        """
        for n in self.tree.walk():
            if n.is_video() and n.item_id == item.iid:
                return True
        return False

    def find_node_by_item(self, iid):
        for n in self.tree.walk():
            if n.is_video() and n.item_id == iid:
                return n
        return None

    def drain(self):
        return [self.item_dict(i) for i in self.done if getattr(i, "stage", "") == "done"]

    def tree_item_ids(self):
        """导图上挂着的条目 id 集合（一遍扫完，别对每条都重走一次树）。"""
        return {n.item_id for n in self.tree.walk()
                if n.is_video() and n.item_id}

    def queue(self):
        """**预处理队列** —— 处理视频浮层左边那个列表显示的就是它。

        🔴 它是**收件箱**，不是条目库。三样都满足才在里头：

          1. 没清洗完（清洗完了算「已完成」，去别处）—— 老规矩
          2. **没进导图** —— 进了导图就是"正文"了，队列里不该再有它
             （用户原话：「他处理完到正文就不需要他了」）
          3. **没被手动出队** —— 用户在这个列表上点 ✕ = "我暂时不处理它了"

        ⚠ **这只是"显示用的视图"，不是存档。** `self.pending` 仍然是
        "所有没清洗的条目"（含出队和已进树的）—— 落盘走的是它。
        要是这里把 pending 本身筛掉，一条出队的记录下次落盘就**没了**。
        """
        on_tree = self.tree_item_ids()
        return [it for it in self.pending
                if it.iid not in on_tree
                and not getattr(it, "dequeued", False)]

    def pending_newest_first(self):
        """预处理队列，**按导入时间倒序**（最新导入的排最上面）。

        两个键一起用，缺一不可：
          · 主键 `created` —— 它才是"导入时间"（`add_item` 时写下的）。
          · 次键"在队列里的先后" —— `created` 只到**分钟**
            （`%Y-%m-%d %H:%M`），一次导十几条会全撞在同一分钟里，
            单键排序对并列的那批等于没排（sorted 稳定，结果就是文件顺序）。

        【为什么不直接倒排 self.pending —— 试过，是错的】
        `pending` 的顺序是**清单文件里的先后**，不等于导入先后：
        条目会在「已完成 / 待处理」两块之间来回搬，搬一次就换个位置。
        实测用户那份数据（2026-10-13）：一条 `created=2026-10-12 20:56`
        的录制 —— 就是丢产物那次的一批 —— 排在 pending 的**第一个**，
        因为它原先在「已完成」块里、掉了清洗稿之后被重新归类。纯倒排会把它
        甩到**最底下**，被压在 8 条 09-27 的老素材下面，看着就是"最新的沉底了"。
        """
        q = self.queue()
        order = sorted(range(len(q)),
                       key=lambda i: (q[i].created or "", i),
                       reverse=True)
        return [q[i] for i in order]

    def dequeue_item(self, iid):
        """把一条从**预处理队列**里拿掉（✕ 干的事）。

        🔴 **只置一个位**。不动导图、不动转写/清洗产物、不动视频文件、
           不删记录 —— 所以它随时能回来（`requeue_item`）。

        这里**不是** delete_item，两个是完全不同的动作，别接错了：

          dequeue_item  「我暂时不处理它了」 → 只出队
          delete_item   「从我的库里删掉它」 → 记录 + 导图节点 + 产物归档
        """
        it = self._items.get(iid)
        if it is None:
            return None
        it.dequeued = True
        return True

    def requeue_item(self, iid):
        """把出队的条目放回队列（可逆的那一半）。"""
        it = self._items.get(iid)
        if it is None:
            return None
        it.dequeued = False
        return True

    def snapshot(self):
        return {
            "fake": self.fake,               # 前端用来区分"设置是否落盘"等提示
            "tree": self.node_dict(self.tree),
            "done": [self.item_dict(i, True) for i in self.done],
            "pending": [self.item_dict(i) for i in self.pending_newest_first()],
            "settings": dict(self.settings),
        }

    def light(self):
        """轮询用的轻量载荷：两个列表 + 导入进度 + 最近一次操作结果。

        为什么要 event：裁剪/合并是后台任务，前端拿不到"完成回调"，
        只能靠轮询。这里把"刚做完什么"捎回去，前端用 seq 判断是不是新的，
        新的就用 setListStatus 显示（那条自带 3 秒保护期，不会被进度冲掉）。
        """
        return {
            "done": [self.item_dict(i, True) for i in self.done],
            "pending": [self.item_dict(i) for i in self.pending_newest_first()],
            "import": dict(self.import_status),
            "camera": dict(self.camera_status),
            "event": dict(self.last_event) if self.last_event else None,
        }

    def _emit(self, text, ok=True, **extra):
        """记一条"刚做完"的事件，交给轮询捎给前端。"""
        self._event_seq = getattr(self, "_event_seq", 0) + 1
        ev = {"seq": self._event_seq, "text": text, "ok": bool(ok)}
        ev.update(extra)
        self.last_event = ev
        # 【必须】让下一次 poll() 报 changed=True。事件本身不改队列状态，
        # 不打这一下前端永远收不到 —— 摄像头导入那次就是这么卡住的。
        if self.jobs is not None:
            self.jobs.touch()

    # ------------------------------------------------- 摄像头（调系统相机应用）
    def open_camera_watch(self):
        """调起系统相机应用并开始等它产出录制文件。

        顺序很重要：**先快照、再调起**。反过来的话，相机应用启动过程中
        可能已经写进文件，那一段就会被当成"启动前就有的旧文件"漏掉。
        """
        import camera_app

        if self.fake:
            return {"ok": False, "error": "假链路（VKB_FAKE=1）不调起系统相机"}

        # 【别再拒绝】以前这里有一句 `if 已有监视在跑: return 已经在等录制了`，
        # 结果是"关掉相机再点"永远打不开 —— 旧监视在相机关闭后还要等
        # REOPEN_GRACE_SEC 才结束，那段时间内全被拒。（现在是 5 秒，
        # 但同理：只要它还在跑就不该拒绝，用户想再开就该能开。）
        # 现在：已有监视就**只拉起相机、不动监视**。理由：
        #   · 旧监视管的是"抓录制文件"，跟"再开一次相机"不冲突
        #   · 取消它反而会丢掉已经收到、还没导入的文件
        #   · 相机一回来 app_running() 变真，监视里的 exit_seen 自动清零，
        #     60 秒宽限那条逻辑照样有效
        running = camera_app.status().get("active")
        if running:
            res = camera_app.launch()
            camera_app._t("已有监视在跑 -> 不新建监视，只拉起相机（ok=%s）"
                          % res.get("ok"))
            if not res.get("ok"):
                return {"ok": False, "error": res.get("error"), "fallback": "dshow"}
            self.camera_status.update(active=True, stage="waiting")
            self.camera_status["reused"] = True
            return {"ok": True, "how": res.get("how"), "reused": True,
                    "frontOk": res.get("frontOk"),
                    "dirs": self.camera_status.get("dirs") or []}

        self.camera_status = {"active": True, "stage": "launching",
                              "note": "正在打开系统相机应用…", "found": [],
                              "photos": 0, "error": None, "pct": 0.0, "name": "",
                              "dirs": []}
        w = camera_app.start_watch(on_done=self._camera_done)
        if w is None:
            return {"ok": False, "error": "上一个监视还没结束"}
        res = camera_app.launch()
        if not res.get("ok"):
            w.cancel()
            self.camera_status.update(active=False, stage="error",
                                      error=res.get("error"),
                                      note="调不起系统相机应用")
            return {"ok": False, "error": res.get("error"),
                    "fallback": "dshow"}
        self.camera_status["dirs"] = camera_app.candidate_dirs()
        camera_app._t("open_camera_watch：快照了 %d 个候选目录，开始监视"
                      % len(self.camera_status["dirs"]))
        # 已经是运行中的实例：拉前台成功就别再说"已打开"，说清是复用的
        front = res.get("frontOk")
        self.camera_status["frontOk"] = front
        if res.get("how") == "already":
            self.camera_status["note"] = (
                "相机应用本来就在运行，已把它切到前台 · "
                "录完关掉它（或停录后静止 8 秒）就会自动导入"
                if front else
                "相机应用在后台运行，但没能自动切到前台 —— "
                "请点任务栏上的「相机」窗口。录制仍会被自动导入")
        else:
            self.camera_status["note"] = (
                "已打开系统相机应用 · 录完关掉相机应用（或停录后静止 8 秒）"
                "就会自动导入")
        # 后台尽力确认/切换到视频模式。切不了不影响主流程，
        # 结果会出现在 camera_status["mode"] 里，界面据此提示。
        camera_app.ensure_video_mode_async()
        return {"ok": True, "how": res.get("how"),
                "dirs": self.camera_status["dirs"]}

    def _camera_done(self, result):
        """监视结束（跑在**监视线程**里）：导入 + 登记 + 发事件。"""
        import camera_app

        if not result.get("ok"):
            why = result.get("reason")
            note = ("没等到录制（10 分钟内相机目录里没有出现新视频）"
                    if why == "timeout"
                    else "相机应用已关闭，但没有检测到新录制的视频"
                    if why == "closed"
                    else "已取消等待" if why == "cancelled"
                    else "监视出错")
            self.camera_status.update(active=False, stage=why or "failed",
                                      note=note,
                                      error=result.get("error"))
            camera_app.set_result(result)
            self._emit(note, ok=False)
            return

        files = result.get("files") or []

        # 导入进度**复用现成的那条导入进度条**（import_status + importWrap）。
        # 为什么不新造一条：那条在导入 4.3 GB 视频时已经验证过，而且浮层删掉后
        # 界面本来就没有第二处放进度条的地方。
        imp = self.import_status
        imp.update(active=True, total=len(files), done=0, pct=0.0,
                   name="", error=None)

        def prog(f, name):
            n = len(files) or 1
            i = 0
            for k, x in enumerate(files):
                if x[1] == name:
                    i = k
                    break
            imp.update(pct=float(f), name=name, done=i)
            self.camera_status.update(pct=float(f), name=name,
                                      note="正在导入 %s" % name)

        try:
            box = camera_app.import_recordings(files, on_progress=prog)
        except Exception as e:                          # noqa: BLE001
            imp.update(active=False, error="%s: %s" % (type(e).__name__, e))
            self.camera_status.update(active=False, stage="error",
                                      note="导入录制失败",
                                      error="%s: %s" % (type(e).__name__, e))
            return
        imp.update(active=False, done=len(files), pct=1.0)

        for x in box["added"]:
            it = x["item"]
            self._items[it.iid] = it
            self.pending.append(it)
        if box["added"]:
            self._persist()

        n_ok, n_bad = len(box["added"]), len(box["failed"])
        photos = result.get("photos") or 0
        camera_app._t("导入完成：%d 段成功 / %d 段失败" % (n_ok, n_bad))
        parts = []
        if n_ok:
            parts.append("已导入 %d 段录制" % n_ok)
        if n_bad:
            parts.append("%d 段导入失败（%s）"
                         % (n_bad, box["failed"][0][1][:40]))
        if photos:
            parts.append("另有 %d 张照片，本程序只导入视频" % photos)
        if not parts:
            parts.append("没有收到可导入的视频")
        text = " · ".join(parts)

        self.camera_status.update(
            active=False, stage="done" if n_ok else "failed",
            note=text, pct=1.0 if n_ok else 0.0,
            # 保留 found：e2e 要靠它报告"新文件出现在哪个目录"，
            # 也要靠它核对相机胶卷里的原文件还在（证明是复制不是搬家）
            found=[{"dir": f[0], "name": f[1], "size": f[2]} for f in files],
            imported=[{"iid": x["iid"], "mediaName": x["mediaName"]}
                      for x in box["added"]],
            failed=box["failed"])
        camera_app.set_result(result)
        self._emit(text, ok=bool(n_ok),
                   imported=[{"iid": x["iid"], "mediaName": x["mediaName"]}
                             for x in box["added"]])

    # ------------------------------------------------------------ 导入（真实）
    def start_import(self, paths):
        """把选中的视频复制进 data/media/。**后台线程做**，界面靠轮询看进度。

        不能在 js_api 调用里同步复制：那会把 WebView 卡住，大文件就是几十秒假死。
        """
        if self.fake:
            return False
        if self._import_thread is not None and self._import_thread.is_alive():
            return False
        paths = [p for p in (paths or []) if os.path.isfile(p)]
        if not paths:
            return False
        self.import_status = {"active": True, "total": len(paths), "done": 0,
                              "pct": 0.0, "name": "", "error": None}
        self._import_touch()        # 起点也要打一下，别等第一次进度回调
        self._import_thread = threading.Thread(
            target=self._import_worker, args=(paths,), name="vkb-import", daemon=True)
        self._import_thread.start()
        return True

    def _import_touch(self):
        """让下一次 poll() 一定报 changed=True。

        【为什么必须显式打这一下】导入**不是队列任务** —— 它只写 import_status，
        队列状态一个字节都没动。以前靠 `_tick_real` 里"看到 active=True 就报
        changed"兜着，可那要求**轮询恰好撞上它 active 的那一小段**：
        复制比两次轮询（120ms）还快、或者文件对话框把 UI 线程堵住让轮询积压，
        就会一次都没撞上 —— 前端于是整包收不到（用户看到"导入一个不显示，
        再导一个一起冒出来"）。这里在**每次状态变化时**主动打一下，把这个
        时间窗彻底消掉，不再依赖"恰好被看见"。
        """
        if self.jobs is not None:
            try:
                self.jobs.touch()
            except Exception:                           # noqa: BLE001
                pass

    def _import_worker(self, paths):
        st = self.import_status
        try:
            for i, p in enumerate(paths):
                st["name"] = os.path.basename(p)
                st["pct"] = 0.0
                done_i = i

                def on_prog(f, _i=done_i):
                    st["pct"] = float(f)
                    st["done"] = _i
                    self._import_touch()

                name = store.import_media(p, on_progress=on_prog)
                it = store.add_item(name, p, media_name=name)
                self._items[it.iid] = it
                self.pending.append(it)
                st["done"] = i + 1
                self._import_touch()
            st["pct"] = 1.0
            self._persist()
        except Exception as e:                          # noqa: BLE001
            st["error"] = "%s: %s" % (type(e).__name__, e)
        finally:
            st["active"] = False
            self._import_touch()

    # ------------------------------------------------------------------ 树操作
    def rename_node(self, nid, name):
        n = self.node(nid)
        if n is None or not name or not name.strip():
            return False
        n.name = name.strip()
        return True

    def set_body(self, nid, text):
        n = self.node(nid)
        if n is None:
            return False
        n.body = text or ""
        return True

    def _attach(self, parent_nid, child):
        parent = self.node(parent_nid) or self.tree
        if parent.is_video():
            parent = self.tree
        child.nid = self._new_id("n")
        parent.add(child)
        parent.collapsed = False
        self._nodes[child.nid] = child
        return child.nid

    def add_text_node(self, parent_nid, name):
        """新建「文字节点」：只有名字，没有来源条目。"""
        if not name or not name.strip():
            return None
        return self._attach(parent_nid, mock_data.MockNode(name.strip(), "topic"))

    def add_content_node(self, parent_nid, iid):
        """新建「内容节点」：从条目挂上去。

        节点名 = 条目标题**去掉扩展名**；节点带 item_id，
        「已添加/未添加」就靠它判定。已经在树里的不再重复挂。
        """
        it = self.item(iid)
        if it is None:
            return None
        if self.find_node_by_item(iid) is not None:
            return None
        # 正文要**全文**：真实链路下 it.text 只有开头 400 字（那是给列表摘要用的），
        # 挂进树时必须换成正篇，否则文章面板永远只有一小段
        body = it.text or ""
        if not self.fake:
            body = store.read_body(it)
        child = mock_data.MockNode(it.title_stem, "video", body=body, item_id=iid)
        return self._attach(parent_nid, child)

    def rename_item(self, iid, name):
        """条目改名，并同步树上挂着的那个内容节点（若有）。"""
        it = self.item(iid)
        if it is None or not name or not name.strip():
            return False
        it.video_name = name.strip()
        node = self.find_node_by_item(iid)
        if node is not None:
            node.name = it.title_stem
        return True

    # ------------------------------------------------------------ 裁剪 / 合并
    @staticmethod
    def _clean_clips(clips):
        out = []
        for c in clips or []:
            if not isinstance(c, dict):
                continue
            try:
                out.append({
                    "media": str(c.get("media", "")),
                    "start": round(float(c.get("start", 0)), 3),
                    "end": round(float(c.get("end", 0)), 3),
                })
            except (TypeError, ValueError):
                continue
        return out

    def set_clips(self, iid, clips):
        """写回一条条目的片段数据。本轮只记录，不真的做视频处理。"""
        it = self.item(iid)
        if it is None or not isinstance(clips, list):
            return False
        it.clips = self._clean_clips(clips)
        return True

    def _unique_title(self, want):
        """同名的条目加序号，避免列表里出现两个一模一样的标题。"""
        taken = {it.title for it in self._items.values()}
        if want not in taken:
            return want
        stem, dot, ext = want.rpartition(".")
        if not dot:
            stem, ext = want, ""
        for n in range(2, 1000):
            cand = f"{stem}_{n}.{ext}" if ext else f"{stem}_{n}"
            if cand not in taken:
                return cand
        return want

    def _add_item(self, title, media, clips, origin, created=None):
        """新建一条条目并放进待处理列表（导入 / 裁剪产物 / 合并产物都走这里）。"""
        it = mock_data.MockItem(
            title, created or datetime.now().strftime("%Y-%m-%d %H:%M"), media=media)
        it.origin = origin
        it.clips = self._clean_clips(clips)
        it.iid = self._new_id("i")
        self._items[it.iid] = it
        self.pending.append(it)
        return it

    def save_clip(self, iid, start, end, overwrite=False):
        """裁剪的两种去处。**不动任何文件**，只记录数据。

        overwrite=False -> 新建一条「片段」条目，原条目原样不动
        overwrite=True  -> 原条目打上待覆盖标记（下一轮 ffmpeg 读它去替换原文件）

        返回 (条目 id, 是否为新建)。失败返回 (None, False)。
        """
        it = self.item(iid)
        if it is None:
            return None, False
        try:
            a, b = float(start), float(end)
        except (TypeError, ValueError):
            return None, False
        if not (0 <= a < b):
            return None, False

        clip = {"media": it.media, "start": a, "end": b}
        if overwrite:
            it.clips = self._clean_clips([clip])
            it.overwrite = True
            return it.iid, False

        title = self._unique_title(it.title_stem + "_clip.mp4")
        new = self._add_item(title, it.media, [clip], "clip")
        return new.iid, True

    def make_merge(self, segments):
        """合并导出：产物是**新条目**，输入的有序片段原样不动。"""
        segs = self._clean_clips(segments)
        if len(segs) < 2:
            return None
        title = "合并_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".mp4"
        new = self._add_item(title, segs[0]["media"], segs, "merge")
        return new.iid

    # ------------------------------------------------- 真生成：裁剪 / 合并（后台任务）
    def submit_clip(self, iid, start, end, overwrite=False):
        """真裁剪：交给串行队列跑 ffmpeg。返回提交成功与否。

        overwrite=False -> 跑完生成新条目（origin="clip"）
        overwrite=True  -> 跑完原地替换原文件，并把旧的转写/清洗产物归档
        """
        if self.fake or self.jobs is None:
            return False
        it = self.item(iid)
        if it is None:
            return False
        if it.stage in ("queued", "loading", "working", "transcribing", "cleaning"):
            return False
        it.stage = "queued"
        it.note = "排队"
        it.error = None
        return self.jobs.submit(
            it, kind="clip",
            payload={"src_media_name": it.media_name, "start": float(start),
                     "end": float(end), "overwrite": bool(overwrite)},
            on_done=self._clip_done)

    def submit_merge(self, segments):
        """真合并：先立一条占位条目（这样列表里看得见「合并 3/7 段」），
        再把任务挂上去；跑完把真实产物名和区间写回这条条目。"""
        if self.fake or self.jobs is None:
            return None
        segs = self._clean_clips(segments)
        if len(segs) < 2:
            return None
        out_name = "合并_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".mp4"
        it = self._add_item(out_name, "media/" + out_name, segs, "merge")
        it.stage = "queued"
        it.note = "排队"
        ok = self.jobs.submit(
            it, kind="merge",
            payload={"segs": segs, "out_name": out_name},
            on_done=self._merge_done)
        if not ok:
            self.pending.remove(it)
            return None
        self._persist()
        return it.iid

    def _finish_job(self, iid):
        """任务收尾：把状态表里这条摘掉，并把条目的 stage 复位。

        不摘掉的话 `_tick_real` 会一直把 stage 读成 done/error，
        条目就永远显示"处理中"了。
        """
        if self.jobs is not None:
            self.jobs.drop(iid)
        it = self.item(iid)
        if it is not None:
            it.stage = "idle"
            it.note = ""
            it.transcribe_pct = 0
            it.clean_pct = 0

    def _clip_done(self, result):
        """裁剪任务成功的收尾（跑在**工作线程**里）。"""
        iid = result["iid"]
        it = self.item(iid)
        if result.get("overwrite"):
            if it is not None:
                it.clips = []
                it.overwrite = False
                # 内容变了，基于旧内容的转写/清洗不再代表这条视频 ——
                # 产物已被 jobs 归档（移进 data/_stale/），状态由磁盘推导，
                # 自然回到「需要重新处理」
                store.refresh_status(it)
                if it.ai_processed:
                    # 理论上不会发生（产物已挪走），真发生了说明归档没生效，
                    # 必须让人看见，不能装作没事
                    it.warning = "覆盖后旧清洗稿仍在，状态可能不准"
                if it in self.done:
                    self.done.remove(it)
                if it not in self.pending:
                    self.pending.append(it)
            self._emit("已覆盖原视频（备份在 data/backups/，旧的转写稿已归档）")
        else:
            name = result["media_name"]
            new = self._add_item(name, "media/" + name,
                                 [{"media": "media/" + name,
                                   "start": result["start"], "end": result["end"]}],
                                 "clip")
            self._emit("已生成片段 %s" % name)
        self._finish_job(iid)
        self._persist()

    def _merge_done(self, result):
        """合并任务成功的收尾（跑在**工作线程**里）。"""
        iid = result["iid"]
        it = self.item(iid)
        if it is not None:
            name = result["media_name"]
            it.media_name = name
            it.media = "media/" + name
            it.video_name = name
            it.clips = self._clean_clips(result.get("clips") or [])
        how = "无损拼接" if result.get("mode") == "copy" else "重编码合并"
        self._emit("已合并 %d 段（%s：%s）" % (result.get("seg_count") or 0,
                                              how, result.get("reason") or ""))
        self._finish_job(iid)
        self._persist()

    def add_recorded(self, media_name, display_name):
        """摄像头录完，命名后入列。media_name 是磁盘上的真实文件名，
        显示名随便改 —— 改名不会把产物链接带走（那是上一轮修好的坑）。"""
        if self.fake:
            return None
        name = (display_name or "").strip() or media_name
        ext = os.path.splitext(media_name)[1]
        if ext and not name.lower().endswith(ext.lower()):
            name = name + ext
        it = store.add_item(name, "", origin="record", media_name=media_name)
        self._items[it.iid] = it
        self.pending.append(it)
        self._persist()
        self._emit("已加入录制视频 %s" % name)
        return it.iid

    def delete_node(self, nid):
        n = self.node(nid)
        if n is None or n.parent is None:      # 根节点不能删
            return False
        n.parent.children.remove(n)
        for x in n.walk():
            self._nodes.pop(x.nid, None)
        return True

    def delete_item(self, iid):
        """删除一个条目 —— **四处一起清**：

          1. 条目记录（会由 persist_all 落回 workspace.json）
          2. 它在导图上的那个节点（连子节点一起；不必分两步删）
          3. 转写 / 清洗产物 —— 走 archive_artifacts()，**归档进 _stale/ 而不是删**
          4. 内存态（_items / done / pending）和队列里挂着的任务

        **视频文件不删**：留在 data/media。确认框里也这么告诉用户。

        返回被归档的产物文件数；条目不存在返回 None（桥接层据此报"找不到"）。
        """
        it = self._items.get(iid)
        if it is None:
            return None

        # 1) 导图上的节点（含它的全部子节点）
        n = self.find_node_by_item(iid)
        if n is not None and n.parent is not None:
            n.parent.children.remove(n)
            for x in n.walk():
                self._nodes.pop(x.nid, None)

        # 2) 三个列表 + 索引
        for lst in (self.done, self.pending):
            if it in lst:
                lst.remove(it)
        self._items.pop(iid, None)

        # 3) 队列里可能还挂着它的任务：先取消再摘。
        #    不取消的话，转写线程跑完还会给一个**已经删掉的条目**重新写出
        #    raw/cleaned 产物 —— 那就白删了。
        if self.jobs is not None:
            for fn in ("cancel", "drop"):
                try:
                    getattr(self.jobs, fn)(iid)
                except Exception:                       # noqa: BLE001
                    pass

        # 4) 派生产物归档（挪进 _stale/，可回溯）
        #    **假链路一律不碰磁盘** —— 整套代码的约定就是这样（persist_all 也是
        #    假链路直接 return）。而且假数据的 base 是 sample_0X，万一哪天跟真实
        #    数据撞名，就会把用户的真产物挪走。
        moved = 0
        if not self.fake:
            try:
                moved = store.archive_artifacts(it.base)
            except Exception as e:                      # noqa: BLE001
                # 归档失败不能装作没事 —— 但也不该拦住删除本身，如实报出来
                print(f"[state] 归档 {it.base} 的产物失败：{e}", file=sys.stderr)

        self._body_cache.pop(iid, None)
        return moved

    def reparent_node(self, nid, target_nid):
        n, t = self.node(nid), self.node(target_nid)
        if n is None or t is None or n is t or n.parent is None:
            return False
        # 禁止拖进自己的后代
        p = t.parent
        while p is not None:
            if p is n:
                return False
            p = p.parent
        n.parent.children.remove(n)
        t.add(n)
        t.collapsed = False
        return True

    def detach_node(self, nid):
        """把一个节点从它的父节点摘出来，挂到**根节点**下（成为顶层节点）。

        **复用 reparent_node** —— "脱离"本质就是"移动到根"，没必要写第二套
        移动逻辑（那套里已经处理了"禁止移进自己的后代"等边界）。
        **子节点跟着一起走**：移动的是整棵子树。

        为什么不是"脱离整棵树"：`save_tree()` 走的是 `_node_to_dict(root)`
        **从根递归**，不在根之下的节点**根本不会被写进 knowledge_tree.json** ——
        重启就没了。所以脱离只能是"挂到根下"。

        **只有根节点不能脱离**。其余任何节点一律执行移动 —— 包括"父就是根"的
        节点：那种情况下 reparent_node 会把它从根摘下来再挂回根，是一次
        **成功的 no-op**（没变化，但也不算失败）。

        （曾经这里还有个"已经是顶层就早退"的分支，前端配套把它禁用。但那个
        特殊处理和用户的心智模型错位 —— 用户说"有子节点的中间节点就该能脱离"，
        而在两层树上，唯一的中间节点恰好就是根的直接子节点，于是被误伤，
        看起来像"只有叶子能用"。现在一律放行。）

        返回 nid；节点不存在 / 是根 返回 None。
        """
        n = self.node(nid)
        root = self.tree
        if n is None or n is root or n.parent is None:
            return None
        return nid if self.reparent_node(nid, root.nid) else None

    def toggle_collapse(self, nid):
        n = self.node(nid)
        if n is None or not n.children:
            return False
        n.collapsed = not n.collapsed
        return True

    # ------------------------------------------------------------------ 条目
    def import_videos(self, names):
        """导入视频 -> 待处理列表。默认不处理。

        本轮没有真实视频文件，给每条轮转挂一段样片，好让预览/裁剪/合并有东西可放。
        """
        created = datetime.now().strftime("%Y-%m-%d %H:%M")
        added = []
        for name in names:
            it = mock_data.MockItem(
                name, created,
                media=mock_data._sample_url(self._seq))   # 轮转换样片
            it.iid = self._new_id("i")
            self._items[it.iid] = it
            self.pending.append(it)
            added.append(it.iid)
        return added

    def add_real_items(self, pairs):
        """真实链路导入后登记。pairs = [(文件名, 源路径)]，返回新条目 id 列表。"""
        added = []
        for name, src in pairs:
            it = store.add_item(name, src)
            self._items[it.iid] = it
            self.pending.append(it)
            added.append(it.iid)
        if added:
            self._persist()
        return added

    def start_processing(self, iid):
        it = self.item(iid)
        if it is None:
            return False
        if not self.fake:
            if self.jobs is None or it.stage in ("queued", "loading",
                                                 "transcribing", "cleaning"):
                return False
            it.stage = "queued"
            it.error = None
            self.jobs.submit(it)
            return True
        if it.stage != "idle":
            return False
        it.stage = "transcribing"
        it.transcribe_pct = 0
        it.clean_pct = 0
        self._processing[iid] = self._clock()
        return True

    def tick(self):
        """推进处理状态。返回是否有任何变化。"""
        if not self.fake:
            return self._tick_real()
        changed = False
        now = self._clock()
        for iid, t0 in list(self._processing.items()):
            it = self._items.get(iid)
            if it is None:
                self._processing.pop(iid, None)
                continue
            el = now - t0
            if el < TRANSCRIBE_SEC:
                it.stage = "transcribing"
                p = int(el / TRANSCRIBE_SEC * 100)
                if p != it.transcribe_pct:
                    it.transcribe_pct = p
                    changed = True
            elif el < TRANSCRIBE_SEC + CLEAN_SEC:
                it.stage = "cleaning"
                if it.transcribe_pct != 100:
                    it.transcribe_pct = 100
                    changed = True
                p = int((el - TRANSCRIBE_SEC) / CLEAN_SEC * 100)
                if p != it.clean_pct:
                    it.clean_pct = p
                    changed = True
            else:
                it.stage = "done"
                it.transcribe_pct = 100
                it.clean_pct = 100
                self._processing.pop(iid, None)
                if it in self.pending:
                    self.pending.remove(it)
                if it not in self.done:
                    self.done.insert(0, it)
                changed = True
        return changed

    def _tick_real(self):
        """真实链路：进度由工作线程写、这里读（**不跨线程调 evaluate_js**）。"""
        if self.jobs is None:
            return False
        changed = self.jobs.changed()
        # 导入期间每轮都算"有变化"，界面才能看到复制进度条在走；
        # 结束那一下也必须报一次，否则列表里新导入的条目不刷新。
        imp = self.import_status
        if imp["active"]:
            changed = True
        if imp["active"] != self._import_was_active:
            self._import_was_active = imp["active"]
            changed = True

        # 系统相机监视：进行中就每轮都刷（界面要看到"已检测到 N 段"在动）。
        # 一旦它停下来，状态由 _camera_done 定稿，这里不再覆盖。
        try:
            import camera_app
            cs = camera_app.status()
            if cs.get("active"):
                keep_pct = self.camera_status.get("pct", 0.0)
                self.camera_status = dict(cs)
                self.camera_status["pct"] = keep_pct
                changed = True
            elif cs.get("mode") != self.camera_status.get("mode"):
                # 模式探测是后台线程干的，它出结果时要让界面刷一次
                self.camera_status["mode"] = cs.get("mode")
                changed = True

            # 分级时间线（查"走了哪一级降级、卡在哪一步"用）。它只在调起和
            # 导入期间增长，之后稳定，不会让 poll 永远报 changed。
            tl = camera_app.timeline()
            if tl != self.camera_status.get("timeline"):
                self.camera_status["timeline"] = tl
                changed = True
        except Exception:                               # noqa: BLE001
            pass

        for it in list(self.pending) + list(self.done):
            st = self.jobs.state_of(it.iid)
            if not st:
                continue
            it.stage = st.get("stage", "idle")
            it.note = st.get("note") or ""
            it.transcribe_pct = int(st.get("pct", 0) or 0)
            it.clean_pct = int(st.get("cleanPct", 0) or 0)
            it.queued_pos = int(st.get("queued", 0) or 0)
            it.error = st.get("error")
            it.warning = st.get("warning")

        # 清洗完成 -> 从「待处理」移进「已完成」
        moved = False
        for it in list(self.pending):
            store.refresh_status(it)
            if it.ai_processed:
                self.pending.remove(it)
                self.done.insert(0, it)
                it.text = store.read_body(it, store.SUMMARY_CHARS)
                it.stage = "done"
                it.queued_pos = 0
                moved = True
        if moved:
            self._persist()
            changed = True
        return changed

    def processing_count(self):
        if not self.fake and self.jobs is not None:
            return self.jobs.active_count()
        return len(self._processing)

    # ------------------------------------------------------------------ 设置
    def save_settings(self, values):
        if not isinstance(values, dict):
            return False
        if self.fake:
            for k in mock_data.DEFAULT_SETTINGS:
                if k in values:
                    self.settings[k] = values[k]
            return True
        self.settings = store.save_settings(values)
        return True

    def reset_settings(self):
        if self.fake:
            self.settings = dict(mock_data.DEFAULT_SETTINGS)
        else:
            self.settings = store.reset_settings()
        return dict(self.settings)
