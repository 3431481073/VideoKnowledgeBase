/* 处理浮层（非模态，可拖动）。三个模式：

     常态  ──勾选 1 条 + 点「裁剪」──▶  裁剪（单视频）
           ──勾选 ≥2 条 + 点「合并」──▶  合并（多视频）

   常态页里三种点击互不干扰（规格要求）：
     勾选框   -> 只切换选中，**不动预览**
     行的其余 -> 只在右边预览，**不进任何模式、不改选中**
     「转写」 -> 只对本行触发
     「✕」    -> **只把这条从预处理列表里拿掉**，什么都不删
                 （导图节点 / 转写稿 / 视频文件 / 记录全不动 —— 见 dequeueRow）

   这个列表是**预处理队列**（收件箱），不是条目库 —— 所以这里没有"删除"这个动作。

   【为什么单击不再选中】以前单击行 = 选中 + 预览，用户的原话是
   "单击视频条就默认选中了左边的框"。选中的唯一入口现在只有勾选框。

   裁剪和合并互不知情：各自的进入/退出路径、各自的播放器实例、各自的状态。
   两个模式都不动文件，只产生**数据**（clips / origin / overwrite）或**新条目**。
   下一轮接 ffmpeg 时，ffmpeg 只读这些字段，这个文件一行不用改。
*/
(function () {
  'use strict';

  var $ = function (s) { return document.querySelector(s); };

  var P = {
    open_: false,
    page: 'list',          // list | trim | merge
    items: [],             // 待处理条目（app.js 灌进来）
    checked: {},           // iid -> true（给裁剪/合并用；与预览无关）
    preview: null,         // 常态页右边正在预览的条目
    cropItem: null,        // 裁剪模式操作的那一条
    trim: { a: 0, b: 0 },
    duration: 0,
    segs: [],              // 合并顺序 [{media, title, start, end}]
    transcribingId: null,
    listP: null,
    trimP: null,
    mergeP: null,
    _seqActive: false,
    _seqIdx: 0,
    _autoBack: null,
    _lastEventSeq: 0,      // 后台任务完成事件的去重（靠 seq 判新旧）
    cameraStatus: {},      // 系统相机监视/导入状态（轮询灌进来）
  };

  function fmt(t) { return (t || 0).toFixed(2) + 's'; }
  function range(c) { return (c.start || 0).toFixed(1) + '–' + (c.end || 0).toFixed(1) + 's'; }

  // ------------------------------------------------------------------ 初始化
  function init() {
    var barOpts = function (prefix, stage) {
      return {
        video: $('#' + prefix + 'Video'), playBtn: $('#' + prefix + 'Play'),
        seek: $('#' + prefix + 'Seek'), timeLabel: $('#' + prefix + 'Time'),
        vol: $('#' + prefix + 'Vol'), muteBtn: $('#' + prefix + 'Mute'),
        muteToggles: false, rotateBtn: $('#' + prefix + 'Rotate'),
        stage: $(stage), empty: $('#' + prefix + 'Empty'),
      };
    };
    P.listP = window.VKBPlayer.make(Object.assign(barOpts('list', '#listStage'), {
      emptyText: '点左边列表里的视频预览',
    }));
    P.trimP = window.VKBPlayer.make(Object.assign(barOpts('trim', '#trimStage'), {
      emptyText: '没有可裁剪的视频',
    }));
    P.mergeP = window.VKBPlayer.make(Object.assign(barOpts('merge', '#mergeStage'), {
      emptyText: '点播放按顺序播放',
      // 合并页的播放键 = 启动顺序播放（规格：「点播放按顺序播」）
      beforePlay: function () {
        if (P._seqActive) return true;      // 进行中/中途暂停 → 交给播放器正常继续
        startSequence();
        return false;                        // 已接管
      },
    }));

    $('#procClose').addEventListener('click', close);
    $('#procImport').addEventListener('click', doImport);
    // 摄像头：打开预览浮层（真接入。权限放行在 src/camera.py 里）。
    // 浮层自己负责预览/录制/错误提示，这里只负责开。
    $('#procCamera').addEventListener('click', function () {
      if (window.VKBCamera) { window.VKBCamera.open(); }
    });
    $('#btnCropMode').addEventListener('click', enterCrop);
    $('#btnMergeMode').addEventListener('click', enterMerge);
    $('#btnTranscribeSel').addEventListener('click', transcribeSelected);
    $('#chkAll').addEventListener('change', function () {
      var on = $('#chkAll').checked;
      P.checked = {};
      if (on) P.items.forEach(function (it) { P.checked[it.id] = true; });
      renderList();
    });

    // 裁剪页
    $('#trimBack').addEventListener('click', function () { gotoPage('list'); });
    $('#btnSaveClip').addEventListener('click', function () { saveClip(false); });
    $('#btnOverwrite').addEventListener('click', function () { saveClip(true); });

    // 合并页
    $('#mergeBack').addEventListener('click', function () { gotoPage('list'); });
    $('#btnExportMerge').addEventListener('click', exportMerge);

    bindTrimDrag();
    bindMergeDrag();
    bindPanelDrag();
  }

  // ------------------------------------------------------------------ 开关 / 翻页
  function open() {
    P.open_ = true;
    $('#procOverlay').classList.remove('hidden');
    gotoPage('list');
    placeDefault();
  }
  function close() {
    P.open_ = false;
    $('#procOverlay').classList.add('hidden');
    stopPlayers();
  }
  function isOpen() { return P.open_; }

  function stopPlayers() {
    P.listP.pause();
    P.trimP.pause(); P.trimP.clearRange();
    P.mergeP.pause(); P.mergeP.clearRange();
    P._seqActive = false;
  }

  var PAGE_HINT = {
    list: '点一条预览 · 勾选 1 条裁剪 · 勾选 2 条以上合并',
    trim: '拖两个把手选区间 · 点播放只在区间内循环 · 不动原文件',
    merge: '拖 ⠿ 改顺序 · 点播放按顺序播 · 导出为新文件',
  };

  /** 取消"保存后自动回常态"的定时器。
   *  不取消的话，用户在延时窗口内又进了裁剪/合并，会被这个旧定时器拽出去。 */
  function clearAutoBack() {
    if (P._autoBack) { clearTimeout(P._autoBack); P._autoBack = null; }
  }

  function gotoPage(name) {
    clearAutoBack();
    P.page = name;
    ['list', 'trim', 'merge'].forEach(function (p) {
      var el = $('#pageProc' + p.charAt(0).toUpperCase() + p.slice(1));
      if (el) el.classList.toggle('hidden', p !== name);
    });
    $('#procHint').textContent = PAGE_HINT[name] || PAGE_HINT.list;
    // 离开哪一页就把哪一页的播放器停掉 —— 三个模式互不干扰
    if (name !== 'list') P.listP.pause();
    if (name !== 'trim') P.trimP.pause();
    if (name !== 'merge') { P.mergeP.pause(); P._seqActive = false; }
  }

  function placeDefault() {
    var panel = $('#procPanel');
    if (panel.dataset.placed) return;
    panel.dataset.placed = '1';
    panel.style.marginRight = '0px';
    panel.style.marginBottom = '0px';
  }

  /** 拖动标题栏移动面板 */
  function bindPanelDrag() {
    var head = $('#procHead'), panel = $('#procPanel');
    var dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
    head.addEventListener('mousedown', function (e) {
      if (e.target.closest('button')) return;
      dragging = true;
      var r = panel.getBoundingClientRect();
      sx = e.clientX; sy = e.clientY; ox = r.left; oy = r.top;
      panel.style.position = 'fixed';
      panel.style.left = ox + 'px';
      panel.style.top = oy + 'px';
      panel.style.alignSelf = 'flex-start';
      e.preventDefault();
    });
    window.addEventListener('mousemove', function (e) {
      if (!dragging) return;
      var nx = Math.max(0, Math.min(window.innerWidth - 120, ox + e.clientX - sx));
      var ny = Math.max(0, Math.min(window.innerHeight - 40, oy + e.clientY - sy));
      panel.style.left = nx + 'px';
      panel.style.top = ny + 'px';
    });
    window.addEventListener('mouseup', function () { dragging = false; });
  }

  // ------------------------------------------------------------------ 常态页
  function setItems(items) {
    P.items = items || [];
    // 条目没了就把它从选中/预览里摘掉
    var alive = {}, byId = {};
    P.items.forEach(function (it) { byId[it.id] = it; if (P.checked[it.id]) alive[it.id] = true; });
    P.checked = alive;
    if (P.preview && !byId[P.preview.id]) {
      P.preview = null;
      P.listP.clear('点左边列表里的视频预览');
    }
    renderList();
    updateActions();
  }

  function tagOf(it) {
    var c = (it.clips && it.clips[0]) || null;
    if (it.warning) return { cls: 'warn', text: '⚠ 清洗稿可能不完整' };
    if (it.error) return { cls: 'ow', text: '⚠ 未完成' };
    if (it.origin === 'merge') return { cls: 'mg', text: '合并 ' + (it.clips || []).length + ' 段' };
    if (it.origin === 'clip' && c) return { cls: 'cl', text: '片段 ' + range(c) };
    if (it.overwrite && c) return { cls: 'ow', text: '待覆盖 ' + range(c) };
    return null;
  }

  /* 真实链路的阶段比假链路多：排队 / 加载模型 / 已转写未清洗 / 失败。
     这些都要如实显示 —— 「转写 100% 却停着不动」是最难排查的那种状态。 */
  function stageText(it) {
    switch (it.stage) {
      case 'queued': return it.queuedPos ? '排队 ' + it.queuedPos : '排队';
      case 'loading': return '加载模型…';
      case 'transcribing': return (it.transcribePct || 0) + '%';
      case 'cleaning': return '整理 ' + (it.cleanPct || 0) + '%';
      case 'transcribed': return '已转写';
      case 'working': return it.note || '处理中';
      case 'error': return '失败';
      case 'done': return '已完成';
      default: return '转写';
    }
  }

  function stageDetail(it) {
    switch (it.stage) {
      case 'queued': return '排队中（第 ' + (it.queuedPos || 1) + ' 位）';
      case 'loading': return '正在加载转写模型（首次约 10 秒）…';
      case 'transcribing': return '转写 ' + (it.transcribePct || 0) + '%';
      case 'cleaning': return '整理中…（大模型清洗没有中间进度）';
      case 'transcribed': return it.error || '已转写，未清洗';
      case 'working': return it.note || '处理中…';
      case 'error': return '失败：' + (it.error || '未知原因');
      case 'done': return '已完成';
      default: return '未处理';
    }
  }

  function renderList() {
    var host = $('#procList');
    host.innerHTML = '';
    $('#procCount').textContent = '共 ' + P.items.length + ' 条';

    // 导入中：列表顶部给个占位行，让人看见"东西正在进来"
    var imp = P.importStatus || {};
    if (imp.active) {
      var ph = document.createElement('div');
      ph.className = 'proc-item importing';
      ph.textContent = '正在导入… ' + (imp.name || '') +
        '（' + (imp.done || 0) + '/' + (imp.total || 0) + '）';
      host.appendChild(ph);
    }

    if (!P.items.length) {
      if (!imp.active) {
        host.innerHTML = '<div class="pick-empty">还没有待处理视频<br>点上面「导入视频」加一个</div>';
      }
      updateActions();
      return;
    }
    P.items.forEach(function (it) {
      var d = document.createElement('div');
      d.className = 'proc-item'
        + (P.checked[it.id] ? ' checked' : '')
        + (P.preview && P.preview.id === it.id ? ' active' : '');
      d.dataset.id = it.id;

      // 勾选框：只切换选中，不动预览
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.className = 'ci';
      cb.checked = !!P.checked[it.id];
      cb.title = '勾选（给裁剪 / 合并 / 转写用）';
      cb.addEventListener('click', function (e) { e.stopPropagation(); });
      cb.addEventListener('change', function () {
        setChecked(it.id, cb.checked);
        d.classList.toggle('checked', cb.checked);
        updateActions();
      });

      var nm = document.createElement('span');
      nm.className = 'nm';
      nm.textContent = it.titleStem || it.title;
      nm.title = '双击改名';

      // 转写：只对本行触发
      var tr = document.createElement('button');
      tr.className = 'btn tr';
      tr.textContent = stageText(it);
      tr.title = '只转写这一条';
      tr.addEventListener('click', function (e) { e.stopPropagation(); transcribe(it); });

      // 出队：把这条从**预处理列表**里拿掉。**什么都不删** ——
      // 导图节点 / 转写稿 / 视频文件全都不动（第一版接到了 delete_item 上，
      // 结果在列表里点一下，导图上对应的节点跟着没了）。
      var del = document.createElement('button');
      del.className = 'btn del';
      del.textContent = '✕';
      del.title = '从待处理列表里移除（导图上的内容和视频文件都不动）';
      del.addEventListener('click', function (e) { e.stopPropagation(); dequeueRow(it); });

      d.appendChild(cb);
      d.appendChild(nm);
      var tg = tagOf(it);
      if (tg) {
        var t = document.createElement('span');
        t.className = 'pill ' + tg.cls;
        t.textContent = tg.text;
        d.appendChild(t);
      }
      d.appendChild(tr);
      d.appendChild(del);

      // 单击行 = **只预览**。不改选中 —— 多选的唯一入口是左边的勾选框
      //（用户原话："单击视频条就默认选中了左边的框"）
      d.addEventListener('click', function () { previewItem(it); });
      // 双击名字 = 改名
      d.addEventListener('dblclick', function (e) {
        if (e.target.closest('.ci') || e.target.closest('.tr') ||
            e.target.closest('.del')) return;
        e.preventDefault();
        renameItemDialog(it);
      });
      host.appendChild(d);
    });
    updateActions();
  }

  function setChecked(iid, on) {
    if (on) P.checked[iid] = true; else delete P.checked[iid];
  }

  /** 双击改名：弹框交给 app.js（它已经有统一的输入弹层） */
  function renameItemDialog(it) {
    if (!window.VKBApp || !window.VKBApp.renameItemPrompt) return;
    window.VKBApp.renameItemPrompt(it);
  }

  /** 常态页右边预览某一条。**不进入任何模式、不改选中。**
   *
   * 已经在放这一条就什么都不做 —— 列表每 120ms 重渲染一次，
   * 不挡一下的话双击改名（=两次 click）会把视频重载两遍。
   */
  function previewItem(it) {
    if (P.preview && P.preview.id === it.id) return;
    P.preview = it;
    Array.prototype.forEach.call($('#procList').querySelectorAll('.proc-item'), function (el) {
      el.classList.toggle('active', el.dataset.id === it.id);
    });
    var url = it.media || '';
    $('#listEmpty').textContent = url ? '正在加载…' : '这条没有关联视频文件';
    P.listP.load(url, { autoplay: false, emptyText: '这条没有关联视频文件' });
  }

  function checkedIds() {
    return P.items.filter(function (it) { return P.checked[it.id]; })
                  .map(function (it) { return it.id; });
  }

  /** 行尾「✕」= **把这条从预处理列表里拿掉**。不是删除。
   *
   *  🔴 这个列表是**预处理队列**（收件箱），不是条目库。在这儿点 ✕ 的意思是
   *     "我暂时不处理它了"，**不是**"从我的知识库里删掉它"：
   *
   *       导图上的节点 / 正文   —— 不动
   *       转写稿 / 清洗稿       —— 不动
   *       视频文件              —— 不动
   *       条目记录              —— 留着（只置一个"出队"位，可逆）
   *
   *  第一版这里接的是 `delete_item`，用户在列表里点一下，**导图上对应的节点
   *  跟着没了** —— 实测丢过一个节点。所以两个动作彻底分开了：
   *      这个按钮 -> dequeue_item（只出队）
   *      右下角卡片的右键删除 -> delete_item（真删，带归档）
   *
   *  **不弹确认框** —— 用户要求的："直接删了就行，不需要确认"。理由也站得住：
   *  这个动作不删任何东西、而且可逆，那层遮挡纯属多余。点了立刻生效，
   *  状态行给一句话回执。
   */
  function dequeueRow(it) {
    var name = it.titleStem || it.title;
    // 【不弹确认框】用户明确要求："直接删了就行，不需要确认"。
    // 这个动作本来就不删任何东西（只置一个"出队"位，可逆），
    // 所以确认框那层遮挡纯属多余 —— 点了就立刻生效，状态行给一句话回执。
    VKB.call('dequeue_item', it.id).then(function (r) {
      if (!r) return;
      if (window.VKBApp && r.state) window.VKBApp.applyState(r.state);
      if (!r.ok) {
        setListStatus('移除失败：' + (r.error || '未知原因'));
        return;
      }
      // 它已经不在列表里了，预览/勾选别留着一个看不见的条目
      if (P.preview && P.preview.id === it.id) {
        P.preview = null;
        P.listP.clear('点左边列表里的视频预览');
      }
      delete P.checked[it.id];
      updateActions();
      setListStatus('已从待处理列表移除「' + name + '」（导图和视频都没动）');
    }).catch(function (e) { setListStatus('移除失败：' + e.message); });
  }

  /** 按钮启用规则（规格定死）：
   *  裁剪 = 选中恰好 1 条；合并 = 选中 ≥2 条；转写 = 选中 ≥1 条。 */
  function updateActions() {
    var n = checkedIds().length;
    var total = P.items.length;
    $('#pickCount').textContent = '已选 ' + n + ' 条';
    $('#btnCropMode').disabled = (n !== 1);
    $('#btnMergeMode').disabled = (n < 2);
    $('#btnTranscribeSel').disabled = (n < 1);
    $('#btnTranscribeSel').textContent = n > 1 ? ('转写 ' + n + ' 条') : '转写';
    // 全选：全中都勾上；否则一律不勾（部分选中不显示成"勾上"，免得误判）
    var all = $('#chkAll');
    if (all) {
      all.checked = (total > 0 && n === total);
      all.indeterminate = (n > 0 && n < total);
    }
  }

  function doImport() {
    VKB.call('pick_videos').then(function (r) {
      if (r && r.cancelled) { setListStatus('导入已取消'); return; }
      if (r && r.state && window.VKBApp) window.VKBApp.applyState(r.state);
      if (r && r.started) {
        // 真实链路：这里只是"开始复制"，进度靠轮询带回来。
        // 【立刻把占位行画出来，不等下一次轮询】—— 用户点了按钮就该马上有反应，
        // 不能出现"点了没动静、过一会儿东西才凭空冒出来"那种感觉。
        P.importStatus = { active: true, total: r.count || 0, done: 0,
                           pct: 0.0, name: '', error: null };
        renderList();
        setListStatus('已选择 ' + (r.count || 0) + ' 个视频，正在复制进媒体库…');
        return;
      }
      if (r && r.added) { setListStatus('已导入 ' + r.added + ' 个视频'); return; }
      // 失败也要说清为什么 —— 以前这里只会显示"导入未开始"，等于什么都没说
      setListStatus('导入没开始：' + ((r && r.error) || '原因不明'));
    }).catch(function (e) { setListStatus('导入失败：' + e.message); });
  }

  function transcribe(it) {
    VKB.call('start_processing', it.id).then(function (r) {
      if (!r || !r.ok) { setListStatus('这条已经在处理了'); return; }
      P.transcribingId = it.id;
      setListStatus('开始转写：' + (it.titleStem || it.title));
      if (window.VKBApp && window.VKBApp.onProcessingStarted) {
        window.VKBApp.onProcessingStarted();
      }
    }).catch(function (e) { setListStatus('启动失败：' + e.message); });
  }

  /** 批量转写：把所有选中的条目入队（队列本来就是串行的，一次提交即可）。 */
  function transcribeSelected() {
    var ids = checkedIds();
    if (!ids.length) { setListStatus('先选中至少一条'); return; }
    setListStatus('已提交 ' + ids.length + ' 条到转写队列…');
    var done = 0;
    ids.forEach(function (iid) {
      VKB.call('start_processing', iid).then(function (r) {
        done++;
        if (done === ids.length) setListStatus('已提交 ' + ids.length + ' 条，队列串行处理中');
      }).catch(function () { done++; });
    });
  }

  // ------------------------------------------------------------------ 裁剪
  function enterCrop() {
    var ids = checkedIds();
    if (ids.length !== 1) { setListStatus('勾选**一条**再点「裁剪」'); return; }
    var it = P.items.filter(function (x) { return x.id === ids[0]; })[0];
    if (!it) return;
    P.cropItem = it;
    P.duration = 0;
    P.trim = { a: 0, b: 0 };

    var url = it.media || '';
    $('#trimTitle').textContent = '裁剪：' + (it.titleStem || it.title);
    $('#trimEmpty').textContent = url ? '正在加载…' : '这条没有关联视频文件';
    P.trimP.load(url, { autoplay: false, emptyText: '这条没有关联视频文件' });
    syncTrimUI();
    setTrimStatus('');

    // 这条已经有片段数据（片段条目 / 待覆盖）→ 把手落回原来的区间
    var c = (it.clips && it.clips[0]) || null;
    var preset = (c && c.media === url) ? c : null;

    VKB.call('media_probe', url).then(function (r) {
      if (P.cropItem !== it) return;
      if (r && r.ok && r.duration) {
        P.duration = r.duration;
        P.trim = preset ? { a: preset.start, b: preset.end } : { a: 0, b: r.duration };
        syncTrimUI();
        if (preset) P.trimP.seekTo(preset.start);
      } else {
        P.trim = { a: 0, b: P.trimP.duration() || 0 };
        syncTrimUI();
      }
    }).catch(function () {});

    gotoPage('trim');
  }

  function bindTrimDrag() {
    var track = $('#trimTrack');
    ['#trimA', '#trimB'].forEach(function (sel, idx) {
      var el = $(sel);
      el.addEventListener('mousedown', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var move = function (ev) { setHandle(idx === 0 ? 'a' : 'b', fracFromX(ev.clientX)); };
        var up = function () {
          window.removeEventListener('mousemove', move);
          window.removeEventListener('mouseup', up);
        };
        window.addEventListener('mousemove', move);
        window.addEventListener('mouseup', up);
      });
    });
    track.addEventListener('mousedown', function (e) {
      if (e.target !== track && e.target !== $('#trimSel')) return;
      P.trimP.seekTo(fracFromX(e.clientX) * P.duration);
    });
  }

  function fracFromX(clientX) {
    var r = $('#trimTrack').getBoundingClientRect();
    return Math.max(0, Math.min(1, (clientX - r.left) / Math.max(1, r.width)));
  }

  function setHandle(which, frac) {
    if (!P.duration) return;
    var t = frac * P.duration;
    if (which === 'a') P.trim.a = Math.min(t, P.trim.b - 0.05);
    else P.trim.b = Math.max(t, P.trim.a + 0.05);
    P.trim.a = Math.max(0, P.trim.a);
    P.trim.b = Math.min(P.duration, P.trim.b);
    syncTrimUI();
    // 拖动把手时预览实时 seek 到对应帧
    P.trimP.seekTo(which === 'a' ? P.trim.a : P.trim.b);
  }

  function syncTrimUI() {
    var d = P.duration || 1;
    var a = (P.trim.a / d) * 100, b = (P.trim.b / d) * 100;
    $('#trimA').style.left = a + '%';
    $('#trimB').style.left = b + '%';
    $('#trimSel').style.left = a + '%';
    $('#trimSel').style.width = Math.max(0, b - a) + '%';
    $('#trimLabel').textContent = P.duration
      ? fmt(P.trim.a) + ' – ' + fmt(P.trim.b) + '  （' + (P.trim.b - P.trim.a).toFixed(1) + 's）'
      : '—';
    // 把手一动就把区间同步给播放器（loop=true）：点播放只在 A–B 内循环。
    // loop 只在**播放中**生效，暂停时用户仍可自由拖播放头挑位置。
    if (P.duration) P.trimP.setRange(P.trim.a, P.trim.b, true);
  }

  /** 裁剪的两个去处：为新片段 / 覆盖原视频。两条路都不动文件。 */
  function saveClip(overwrite) {
    if (!P.cropItem) { setTrimStatus('先选一条视频'); return Promise.resolve(null); }
    if (!P.duration) { setTrimStatus('视频还没加载好'); return Promise.resolve(null); }
    if (P.trim.b - P.trim.a < 0.05) { setTrimStatus('区间太短'); return Promise.resolve(null); }
    var id = P.cropItem.id;
    setTrimStatus(overwrite ? '正在裁剪并覆盖…' : '正在裁剪…');
    return VKB.call('save_clip', id, P.trim.a, P.trim.b, !!overwrite)
      .then(function (r) {
        if (!r || !r.ok) { setTrimStatus('保存失败'); return r; }
        // 真实链路：任务是后台跑的，立即返回，结果由轮询捎回来（applyEvent）
        if (r.queued) {
          setTrimStatus(overwrite
            ? '已提交，正在后台裁剪并覆盖（原文件会先备份）'
            : '已提交，正在后台裁剪…');
          return r;
        }
        if (r.state && window.VKBApp) window.VKBApp.applyState(r.state);
        setTrimStatus(overwrite
          ? '已覆盖原视频（备份在 data/backups/）'
          : '已保存为新片段，见左边列表');
        if (r.created) {
          P.cropItem = null;
          clearAutoBack();
          P._autoBack = setTimeout(function () {
            P._autoBack = null;
            if (P.page === 'trim') gotoPage('list');
          }, 700);
        }
        return r;
      }).catch(function (e) { setTrimStatus('失败：' + e.message); return null; });
  }

  function setTrimStatus(m) { $('#trimStatus').textContent = m; }

  // ------------------------------------------------------------------ 合并
  function enterMerge() {
    var ids = checkedIds();
    if (ids.length < 2) { setListStatus('至少勾选两条才能合并'); return; }
    var picked = P.items.filter(function (it) { return P.checked[it.id]; });
    setListStatus('正在读取时长…');

    // 每条贡献一段：有 clips 用 clips[0]，否则整条
    Promise.all(picked.map(function (it) {
      var c = (it.clips && it.clips[0]) || null;
      if (c && c.media === it.media) {
        return Promise.resolve({ media: it.media, title: it.titleStem, start: c.start, end: c.end });
      }
      return VKB.call('media_probe', it.media).then(function (r) {
        var d = (r && r.ok && r.duration) ? r.duration : 0;
        return { media: it.media, title: it.titleStem, start: 0, end: d };
      }).catch(function () { return { media: it.media, title: it.titleStem, start: 0, end: 0 }; });
    })).then(function (segs) {
      P.segs = segs;
      P._seqActive = false;
      renderMergeList();
      setMergeStatus('');
      setListStatus('');
      gotoPage('merge');
    });
  }

  function totalLen() {
    return P.segs.reduce(function (s, x) { return s + Math.max(0, x.end - x.start); }, 0);
  }

  function renderMergeList() {
    var host = $('#mergeList');
    host.innerHTML = '';
    $('#mergeCount').textContent = P.segs.length + ' 段 · ' + totalLen().toFixed(1) + 's';
    P.segs.forEach(function (s, i) {
      var li = document.createElement('li');
      li.className = 'mrow';
      li.dataset.i = i;

      var h = document.createElement('span');
      h.className = 'mh';
      h.textContent = '⠿';
      h.title = '按住上下拖动改顺序';

      var n = document.createElement('span');
      n.className = 'mn';
      n.textContent = (i + 1) + '.';

      var t = document.createElement('span');
      t.className = 'mt';
      t.textContent = s.title + '  ' + fmt(s.start) + ' – ' + fmt(s.end);

      var x = document.createElement('span');
      x.className = 'mx';
      x.textContent = '✕';
      x.title = '从合并里移除';
      x.addEventListener('click', function () {
        P.segs.splice(i, 1);
        renderMergeList();
      });

      li.appendChild(h); li.appendChild(n); li.appendChild(t); li.appendChild(x);
      host.appendChild(li);
    });
  }

  /** 拖动改顺序：按下 ⠿ 后，指针越过某一行中线就把它插到那一行之前。 */
  function bindMergeDrag() {
    var host = $('#mergeList');
    host.addEventListener('mousedown', function (e) {
      var handle = e.target.closest('.mh');
      if (!handle) return;
      e.preventDefault();
      var row = handle.closest('.mrow');
      var idx = parseInt(row.dataset.i, 10);
      row.classList.add('dragging');

      var move = function (ev) {
        var rows = Array.prototype.slice.call(host.querySelectorAll('.mrow'));
        var to = rows.length - 1;
        for (var i = 0; i < rows.length; i++) {
          var r = rows[i].getBoundingClientRect();
          if (ev.clientY < r.top + r.height / 2) { to = i; break; }
        }
        if (to !== idx) {
          var seg = P.segs.splice(idx, 1)[0];
          // 先把元素摘掉，后面的下标会整体前移一位 —— 落点在原位之后
          // 就得补回这一位，否则每次都会多挪一格（实测：往下拖一格会跑到最后）。
          var to2 = to > idx ? to - 1 : to;
          P.segs.splice(to2, 0, seg);
          idx = to2;
          renderMergeList();
          var nr = host.querySelectorAll('.mrow')[idx];
          if (nr) nr.classList.add('dragging');
        }
      };
      var up = function () {
        window.removeEventListener('mousemove', move);
        window.removeEventListener('mouseup', up);
        var d = host.querySelector('.mrow.dragging');
        if (d) d.classList.remove('dragging');
      };
      window.addEventListener('mousemove', move);
      window.addEventListener('mouseup', up);
    });
  }

  /** 顺序播放：一段播完自动切下一段。loop=false，跑到 b 就停并回调。 */
  function startSequence() {
    if (P.segs.length < 2) { setMergeStatus('至少两段才能预览'); return; }
    P._seqActive = true;
    P._seqIdx = 0;
    P.mergeP.setRangeEndHandler(function () { if (P._seqActive) nextSeg(); });
    nextSeg();
  }

  function nextSeg() {
    if (!P._seqActive) return;
    if (P._seqIdx >= P.segs.length) {
      P._seqActive = false;
      setMergeStatus('顺序预览结束');
      return;
    }
    var s = P.segs[P._seqIdx++];
    var v = $('#mergeVideo');
    var onMeta = function () {
      v.removeEventListener('loadedmetadata', onMeta);
      if (!P._seqActive) return;
      setMergeStatus('第 ' + P._seqIdx + ' / ' + P.segs.length + ' 段');
      P.mergeP.playRange(s.start, s.end);
    };
    v.addEventListener('loadedmetadata', onMeta);
    P.mergeP.load(s.media, { autoplay: false });
  }

  function exportMerge() {
    if (P.segs.length < 2) { setMergeStatus('至少两段才能导出'); return Promise.resolve(null); }
    setMergeStatus('正在导出…');
    var payload = P.segs.map(function (s) {
      return { media: s.media, start: s.start, end: s.end };
    });
    return VKB.call('make_merge', payload).then(function (r) {
      if (!r || !r.ok) { setMergeStatus('导出失败'); return r; }
      if (r.queued) {
        setMergeStatus('已提交，正在后台合并…（进度见左边列表那一行）');
        return r;
      }
      if (r.state && window.VKBApp) window.VKBApp.applyState(r.state);
      setMergeStatus('已导出为新条目');
      return r;
    }).catch(function (e) { setMergeStatus('失败：' + e.message); return null; });
  }

  function setMergeStatus(m) { $('#mergeStatus').textContent = m; }

  // ------------------------------------------------------------------ 进度
  /** 显式操作（点摄像头、提交转写、导入…）的消息。
   *
   *  必须**保护 3 秒**：进度轮询每 120ms 就会重写状态行，不保护的话
   *  用户刚点完按钮，消息立刻被「转写 58%」冲掉 —— 看起来就是"没反应"。
   *  进度条不受影响，照样在走。 */
  function setListStatus(m) {
    P._statusHold = Date.now() + 3000;
    $('#procStatus').textContent = m;
  }

  /** 进度文字：不设保护期，会被上面的显式消息压住 3 秒 */
  function progressStatus(m) {
    if (Date.now() < (P._statusHold || 0)) return;
    $('#procStatus').textContent = m;
  }

  /** 由 app.js 的轮询回调驱动：底部进度条 + 每行的进度文字 */
  function updateProgress(items) {
    if (!P.open_) return;
    items = items || [];
    var byId = {};
    items.forEach(function (x) { byId[x.id] = x; });

    var it = byId[P.transcribingId] || null;
    if (!it) {
      for (var i = 0; i < items.length; i++) {
        if (items[i].stage && items[i].stage !== 'idle') { it = items[i]; break; }
      }
    }
    // 导入（复制大文件）走自己的进度条，不和转写抢
    var imp = P.importStatus || {};
    var wrap = $('#importWrap');
    if (imp.active || imp.error) {
      wrap.classList.remove('hidden');
      var pctI = Math.round((imp.pct || 0) * 100);
      $('#importText').textContent = imp.error
        ? ('导入失败：' + imp.error)
        : ('复制中 ' + (imp.name || '') + '（' + (imp.done || 0) + '/'
           + (imp.total || 0) + '）' + pctI + '%');
      $('#importFill').style.width = (imp.error ? 100 : pctI) + '%';
    } else {
      wrap.classList.add('hidden');
    }
    if (P._impWasActive && !imp.active && !imp.error && imp.total) {
      setListStatus('已导入 ' + imp.total + ' 个视频');
    }
    P._impWasActive = !!imp.active;
    // 列表里的"正在导入…"占位行跟着走。
    // 只改那一行的文字，不整表重渲染 —— 否则每 120ms 重建一次列表，
    // 滚动位置和 hover 状态都会被抖掉。
    if (imp.active) {
      var ph = document.querySelector('#procList .proc-item.importing');
      var txt = '正在导入… ' + (imp.name || '') + '（' + (imp.done || 0)
        + '/' + (imp.total || 0) + '）';
      if (ph) { if (ph.textContent !== txt) ph.textContent = txt; }
      else renderList();
    } else {
      // 导入结束：占位行要立刻撤掉。等下一轮 renderList 也行，
      // 但那样会残留最多一个轮询周期，看着像卡住了。
      var stale = document.querySelector('#procList .proc-item.importing');
      if (stale) stale.parentNode.removeChild(stale);
    }

    var bar = 0;
    if (it) {
      bar = it.stage === 'transcribing' ? (it.transcribePct || 0)
        : it.stage === 'cleaning' ? (it.cleanPct || 0)
          : it.stage === 'working' ? (it.transcribePct || 0)
            : it.stage === 'done' ? 100 : 0;
      progressStatus((it.titleStem || it.title) + '：' + stageDetail(it));
    } else if (imp.error) {
      progressStatus('导入失败：' + imp.error);
    }
    $('#procBar').style.width = bar + '%';

    // 每行的进度文字 + 失败原因挂到 hover 上
    Array.prototype.forEach.call($('#procList').querySelectorAll('.proc-item'), function (el) {
      var x = byId[el.dataset.id];
      if (!x) return;
      var btn = el.querySelector('.tr');
      if (btn) btn.textContent = stageText(x);
      el.title = x.error || x.warning || (x.title || '');
    });
  }

  /** 由 app.js 的轮询回调灌进来 */
  function setImportStatus(imp) { P.importStatus = imp || {}; }

  /** 后台任务（裁剪/合并）完成的事件。轮询捎回来的，靠 seq 判新旧。
   *
   *  为什么要这一条：这两个是后台任务，前端拿不到完成回调。没有它的话
   *  用户点了「导出」之后，除了列表里多一行，得不到任何"做完了"的反馈。 */
  function applyEvent(ev) {
    if (!ev || !ev.text) return;
    if (ev.seq === P._lastEventSeq) return;
    P._lastEventSeq = ev.seq;
    setListStatus(ev.text);
    if (window.VKBApp && window.VKBApp.toast) window.VKBApp.toast(ev.text);
    // 裁剪/合并页自己也有状态行，一并刷一下
    if (P.page === 'trim') setTrimStatus(ev.text);
    if (P.page === 'merge') setMergeStatus(ev.text);
    // 摄像头录完导入的条目要挨个弹命名框
    if (window.VKBCamera) window.VKBCamera.applyEvent(ev);
  }

  /** 系统相机监视/导入的状态（app.js 轮询灌进来） */
  function setCameraStatus(cam) {
    P.cameraStatus = cam || {};
    if (window.VKBCamera) window.VKBCamera.applyStatus(cam);
  }

  /** 摄像头那边要往状态行写话。走 setListStatus（自带 3 秒保护期），
      否则刚写完就被 120ms 的进度轮询冲掉 —— 那个坑踩过一次了。 */
  function status(m) { setListStatus(m); }

  /** 监视目录收进状态行的 tooltip：不占地方，但排查时要能看见 */
  function setCameraDirs(dirs) {
    var el = $('#procStatus');
    if (el) {
      el.title = (dirs && dirs.length) ? ('监视目录：\n' + dirs.join('\n')) : '';
    }
  }

  // ------------------------------------------------------------------ 调试
  function state() {
    return {
      open: P.open_,
      page: P.page,
      items: P.items.length,
      itemIds: P.items.map(function (x) { return x.id; }),   // 服务端给的顺序
      checked: checkedIds(),
      actions: {
        cropDisabled: $('#btnCropMode').disabled,
        mergeDisabled: $('#btnMergeMode').disabled,
        transcribeDisabled: $('#btnTranscribeSel').disabled,
        transcribeLabel: $('#btnTranscribeSel').textContent,
      },
      selectAll: $('#chkAll') ? $('#chkAll').checked : null,
      selectAllIndeterminate: $('#chkAll') ? $('#chkAll').indeterminate : null,
      camera: P.cameraStatus,
      importActive: !!(P.importStatus && P.importStatus.active),
      importText: $('#importText') ? $('#importText').textContent : '',
      importBarHidden: $('#importWrap') ? $('#importWrap').classList.contains('hidden') : null,
      previewId: P.preview ? P.preview.id : null,
      previewTitle: P.preview ? P.preview.title : null,
      previewUrl: P.listP ? P.listP.state().url : null,
      cropId: P.cropItem ? P.cropItem.id : null,
      cropTitle: $('#trimTitle').textContent,
      trim: { a: P.trim.a, b: P.trim.b },
      duration: P.duration,
      segs: P.segs.map(function (s) {
        return { media: s.media, title: s.title, start: s.start, end: s.end };
      }),
      seqActive: P._seqActive,
      seqIdx: P._seqIdx,
      listStatus: $('#procStatus').textContent,
      trimStatus: $('#trimStatus').textContent,
      mergeStatus: $('#mergeStatus').textContent,
      barWidth: $('#procBar').style.width,
      listPlayer: P.listP ? P.listP.state() : null,
      trimPlayer: P.trimP ? P.trimP.state() : null,
      mergePlayer: P.mergeP ? P.mergeP.state() : null,
      overlayPointerEvents: getComputedStyle($('#procOverlay')).pointerEvents,
      panelPointerEvents: getComputedStyle($('#procPanel')).pointerEvents,
      listTags: Array.prototype.map.call(
        $('#procList').querySelectorAll('.pill'), function (e) { return e.textContent; }),
      mergeRows: Array.prototype.map.call(
        $('#mergeList').querySelectorAll('.mrow .mt'), function (e) { return e.textContent; }),
    };
  }

  window.VKBProcess = {
    init: init, open: open, close: close, isOpen: isOpen,
    setItems: setItems, updateProgress: updateProgress,
    gotoPage: gotoPage, state: state, setImportStatus: setImportStatus,
    applyEvent: applyEvent, setCameraStatus: setCameraStatus,
    status: status, setCameraDirs: setCameraDirs,
    // 测试钩子
    _preview: previewItem,
    _enterCrop: enterCrop,
    _enterMerge: enterMerge,
    _trim: function (a, b) { P.trim = { a: a, b: b }; syncTrimUI(); },
    _saveClip: saveClip,
    _startSequence: startSequence,
    _exportMerge: exportMerge,
    _transcribe: transcribe,
    _dequeueRow: dequeueRow,
    _import: doImport,
    _setChecked: function (ids) {
      P.checked = {};
      (ids || []).forEach(function (i) { P.checked[i] = true; });
      renderList();
      updateActions();
    },
    _moveSeg: function (from, to) {
      var s = P.segs.splice(from, 1)[0];
      P.segs.splice(to, 0, s);
      renderMergeList();
    },
  };
})();
