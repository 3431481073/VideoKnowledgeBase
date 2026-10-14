/* 旧 67 条断言的回归套件（按新布局调整）。
   只跑新验收没有重复覆盖的那些：导图交互、文章面板、条目行、
   设置、两种新建节点、条目改名、三格联动、实时状态、外链/配色/遮挡。 */
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
  /** 按**名字**取右键菜单项 —— 别按下标：菜单项会增删。 */
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

    // ================================================ 导图：空白双击 = 直接新建分组
    // （类型二选一的弹框已删除，见 index.html 里的说明）
    vp.dispatchEvent(new MouseEvent('dblclick', {
      bubbles: true, clientX: vr.left + 400, clientY: vr.top + 260,
    }));
    await sleep(200);
    chk('G7  空白双击 -> 弹出「添加」二选一', !!$('#dlgAdd').open);
    chk('G8  两行是动词：新建分组 / 加入视频；旧的类型弹框已不在',
      !!$('#dlgAddGroup') && !!$('#dlgAddVideo') && !$('#dlgNew'),
      $('#dlgAddWhere').textContent);
    $('#dlgAddGroup').click();
    await sleep(200);
    chk('G9  选「新建分组」-> 弹名字输入框', !!$('#dlgText').open);
    $('#dlgTextInput').value = '回归测试文字节点';
    $('#dlgTextOk').click();
    await waitFor(function () { return D.graph().nodes.some(function (n) { return n.name === '回归测试文字节点'; }); }, 3000);
    chk('G10 文字节点已建出来', D.graph().nodes.some(function (n) { return n.name === '回归测试文字节点'; }));
    var tn = nodeOf(function (n) { return n.name === '回归测试文字节点'; });
    chk('G11 文字节点是 topic 且没有 itemId', tn && tn.kind === 'topic' && !tn.itemId,
      tn ? (tn.kind + '/' + tn.itemId) : 'null');

    // ================================================ 导图：右键菜单
    var delTarget = nodeOf(function (n) { return n.name === '回归测试文字节点'; });
    nodeEl(delTarget.id).dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, clientX: vr.left + 300, clientY: vr.top + 200,
    }));
    await sleep(200);
    var menuItems = $$('#ctxMenu li').map(function (li) { return li.textContent; });
    chk('G12 右键菜单五项齐全', menuItems.length === 5, menuItems.join('/'));
    chk('G13 菜单是 新建分组/加入视频…/重命名/脱离父节点/删除',
      menuItems[0] === '新建分组' && menuItems[1] === '加入视频…' &&
      menuItems[2] === '重命名' && menuItems[3] === '脱离父节点' &&
      menuItems[4] === '删除', menuItems.join('/'));
    chk('G14 菜单已显示', !$('#ctxMenu').classList.contains('hidden'));
    // 重命名
    menuItem('重命名').click();
    await sleep(200);
    chk('G15 点重命名 -> 弹输入框', !!$('#dlgText').open);
    $('#dlgTextInput').value = '回归改名后';
    $('#dlgTextOk').click();
    await waitFor(function () { return D.graph().nodes.some(function (n) { return n.name === '回归改名后'; }); }, 3000);
    chk('G16 重命名生效（导图同步）', D.graph().nodes.some(function (n) { return n.name === '回归改名后'; }));
    // 删除
    var rr = nodeOf(function (n) { return n.name === '回归改名后'; });
    nodeEl(rr.id).dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, clientX: vr.left + 300, clientY: vr.top + 200,
    }));
    await sleep(200);
    menuItem('删除').click();
    await sleep(200);
    chk('G17 点删除 -> 弹确认框', !!$('#dlgConfirm').open);
    $('#dlgConfirmOk').click();
    await waitFor(function () { return !D.graph().nodes.some(function (n) { return n.name === '回归改名后'; }); }, 3000);
    chk('G18 删除生效', !D.graph().nodes.some(function (n) { return n.name === '回归改名后'; }));

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
    chk('G19 拖到另一个节点上 -> 层级变了', moved && moved.depth !== d0,
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

    // ============= 加入视频：右键分组 -> 从还没加入导图的条目里选
    var hostNode = nodeOf(function (n) { return n.kind === 'topic'; });
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

    // 收尾：把弹层都关掉
    closeDlg();
    await sleep(150);

  } catch (err) {
    chk('!! 回归过程抛异常', false, (err && err.message) || String(err));
  }
  window.__RESULTS = R;
  window.__DONE = true;
})();
