# -*- coding: utf-8 -*-
"""任务队列：转写 / 清洗 / 裁剪 / 合并，**串行 FIFO**。

为什么串行、不并发（三条任一条都够）：
  1. `transcriber.get_model()` 是单例，而 faster-whisper 的
     `WhisperModel.transcribe()` **不是线程安全的**（共享 CUDA 上下文与解码器）。
  2. 转写和重编码都把 GPU/CPU 吃满，并发只会互相拖慢。
  3. 本机 RTX 4060 Laptop 共 8188 MiB，medium 要 1200 MiB —— 够用，但没理由浪费。

为什么裁剪/合并也走这个队列，而不是在 js_api 里同步跑：
  重编码一段视频要几十秒到几分钟。同步跑会把 WebView 卡死，和导入大文件
  是同一个坑（导入当年就是这么栽的，所以它走了后台线程 + 轮询进度）。

进度怎么送到界面：
  工作线程只往 `self._state` 写，界面侧的 `poll()` 每 120ms 来读。
  **绝不从工作线程调 `window.evaluate_js()`** —— pywebview 的 evaluate_js 走
  WebView2 的 COM 线程模型，跨线程调用会踩线程亲和性，这是 pywebview 里最
  容易炸的地方。

任务分派：task["kind"] = transcribe | clip | merge，各自一个 _process_xxx。
失败一律落到 stage="error" 并把原因写进 error 字段，**不吞异常**。
"""

import os
import queue
import threading
import time
import uuid

import store

#: 清洗阶段没有中间进度，用「已耗时」渐近到 90%，不谎报百分比
CLEAN_ASYMPTOTE = 90
CLEAN_HALF_LIFE_SEC = 15.0


