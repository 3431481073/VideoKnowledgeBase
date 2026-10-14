/* ui-tree：导图交互 / 文章面板 / 条目 / 设置 / 三格联动。
   改这些地方跑这一套就够（目标 ~6 秒）。 */
(async function () {
  var R = [];
  function chk(name, cond, extra) {
    R.push({ name: name, pass: !!cond, extra: extra === undefined ? '' : String(extra) });
    window.__RESULTS = R;
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  async function waitFor(fn, ms) {
    var t = Date.now();
    while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) { } await sleep(40); }
    return false;
  }
  function $(s) { return document.querySelector(s); }
  function $$(s) { return Array.prototype.slice.call(document.querySelectorAll(s)); }
  /** 按**名字**取右键菜单项。
   *  【为什么不用下标】菜单项会增删 —— 加「脱离父节点」那次，原来按 [3] 点"删除"
   *  的地方全都点到了新项上，两条断言当场假失败。按名字取就没这回事。 */
  function menuItem(label) {
    return $$('#ctxMenu li').filter(function (li) {
      return li.textContent === label; })[0];
  }
  var D = window.VKB_DEBUG, G = window.VKBGraph;

  function nodeEl(id) { return document.querySelector('#nodes .node[data-id="' + id + '"]'); }
  function nodeOf(pred) { return D.graph().nodes.filter(pred)[0]; }
  function closeDlg() {
    var d = document.querySelector('dialog[open]');
    if (!d) return;
    var b = d.querySelector('.dlg-foot .btn:not(.primary):not(.danger)');
    if (b) b.click(); else d.close();
  }

  try {
    var g0 = D.graph();

    // ================================================ 导图：缩放
    var vp = $('#graphViewport');
    var vr = vp.getBoundingClientRect();
    var sc0 = G.debug().scale;
    vp.dispatchEvent(new WheelEvent('wheel', {
      deltaY: -100, clientX: vr.left + 200, clientY: vr.top + 150,
      bubbles: true, cancelable: true,
    }));
    var zoomed = await waitFor(function () { return G.debug().scale > sc0 + 0.01; }, 2000);
    var sc1 = G.debug().scale;
    chk('G1  滚轮向上 -> 放大', zoomed, sc0 + ' -> ' + sc1);
    chk('G2  放大步长温和（一格 <= 8%）', sc1 / sc0 <= 1.08, (sc1 / sc0).toFixed(4));
    G.resetView();
    await sleep(120);

    // ================================================ 导图：空白平移
    var px0 = G.debug().panX;
    vp.dispatchEvent(new MouseEvent('mousedown', {
      bubbles: true, button: 0, clientX: vr.left + 600, clientY: vr.top + 300,
    }));
    window.dispatchEvent(new MouseEvent('mousemove', {
      bubbles: true, clientX: vr.left + 660, clientY: vr.top + 300,
    }));
    window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    await sleep(120);
    chk('G3  空白拖动 -> 画布平移', Math.abs(G.debug().panX - px0 - 60) < 8,
      px0 + ' -> ' + G.debug().panX);
    G.resetView();
    await sleep(120);

    // ================================================ 导图：双击折叠
    var parent = nodeOf(function (n) { return n.children >= 2 && n.kind === 'topic'; });
    chk('G4  找到有子节点的节点', !!parent, JSON.stringify(g0.nodes.map(function (n) { return n.name; })).slice(0, 60));
    var n0 = G.debug().count;
    nodeEl(parent.id).dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    await waitFor(function () { return G.debug().count !== n0; }, 2000);
    var n1 = G.debug().count;
    chk('G5  双击 -> 折叠，可见节点变少', n1 < n0, n0 + ' -> ' + n1);
    nodeEl(parent.id).dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    await waitFor(function () { return G.debug().count === n0; }, 2000);
    chk('G6  再双击 -> 展开还原', G.debug().count === n0, G.debug().count + ' vs ' + n0);

    // ============= 导图：空白双击 = 添加（分组 / 视频 二选一）
    vp.dispatchEvent(new MouseEvent('dblclick', {
      bubbles: true, clientX: vr.left + 400, clientY: vr.top + 260,
    }));
    await sleep(200);
    chk('G7  空白双击 -> 弹出「添加」二选一（不是直接建分组）',
      !!$('#dlgAdd').open);
    chk('G8  两行是动词：新建分组 / 加入视频；旧的类型弹框已不在',
      !!$('#dlgAddGroup') && !!$('#dlgAddVideo') && !$('#dlgNew'),
      $('#dlgAddWhere').textContent);
    chk('G8b 标题写清"加到哪儿"',
      ($('#dlgAddWhere').textContent || '').length > 0,
      $('#dlgAddWhere').textContent);
    $('#dlgAddGroup').click();
    await sleep(200);
    chk('G9  选「新建分组」-> 弹名字输入框', !!$('#dlgText').open);
    $('#dlgTextInput').value = '回归测试分组';
    $('#dlgTextOk').click();
    await waitFor(function () { return D.graph().nodes.some(function (n) { return n.name === '回归测试分组'; }); }, 3000);
    chk('G9b 分组已建出来',
      D.graph().nodes.some(function (n) { return n.name === '回归测试分组'; }));

    // 另一条分支：双击 -> 加入视频 -> 弹出条目选择框
    vp.dispatchEvent(new MouseEvent('dblclick', {
      bubbles: true, clientX: vr.left + 400, clientY: vr.top + 260,
    }));
    await sleep(200);
    $('#dlgAddVideo').click();
    await sleep(250);
    chk('G9c 选「加入视频」-> 弹出条目选择框', !!$('#dlgPick').open);
    $('#dlgPickCancel').click();
    await sleep(200);

    var tn = nodeOf(function (n) { return n.name === '回归测试分组'; });
    chk('G10 它是 topic 且没有 itemId', tn && tn.kind === 'topic' && !tn.itemId,
      tn ? (tn.kind + '/' + tn.itemId) : 'null');

    // ============= 导图：右键菜单（四个自解释的动作）
    nodeEl(tn.id).dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, clientX: vr.left + 300, clientY: vr.top + 200,
    }));
    await sleep(200);
    var menuItems = $$('#ctxMenu li').map(function (li) { return li.textContent; });
    chk('G11 右键菜单五项齐全', menuItems.length === 5, menuItems.join('/'));
    chk('G12 菜单是 新建分组/加入视频…/重命名/脱离父节点/删除',
      menuItems[0] === '新建分组' && menuItems[1] === '加入视频…' &&
      menuItems[2] === '重命名' && menuItems[3] === '脱离父节点' &&
      menuItems[4] === '删除', menuItems.join('/'));
    chk('G13 菜单已显示', !$('#ctxMenu').classList.contains('hidden'));

    // 重命名
    menuItem('重命名').click();
    await sleep(200);
    chk('G14 点重命名 -> 弹输入框', !!$('#dlgText').open);
    $('#dlgTextInput').value = '回归改名后';
    $('#dlgTextOk').click();
    await waitFor(function () { return D.graph().nodes.some(function (n) { return n.name === '回归改名后'; }); }, 3000);
    chk('G15 重命名生效（导图同步）',
      D.graph().nodes.some(function (n) { return n.name === '回归改名后'; }));

    // 加入视频…（索引 1）：直接弹条目选择框，中间不再有"节点类型"
    var rn = nodeOf(function (n) { return n.name === '回归改名后'; });
    nodeEl(rn.id).dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, clientX: vr.left + 300, clientY: vr.top + 200,
    }));
    await sleep(200);
    menuItem('加入视频…').click();
    await sleep(250);
    chk('G16 点「加入视频…」-> 直接弹出条目选择框', !!$('#dlgPick').open);
    chk('G17 条目选择框不再用「未添加」这个界面术语',
      $('#dlgPick').textContent.indexOf('未添加') < 0,
      $('#dlgPick').querySelector('p').textContent);
    $('#dlgPickCancel').click();
    await sleep(200);

    // 删除（索引 3）
    nodeEl(rn.id).dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, clientX: vr.left + 300, clientY: vr.top + 200,
    }));
    await sleep(200);
    menuItem('删除').click();
    await sleep(200);
    chk('G18 点删除 -> 弹确认框', !!$('#dlgConfirm').open);
    $('#dlgConfirmOk').click();
    await waitFor(function () { return !D.graph().nodes.some(function (n) { return n.name === '回归改名后'; }); }, 3000);
    chk('G19 删除生效（导图节点没了）',
      !D.graph().nodes.some(function (n) { return n.name === '回归改名后'; }));

    // ================================================ 导图：拖动改结构
    var kid = nodeOf(function (n) { return n.kind === 'video' && n.depth >= 2; });
    var newParent = nodeOf(function (n) { return n.kind === 'topic' && n.id !== kid.id && n.depth >= 1; });
    var d0 = kid.depth;
    var ke = nodeEl(kid.id), te = nodeEl(newParent.id);
    var kb = ke.getBoundingClientRect(), tb = te.getBoundingClientRect();
    ke.dispatchEvent(new MouseEvent('mousedown', {
      bubbles: true, button: 0, clientX: kb.left + kb.width / 2, clientY: kb.top + kb.height / 2,
    }));
    window.dispatchEvent(new MouseEvent('mousemove', {
      bubbles: true, clientX: tb.left + tb.width / 2, clientY: tb.top + tb.height / 2,
    }));
    window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    await waitFor(function () {
      var x = D.graph().nodes.filter(function (n) { return n.id === kid.id; })[0];
      return x && x.depth !== d0;
    }, 3000);
    var moved = D.graph().nodes.filter(function (n) { return n.id === kid.id; })[0];
    chk('G20 拖到另一个节点上 -> 层级变了', moved && moved.depth !== d0,
      d0 + ' -> ' + (moved ? moved.depth : 'null'));

    // ================================================ 文章面板
    var topic = nodeOf(function (n) { return n.kind === 'topic' && n.children >= 1; });
    nodeEl(topic.id).dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0, clientX: 0, clientY: 0 }));
    window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    await sleep(250);
    var art = D.article();
    chk('A1  点节点 -> 文章有内容', art.blocks > 0, art.blocks);
    chk('A2  文章层级用字号表达（逐级递减）',
      art.levels.length >= 2 && art.levels[0].size >= art.levels[art.levels.length - 1].size,
      art.levels.map(function (l) { return l.lv + ':' + l.size; }).join(' '));
    chk('A3  文章有左缩进层级',
      art.levels.length >= 2 && art.levels[art.levels.length - 1].indent >= art.levels[0].indent,
      art.levels.map(function (l) { return l.indent; }).join(','));
    chk('A4  文章用 textarea 呈现（可编辑）',
      art.levels.every(function (l) { return l.tag === 'textarea'; }),
      art.levels.map(function (l) { return l.tag; }).join(','));

    // 改文章标题 -> 导图同步
    var hEls = $$('#article .h');
    var targetName = '文章标题改过了';
    var vidNode = null;
    for (var i = 0; i < hEls.length; i++) {
      var nodeId = null;
      // 通过 name 反查
      var v = hEls[i].value;
      var found = D.graph().nodes.filter(function (n) { return n.name === v; })[0];
      if (found && found.kind === 'video') {
        vidNode = found;
        // 必须先 focus 再 blur —— 元素没聚焦时 blur() 是空操作，不会派发
        // blur 事件，保存逻辑根本不会跑。上一版测试就栽在这里。
        hEls[i].focus();
        hEls[i].value = targetName;
        hEls[i].dispatchEvent(new Event('input', { bubbles: true }));
        hEls[i].blur();
        break;
      }
    }
    if (vidNode) {
      await waitFor(function () {
        return D.graph().nodes.some(function (n) { return n.name === targetName; });
      }, 3000);
      chk('A5  文章里改标题 -> 导图同步', D.graph().nodes.some(function (n) { return n.name === targetName; }));
    } else {
      chk('A5  文章里改标题 -> 导图同步', false, '没找到视频节点标题');
    }

    // ================================================ 右下条目 + tab
    var done0 = D.done();
    var rows = $$('#doneList .row-item');
    chk('B1  条目列表有行', rows.length > 0, rows.length);
    chk('B2  每行三行结构（标题/时间/摘要）',
      rows.every(function (r) { return r.children.length === 3; }),
      rows[0] ? rows[0].children.length : 0);
    chk('B3  标题行有文字', rows[0].children[0].textContent.length > 0);
    chk('B4  摘要行有文字', rows[0].children[2].textContent.length > 0);
    chk('B5  三个 tab 都在', $$('#doneTabs button').length === 3,
      $$('#doneTabs button').map(function (b) { return b.textContent; }).join('/'));

    D.selectTab('out');
    await sleep(200);
    var outRows = $$('#doneList .row-item').length;
    chk('B6  「未添加」筛选生效', outRows === (done0.total - done0.inTree),
      outRows + ' vs ' + (done0.total - done0.inTree));
    D.selectTab('in');
    await sleep(200);
    chk('B7  「已添加到树」筛选生效', $$('#doneList .row-item').length === done0.inTree,
      $$('#doneList .row-item').length + ' vs ' + done0.inTree);
    D.selectTab('all');
    await sleep(200);
    chk('B8  「全部」= 两者之和', $$('#doneList .row-item').length === done0.total,
      $$('#doneList .row-item').length + ' vs ' + done0.total);

    // ================================================ 条目改名（双击）
    var firstRow = $$('#doneList .row-item')[0];
    var oldTitle = firstRow.children[0].textContent;
    firstRow.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    await sleep(250);
    chk('B9  双击条目 -> 弹改名框', !!$('#dlgText').open);
    $('#dlgTextInput').value = oldTitle + '【已改】';
    $('#dlgTextOk').click();
    await waitFor(function () {
      return $$('#doneList .row-item')[0].children[0].textContent !== oldTitle;
    }, 3000);
    chk('B10 条目改名生效', $$('#doneList .row-item')[0].children[0].textContent !== oldTitle,
      $$('#doneList .row-item')[0].children[0].textContent);

    // ---------------- 点条目 -> 左下显示全文（规格 1）----------------
    $('#article').innerHTML = '';
    var firstRow2 = $$('#doneList .row-item')[0];
    firstRow2.click();
    var gotText = await waitFor(function () {
      return $('#article .body.ro') && $('#article .body.ro').textContent.length > 5;
    }, 3000);
    chk('B10a ★ 点条目 -> 左下出现正文', gotText,
      $('#article .body.ro') ? $('#article .body.ro').textContent.slice(0, 40) : '(空)');
    chk('B10b 点条目 -> 有来源标注（清洗稿 / 原始转写）',
      !!$('#article .ro-meta'), $('#article .ro-meta') ? $('#article .ro-meta').textContent : '无');
    chk('B10c 点条目 -> 该条高亮选中',
      $$('#doneList .row-item.sel').length === 1, $$('#doneList .row-item.sel').length);
    chk('B10d 点条目 -> 显示的是全文而不是 20 字摘要',
      $('#article .body.ro').textContent.length >=
      firstRow2.querySelector('.s').textContent.length,
      $('#article .body.ro').textContent.length);

    // ---------------- 主题节点也有正文框（规格 2）----------------
    var topicNode = nodeOf(function (n) { return n.kind === 'topic'; });
    nodeEl(topicNode.id).dispatchEvent(new MouseEvent('mousedown', {
      bubbles: true, button: 0, clientX: 0, clientY: 0,
    }));
    window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    await sleep(300);
    var tArt = D.article();
    var topicHasBody = $$('#article .body').length;
    chk('B10e ★ 主题节点的文章里也有正文框', topicHasBody > 0,
      'blk=' + tArt.blocks + ' body=' + topicHasBody);
    chk('B10f 正文框数量 >= 块数量（每个节点都有）', topicHasBody >= tArt.blocks,
      topicHasBody + ' vs ' + tArt.blocks);

    // ---------------- 实时保存（规格 19）----------------
    var bodyEl = $$('#article .body')[0];
    if (bodyEl) {
      var marker = '实时保存测试' + Date.now() % 100000;
      bodyEl.focus();
      bodyEl.value = marker;
      bodyEl.dispatchEvent(new Event('input', { bubbles: true }));
      // 500ms 防抖，等 900ms 后应当已经落库（不靠 blur）
      await sleep(900);
      var saved = await VKB.call('get_state');
      var flat = JSON.stringify(saved.tree);
      chk('B10g ★ 打字 900ms 后已自动保存（没失焦）', flat.indexOf(marker) >= 0,
        '在树里找到 = ' + (flat.indexOf(marker) >= 0));
      bodyEl.blur();
      await sleep(200);
    } else {
      chk('B10g ★ 打字 900ms 后已自动保存（没失焦）', false, '没找到正文框');
    }

    // ============= 加入视频：右键分组 -> 从还没加入导图的条目里选
    var hostNode = nodeOf(function (n) { return n.kind === 'topic'; });
    chk('B11a 有可以往里加视频的分组/主题节点', !!hostNode);
    nodeEl(hostNode.id).dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, clientX: vr.left + 300, clientY: vr.top + 200,
    }));
    await sleep(200);
    menuItem('加入视频…').click();
    await sleep(250);
    chk('B11 点「加入视频…」-> 弹出条目选择', !!$('#dlgPick').open);
    var pickItems = $$('#dlgPickList .pick-item');
    chk('B12 候选列表非空', pickItems.length > 0, pickItems.length);
    var pickText = pickItems[0].textContent;
    chk('B13 候选名已是去扩展名的形式', pickText.indexOf('.mp4') < 0, pickText);
    var inTreeBefore = D.done().inTree;
    pickItems[0].click();
    await waitFor(function () { return D.done().inTree === inTreeBefore + 1; }, 3000);
    chk('B14 挂上内容节点 -> 已添加数 +1', D.done().inTree === inTreeBefore + 1,
      inTreeBefore + ' -> ' + D.done().inTree);
    chk('B15 新节点名不含 .mp4',
      D.graph().nodes.some(function (n) { return n.name === pickText; }), pickText);

    // ================================================ 实时「已添加/未添加」
    var d1 = D.done();
    chk('B16 三 tab 计数实时自洽', d1.rendered === d1.total || d1.rendered === d1.inTree,
      JSON.stringify(d1));

    // ================================================ 设置
    D.showSettings();
    await sleep(200);
    chk('C1  设置页可见', D.settingsVisible() === true);
    var s = D.settings();
    chk('C2  四个字段齐全', s.fields === 4, s.fields);
    chk('C3  字段非空', !!s.url && !!s.model && !!s.prompt, s.url);
    var oldUrl = s.url;
    $('#setUrl').value = 'https://example.invalid/v1';
    $('#btnSetSave').click();
    await waitFor(function () { return D.settingsVisible() === false; }, 3000);
    chk('C4  保存后回到列表页', D.settingsVisible() === false);
    D.showSettings();
    await sleep(150);
    chk('C5  保存的值还在', D.settings().url === 'https://example.invalid/v1', D.settings().url);
    $('#btnSetReset').click();
    await sleep(250);
    chk('C6  恢复默认值', D.settings().url === oldUrl, D.settings().url + ' vs ' + oldUrl);
    $('#btnSetBack').click();
    await sleep(200);
    chk('C7  返回后回到列表页', D.settingsVisible() === false);

    // ================================================ 外链 / 配色 / 遮挡
    chk('D1  无 CDN 外链脚本/样式',
      $$('script[src^="http"],link[href^="http"]').length === 0);
    chk('D2  浅色背景', getComputedStyle(document.body).backgroundColor === 'rgb(238, 240, 243)',
      getComputedStyle(document.body).backgroundColor);
    var fc = D.fitCheck();
    chk('D3  无横向溢出', fc.hOverflow <= 0, fc.hOverflow);
    chk('D4  无纵向溢出', fc.vOverflow <= 0, fc.vOverflow);
    chk('D5  启动遮罩已隐藏', fc.bootHidden === true);
    chk('D6  无媒体错误条', fc.mediaErrorShown === false);
    // 导图画布比视口大得多（绝对定位 + 大 SVG），scrollHeight 必然大于
    // clientHeight —— 查"有没有滚动条"要看 overflow 和 clientWidth，
    // 不是看 scrollHeight。
    var vpcs = getComputedStyle($('#graphViewport'));
    chk('D7  导图视口 overflow:hidden（不会出滚动条）',
      vpcs.overflow === 'hidden' && vpcs.overflowY === 'hidden', vpcs.overflowY);
    var vpEl = $('#graphViewport');
    chk('D7b 导图视口没有被滚动条吃掉宽度',
      vpEl.clientWidth === vpEl.offsetWidth,
      vpEl.clientWidth + ' vs ' + vpEl.offsetWidth);
    var artScroll = D.scrolls().content;
    chk('D8  文章区可滚动', artScroll >= 0, artScroll);

    // ---- F. 四格联动：点右下卡片必须同时更新右上播放器 ----
    // 用户报的现象：点右下卡片 -> 左下文章有了、左上导图也对，但**右上不出视频**；
    // 而点左上导图节点 -> 右上能播。这里两条路径各用行为验一遍。
    function pUrl() { return (D.player() || {}).url || ''; }
    function clickNode(id) {
      nodeEl(id).dispatchEvent(new MouseEvent('mousedown',
        { bubbles: true, button: 0, clientX: 0, clientY: 0 }));
      window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    }

    var vn = D.graph().nodes.filter(function (n) { return n.kind === 'video'; })[0];
    chk('F0  假数据里有内容节点（否则 F1 测不到）', !!vn, D.graph().nodes.length);
    if (vn) {
      clickNode(vn.id);
      await sleep(250);
      chk('F1  点左上导图内容节点 -> 右上加载了视频',
        pUrl().indexOf('media/') >= 0, pUrl());
    }

    // 先把右上清空，下一步"有没有被填回来"才是确定的
    var tn = D.graph().nodes.filter(function (n) {
      return n.kind !== 'video' && nodeEl(n.id); })[0];
    chk('F2a 假数据里有文字节点（用来清空右上）', !!tn);
    if (tn) {
      clickNode(tn.id);
      await sleep(250);
      chk('F2b 点文字节点 -> 右上被清空（前置条件）', pUrl() === '', pUrl());
    }

    var card = $('#doneList .row-item');
    chk('F3  右下有已完成卡片', !!card, $$('#doneList .row-item').length);
    if (card) {
      var cid = card.dataset.id;
      var pr = await VKB.call('poll');
      var cit = ((pr && pr.done) || []).filter(function (x) {
        return x.id === cid; })[0];
      card.click();
      await sleep(400);
      chk('F4 ★★ 点右下卡片 -> 右上必须加载该条目的视频',
        !!cit && pUrl() === cit.media,
        '播放器 url=' + pUrl() + '  条目 media=' + (cit && cit.media));
    }

    // ---- H. 删除条目：四处一起清（左上导图 / 左下文章 / 右上播放器 / 右下卡片）----
    var card2 = $('#doneList .row-item');
    chk('H0  有可删的卡片', !!card2, $$('#doneList .row-item').length);
    if (card2) {
      var hId = card2.dataset.id;
      var hTotal = D.done().total;
      var hpr = await VKB.call('poll');
      var hit = ((hpr && hpr.done) || []).filter(function (x) { return x.id === hId; })[0];
      var hMedia = hit && hit.media;
      // 先点它，让右上/左下都指向它，再删 —— 这样"清干净了没有"才验得出来
      card2.click();
      await sleep(350);
      chk('H1  删除前右上确实在放它（前置条件）', pUrl() === hMedia,
        '播放器=' + pUrl() + ' 条目=' + hMedia);

      card2.dispatchEvent(new MouseEvent('contextmenu', {
        bubbles: true, cancelable: true, clientX: 300, clientY: 300 }));
      await sleep(200);
      var hm = $$('#ctxMenu li').map(function (li) { return li.textContent; });
      chk('H2  卡片右键菜单只有「删除」', hm.length === 1 && hm[0] === '删除',
        hm.join('/'));
      menuItem('删除').click();
      await sleep(250);
      chk('H3  弹确认框', !!$('#dlgConfirm').open);
      chk('H4 ★ 确认框里明说「视频文件会保留」（别让人以为连文件一起删）',
        $('#dlgConfirmMsg').textContent.indexOf('视频文件会保留') >= 0,
        $('#dlgConfirmMsg').textContent.replace(/\s+/g, ' ').slice(0, 80));
      $('#dlgConfirmOk').click();
      await waitFor(function () { return D.done().total === hTotal - 1; }, 3000);
      chk('H5 ★★ 右下：卡片没了', D.done().total === hTotal - 1,
        hTotal + ' -> ' + D.done().total);
      chk('H6 ★★ 左上：导图里再也没有挂着这个条目的节点',
        !D.graph().nodes.some(function (n) { return n.itemId === hId; }));
      chk('H7 ★★ 右上：播放器不再指着刚删的那条', pUrl() !== hMedia,
        '播放器=' + pUrl() + ' 已删=' + hMedia);
    }

    // ---- I. 脱离父节点：摘出来挂到根下，子节点跟着走 ----
    var nodeList = D.graph().nodes;
    var deep = null;
    for (var di = 0; di < nodeList.length; di++) {
      // 【多根】顶层节点现在是 depth 0，"嵌套的中间节点"从 depth>=1 起算
      if (nodeList[di].depth >= 1 && nodeList[di].children > 0) {
        deep = nodeList[di]; break;
      }
    }
    chk('I1  假数据里有嵌套的中间节点（depth>=1 且有子节点）', !!deep,
      nodeList.length);
    if (deep) {
      var nBefore = D.graph().nodes.length;
      var topsBefore = D.graph().nodes.filter(function (n) {
        return n.depth === 0; }).length;
      var kidsBefore = deep.children;
      nodeEl(deep.id).dispatchEvent(new MouseEvent('contextmenu', {
        bubbles: true, cancelable: true, clientX: vr.left + 300, clientY: vr.top + 200,
      }));
      await sleep(200);
      var di3 = menuItem('脱离父节点');
      chk('I2  菜单里有「脱离父节点」', !!di3);
      chk('I3  嵌套节点上它是**可点**的（没被禁用）',
        !!di3 && !di3.classList.contains('disabled'));
      di3.click();
      await sleep(450);

      var after = D.graph().nodes.filter(function (n) {
        return n.id === deep.id; })[0];
      chk('I4 ★★ 脱离后成了**顶层节点**（depth 变 0）',
        !!after && after.depth === 0, after ? ('depth=' + after.depth) : '节点没了');
      chk('I5 ★★ 节点还在（脱离不是删除）', !!after);
      chk('I6 ★★ 子树跟着走（子节点数没变）',
        !!after && after.children === kidsBefore,
        (after ? after.children : '?') + ' vs ' + kidsBefore);
      chk('I7 ★★ 树上一共还是那么多节点（一个都没丢）',
        D.graph().nodes.length === nBefore,
        nBefore + ' -> ' + D.graph().nodes.length);
      var topsAfter = D.graph().nodes.filter(function (n) {
        return n.depth === 0; }).length;
      chk('I8 ★★★ **顶层多出来一个** —— 这就是「多根」',
        topsAfter === topsBefore + 1, topsBefore + ' -> ' + topsAfter);

      // 对已经是顶层的节点再脱离一次：允许、成功、结构不变（真 no-op）
      nodeEl(deep.id).dispatchEvent(new MouseEvent('contextmenu', {
        bubbles: true, cancelable: true, clientX: vr.left + 300, clientY: vr.top + 200,
      }));
      await sleep(200);
      var di4 = menuItem('脱离父节点');
      chk('I9  已经是顶层的节点 -> 菜单项**仍可点**（现在没有禁用项了）',
        !!di4 && !di4.classList.contains('disabled'));
      var sigBefore = D.graph().nodes.map(function (n) {
        return n.id + '@' + n.depth; }).sort().join(',');
      di4.click();
      await sleep(450);
      var di5 = D.graph().nodes.filter(function (n) { return n.id === deep.id; })[0];
      var sigAfter = D.graph().nodes.map(function (n) {
        return n.id + '@' + n.depth; }).sort().join(',');
      chk('I10 ★★ no-op 脱离后节点还在、depth 仍是 0',
        !!di5 && di5.depth === 0, di5 ? ('depth=' + di5.depth) : '节点没了');
      chk('I11 ★★ 整棵树的结构一点没变（no-op 不许改结构）',
        sigBefore === sigAfter);
      G.hideContext();
      await sleep(150);
    }

    // ---- E. 失败提示必须"看得出来是失败" ----
    // 写盘失败 / 加节点失败如果用和成功一模一样的提示，用户会当成无关紧要的
    // 一句话划过去 —— 实测踩过：以为加进树了，其实没写进磁盘。
    var tEl = $('#toast');
    // 诊断：页面通过 HTTP 真正拿到的 app.js 是哪一版（不猜，让它自己报）
    // 【前置守卫】页面真正加载的前端，必须就是**源码目录**那一份。
    // 防的是：pywebview 挑的端口撞上另一个正在跑的实例（打包版），页面被那个
    // 实例的服务器供走 —— 那下面所有断言测的都是构建产物里的旧前端，不是源码。
    // 实测踩过：E2 假失败，查半天才发现页面来自打包版的 42001 端口。
    try {
      var _resp = await fetch('js/app.js');
      var _txt = await _resp.text();
      var _want = (window.__SRC_LEN || {})['js/app.js'];
      chk('E0 ★ 页面里的 app.js 就是源码目录那份（不是构建产物）',
        _want !== undefined && _txt.length === _want,
        '页面=' + location.href + ' 得到=' + _txt.length + ' 期望=' + _want);
    } catch (e2) {
      chk('E0 ★ 页面里的 app.js 就是源码目录那份（不是构建产物）',
        false, String(e2));
    }
    window.VKBApp.toast('普通提示');
    chk('E1  普通提示不带错误样式', !tEl.classList.contains('err'));
    window.VKBApp.toast('写盘失败：模拟', true);
    chk('E2 ★★ 失败提示带错误样式（err）', tEl.classList.contains('err'),
      tEl.className + ' | toast.length=' + window.VKBApp.toast.length
      + ' | 源=' + String(window.VKBApp.toast).replace(/\s+/g, ' ').slice(0, 90));
    chk('E3  失败提示显示的就是那一句原因',
      tEl.textContent.indexOf('写盘失败') >= 0, tEl.textContent);
    window.VKBApp.toast('又一条普通提示');
    chk('E4  下一条普通提示会把错误样式清掉', !tEl.classList.contains('err'));

    // 收尾：把弹层都关掉
    closeDlg();
    await sleep(150);

  } catch (err) {
    chk('!! 回归过程抛异常', false, (err && err.message) || String(err));
  }
  window.__RESULTS = R;
  window.__DONE = true;
})();
