# -*- coding: utf-8 -*-
"""暴露给 JS 的桥接层（pywebview 的 js_api）。

约定：
  - 每次**变更**都返回完整状态 {"ok": bool, "state": {...}} —— 前端拿到后整体重渲染。
    数据量很小（约 10 KB），换来的是"永远不会有局部状态不一致"。
  - 轮询接口 poll() 返回轻量载荷，只含右上/右下两个列表。
"""

import os


class WebBridge:
    def __init__(self, state, window_provider=None):
        self.state = state
        self._window_provider = window_provider
        #: 媒体挂载失败时的原因。非 None 则前端会显示醒目错误。
        self._media_error = None

    def set_media_error(self, msg):
        """由 app_web 在启动时设置。**不做静默降级** —— 宁可显式报错。"""
        self._media_error = msg

    # ------------------------------------------------------------------ 只读
    def get_state(self):
        import timing
        with timing.span("⑨ get_state（前端首屏来取全量）") as s:
            out = self.state.snapshot()
        if timing.ON:
            try:
                import json
                s.extra["KB"] = round(len(json.dumps(out, ensure_ascii=False)) / 1024, 1)
                s.extra["树节点"] = sum(1 for _ in self.state.tree.walk())
            except Exception:                             # noqa: BLE001
                pass
        return out

    def poll(self):
        """JS 每 120ms 调一次：推进"假处理"并带回最新列表。"""
        import timing
        with timing.span("⑩ poll（每 120ms 一次）", slow_ms=80):
            changed = self.state.tick()
            payload = {"changed": changed}
            payload.update(self.state.light())
        return payload

    # ------------------------------------------------------------------ 树
    def _wrap(self, ok, extra=None):
        """每次变更后统一落盘 —— 放在这一个地方就不会漏（假链路里是空操作）。

        【写盘失败必须当场可见】以前这里是裸的 `self.state.persist_all()`：
        它一抛异常，整个 js_api 调用就 reject，而前端那些 .then 链没有 catch，
        于是**"没保存上"被完全静默地吞掉** —— 用户以为改动生效了。
        现在改成：捕获 -> ok=False + 明确文案，前端必然显示出来。
        """
        save_error = None
        if ok:
            try:
                self.state.persist_all()
            except Exception as e:                      # noqa: BLE001
                save_error = "%s: %s" % (type(e).__name__, e)
                ok = False
        out = {"ok": bool(ok), "state": self.state.snapshot()}
        if extra:
            out.update(extra)
        if save_error:
            # 放在最后覆盖：写盘失败优先于调用方自己带的说明
            out["ok"] = False
            out["reason"] = "save-failed"
            out["error"] = "写盘失败，这次改动没有保存：" + save_error
        return out

    def rename_node(self, nid, name):
        return self._wrap(self.state.rename_node(nid, name))

    def set_body(self, nid, text):
        return self._wrap(self.state.set_body(nid, text))

    def add_text_node(self, parent_nid, name):
        """新建「文字节点」：只有名字。"""
        nid = self.state.add_text_node(parent_nid, name)
        return self._wrap(nid is not None, {"newId": nid})

    def add_content_node(self, parent_nid, iid):
        """新建「内容节点」：从条目挂上去，名字去掉扩展名。

        【失败要说清是哪一种】以前只返回 nid/None，前端不管什么原因一律弹
        「该条目已经在树里了」。于是**一次真正的失败（条目不存在 / 挂不上）
        会被伪装成一句无关紧要的提示**，用户以为只是重复添加，划过去就算了。
        实测踩过：用户以为加进树了，重启后没有。
        现在把三种原因分开带回去，前端按 error 原文显示。
        """
        if self.state.item(iid) is None:
            return self._wrap(False, {
                "reason": "item-missing",
                "error": "找不到这个条目（列表可能还没刷新），请稍后重试"})
        if self.state.find_node_by_item(iid) is not None:
            return self._wrap(False, {
                "reason": "already", "error": "该条目已经在树里了"})
        nid = self.state.add_content_node(parent_nid, iid)
        if nid is None:
            return self._wrap(False, {
                "reason": "attach-failed", "error": "挂到树上失败（父节点可能已不存在）"})
        return self._wrap(True, {"newId": nid})

    def delete_node(self, nid):
        return self._wrap(self.state.delete_node(nid))

    def delete_item(self, iid):
        """删除条目：记录 + 导图节点 + 产物归档（**视频文件保留在 data/media**）。

        走 _wrap —— 落盘失败会变成 ok=False + 明确的写盘失败文案，
        前端一定看得见（不再被 .then 链静默吞掉）。
        """
        moved = self.state.delete_item(iid)
        if moved is None:
            return self._wrap(False, {
                "reason": "item-missing",
                "error": "找不到这个条目（列表可能还没刷新），请稍后重试"})
        return self._wrap(True, {"archived": moved})

    def dequeue_item(self, iid):
        """把一条从**预处理队列**里拿掉 —— 处理浮层那个 ✕ 干的事。

        🔴 和 delete_item 是两码事，别接错：
            dequeue_item  「暂时不处理它了」→ 只置一个位，**什么都不删**
            delete_item   「从库里删掉它」  → 记录 + 导图节点 + 产物归档

        第一版把 ✕ 接到了 delete_item 上 —— 用户在预处理列表里点一下，
        导图上对应的节点跟着没了（实测丢了一个节点）。那条路已经断掉。
        """
        if self.state.dequeue_item(iid) is None:
            return self._wrap(False, {
                "reason": "item-missing",
                "error": "找不到这个条目（列表可能还没刷新），请稍后重试"})
        return self._wrap(True, {"dequeued": True})

    def requeue_item(self, iid):
        """把出队的条目放回队列（可逆的那一半）。"""
        if self.state.requeue_item(iid) is None:
            return self._wrap(False, {"reason": "item-missing",
                                      "error": "找不到这个条目"})
        return self._wrap(True, {"dequeued": False})

    def reparent_node(self, nid, target_nid):
        return self._wrap(self.state.reparent_node(nid, target_nid))

    def detach_node(self, nid):
        """把节点从父节点摘出来、挂到根下（成为顶层节点）。子节点跟着走。

        **只有根节点不能脱离。** 已经是根的直接子节点时，这次操作是 no-op ——
        但**算成功**（ok=True），并用 `moved=False` 告诉前端"什么都没变，
        别弹'已脱离'那种假话"。
        """
        n = self.state.node(nid)
        root = self.state.tree
        if n is None:
            return self._wrap(False, {"reason": "node-missing",
                                      "error": "找不到这个节点（列表可能还没刷新）"})
        if n is root:
            return self._wrap(False, {"reason": "is-root",
                                      "error": "根节点不能脱离自己"})
        was_top = (n.parent is root)
        if self.state.detach_node(nid) is None:
            return self._wrap(False, {"reason": "detach-failed",
                                      "error": "脱离失败（节点可能已经不在了）"})
        return self._wrap(True, {"nid": nid, "moved": not was_top})

    def toggle_collapse(self, nid):
        return self._wrap(self.state.toggle_collapse(nid))

    # ------------------------------------------------------------------ 条目
    def rename_item(self, iid, name):
        """条目改名（右下已完成列表支持），树上挂着的节点名同步。"""
        return self._wrap(self.state.rename_item(iid, name))

    def set_clips(self, iid, clips):
        """保存裁剪/合并结果。本轮只记录，不做真实视频处理。"""
        return self._wrap(self.state.set_clips(iid, clips))

    def save_clip(self, iid, start, end, overwrite=False):
        """裁剪：保存为新片段 / 覆盖原视频。

        假链路 = 老行为（只记数据，供 ui-panel 断言）。
        真实链路 = 提交后台任务真跑 ffmpeg，立即返回；进度靠 poll 带出去，
        结果由 state 的 _clip_done 收尾并 emit 事件。
        """
        if not self.state.fake:
            ok = self.state.submit_clip(iid, start, end, overwrite)
            return self._wrap(ok, {"queued": ok})
        nid, created = self.state.save_clip(iid, start, end, overwrite)
        return self._wrap(nid is not None, {"iid": nid, "created": created})

    def make_merge(self, segments):
        """合并导出。

        假链路 = 老行为（立即产出一条新条目）。
        真实链路 = 提交后台任务，**先立一条占位条目**（列表里就能看见
        「合并 3/7 段」），跑完把真实产物名写回去。
        """
        if not self.state.fake:
            iid = self.state.submit_merge(segments)
            return self._wrap(iid is not None, {"iid": iid, "queued": iid is not None})
        nid = self.state.make_merge(segments)
        return self._wrap(nid is not None, {"iid": nid})

    def cancel_job(self, iid):
        """取消排队中/进行中的任务（转写、裁剪、合并都走这条）。"""
        if self.state.jobs is None:
            return self._wrap(False)
        return self._wrap(self.state.jobs.cancel(iid), self.state.light())

    # ------------------------------------------------------------------ 摄像头
    # 正路：调起**系统相机应用**（src/camera_app.py），用户在里面录，
    # 我们盯目录、拿结果。页面里不再调 getUserMedia，也不再走 js_api 传分片。
    def open_camera_app(self):
        """调起系统相机应用并开始等录制产物。"""
        r = self.state.open_camera_watch()
        return self._wrap(r.get("ok", False), {"camera": r})

    def camera_status(self):
        """监视/导入进度。前端轮询 poll() 已经能拿到，这个是按需查询口。"""
        import camera_app
        return {"ok": True, "camera": self.state.camera_status,
                "watch": camera_app.status()}

    def cancel_camera(self):
        import camera_app
        ok = camera_app.cancel()
        return {"ok": bool(ok)}

    def cam_devices(self):
        """给降级路径/设置页看有哪些 dshow 设备。"""
        import camera
        return camera.devices()

    def cam_dshow_record(self, seconds, device=None):
        """**降级路径**：ffmpeg 直接抓摄像头。

        触发条件写死在前端：`open_camera_app` 失败（系统相机应用调不起来）
        才会走到这里。代价是录制期间没有画面可看。
        """
        import camera
        try:
            r = camera.dshow_record(seconds, device)
        except Exception as e:                          # noqa: BLE001
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        it = self.state.add_recorded(r["mediaName"], r["mediaName"])
        return {"ok": bool(it), "mediaName": r["mediaName"], "seconds": r["seconds"],
                "iid": it, "device": r.get("device")}

    def start_processing(self, iid):
        return self._wrap(self.state.start_processing(iid), self.state.light())

    def item_text(self, iid):
        """某条目的正文全文（清洗稿优先，否则原始转写）。

        点右下条目时前端来取一次 —— 列表里的 summary 只有 20 字，不够显示全文。
        """
        it = self.state.item(iid)
        if it is None:
            return {"ok": False, "text": ""}
        # 假链路没有磁盘产物，正文就是条目自带的那段
        text = it.text or ""
        if not self.state.fake:
            import store
            text = store.read_body(it)
        return {"ok": True, "text": text, "title": it.title,
                "transcribed": bool(it.transcribed),
                "aiProcessed": bool(it.ai_processed)}

    def cancel_processing(self, iid):
        """取消排队中/进行中的转写。已落盘的 raw 保留（不是回滚）。"""
        if self.state.jobs is None:
            return self._wrap(False)
        return self._wrap(self.state.jobs.cancel(iid), self.state.light())

    # ------------------------------------------------------------------ 媒体
    def list_media(self):
        """可用媒体列表 + 挂载状态。挂载失败会带上明确原因，不做静默降级。"""
        import media
        return {
            "ok": media.link_ok(),
            "error": self._media_error,
            "dir": media.MEDIA_DIR,
            "items": media.list_media() if media.link_ok() else [],
        }

    def media_probe(self, url):
        """读某段媒体的时长（秒）。前端播放器需要它来画时间轴。"""
        import media
        import os
        name = os.path.basename(str(url or ""))
        path = os.path.join(media.MEDIA_DIR, name)
        if not os.path.isfile(path):
            return {"ok": False, "duration": None}
        return {"ok": True, "duration": media.probe_duration(path)}

    def import_videos(self, names):
        ids = self.state.import_videos(list(names or []))
        return self._wrap(bool(ids), {"added": len(ids)})

    def pick_videos(self):
        """弹系统文件选择框。

        真实链路：选中的视频**复制进 data/media/**，后台线程做，界面轮询看进度
        （同步复制会把 WebView 卡死几十秒）。
        假链路：只把文件名变成条目，用于界面断言。
        """
        import webview

        win = self._window_provider() if self._window_provider else None
        if win is None:
            return self._wrap(False, {"error": "no window"})
        try:
            files = win.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=True,
                file_types=("视频文件 (*.mp4;*.avi;*.mov;*.mkv;*.flv;*.wmv)",
                            "所有文件 (*.*)"))
        except Exception as e:
            return self._wrap(False, {"error": str(e)})
        if not files:
            return self._wrap(False, {"cancelled": True})

        if not self.state.fake:
            started = self.state.start_import(list(files))
            return self._wrap(started, {"started": started, "count": len(files)})

        names = [os.path.basename(f) for f in files]
        ids = self.state.import_videos(names)
        return self._wrap(bool(ids), {"added": len(ids), "started": bool(ids)})

    # ------------------------------------------------------------------ 设置
    def save_settings(self, values):
        ok = self.state.save_settings(values or {})
        return self._wrap(ok, {"settings": dict(self.state.settings)})

    def reset_settings(self):
        vals = self.state.reset_settings()
        return self._wrap(True, {"settings": vals})