class JobQueue:
    def __init__(self):
        self._q = queue.Queue()
        self._lock = threading.Lock()
        self._state = {}          # iid -> {stage, pct, cleanPct, queued, note, error}
        self._order = []          # 还在排队的 iid（有序，用来算位次）
        self._cancel = set()
        self._dirty = True
        self._running = 0
        self._worker = None

    # ------------------------------------------------------------------ 生命周期
    def start(self):
        if self._worker is not None:
            return
        self._worker = threading.Thread(target=self._loop, name="vkb-jobs", daemon=True)
        self._worker.start()

    def stop(self):
        """窗口关闭时叫停。队列是 daemon，进程退出也不会卡住。"""
        with self._lock:
            for iid in list(self._state):
                self._cancel.add(iid)
        self._q.put(None)

    # ------------------------------------------------------------------ 对外
    def submit(self, item, kind="transcribe", payload=None, on_done=None):
        """投一个任务。kind 决定跑哪条流水（转写 / 裁剪 / 合并）。

        on_done(result)：成功后在**工作线程**里回调，由调用方把结果并进
        数据模型（新条目、覆盖标记、状态刷新…）。队列本身不碰界面态。
        """
        with self._lock:
            self._state[item.iid] = {
                "stage": "queued", "pct": 0, "cleanPct": 0, "queued": 0,
                "note": "排队", "error": None, "warning": None, "kind": kind,
            }
            self._order.append(item.iid)
            self._dirty = True
            self._recount_locked()
        self._q.put({"iid": item.iid, "base": item.base,
                     "name": item.video_name, "media_name": item.media_name,
                     "src": item.src, "kind": kind,
                     "payload": payload or {}, "on_done": on_done})
        return True

    def cancel(self, iid):
        with self._lock:
            self._cancel.add(iid)
            if iid in self._order:
                self._order.remove(iid)
                self._recount_locked()
            self._dirty = True
        return True

    def state_of(self, iid):
        with self._lock:
            st = self._state.get(iid)
            return dict(st) if st else None

    def changed(self):
        """自上次调用以来有没有变化（读取即清零）。"""
        with self._lock:
            d = self._dirty
            self._dirty = False
            return d

    def touch(self):
        """标记"有新东西"，让下一次 poll() 报 changed=True。

        给那些**不改队列状态、但界面必须刷新**的事件用。踩过的坑：
        摄像头导入是在监视线程里完成的，它只写了 WebState 的字段，
        没碰队列 —— poll() 于是永远报 changed=False，前端拿不到结果，
        e2e 一直等到超时（文件其实早就导进来了）。
        """
        with self._lock:
            self._dirty = True

    def active_count(self):
        with self._lock:
            return self._running + len(self._order)

    def is_cancelled(self, iid):
        with self._lock:
            return iid in self._cancel

    def drop(self, iid):
        """把一条从状态表里摘掉（条目被删掉时用）。"""
        with self._lock:
            self._state.pop(iid, None)
            if iid in self._order:
                self._order.remove(iid)
            self._cancel.add(iid)
            self._recount_locked()
            self._dirty = True

    # ------------------------------------------------------------------ 内部
    def _recount_locked(self):
        pos = 1
        for iid in self._order:
            st = self._state.get(iid)
            if st is not None:
                st["queued"] = pos
                pos += 1

    def _set(self, iid, **kw):
        with self._lock:
            st = self._state.get(iid)
            if st is None:
                st = {"stage": "queued", "pct": 0, "cleanPct": 0, "queued": 0,
                      "note": "", "error": None, "warning": None}
                self._state[iid] = st
            st.update(kw)
            self._dirty = True

    def _loop(self):
        while True:
            task = self._q.get()
            if task is None:
                return
            iid = task["iid"]
            try:
                with self._lock:
                    self._running += 1
                    if iid in self._order:
                        self._order.remove(iid)
                    self._recount_locked()
                    self._dirty = True
                if self.is_cancelled(iid):
                    self._set(iid, stage="idle", queued=0, pct=0, cleanPct=0,
                              note="")
                else:
                    kind = task.get("kind") or "transcribe"
                    if kind == "clip":
                        self._process_clip(task)
                    elif kind == "merge":
                        self._process_merge(task)
                    else:
                        self._process_transcribe(task)
            except Exception as e:                      # noqa: BLE001
                self._set(iid, stage="error", queued=0, note="",
                          error="%s: %s" % (type(e).__name__, e))
            finally:
                with self._lock:
                    self._running -= 1
                    self._cancel.discard(iid)
                    self._recount_locked()
                    self._dirty = True

    # ------------------------------------------------------------- 转写（原有）
    def _process_transcribe(self, task):
        iid, base, name, src = task["iid"], task["base"], task["name"], task["src"]
        media_name = task.get("media_name") or name

        # 延迟到用时才 import：faster-whisper 很重（拉 ctranslate2 + CUDA），
        # 放到启动期会让开窗变慢；放在这里正好算进"加载模型"那一段。
        import ai_processor
        import transcriber

        self._set(iid, stage="loading", queued=0, pct=0, cleanPct=0,
                  note="加载模型", error=None)

        def on_prog(done, total):
            pct = int(min(99, max(0, done / total * 100)))
            self._set(iid, stage="transcribing", pct=pct, note="转写 %d%%" % pct)

        segments = []
        for seg in transcriber.transcribe_video_iter(
                store.media_path(media_name),
                on_progress=on_prog,
                should_stop=lambda: self.is_cancelled(iid)):
            segments.append(seg)

        if self.is_cancelled(iid):
            self._set(iid, stage="idle", queued=0, pct=0, cleanPct=0, note="")
            return

        if not segments:
            # VAD 把整段都过滤掉了：这不是成功，必须说清楚
            self._set(iid, stage="error", queued=0, pct=0, note="",
                      error="未识别到语音（VAD 过滤掉了全部音频）")
            return

        # 原始转写只写一次
        store.write_raw(base, segments)
        self._set(iid, stage="cleaning", pct=100, cleanPct=0, note="整理")

        cfg = store.load_settings()
        api_key = (cfg.get("clean_api_key") or "").strip()
        if not api_key:
            # 降级路径：转写照做、raw 已落盘、不崩，只是不清洗
            self._set(iid, stage="transcribed", queued=0, pct=100, cleanPct=0,
                      note="已转写",
                      error="未配置清洗 API Key，原始转写已保存（未清洗）")
            return

        result = self._clean_with_progress(iid, segments, cfg, api_key)
        cleaned = (result or {}).get("cleaned_text") or ""
        if not cleaned.strip():
            self._set(iid, stage="error", queued=0, pct=100, cleanPct=0, note="",
                      error="清洗返回了空正文")
            return

        store.write_cleaned(base, cleaned,
                            store.make_meta(name, media_name, src,
                                            store.cleaned_path(base)))
        warn = None
        if ai_processor.will_truncate(segments):
            warn = ("原始转写超过 %d 字，本轮清洗只处理了开头部分，"
                    "清洗稿可能不完整" % ai_processor.MAX_INPUT_CHARS)
        self._set(iid, stage="done", queued=0, pct=100, cleanPct=100, note="",
                  error=None, warning=warn)

    def _clean_with_progress(self, iid, segments, cfg, api_key):
        """清洗是一次阻塞 HTTP，没有中间进度。

        所以拿一个旁路线程去跑它，主线程按**已耗时**推一个渐近值
        （t/(t+15) 封顶 90%）—— 只表达"还在跑"，不假装知道百分比。
        """
        import ai_processor

        box = {}

        def call():
            try:
                box["v"] = ai_processor.process_segments(
                    segments, api_key=api_key,
                    url=cfg.get("clean_url"), model=cfg.get("clean_model"),
                    prompt=cfg.get("clean_prompt"))
            except Exception as e:                      # noqa: BLE001
                box["e"] = e

        t = threading.Thread(target=call, name="vkb-clean", daemon=True)
        t0 = time.monotonic()
        t.start()
        while t.is_alive():
            el = time.monotonic() - t0
            pct = int(CLEAN_ASYMPTOTE * el / (el + CLEAN_HALF_LIFE_SEC))
            self._set(iid, stage="cleaning", cleanPct=pct,
                      note="整理 %d%%" % pct)
            t.join(0.25)

        if "e" in box:
            raise box["e"]
        return box.get("v") or {}

    # ------------------------------------------------------------- 裁剪（真生成）
    def _process_clip(self, task):
        """按 A–B 区间真裁一个文件出来。

        overwrite=False -> 新文件 + 新条目（原名_clip.mp4）
        overwrite=True  -> **先备份**原文件，再原地替换，并归档旧转写产物
        """
        import video_ops

        iid = task["iid"]
        p = task["payload"]
        src_name = p.get("src_media_name") or task.get("media_name")
        src = store.media_path(src_name)
        a, b = float(p.get("start") or 0), float(p.get("end") or 0)
        overwrite = bool(p.get("overwrite"))
        base = store.base_of(src_name)

        self._set(iid, stage="working", queued=0, pct=0, cleanPct=0,
                  error=None, note="裁剪 0%")

        def prog(f):
            pct = int(min(99, max(0, f * 100)))
            self._set(iid, stage="working", pct=pct, note="裁剪 %d%%" % pct)

        def log(m):
            self._set(iid, warning=str(m)[:200])

        stop = lambda: self.is_cancelled(iid)
        tmp = os.path.join(store.MEDIA_DIR, ".clip-%s.mp4" % uuid.uuid4().hex[:8])

        try:
            if overwrite:
                # 【铁律】唯一会动用户原文件的操作：先备份成功，才允许继续。
                # 备份失败直接抛，原文件一个字节都不动。
                backup = store.backup_media(src_name)
                self._set(iid, note="覆盖中（已备份）")
            else:
                backup = None
                out_name = store.unique_media_name(base + "_clip.mp4")
                dst = store.media_path(out_name)

            video_ops.clip(src, tmp, a, b, on_progress=prog, should_stop=stop,
                           log=log)
            if overwrite:
                os.replace(tmp, src)          # 同目录原子替换
                out_name = src_name
                archived = store.archive_artifacts(base)
            else:
                os.replace(tmp, dst)
                archived = 0
        except BaseException:
            # 半截产物不许留在 media/ 里冒充成品
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            raise

        if self.is_cancelled(iid):
            self._set(iid, stage="idle", queued=0, pct=0, note="")
            return

        result = {"iid": iid, "media_name": out_name, "start": a, "end": b,
                  "overwrite": overwrite, "backup": backup,
                  "archived": archived, "src_media_name": src_name}
        self._set(iid, stage="done", queued=0, pct=100, note="", error=None,
                  warning=None)
        if task.get("on_done"):
            task["on_done"](result)

    # ------------------------------------------------------------- 合并（真生成）
    def _process_merge(self, task):
        import video_ops

        iid = task["iid"]
        p = task["payload"]
        raw_segs = p.get("segs") or []
        out_name = p.get("out_name") or ("合并_%s.mp4" % time.strftime("%Y%m%d_%H%M%S"))

        segs = []
        for s in raw_segs:
            # media 是相对 URL（media/xxx.mp4），落盘要的是 data/media 下的名字
            name = os.path.basename(str(s.get("media") or ""))
            segs.append({"path": store.media_path(name),
                         "name": name,
                         "start": float(s.get("start") or 0),
                         "end": float(s.get("end") or 0)})

        total = sum(max(0.0, s["end"] - s["start"]) for s in segs) or 1.0
        bounds = []
        acc = 0.0
        for s in segs:
            acc += max(0.0, s["end"] - s["start"])
            bounds.append(acc / total)

        n = len(segs)

        def prog(f):
            t = f * total
            done = 1
            for i, bnd in enumerate(bounds):
                if t <= bnd * total:
                    done = i + 1
                    break
            else:
                done = n
            pct = int(min(99, max(0, f * 100)))
            self._set(iid, stage="working", pct=pct,
                      note="合并 %d/%d 段" % (min(done, n), n))

        def log(m):
            self._set(iid, warning=str(m)[:200])

        self._set(iid, stage="working", queued=0, pct=0, cleanPct=0,
                  error=None, note="合并 0/%d 段" % n)

        out_name = store.unique_media_name(out_name)
        dst = store.media_path(out_name)
        plan = video_ops.merge(segs, dst, on_progress=prog,
                               should_stop=lambda: self.is_cancelled(iid),
                               log=log)

        if self.is_cancelled(iid):
            try:
                if os.path.isfile(dst):
                    os.remove(dst)
            except OSError:
                pass
            self._set(iid, stage="idle", queued=0, pct=0, note="")
            return

        result = {"iid": iid, "media_name": out_name, "mode": plan["mode"],
                  "reason": plan["reason"], "seg_count": n,
                  "order": [s["name"] for s in segs],
                  "clips": [{"media": "media/" + s["name"],
                             "start": s["start"], "end": s["end"]} for s in segs]}
        self._set(iid, stage="done", queued=0, pct=100, note="", error=None)
        if task.get("on_done"):
            task["on_done"](result)
