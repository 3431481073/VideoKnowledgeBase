/* 界面编排：状态拉取、三格联动、播放器、两种新建节点、处理小窗口接线。 */
(function () {
  'use strict';

  var $ = function (s) { return document.querySelector(s); };
  var $$ = function (s) { return Array.prototype.slice.call(document.querySelectorAll(s)); };
  var G = window.VKBGraph;

  var App = {
    state: null,
    tab: 'all',
    selectedNodeId: null,
    articleItemId: null,     // 左下正在看的条目（点右下条目时设）
    player: null,
    _pending: [],            // 待处理条目（给处理小窗口）
    _pollTimer: null,
    _toastTimer: null,
  };

  // ==================================================================== 启动
  var _booted = false, _bootFailed = false;

  async function boot() {
    if (_booted) return;
    _booted = true;
    setTimeout(function () { if (!_bootFailed) hideBoot(); }, 8000);

    try {
      var ok = await VKB.init();
      if (!ok) {
        _bootFailed = true;
        showBoot('无法连接到 Python 后端（请通过 启动视频知识库.bat 启动，不要直接打开本文件）');
        return;
      }
      G.mount($('#graphViewport'), $('#graphCanvas'), $('#edges'), $('#nodes'));
      App.player = window.VKBPlayer.make({
        video: $('#playerVideo'),
        playBtn: $('#btnPlay'),
        seek: $('#seek'),
        timeLabel: $('#timeLabel'),
        vol: $('#vol'),
        muteBtn: $('#btnMute'),
        muteToggles: false,          // 点音量图标 = 展开/收起竖滑块，不是静音开关
        rotateBtn: $('#btnRotate'),
        stage: $('#playerStage'),
        empty: $('#playerEmpty'),
        emptyText: '点右下卡片，或左上导图里的视频',
      });
      window.VKBProcess.init();
      if (window.VKBCamera) window.VKBCamera.init();

      wireGraphCallbacks();
      wireDividers();
      wireToolbar();
      wireSettings();
      wireDialogs();

      App.state = await VKB.call('get_state');
      applyState(App.state);
      checkMedia();
      hideBoot();
      startPolling();
    } catch (err) {
      _bootFailed = true;
      showBoot('界面初始化失败：' + ((err && err.message) || err));
      console.error('[boot]', err);
    }
  }

  function showBoot(msg) { var b = $('#boot'); b.classList.remove('hidden'); b.textContent = msg; }
  function hideBoot() { $('#boot').classList.add('hidden'); }

  function checkMedia() {
    VKB.call('list_media').then(function (r) {
      if (r && !r.ok && r.error) revealMediaError(r.error);
    }).catch(function () {});
  }
  function revealMediaError(msg) {
    var el = $('#mediaError');
    el.textContent = '视频无法播放：' + msg;
    el.classList.remove('hidden');
  }

  // ==================================================================== 状态
  function applyState(s) {
    App.state = s;
    // 【多根】s.tree 是**隐形根**（界面上不画它），画的是它的 children ——
    // 那才是用户看到的顶层节点，可以有多个（"多根"）
    G.render((s.tree && s.tree.children) || []);
    G.setSelected(App.selectedNodeId);
    renderDone();
    App._pending = (s.pending || []).map(function (x) {
      return { id: x.id, title: x.title, titleStem: x.titleStem,
               media: x.media, clips: x.clips, stage: x.stage,
               origin: x.origin, overwrite: x.overwrite };
    });
    window.VKBProcess.setItems(App._pending);
    renderSettings(s.settings);
  }

  // ------------------------------------------------------------- 左上：导图
  function wireGraphCallbacks() {
    G.onSelect = function (id) {
      App.selectedNodeId = id;
      G.setSelected(id);
      renderArticle(id);
      loadPlayerFor(id);
    };
    G.onReparent = async function (id, targetId) {
      var r = await VKB.call('reparent_node', id, targetId);
      applyState(r.state);
      toast(r.ok ? '已改变层级' : '不能移到自己的子节点下');
    };
    G.onToggle = async function (id) {
      var r = await VKB.call('toggle_collapse', id);
      applyState(r.state);
    };
    // 双击空白 = 直接新建分组（最常做的那个动作），不再弹"类型"二选一
    // 双击空白 = **添加**（分组 / 视频 二选一），加到当前选中的节点下；
    // 没选中任何节点就加到顶层（成为一棵新树）
    G.onBlankDblClick = function (selectedId) { addUnder(selectedId || null); };
    G.onContext = function (id, x, y) { showContext(id, x, y); };
  }

  function findNode(id, n) {
    n = n || (App.state && App.state.tree);
    if (!n) return null;
    if (n.id === id) return n;
    for (var i = 0; i < n.children.length; i++) {
      var f = findNode(id, n.children[i]);
      if (f) return f;
    }
    return null;
  }

  /** 按条目 id 找它挂在树上的那个节点；没挂就返回 null。 */
  function findNodeByItem(iid, n) {
    n = n || (App.state && App.state.tree);
    if (!n) return null;
    if (n.itemId === iid) return n;
    for (var i = 0; i < n.children.length; i++) {
      var f = findNodeByItem(iid, n.children[i]);
      if (f) return f;
    }
    return null;
  }

  // ------------------------------------------------------------- 右上：播放器
  /**
   * loadPlayerFor(nodeId, fallbackMedia)
   *
   * `fallbackMedia` 是"这条条目**没有挂在树上**"时的兜底视频。
   * 【为什么需要】右下卡片里的条目不一定挂到导图上，但点它照样该能播。
   * 以前只认导图节点，于是出现"点右下卡片右上不出视频"——
   * 只有点左上导图那条路（它传了 nodeId）才播得出来。
   */
  function loadPlayerFor(nodeId, fallbackMedia) {
    var n = nodeId ? findNode(nodeId) : null;
    if (n && n.kind === 'video' && n.media) {
      // 规格：点视频**默认暂停**，停在第一帧，不自动播
      App.player.load(n.media, { autoplay: false });
      return;
    }
    if (fallbackMedia) {
      App.player.load(fallbackMedia, { autoplay: false });
      return;
    }
    App.player.clear('');
  }

  // ------------------------------------------------------------- 左下：文章
  function renderArticle(nodeId) {
    var host = $('#article');
    host.innerHTML = '';
    var node = findNode(nodeId);
    if (!node) {
      host.innerHTML = '<div class="pick-empty">点击左上导图里的节点，这里显示对应的文章。</div>';
      return;
    }
    addBlocks(host, node, 0);
    host.scrollTop = 0;
  }

  /** 点右下条目 -> 左下显示该条目的清洗稿全文（规格 1）。 */
  async function renderArticleForItem(iid) {
    var host = $('#article');
    host.innerHTML = '<div class="pick-empty">正在读取…</div>';
    var r = await VKB.call('item_text', iid);
    host.innerHTML = '';
    if (!r || !r.ok) {
      host.innerHTML = '<div class="pick-empty">读不到这条的内容</div>';
      return;
    }
    var wrap = document.createElement('div');
    wrap.className = 'blk lv0';
    var h = document.createElement('div');
    h.className = 'h ro';
    h.textContent = r.title;
    var meta = document.createElement('div');
    meta.className = 'ro-meta';
    meta.textContent = r.aiProcessed ? '清洗稿'
      : (r.transcribed ? '原始转写（还没清洗）' : '这条还没有转写内容');
    var body = document.createElement('div');
    body.className = 'body ro';
    body.textContent = r.text || '（无内容）';
    wrap.appendChild(h);
    wrap.appendChild(meta);
    wrap.appendChild(body);
    host.appendChild(wrap);
    host.scrollTop = 0;
  }

  function autoGrow(el) {
    var fit = function () {
      el.style.height = 'auto';
      el.style.height = (el.scrollHeight + 2) + 'px';
    };
    el.addEventListener('input', fit);
    setTimeout(fit, 0);
    return fit;
  }

  function addBlocks(host, node, depth) {
    var lv = Math.min(depth, 4);
    var wrap = document.createElement('div');
    wrap.className = 'blk lv' + lv;

    var h = document.createElement('textarea');
    h.className = 'h';
    h.rows = 1;
    h.spellcheck = false;
    h.value = node.name;
    h.title = '直接改标题，失焦或回车保存（导图上同步变）';
    var fitH = autoGrow(h);
    var hTimer = null;
    h.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); h.blur(); }
    });
    async function saveTitle() {
      var v = h.value.trim();
      if (!v) { h.value = node.name; fitH(); return; }
      if (v === node.name) { fitH(); return; }
      var r = await VKB.call('rename_node', node.id, v);
      if (r.ok) {
        App.state = r.state;
        G.render((r.state.tree && r.state.tree.children) || []);
        G.setSelected(App.selectedNodeId);
        renderDone();
        if (node.itemId) syncItemTitleAfterNodeRename(node, v);
      } else { h.value = node.name; }
      fitH();
    }
    // 边打字边存（500ms 防抖），别等失焦
    h.addEventListener('input', function () {
      clearTimeout(hTimer);
      hTimer = setTimeout(saveTitle, 500);
    });
    h.addEventListener('blur', function () { clearTimeout(hTimer); saveTitle(); });
    wrap.appendChild(h);

    // 主题节点也要有正文框 —— 之前只有 video 节点才建 .body，
    // 于是点根节点只能看到一个标题，用户没地方写字。
    var b = document.createElement('textarea');
    b.className = 'body';
    b.rows = 1;
    b.spellcheck = false;
    b.value = node.body || '';
    b.placeholder = node.kind === 'video' ? '（无正文）' : '（在这里写这个主题的内容）';
    autoGrow(b);
    var bTimer = null;
    function saveBody() {
      node.body = b.value;
      VKB.call('set_body', node.id, b.value).catch(function () { });
    }
    b.addEventListener('input', function () {
      clearTimeout(bTimer);
      bTimer = setTimeout(saveBody, 500);
    });
    b.addEventListener('blur', function () { clearTimeout(bTimer); saveBody(); });
    wrap.appendChild(b);

    host.appendChild(wrap);
    node.children.forEach(function (c) { addBlocks(host, c, depth + 1); });
  }

  // 改的是内容节点的标题 -> 右下条目名也要跟着变（三格联动）
  function syncItemTitleAfterNodeRename(node, newName) {
    var it = App.state.done.filter(function (x) { return x.id === node.itemId; })[0]
          || App._pending.filter(function (x) { return x.id === node.itemId; })[0];
    if (!it) return;
    if (it.titleStem === newName) return;
    var ext = (it.title.match(/\.[a-z0-9]+$/i) || [''])[0];
    VKB.call('rename_item', node.itemId, newName + ext).then(function (r) {
      if (r && r.state) applyState(r.state);
    }).catch(function () {});
  }

  // ------------------------------------------------------------- 右下：已完成
  function renderDone() {
    var host = $('#doneList');
    if (!App.state) return;
    var items = App.state.done;
    if (App.tab === 'in') items = items.filter(function (i) { return i.inTree; });
    else if (App.tab === 'out') items = items.filter(function (i) { return !i.inTree; });

    host.innerHTML = '';
    if (!items.length) { host.innerHTML = '<div class="pick-empty">没有条目</div>'; return; }
    items.forEach(function (it) {
      var d = document.createElement('div');
      d.className = 'row-item';
      d.dataset.id = it.id;
      d.title = '双击改名';
      d.innerHTML = '<div class="t"></div><div class="m"></div><div class="s"></div>';
      d.children[0].textContent = it.title;
      // 保持三行结构不变：提醒并进第二行，完整原因挂 title
      d.children[1].textContent = it.created
        + (it.inTree ? '   · 已添加到树' : '')
        + (it.warning ? '   · ⚠ 清洗稿可能不完整' : '');
      d.children[2].textContent = it.summary;
      var tip = [it.title];
      if (it.warning) tip.push(it.warning);
      if (it.error) tip.push(it.error);
      tip.push('双击改名');
      d.title = tip.join('\n');
      if (App.articleItemId === it.id) d.classList.add('sel');
      // 单击 = 左下显示这条的清洗稿全文（规格 1）＋ 左上/右上跟着走（四格联动）
      d.addEventListener('click', function () {
        App.articleItemId = it.id;
        $$('#doneList .row-item').forEach(function (x) {
          x.classList.toggle('sel', x.dataset.id === it.id);
        });
        renderArticleForItem(it.id);
        // 【四格联动】以前这里**只更新了左下**，于是"点卡片右上不出视频"；
        // 而点左上导图能播 —— 因为那条路调了 loadPlayerFor，这条没调。
        var n = findNodeByItem(it.id);
        App.selectedNodeId = n ? n.id : null;
        G.setSelected(App.selectedNodeId);
        // 挂了树就用那个节点；没挂树就用条目自己的视频 —— 两条路都得能播
        loadPlayerFor(App.selectedNodeId, it.media);
      });
      d.addEventListener('dblclick', function () { renameItem(it); });
      // 右键 = 删除（左上/左下/右上/右下 四处一起清）
      d.addEventListener('contextmenu', function (ev) {
        ev.preventDefault();
        openMenu([{ label: '删除', run: function () { deleteItem(it); } }],
                 ev.clientX, ev.clientY);
      });
      host.appendChild(d);
    });
  }

  async function renameItem(it) {
    var name = await askText('重命名条目', '视频文件名', it.title);
    if (name === null || name === it.title) return;
    var r = await VKB.call('rename_item', it.id, name);
    if (r && r.state) {
      applyState(r.state);
      var nid = App.selectedNodeId;
      if (nid) renderArticle(nid);
      loadPlayerFor(nid);
      toast('条目已改名');
    }
  }

  /**
   * 删除条目：条目记录 + 导图上的节点 + 转写/清洗产物（**归档**进 _stale/）
   * —— **视频文件保留在 data/media，不删**。
   *
   * 四处同步清空：左上导图节点（后端一并摘掉，applyState 重绘）、
   * 左下文章、右上播放器、右下卡片（applyState 重绘）。
   */
  async function deleteItem(it) {
    var ok = await askConfirm('删除条目',
      '确定删除「' + it.title + '」？\n' +
      '· 条目记录和它在导图上的节点会被删掉\n' +
      '· 转写稿 / 清洗稿归档到 data/_stale/（可回溯）\n' +
      '· 视频文件会保留在 data/media，不会被删',
      '删除');
    if (!ok) return;
    try {
      var r = await VKB.call('delete_item', it.id);
      if (!r || !r.ok) {
        if (r && r.state) applyState(r.state);
        toast((r && r.error) || '删除失败', true);
        return;
      }
      applyState(r.state);
      // 被删的条目如果正占着树上的选中态，选中态要复位
      //（复位成 **null**，不是"选那个根" —— 现在根是隐形的，选它没有意义）
      if (!findNode(App.selectedNodeId)) App.selectedNodeId = null;
      App.articleItemId = null;
      G.setSelected(App.selectedNodeId);
      renderArticle(App.selectedNodeId);
      loadPlayerFor(App.selectedNodeId);
      toast('已删除（视频文件保留在 data/media）');
    } catch (e) {
      toast('操作失败：' + ((e && e.message) ? e.message : e), true);
    }
  }

  // ------------------------------------------------------------- 新建
  /**
   * 双击空白 -> 问一句"加什么"，再加到 parentId 下面（null = 顶层）。
   *
   * 为什么是"问一句"而不是直接建分组：双击是最顺手的添加手势，但**加分组和
   * 加视频都是常做的事** —— 只让双击建分组，加视频就得去右键菜单，绕。
   */
  async function addUnder(parentId) {
    var kind = await askAddKind(parentId);
    if (!kind) return;
    if (kind === 'group') { await newGroup(parentId); }
    else { await addVideoUnder(parentId); }
  }

  /**
   * 问"加分组还是加视频"。
   *
   * 【和以前那个"节点类型二选一"的区别 —— 别退回去】以前是两个长得一模一样
   * 的方块（文字节点 / 内容节点），区别只在灰色小字里、用的还是数据模型的词
   * （kind=topic / video），用户看不出为什么要选 —— 那正是它被删掉的原因。
   * 现在每一行是一个**动词**（新建分组 / 加入视频），带图标和一句白话说明，
   * 标题里还写清"加到哪儿"。
   */
  function askAddKind(parentId) {
    return new Promise(function (resolve) {
      var dlg = $('#dlgAdd');
      var where = findNode(parentId);
      $('#dlgAddWhere').textContent = where
        ? ('加到「' + where.name + '」下面')
        : '加到顶层（成为一棵新的树）';
      var done = false;
      function fin(v) {
        if (done) return; done = true;
        dlg.close();
        $('#dlgAddGroup').removeEventListener('click', onG);
        $('#dlgAddVideo').removeEventListener('click', onV);
        $('#dlgAddCancel').removeEventListener('click', onX);
        resolve(v);
      }
      function onG() { fin('group'); }
      function onV() { fin('video'); }
      function onX() { fin(null); }
      $('#dlgAddGroup').addEventListener('click', onG);
      $('#dlgAddVideo').addEventListener('click', onV);
      $('#dlgAddCancel').addEventListener('click', onX);
      dlg.showModal();
    });
  }

  /**
   * 新建「分组」—— 树上那个纯文字主题节点。
   *
   * 【为什么没有"节点类型"这个选择】原来新建要先弹一个「文字节点 / 内容节点」
   * 二选一：两个按钮长得一模一样、区别只在灰色小字里，用的还是数据模型的词
   * （`kind='topic'` / `'video'`）。用户看到的是"看不出为什么会是这样"。
   * 现在把选择变成两个**名字自解释的动作**（右键菜单里的「新建分组」/
   * 「加入视频…」），点哪个干哪个 —— 界面上不再出现"节点类型"这个概念。
   */
  async function newGroup(parentId) {
    var name = await askText('新建分组', '分组名称');
    if (name === null) return;
    try {
      var r = await VKB.call('add_text_node', parentId, name);
      applyState(r.state);
      if (r.ok) { toast('已新建分组'); }
      else { toast(r.error || '新建分组失败', true); }
    } catch (e) {
      toast('操作失败：' + ((e && e.message) ? e.message : e), true);
    }
  }

  /** 把一条已完成条目作为**视频**挂到导图上。 */
  async function addVideoUnder(parentId) {
    var iid = await askPickItem();
    if (!iid) return;
    try {
      var r = await VKB.call('add_content_node', parentId, iid);
      applyState(r.state);
      // 失败时显示后端给的**真实原因**（条目不存在 / 已在导图里 / 写盘失败）
      if (r.ok) { toast('已加入导图（名字已去掉扩展名）'); }
      else { toast(r.error || '加入失败', true); }
    } catch (e) {
      toast('操作失败：' + ((e && e.message) ? e.message : e), true);
    }
  }

  function askPickItem() {
    return new Promise(function (resolve) {
      var dlg = $('#dlgPick');
      var list = $('#dlgPickList');
      var search = $('#dlgPickSearch');
      search.value = '';
      var done = false;

      // 规格：内容节点从**右下「未添加」列表**里选 —— 也就是已完成里
      // inTree 为 false 的那些，不是待处理区的条目。
      function candidates() {
        var q = search.value.trim().toLowerCase();
        return App.state.done.filter(function (it) {
          if (it.inTree) return false;
          return !q || it.title.toLowerCase().indexOf(q) >= 0;
        });
      }
      function render() {
        list.innerHTML = '';
        var cs = candidates();
        if (!cs.length) { list.innerHTML = '<div class="pick-empty">没有匹配的条目</div>'; return; }
        cs.forEach(function (it) {
          var d = document.createElement('div');
          d.className = 'pick-item';
          d.textContent = it.titleStem || it.title;   // 进树后的名字（已去扩展名）
          d.dataset.id = it.id;
          d.addEventListener('click', function () { fin(it.id); });
          list.appendChild(d);
        });
      }
      function fin(v) {
        if (done) return; done = true;
        dlg.close();
        search.removeEventListener('input', render);
        $('#dlgPickCancel').removeEventListener('click', onX);
        resolve(v);
      }
      function onX() { fin(null); }
      search.addEventListener('input', render);
      $('#dlgPickCancel').addEventListener('click', onX);
      render();
      dlg.showModal();
      search.focus();
    });
  }

  // ------------------------------------------------------------- 右键菜单
  /**
   * openMenu(items, x, y) —— items 每项 {label, run, disabled}。
   *
   * 导图节点和右下卡片**共用同一个 #ctxMenu 元素**，只是菜单项不同。
   * 不新造一个菜单：少一套样式、少一处 z-index 要维护。
   */
  function openMenu(items, x, y) {
    var menu = $('#ctxMenu');
    menu.innerHTML = '';
    items.forEach(function (it) {
      var li = document.createElement('li');
      li.textContent = it.label;
      if (it.disabled) li.classList.add('disabled');
      else li.addEventListener('click', function () {
        menu.classList.add('hidden');
        it.run();
      });
      menu.appendChild(li);
    });
    menu.style.left = Math.min(x, window.innerWidth - 170) + 'px';
    menu.style.top = Math.min(y, window.innerHeight - 130) + 'px';
    menu.classList.remove('hidden');
  }

  function showContext(id, x, y) {
    var node = findNode(id);
    if (!node) return;
    // 【术语换了】「新建分组 / 加入视频」取代「文字节点 / 内容节点」：
    // 用户脑子里想的是"我要干什么"，不是"我要建数据模型里的哪种节点"。
    // 点哪个干哪个，不再先弹一道"你要哪种类型"。
    openMenu([
      { label: '新建分组', run: function () { newGroup(id); } },
      { label: '加入视频…', run: function () { addVideoUnder(id); } },
      { label: '重命名', run: function () { renameNode(id); } },
      // 【多根】现在**任何节点**都能脱离 / 删除 —— 已经没有"唯一的根"这回事了
      //（顶层可以有多个，"脱离"就是把节点提到顶层去跟别人并列）。
      { label: '脱离父节点', run: function () { detachNode(id); } },
      { label: '删除', run: function () { deleteNode(id); } },
    ], x, y);
    G.setSelected(id);
    App.selectedNodeId = id;
    renderArticle(id);
    loadPlayerFor(id);
  }

  async function renameNode(id) {
    var node = findNode(id);
    if (!node) return;
    var name = await askText('重命名', '新名称', node.name);
    if (name === null) return;
    var r = await VKB.call('rename_node', id, name);
    applyState(r.state);
    renderArticle(id);
    if (node.itemId) syncItemTitleAfterNodeRename(node, name);
    toast('已重命名');
  }

  async function deleteNode(id) {
    var node = findNode(id);
    if (!node) return;
    var ok = await askConfirm('删除节点',
      '确定删除「' + node.name + '」及其全部子节点吗？\n\n' +
      '只从导图里移除，条目还在右下角。');
    if (!ok) return;
    var r = await VKB.call('delete_node', id);
    applyState(r.state);
    App.selectedNodeId = null;      // 根是隐形的，删完不选任何节点
    G.setSelected(App.selectedNodeId);
    renderArticle(App.selectedNodeId);
    loadPlayerFor(App.selectedNodeId);
    toast('已删除（条目回到右下角）');
  }

  /**
   * 脱离父节点：把它从当前父节点摘出来挂到**根节点**下，成为顶层节点。
   * **子节点跟着一起走**（移动的是整棵子树）。
   *
   * **只有根节点不能脱离**；已经是根的直接子节点时，这次操作是 no-op ——
   * 允许、不报错、**也不弹提示**（弹「已脱离…成为顶层节点」是假话，它本来就是）。
   *
   * 不做确认框：这个操作**不删任何东西**、移动完还能拖回去，代价很低；
   * 加一道确认反而拖慢常用的整理动作。
   */
  async function detachNode(id) {
    var node = findNode(id);
    if (!node) return;
    try {
      var r = await VKB.call('detach_node', id);
      applyState(r.state);
      if (!r.ok) { toast(r.error || '脱离失败', true); return; }
      // 节点还在（只是换了位置），选中态照旧跟着它
      App.selectedNodeId = id;
      G.setSelected(id);
      renderArticle(id);
      loadPlayerFor(id);
      // 后端用 moved 告诉我们这次**到底动没动**：没动就静默
      //（界面也确实一动不动，这才是事实）
      if (r.moved) toast('已脱离父节点，成为顶层节点');
    } catch (e) {
      toast('操作失败：' + ((e && e.message) ? e.message : e), true);
    }
  }

  // ------------------------------------------------------------- 轮询
  function startPolling() {
    if (App._pollTimer) clearInterval(App._pollTimer);
    App._pollTimer = setInterval(async function () {
      try {
        var p = await VKB.call('poll');
        if (!p) return;

        // 🔴 【这一句以前是 `if (!p.changed) return;` —— 那是个大坑】
        //
        // 后端 poll() 是**无条件**把 light()（导入进度 / 列表 / 摄像头 / 事件）
        // 拼进返回值里的 —— 数据每一轮都是新的，是前端自己整包扔掉了。
        // 后果：只要 changed 有一次算错（导入完成得比两次轮询还快、
        // 文件对话框把 UI 线程堵住导致轮询积压后一起回来……），界面就**冻住**，
        // 直到下一次别的事件把 changed 顶起来 —— 用户看到的就是
        // "导入一个不显示，再导一个一下出来两条"（积压的东西一起冒出来）。
        //
        // 现在：**轻的东西每轮都灌**（幂等、便宜）；`changed` 只用来决定
        // 要不要做重活（整表重渲染）。这样界面不可能再"漏掉一次更新"。
        if (p.changed) {
          App.state.done = p.done;
          App.state.pending = p.pending;
          App._pending = p.pending.map(function (x) {
            return { id: x.id, title: x.title, titleStem: x.titleStem,
                     media: x.media, clips: x.clips, stage: x.stage,
                     note: x.note, origin: x.origin, overwrite: x.overwrite,
                     error: x.error, warning: x.warning };
          });
          renderDone();
          window.VKBProcess.setItems(App._pending);
        }
        window.VKBProcess.setImportStatus(p.import);
        window.VKBProcess.setCameraStatus(p.camera);
        window.VKBProcess.applyEvent(p.event);
        window.VKBProcess.updateProgress(p.pending);
      } catch (e) { /* 窗口关闭时忽略 */ }
    }, 120);
  }

  // ------------------------------------------------------------- 分隔条
  function wireDividers() {
    var grid = $('#grid');
    function bind(el, horizontal) {
      el.addEventListener('mousedown', function (e) {
        if (e.button !== 0) return;
        e.preventDefault();
        el.classList.add('active');
        var rect = grid.getBoundingClientRect();
        function move(ev) {
          var r, key1, key2;
          if (horizontal) {
            r = clamp((ev.clientY - rect.top) / (rect.height - 6), .12, .88);
            key1 = '--rowT'; key2 = '--rowB';
          } else {
            r = clamp((ev.clientX - rect.left) / (rect.width - 6), .12, .88);
            key1 = '--colL'; key2 = '--colR';
          }
          grid.style.setProperty(key1, (r * 10).toFixed(4) + 'fr');
          grid.style.setProperty(key2, ((1 - r) * 10).toFixed(4) + 'fr');
        }
        function up() {
          el.classList.remove('active');
          window.removeEventListener('mousemove', move);
          window.removeEventListener('mouseup', up);
        }
        window.addEventListener('mousemove', move);
        window.addEventListener('mouseup', up);
      });
    }
    bind($('#divV'), false);
    bind($('#divHL'), true);
    bind($('#divHR'), true);
  }

  // ------------------------------------------------------------- 工具栏
  function wireToolbar() {
    $('#btnProcess').addEventListener('click', function () { window.VKBProcess.open(); });

    wireVolumePopups();

    $('#btnGear').addEventListener('click', function () {
      $('#pageDone').classList.add('hidden');
      $('#pageSettings').classList.remove('hidden');
    });
    $('#btnSetBack').addEventListener('click', showDonePage);

    var tabs = $('#doneTabs');
    tabs.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      tabs.querySelectorAll('button').forEach(function (x) { x.classList.toggle('active', x === b); });
      App.tab = b.dataset.tab;
      renderDone();
    });
  }

  function showDonePage() {
    $('#pageSettings').classList.add('hidden');
    $('#pageDone').classList.remove('hidden');
  }

  /** 音量图标常驻，点它展开/收起它自己的竖向滑块。
   *  主播放器 + 处理浮层三个预览一共 4 组，所以是遍历而不是写死 id。 */
  function wireVolumePopups() {
    var wraps = document.querySelectorAll('.vol-wrap');
    Array.prototype.forEach.call(wraps, function (wrap) {
      var btn = wrap.querySelector('button');
      var pop = wrap.querySelector('.vol-pop');
      if (!btn || !pop) return;
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        pop.classList.toggle('hidden');
      });
    });
    document.addEventListener('click', function (e) {
      Array.prototype.forEach.call(document.querySelectorAll('.vol-pop'), function (pop) {
        var wrap = pop.closest('.vol-wrap');
        if (!wrap || !wrap.contains(e.target)) pop.classList.add('hidden');
      });
    });
  }

  // ------------------------------------------------------------- 设置
  function renderSettings(s) {
    $('#setUrl').value = s.clean_url || '';
    $('#setModel').value = s.clean_model || '';
    $('#setKey').value = s.clean_api_key || '';
    $('#setPrompt').value = s.clean_prompt || '';
  }

  function wireSettings() {
    $('#btnSetSave').addEventListener('click', async function () {
      var values = {
        clean_url: $('#setUrl').value,
        clean_model: $('#setModel').value,
        clean_api_key: $('#setKey').value,
        clean_prompt: $('#setPrompt').value,
      };
      var r = await VKB.call('save_settings', values);
      App.state.settings = r.settings;
      showDonePage();
      // 真实链路是落盘的（data/config.json）；假链路只写内存
      toast((App.state && App.state.fake)
        ? '设置已保存（假数据模式：仅内存）' : '设置已保存到 data/config.json');
    });
    $('#btnSetReset').addEventListener('click', async function () {
      var r = await VKB.call('reset_settings');
      App.state.settings = r.settings;
      renderSettings(r.settings);
      toast('已恢复默认值');
    });
  }

  // ------------------------------------------------------------- 弹层
  function askText(title, placeholder, initial) {
    return new Promise(function (resolve) {
      var dlg = $('#dlgText');
      $('#dlgTextTitle').textContent = title;
      var inp = $('#dlgTextInput');
      inp.value = initial || '';
      inp.placeholder = placeholder || '';
      function ok() { cleanup(); resolve(inp.value.trim() || null); }
      function cancel() { cleanup(); resolve(null); }
      function onKey(e) { if (e.key === 'Enter') { e.preventDefault(); ok(); } }
      function cleanup() {
        dlg.close();
        $('#dlgTextOk').removeEventListener('click', ok);
        $('#dlgTextCancel').removeEventListener('click', cancel);
        inp.removeEventListener('keydown', onKey);
      }
      $('#dlgTextOk').addEventListener('click', ok);
      $('#dlgTextCancel').addEventListener('click', cancel);
      inp.addEventListener('keydown', onKey);
      dlg.showModal();
      inp.focus();
      inp.select();
    });
  }

  /** 确认框。okText 不给就是「删除」（现有调用一行不用改）。
      danger 默认 true（红按钮）—— 降级录制那种"有副作用但不算删除"的
      传 danger=false，免得用户以为要删东西。 */
  function askConfirm(title, msg, okText, danger) {
    return new Promise(function (resolve) {
      var dlg = $('#dlgConfirm');
      var btn = $('#dlgConfirmOk');
      $('#dlgConfirmTitle').textContent = title;
      $('#dlgConfirmMsg').textContent = msg;
      btn.textContent = okText || '删除';
      btn.className = 'btn' + ((danger === undefined || danger) ? ' danger' : ' primary');
      function ok() { cleanup(); resolve(true); }
      function cancel() { cleanup(); resolve(false); }
      function cleanup() {
        dlg.close();
        btn.removeEventListener('click', ok);
        $('#dlgConfirmCancel').removeEventListener('click', cancel);
      }
      btn.addEventListener('click', ok);
      $('#dlgConfirmCancel').addEventListener('click', cancel);
      dlg.showModal();
    });
  }

  var _dlgWired = false;
  function wireDialogs() {
    if (_dlgWired) return;
    _dlgWired = true;
    document.addEventListener('click', function (e) {
      if (!e.target.closest('#ctxMenu')) G.hideContext();
    });
  }

  function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }

  /**
   * toast(msg, isError)
   *
   * isError=true 时：换红底 + 停 9 秒。
   * 【为什么必须有这个区分】失败提示如果长得和"已新建文字节点"一模一样、
   * 又是 4.2 秒自动消失，用户就会当成一句无关紧要的提示划过去 ——
   * 实测踩过：加节点其实没写进磁盘，用户以为加上了，重启后东西没了。
   */
  function toast(msg, isError) {
    var t = $('#toast');
    t.textContent = msg;
    t.classList.toggle('err', !!isError);
    t.classList.remove('hidden');
    clearTimeout(App._toastTimer);
    App._toastTimer = setTimeout(function () { t.classList.add('hidden'); },
                                 isError ? 9000 : 4200);
  }

  // ==================================================================== 自测钩子
  window.VKBApp = {
    applyState: applyState,
    onProcessingStarted: function () { window.VKBProcess.setItems(App._pending); },
    toast: toast,
    /** 处理浮层双击改名时调用（那边没有输入弹层，借用这里的） */
    renameItemPrompt: function (it) {
      return renameItem(it);
    },
    /** 摄像头录完命名时调用（那边也没有输入弹层） */
    askText: askText,
    /** 通用确认框（降级录制前要提醒"会独占麦克风"） */
    askConfirm: askConfirm,
  };

  window.VKB_DEBUG = {
    ready: function () { return !!(App.state && window.VKB.ready); },
    rects: function () {
      var g = $('#grid').getBoundingClientRect();
      function q(sel) {
        var r = $(sel).getBoundingClientRect();
        return { x: Math.round(r.left - g.left), y: Math.round(r.top - g.top),
                 w: Math.round(r.width), h: Math.round(r.height) };
      }
      return { tree: q('#paneTree'), content: q('#paneContent'),
               player: q('#panePlayer'), done: q('#paneDone'),
               divV: q('#divV'), divHL: q('#divHL'), divHR: q('#divHR') };
    },
    fitCheck: function () {
      var g = $('#grid').getBoundingClientRect();
      var de = document.documentElement;
      return {
        innerW: window.innerWidth, innerH: window.innerHeight,
        overRight: Math.round(g.right - window.innerWidth),
        overBottom: Math.round(g.bottom - window.innerHeight),
        hOverflow: de.scrollWidth - window.innerWidth,
        vOverflow: de.scrollHeight - window.innerHeight,
        bootHidden: $('#boot').classList.contains('hidden'),
        mediaErrorShown: !$('#mediaError').classList.contains('hidden'),
        mediaErrorText: $('#mediaError').textContent,
      };
    },
    graph: function () { return G.debug(); },
    player: function () { return App.player ? App.player.state() : null; },
    process: function () { return window.VKBProcess.state(); },
    /** 控制栏布局快照：用来断言"播放状态变化时布局纹丝不动" */
    playerBar: function () {
      function r(sel) {
        var e = $(sel);
        if (!e) return null;
        var b = e.getBoundingClientRect();
        return { x: Math.round(b.left * 10) / 10, w: Math.round(b.width * 10) / 10,
                 y: Math.round(b.top * 10) / 10, h: Math.round(b.height * 10) / 10 };
      }
      return {
        bar: r('.player-bar'),
        play: r('#btnPlay'), seek: r('#seek'), time: r('#timeLabel'),
        rotate: r('#btnRotate'), mute: r('#btnMute'),
        volPopHidden: $('#volPop').classList.contains('hidden'),
        volVertical: getComputedStyle($('#vol')).transform !== 'none',
        volRect: r('#vol'),
      };
    },
    done: function () {
      return { tab: App.tab, total: App.state.done.length,
               inTree: App.state.done.filter(function (i) { return i.inTree; }).length,
               rendered: $('#doneList').querySelectorAll('.row-item').length,
               titles: Array.prototype.map.call(
                 $('#doneList').querySelectorAll('.row-item .t'),
                 function (e) { return e.textContent; }) };
    },
    article: function () {
      var host = $('#article');
      var blocks = Array.prototype.slice.call(host.querySelectorAll('.blk'));
      return {
        blocks: blocks.length,
        titles: Array.prototype.map.call(host.querySelectorAll('.h'), function (e) { return e.value; }),
        bodies: host.querySelectorAll('.body').length,
        scrollMax: host.scrollHeight - host.clientHeight,
        levels: blocks.map(function (b) {
          var m = /lv(\d)/.exec(b.className);
          var h = b.querySelector('.h');
          var cs = getComputedStyle(h);
          var hr = host.getBoundingClientRect();
          return { lv: m ? +m[1] : -1, tag: h.tagName.toLowerCase(),
                   size: Math.round(parseFloat(cs.fontSize) * 10) / 10,
                   weight: cs.fontWeight,
                   indent: Math.round(h.getBoundingClientRect().left - hr.left),
                   title: (h.value || '').slice(0, 18) };
        }),
      };
    },
    scrolls: function () {
      function m(sel) { var e = $(sel); return e.scrollHeight - e.clientHeight; }
      return { tree: m('#graphViewport'), content: m('#article'), done: m('#doneList') };
    },
    settingsVisible: function () { return !$('#pageSettings').classList.contains('hidden'); },
    settings: function () {
      return { url: $('#setUrl').value, model: $('#setModel').value,
               key: $('#setKey').value, prompt: $('#setPrompt').value,
               fields: ['#setUrl', '#setModel', '#setKey', '#setPrompt']
                 .filter(function (s) { return $(s); }).length };
    },
    selectTab: function (t) { $('#doneTabs button[data-tab="' + t + '"]').click(); },
    showSettings: function () { $('#btnGear').click(); },
    openProcess: function () { window.VKBProcess.open(); },
    closeProcess: function () { window.VKBProcess.close(); },
  };

  window.addEventListener('pywebviewready', boot);
  document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 0); });
})();
