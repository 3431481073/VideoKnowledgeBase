/* ui-panel：处理浮层。常态选中规则 / 裁剪 / 合并 / 三模式独立 / 转写。
   改浮层相关的东西跑这一套就够（目标 ~8 秒）。 */
(async function () {
  var R = [];
  function chk(name, cond, extra) {
    R.push({ name: name, pass: !!cond, extra: extra === undefined ? '' : String(extra) });
    window.__RESULTS = R;
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  async function waitFor(fn, ms) {
    var t = Date.now();
    while (Date.now() - t < (ms || 4000)) {
      try { if (fn()) return true; } catch (e) { }
      await sleep(30);
    }
    return false;
  }
  function $(s) { return document.querySelector(s); }
  function $$(s) { return Array.prototype.slice.call(document.querySelectorAll(s)); }
  var D = window.VKB_DEBUG, P = window.VKBProcess;
  function rows() { return $$('#procList .proc-item'); }
  function rowById(id) { return document.querySelector('#procList .proc-item[data-id="' + id + '"]'); }
  function rowIds() { return rows().map(function (r) { return r.dataset.id; }); }
  var A = function () { return P.state().actions; };

  try {
    P.open();
    await sleep(200);

    // ---------------- 常态：默认态与启用规则 ----------------
    chk('N1a 进浮层默认是常态', P.state().page === 'list' &&
      $('#pageProcTrim').classList.contains('hidden') &&
      $('#pageProcMerge').classList.contains('hidden'), P.state().page);
    chk('N1b 常态页有列表和预览',
      $('#procList').offsetParent !== null && $('#listVideo') !== null);

    var ids0 = rowIds();
    chk('N1c 列表有多条', ids0.length >= 4, ids0.length);
    P._setChecked([]);
    await sleep(120);
    chk('N1d 0 条：裁剪禁用', A().cropDisabled === true);
    chk('N1e 0 条：合并禁用', A().mergeDisabled === true);
    chk('N1f 0 条：转写禁用', A().transcribeDisabled === true);

    // ---------------- 单击行 = **只预览** ----------------
    // 用户原话："单击视频条就默认选中了左边的框"。点行**不许**动选中；
    // 多选的唯一入口是左边的勾选框。
    P._setChecked([]);
    await sleep(150);
    var preC = P.state();
    chk('N2a0 起始：没选中、也没预览',
      preC.checked.length === 0 && preC.previewId === null,
      preC.checked.length + '/' + preC.previewId);

    rowById(ids0[0]).click();
    await sleep(250);
    var s1 = P.state();
    chk('N2a ★ 单击行 -> **不**选中（左框不动）', s1.checked.length === 0,
      JSON.stringify(s1.checked));
    chk('N2b ★ 单击行 -> 右边预览该条', s1.previewId === ids0[0], s1.previewId);
    chk('N2c 单击行 -> 仍停在常态', s1.page === 'list', s1.page);
    chk('N2d 0 条选中 -> 裁剪仍禁用', A().cropDisabled === true, JSON.stringify(A()));
    chk('N2e 0 条选中 -> 合并仍禁用', A().mergeDisabled === true);
    chk('N2f 0 条选中 -> 转写仍禁用', A().transcribeDisabled === true);

    // 再点同一行 = 还是只预览（不会"点两下就变选中"）
    rowById(ids0[0]).click();
    await sleep(200);
    chk('N2g ★ 再点同一行 -> 选中仍然是空', P.state().checked.length === 0,
      P.state().checked.length);
    chk('N2h 预览还停在同一条', P.state().previewId === ids0[0], P.state().previewId);

    // ---------------- 勾选框 = 选中的唯一入口 ----------------
    rowById(ids0[0]).querySelector('.ci').click();
    await sleep(250);
    var s2 = P.state();
    chk('N2i ★ 点勾选框 -> 选中该条',
      s2.checked.length === 1 && s2.checked[0] === ids0[0], JSON.stringify(s2.checked));
    chk('N2j ★ 1 条选中 -> 裁剪可用', A().cropDisabled === false, JSON.stringify(A()));
    chk('N2k 1 条选中 -> 合并仍禁用', A().mergeDisabled === true);
    chk('N2l 1 条选中 -> 转写可用', A().transcribeDisabled === false);
    chk('N2m 点勾选框不改预览', s2.previewId === ids0[0], s2.previewId);
    rowById(ids0[0]).querySelector('.ci').click();     // 取消
    await sleep(200);
    chk('N2n 取消勾选 -> 裁剪又禁用', A().cropDisabled === true);

    // ---------------- 勾选框：只切换选中，不动预览 ----------------
    var before = P.state();
    rowById(ids0[1]).querySelector('.ci').click();
    await sleep(200);
    var after = P.state();
    chk('N3a 点勾选框 -> 选中 +1', after.checked.length === before.checked.length + 1);
    chk('N3b ★ 点勾选框 -> 预览一字不变', after.previewUrl === before.previewUrl,
      before.previewUrl + ' vs ' + after.previewUrl);
    chk('N3c 点勾选框 -> 预览的条目也没变', after.previewId === before.previewId);

    // ---------------- 多选与启用矩阵 ----------------
    rowById(ids0[2]).querySelector('.ci').click();
    await sleep(200);
    chk('N6a 2 条：裁剪转禁用', A().cropDisabled === true);
    chk('N6b 2 条：合并可用', A().mergeDisabled === false);
    chk('N6c 2 条：转写可用且显示条数', A().transcribeDisabled === false &&
      A().transcribeLabel.indexOf('2') >= 0, A().transcribeLabel);

    rowById(ids0[3]).querySelector('.ci').click();
    await sleep(200);
    chk('N6d ≥2 条：裁剪始终禁用', A().cropDisabled === true);

    // ---------------- 全选 ----------------
    P._setChecked([]);
    await sleep(120);
    chk('N7a 清空后全选框未勾选', P.state().selectAll === false);
    $('#chkAll').click();
    await sleep(250);
    var st = P.state();
    chk('N7b ★ 全选 -> 所有条目都选中', st.checked.length === st.items,
      st.checked.length + '/' + st.items);
    chk('N7c 全选后全选框是勾上的', st.selectAll === true);
    chk('N7d 全选后合并可用', A().mergeDisabled === false);
    chk('N7e ★ 全选后裁剪禁用（≥2 条）', A().cropDisabled === true);
    $('#chkAll').click();
    await sleep(250);
    chk('N7f ★ 再点全选 -> 全部取消', P.state().checked.length === 0,
      P.state().checked.length);
    chk('N7g 全不选后三个按钮都禁用', A().cropDisabled && A().mergeDisabled &&
      A().transcribeDisabled);

    // ---------------- 双击改名（规格 14） ----------------
    var firstName = rowById(ids0[0]).querySelector('.nm').textContent;
    rowById(ids0[0]).querySelector('.nm').dispatchEvent(
      new MouseEvent('dblclick', { bubbles: true }));
    await sleep(250);
    chk('N8a 双击视频名 -> 弹出改名框', !!$('#dlgText').open);
    var newName = firstName + '【改名】';
    $('#dlgTextInput').value = newName;
    $('#dlgTextOk').click();
    var renamed = await waitFor(function () {
      return rowById(ids0[0]) &&
        rowById(ids0[0]).querySelector('.nm').textContent === newName;
    }, 3000);
    chk('N8b ★ 改名生效并显示在列表里', renamed,
      rowById(ids0[0]) ? rowById(ids0[0]).querySelector('.nm').textContent : 'gone');

    // ---------------- 裁剪 ----------------
    P._setChecked([ids0[0]]);
    await sleep(150);
    $('#btnCropMode').click();
    await sleep(300);
    chk('C1a 选中 1 条 + 点裁剪 -> 进裁剪模式', P.state().page === 'trim', P.state().page);
    chk('C1b 裁剪页没有合并列表', $('#mergeList').offsetParent === null);
    chk('C1c 裁剪页没有导出按钮', $('#btnExportMerge').offsetParent === null);
    chk('C1d 标题写清了裁的是哪一条', P.state().cropTitle.indexOf('裁剪：') === 0,
      P.state().cropTitle);
    chk('C1e 底部三件套都在', $('#btnSaveClip').offsetParent !== null &&
      $('#btnOverwrite').offsetParent !== null && $('#trimBack').offsetParent !== null);

    var gotDur = await waitFor(function () { return P.state().duration > 0; }, 5000);
    chk('C2a 拿到时长', gotDur, P.state().duration);
    var st2 = P.state();
    chk('C2b 初始区间 = 整条', st2.trim.a === 0 &&
      Math.abs(st2.trim.b - st2.duration) < 0.05, JSON.stringify(st2.trim));

    // 真拖把手 -> 实时 seek
    var tr = $('#trimTrack').getBoundingClientRect();
    var ha = $('#trimA').getBoundingClientRect();
    $('#trimA').dispatchEvent(new MouseEvent('mousedown', {
      bubbles: true, button: 0, clientX: ha.left + 5, clientY: ha.top + 5,
    }));
    window.dispatchEvent(new MouseEvent('mousemove', {
      bubbles: true, clientX: tr.left + tr.width * 0.3, clientY: tr.top + 13,
    }));
    window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    await sleep(300);
    var st3 = P.state();
    var wantA = st2.duration * 0.3;
    chk('C3a 拖 A 把手 -> 起点落到 30%',
      Math.abs(st3.trim.a - wantA) < st2.duration * 0.05,
      st3.trim.a.toFixed(2) + ' vs ' + wantA.toFixed(2));
    chk('C3b ★ 拖动时预览实时 seek 到该帧',
      Math.abs(st3.trimPlayer.currentTime - st3.trim.a) < 0.35,
      st3.trimPlayer.currentTime + ' vs ' + st3.trim.a);

    // A–B 循环（区间 1 秒，采样 2.5 秒 -> 至少两轮回卷）
    P._trim(1.0, 2.0);
    await sleep(150);
    var stR = P.state();
    chk('C4a 区间已同步给播放器', stR.trimPlayer.range &&
      Math.abs(stR.trimPlayer.range.a - 1.0) < 0.01 &&
      Math.abs(stR.trimPlayer.range.b - 2.0) < 0.01, JSON.stringify(stR.trimPlayer.range));
    chk('C4b 播放器处于循环模式', stR.trimPlayer.loop === true);
    $('#trimPlay').click();
    await waitFor(function () { return P.state().trimPlayer.paused === false; }, 2500);
    var samples = await new Promise(function (resolve) {
      var out = [], t0 = Date.now();
      var iv = setInterval(function () {
        var s = P.state().trimPlayer;
        out.push({ ct: s.currentTime, paused: s.paused });
        if (Date.now() - t0 > 2500) { clearInterval(iv); resolve(out); }
      }, 25);
    });
    var maxCt = Math.max.apply(null, samples.map(function (s) { return s.ct; }));
    var minCt = Math.min.apply(null, samples.map(function (s) { return s.ct; }));
    var anyPaused = samples.some(function (s) { return s.paused; });
    var wraps = 0;
    for (var i = 1; i < samples.length; i++) {
      if (samples[i].ct < samples[i - 1].ct - 0.5) wraps++;
    }
    chk('C4c 播放中没有跳出区间上界（<= 2.35）', maxCt <= 2.35, maxCt.toFixed(3));
    chk('C4d 播放中没有跌出区间下界（>= 0.85）', minCt >= 0.85, minCt.toFixed(3));
    chk('C4e 全程没有停下来', anyPaused === false, anyPaused);
    chk('C4f ★ 确实发生了循环回卷（>=1 次）', wraps >= 1, wraps + ' 次；样本 ' + samples.length);

    // 暂停后可以自由拖播放头，不被拉回区间
    $('#trimPlay').click();
    await waitFor(function () { return P.state().trimPlayer.paused === true; }, 2500);
    var sv = $('#trimSeek');
    sv.value = '6';
    sv.dispatchEvent(new Event('input', { bubbles: true }));
    sv.dispatchEvent(new Event('change', { bubbles: true }));
    await sleep(600);
    var stP = P.state();
    chk('C4g ★ 暂停时能拖到区间外且不被拉回',
      Math.abs(stP.trimPlayer.currentTime - 6) < 0.4 && stP.trimPlayer.paused === true,
      stP.trimPlayer.currentTime);

    // 保存为新片段 / 覆盖原视频
    P._trim(1.5, 4.5);
    var beforeN = P.state().items;
    await P._saveClip(false);
    var backTo = await waitFor(function () { return P.state().page === 'list'; }, 4000);
    var st4 = P.state();
    chk('C5a 保存为新片段 -> 列表多一条', st4.items === beforeN + 1, beforeN + ' -> ' + st4.items);
    chk('C5b 新片段带「片段」标签',
      st4.listTags.some(function (t) { return t.indexOf('片段') === 0; }), st4.listTags.join(' | '));
    chk('C5c 保存后自动回常态页', backTo, st4.page);

    var idsC = rowIds();
    P._setChecked([idsC[1]]);
    await sleep(150);
    $('#btnCropMode').click();
    await waitFor(function () { return P.state().duration > 0; }, 5000);
    P._trim(2.0, 5.0);
    var beforeN2 = P.state().items;
    await P._saveClip(true);
    await sleep(400);
    var st5 = P.state();
    chk('C6a 覆盖原视频 -> 条目数不变', st5.items === beforeN2, beforeN2 + ' -> ' + st5.items);
    chk('C6b 出现「待覆盖」标签',
      st5.listTags.some(function (t) { return t.indexOf('待覆盖') === 0; }), st5.listTags.join(' | '));
    $('#trimBack').click();
    await sleep(200);
    chk('C7  点「返回」回常态页', P.state().page === 'list', P.state().page);

    // ---------------- 合并 ----------------
    chk('M0a 从裁剪退出后合并状态为空', P.state().segs.length === 0, P.state().segs.length);
    var idsM = rowIds();
    P._setChecked(idsM.slice(0, 3));
    await sleep(150);
    chk('M0b 勾选 3 条 -> 裁剪禁用', A().cropDisabled === true);
    chk('M0c 勾选 3 条 -> 合并可用', A().mergeDisabled === false);
    $('#btnMergeMode').click();
    var inMerge = await waitFor(function () { return P.state().page === 'merge'; }, 6000);
    chk('M1a 进入合并模式', inMerge, P.state().page);
    var mst = P.state();
    chk('M1b 合并列表 3 段', mst.segs.length === 3, mst.segs.length);
    chk('M1c 每段都有有效区间', mst.segs.every(function (s) { return s.end > s.start; }));
    chk('M1d 合并页没有时间轴', $('#trimTrack').offsetParent === null);
    chk('M1e 合并页没有「覆盖原视频」', $('#btnOverwrite').offsetParent === null);
    chk('M1f 合并页底部是 导出 / 返回',
      $('#btnExportMerge').offsetParent !== null && $('#mergeBack').offsetParent !== null);

    var order0 = mst.segs.map(function (s) { return s.title; });
    var mrows = $$('#mergeList .mrow');
    var h0 = mrows[0].querySelector('.mh').getBoundingClientRect();
    var r1b = mrows[1].getBoundingClientRect();
    mrows[0].querySelector('.mh').dispatchEvent(new MouseEvent('mousedown', {
      bubbles: true, button: 0, clientX: h0.left + 4, clientY: h0.top + 4,
    }));
    window.dispatchEvent(new MouseEvent('mousemove', {
      bubbles: true, clientX: h0.left + 4, clientY: r1b.bottom + 6,
    }));
    window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    await sleep(250);
    var order1 = P.state().segs.map(function (s) { return s.title; });
    chk('M2a 往下拖 -> 顺序真的变了',
      JSON.stringify(order0) !== JSON.stringify(order1), order1.join('>'));
    chk('M2b 只挪一格（与后一行交换）',
      order1[0] === order0[1] && order1[1] === order0[0], order1.join('>'));

    var rowsN = $$('#mergeList .mrow');
    var lastRow = rowsN[rowsN.length - 1];
    var hN = lastRow.querySelector('.mh').getBoundingClientRect();
    var topRow = rowsN[0].getBoundingClientRect();
    lastRow.querySelector('.mh').dispatchEvent(new MouseEvent('mousedown', {
      bubbles: true, button: 0, clientX: hN.left + 4, clientY: hN.top + 4,
    }));
    window.dispatchEvent(new MouseEvent('mousemove', {
      bubbles: true, clientX: hN.left + 4, clientY: topRow.top + 1,
    }));
    window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    await sleep(250);
    var order2 = P.state().segs.map(function (s) { return s.title; });
    chk('M2c 末行拖到最前 -> 整体右移一位',
      order2[0] === order1[2] && order2[1] === order1[0] && order2[2] === order1[1],
      order2.join('>'));

    var firstSeg = P.state().segs[0];
    $('#mergePlay').click();
    var playing = await waitFor(function () {
      var s = P.state().mergePlayer; return s && s.url && s.readyState >= 2 && !s.paused;
    }, 6000);
    var mp = P.state().mergePlayer;
    chk('M3a 点播放键 -> 顺序预览启动', playing, JSON.stringify(mp));
    chk('M3b 播的是列表里的第一段', mp.url === firstSeg.media, mp.url + ' vs ' + firstSeg.media);
    chk('M3c 合并预览不是循环模式', mp.loop === false);
    chk('M3d 顺序播放标记为进行中', P.state().seqActive === true);

    var beforeN3 = P.state().items;
    await P._exportMerge();
    await sleep(400);
    var st6 = P.state();
    chk('M4a 导出后列表多一条', st6.items === beforeN3 + 1, beforeN3 + ' -> ' + st6.items);
    chk('M4b 新条目带「合并 N 段」标签',
      st6.listTags.some(function (t) { return t.indexOf('合并') === 0 && t.indexOf('段') > 0; }),
      st6.listTags.join(' | '));
    $('#mergeBack').click();
    await sleep(200);
    chk('M5a 「返回」回常态页', P.state().page === 'list', P.state().page);
    chk('M5b 退出合并后合并页隐藏', $('#pageProcMerge').classList.contains('hidden'));
    chk('M5c 退出合并后裁剪页也隐藏', $('#pageProcTrim').classList.contains('hidden'));

    // ---------------- 三模式独立 ----------------
    chk('I1a 常态页看不到裁剪时间轴', $('#trimTrack').offsetParent === null);
    chk('I1b 常态页看不到合并列表', $('#mergeList').offsetParent === null);
    chk('I1c 常态页只有列表预览可见',
      $('#listStage').offsetParent !== null && $('#trimStage').offsetParent === null &&
      $('#mergeStage').offsetParent === null);
    var segsBefore = P.state().segs.map(function (s) { return s.title; });
    P._setChecked([rowIds()[0]]);
    await sleep(120);
    $('#btnCropMode').click();
    await sleep(300);
    chk('I2a 进裁剪后常态页与合并页都隐藏',
      $('#pageProcList').classList.contains('hidden') &&
      $('#pageProcMerge').classList.contains('hidden'));
    chk('I2b ★ 进裁剪不改变合并数据',
      JSON.stringify(P.state().segs.map(function (s) { return s.title; })) ===
      JSON.stringify(segsBefore));
    $('#trimBack').click();
    await sleep(200);
    chk('I3a 裁剪退出后回到常态', P.state().page === 'list');
    chk('I3b 常态页选中状态保留', P.state().checked.length === 1, P.state().checked.length);

    // ---------------- 转写 ----------------
    P._setChecked([]);
    await sleep(120);
    chk('T1a 0 条时底部转写禁用', A().transcribeDisabled === true);
    var idsT = rowIds();
    P._setChecked([idsT[0]]);
    await sleep(120);
    chk('T1b 1 条时底部转写可用', A().transcribeDisabled === false);
    var preT = P.state();
    rowById(idsT[0]).querySelector('.tr').click();
    await sleep(400);
    var postT = P.state();
    chk('T1c ★ 行内「转写」不改变选中', postT.checked.length === preT.checked.length);
    chk('T1d ★ 行内「转写」不改变预览', postT.previewId === preT.previewId,
      preT.previewId + ' -> ' + postT.previewId);
    var started = await waitFor(function () {
      var s = P.state().listStatus;
      return s.indexOf('转写') >= 0 || s.indexOf('整理') >= 0;
    }, 3000);
    chk('T1e 转写真的启动了', started, P.state().listStatus);
    await waitFor(function () { return parseFloat(P.state().barWidth) > 0; }, 3000);
    chk('T1f 进度条在走', parseFloat(P.state().barWidth) > 0, P.state().barWidth);

    // 批量转写：选中 2 条点底部按钮
    var idsB = rowIds().slice(0, 2);
    P._setChecked(idsB);
    await sleep(120);
    $('#btnTranscribeSel').click();
    await sleep(500);
    var batchOk = P.state().listStatus.indexOf('提交') >= 0 ||
      P.state().listStatus.indexOf('队列') >= 0;
    chk('T2a ★ 底部「转写」批量入队', batchOk, P.state().listStatus);

    // ---------------- 列表顺序：服务端说啥顺序就画啥顺序 ----------------
    // 顺序本身（最新导入在最上面）在后端判 —— py-state 里断言。
    // 这里只保证前端**不自己重排**。
    var srvIds = P.state().itemIds;
    chk('ORD1 ★ 列表按服务端给的顺序画（前端不重排）',
      JSON.stringify(rowIds()) === JSON.stringify(srvIds),
      JSON.stringify(rowIds().slice(0, 3)) + ' vs ' + JSON.stringify(srvIds.slice(0, 3)));

    // ---------------- 行尾「✕」= 删这一条 ----------------
    var idsD = rowIds();
    var nBeforeD = idsD.length;
    var victim = idsD[0];
    var victimName = rowById(victim).querySelector('.nm').textContent;
    chk('DEL1 ★ 每行都有「✕」删除按钮',
      $$('#procList .proc-item .del').length === nBeforeD,
      $$('#procList .proc-item .del').length + '/' + nBeforeD);
    chk('DEL2 删除按钮在转写按钮右边',
      rowById(victim).lastElementChild.className.indexOf('del') >= 0,
      rowById(victim).lastElementChild.className);

    // ★ 「存在」≠「看得见」。第一版把 ✕ 做成了 10.5px 淡灰
    //   （color: var(--muted)），假数据全绿、用户却说"右边没有删除键"——
    //   一列小灰叉在长列表里扫不见。所以这里不只查"在不在"，还查
    //   **几何**（有没有尺寸、在不在可视区）和**颜色**（必须是危险色，不是淡灰）。
    var delEls = $$('#procList .proc-item .del');
    var listEl = $('#procList');
    var lbR = listEl.getBoundingClientRect();
    var geoBad = delEls.filter(function (d) {
      var b = d.getBoundingClientRect();
      return !(b.width > 8 && b.height > 8 && b.right <= lbR.right + 1
               && b.left >= lbR.left - 1);
    });
    chk('DEL2b ★ 每个 ✕ 都有真实尺寸且完整落在可视区内（没被挤出容器）',
      geoBad.length === 0,
      geoBad.length + ' 个不合格；第一个 ' + JSON.stringify(
        delEls[0].getBoundingClientRect().width) + '；容器 '
        + Math.round(lbR.width) + 'px');

    var danger = getComputedStyle(document.documentElement)
      .getPropertyValue('--danger').trim();
    // --danger 是十六进制字面量（#d64545），computed color 是 rgb(...) ——
    // 两种写法都得能比。（第一版只处理了 rgb()，把自己写挂了。）
    var rgbaToRgb = function (s) {
      s = (s || '').trim();
      var h = s.match(/^#([0-9a-f]{6})$/i);
      if (h) {
        var n = parseInt(h[1], 16);
        return 'rgb(' + ((n >> 16) & 255) + ', ' + ((n >> 8) & 255)
          + ', ' + (n & 255) + ')';
      }
      var m = s.match(/rgba?\(([^)]+)\)/);
      if (!m) return s;
      var p = m[1].split(',').map(function (x) { return x.trim(); });
      return 'rgb(' + p.slice(0, 3).join(', ') + ')';
    };
    var wantDanger = rgbaToRgb(danger);
    var delColor = getComputedStyle(delEls[0]).color;
    var mutedTxt = document.querySelector('.muted');
    var mutedColor = mutedTxt ? getComputedStyle(mutedTxt).color : '';
    chk('DEL2c ★★ ✕ 用的是「危险色」常显（不是那种扫不见的淡灰）',
      delColor === wantDanger,
      '实际 ' + delColor + ' / 应为 ' + wantDanger);
    chk('DEL2d ★★ ✕ 的颜色**不等于** .muted 那个淡灰（第一版就是栽在这）',
      mutedColor === '' || delColor !== mutedColor,
      delColor + ' vs muted ' + mutedColor);

    // ★★ 点 ✕ = **立刻生效，不弹任何确认框**（用户明确要求"直接删了就行"）。
    //    之所以敢不确认：这个动作不删任何东西、而且可逆。
    rowById(victim).querySelector('.del').click();
    await sleep(300);
    chk('DEL3 ★★ 点 ✕ 不弹确认框（点了就生效）', !$('#dlgConfirm').open);
    var goneD = await waitFor(function () { return rowIds().length === nBeforeD - 1; }, 4000);
    chk('DEL4 ★★ 点一下就当场从列表消失（不用等二次确认）',
      goneD && rowIds().indexOf(victim) < 0, rowIds().length + ' vs ' + nBeforeD);
    chk('DEL5 其余条目一条没少', rowIds().length === nBeforeD - 1, rowIds().length);
    chk('DEL6 ★ 少的正是那一条，别的一条没动',
      JSON.stringify(rowIds()) === JSON.stringify(idsD.filter(function (x) {
        return x !== victim; })),
      JSON.stringify(rowIds()) + ' vs ' + JSON.stringify(idsD.filter(function (x) {
        return x !== victim; })));
    chk('DEL7 ★ 状态行给了回执（不是静默消失）',
      P.state().listStatus.indexOf('移除') >= 0 || P.state().listStatus.indexOf('待处理') >= 0,
      P.state().listStatus);
    // 列表里没有别的弹层残留
    chk('DEL7b 点完之后没有任何 dialog 开着',
      !document.querySelector('dialog[open]'));

    // ★★ 出队 **不是删除**：记录必须还在。
    // 怎么在不看内存的情况下证明"记录还在"？再调一次 dequeue ——
    // 记录没了的话，后端会回 reason=item-missing。这比看界面可信。
    var probe = await VKB.call('dequeue_item', victim);
    chk('DEL9 ★★ 出队之后记录仍然存在（不是把条目删了）',
      probe && probe.ok === true, JSON.stringify(probe && probe.reason));
    var again = await VKB.call('dequeue_item', victim);
    chk('DEL9b ★★ 再出队一次仍然 ok（幂等，记录一直在）',
      again && again.ok === true, JSON.stringify(again && again.reason));
    // 反证：编一个不存在的 iid，必须报 item-missing（证明上面那条不是恒真）
    var bogus = await VKB.call('dequeue_item', 'i绝对不存在');
    chk('DEL9c ★★ 反证：不存在的 iid -> item-missing（上面两条才有意义）',
      bogus && bogus.ok === false && bogus.reason === 'item-missing',
      JSON.stringify(bogus && bogus.reason));
    // 放回去，别给后面的用例留下副作用
    await VKB.call('requeue_item', victim);
    await sleep(400);

    // ---------------- 导入进度（规格 4）----------------
    // 系统文件选择框没法自动点，所以直接灌一条假进度，验界面反应
    // 必须**同步**读：轮询每 120ms 会把真实（未导入）的状态灌回来，
    // 一 await 就被覆盖（第一版就在这栽了）
    P.setImportStatus({ active: true, total: 3, done: 1, pct: 0.42,
                        name: '测试视频.mp4', error: null });
    P.updateProgress([]);
    var st9 = P.state();
    var phEl = $('#procList .proc-item.importing');
    chk('T4a ★ 导入进度文字含 文件名 + 分数 + 百分比',
      st9.importText.indexOf('测试视频.mp4') >= 0 && st9.importText.indexOf('1/3') >= 0 &&
      st9.importText.indexOf('42%') >= 0, st9.importText);
    chk('T4b ★ 导入进度条可见', st9.importBarHidden === false, st9.importBarHidden);
    chk('T4c ★ 列表里有「正在导入…」占位行', !!phEl,
      $$('#procList .proc-item.importing').length);
    chk('T4d 占位行里写了进度', !!phEl && phEl.textContent.indexOf('1/3') >= 0,
      phEl ? phEl.textContent : '');

    P.setImportStatus({ active: false, total: 0, done: 0, pct: 0, name: '', error: null });
    P.updateProgress([]);
    chk('T4e 导入结束后进度条收起', P.state().importBarHidden === true);
    chk('T4f 导入结束后占位行消失', $$('#procList .proc-item.importing').length === 0);

    // ---------------- ★★ 「偶发不显示」那个坑的回归守卫 ----------------
    //
    // 症状（用户原话）："某一次导入会失效，再导一个两条一起冒出来。"
    // 根因：轮询回调里 `if (!p.changed) return;` —— 后端**每轮**都把最新数据
    // （导入进度 / 列表 / 摄像头 / 事件）捎回来了，前端却整包丢掉。只要 changed
    // 算错一次（导入比两次轮询还快、文件对话框把 UI 线程堵住让轮询积压），
    // 界面就冻住，直到别的事件把它顶开 —— 积压的东西一起冒出来。
    //
    // 这条**故意做成"源码形状"断言**：那个坑是计时相关的，行为上很难稳定复现。
    // 与其写一条会飘的行为断言，不如直接钉住"那个早退不许回来"。
    var _src = '';
    try {
      _src = await (await fetch('js/app.js')).text();
    } catch (e) { _src = ''; }
    chk('IMP0 取到 app.js 源码（后面三条靠它）', _src.length > 5000, _src.length);

    // 只看**代码行**，不算注释行 —— 第一版这条被我自己写的注释给判挂了
    // （注释里引用了那句旧代码，正则一视同仁地命中了）。
    var codeLines = _src.split('\n').filter(function (ln) {
      return !/^\s*(\/\/|\*|\/\*)/.test(ln);
    });
    var earlyReturn = codeLines.filter(function (ln) {
      return /!\s*p\.changed\s*\)\s*\{?\s*return/.test(ln);
    });
    chk('IMP1 ★★ app.js 的**代码**里不再有「!p.changed 就整包 return」那个早退',
      earlyReturn.length === 0, earlyReturn.join(' | ').slice(0, 90));
    chk('IMP2 ★★ 轻的东西（导入进度 / 每行进度）在 changed 判断**之外**，每轮都灌',
      /if\s*\(p\.changed\)\s*\{[\s\S]*?\}[\s\S]{0,400}setImportStatus\(p\.import\)[\s\S]{0,400}updateProgress\(p\.pending\)/
        .test(_src));
    chk('IMP3 ★ 重活（整表重渲染）仍然只在 changed 时才做（别把性能搞坏）',
      /if\s*\(p\.changed\)\s*\{[\s\S]{0,600}setItems\(App\._pending\)/.test(_src));
    // doImport 在 process_dialog.js 里，不在 app.js —— 第一版拿 app.js 去匹配，
    // 当然匹配不到（测试自己的错，不是代码的错）。
    var _src2 = '';
    try { _src2 = await (await fetch('js/process_dialog.js')).text(); } catch (e) { }
    chk('IMP3b ★ 点导入会**当场**画占位（不等轮询）—— 源码里紧跟着 renderList()',
      /P\.importStatus\s*=\s*\{\s*active:\s*true[\s\S]{0,240}renderList\(\)/.test(_src2),
      _src2.length + ' 字符');

    // ---------------- ★★ 行为面：changed=false 的轮询也必须把数据灌进去 ----------------
    //
    // 这是那个坑**真正的判别实验**：
    //   本地先清干净（不画占位）-> 让轮询带回"导入中"但 changed=false ->
    //   旧代码：`if (!p.changed) return;` 整包丢掉，占位**永远不出现**；
    //   新代码：轻的东西照灌，占位出现。
    //
    // ⚠ 顺序不能反：**先**在真轮询下清干净、断言没有占位，**再**装桩。
    //   反过来装完桩再清，120ms 后桩又会把它画回来，那条前置断言恒假。
    P.setImportStatus({ active: false, total: 0, done: 0, pct: 0, name: '', error: null });
    P.updateProgress([]);
    await sleep(150);
    chk('IMP4a 前置：先清干净（列表里没有占位行）',
      $$('#procList .proc-item.importing').length === 0,
      $$('#procList .proc-item.importing').length);

    var origCall = window.VKB.call;
    window.VKB.call = function (m) {
      if (m === 'pick_videos') {
        return Promise.resolve({ ok: true, started: true, count: 2 });
      }
      if (m === 'poll') {
        // 恒定 changed=false —— 模拟"轮询一次都没撞上 active 那一下"
        return Promise.resolve({
          changed: false, done: [], pending: [],
          import: { active: true, total: 2, done: 1, pct: 0.5,
                    name: '轮询带回来的.mp4', error: null },
          camera: {}, event: null,
        });
      }
      return origCall.apply(window.VKB, arguments);
    };
    await sleep(400);              // 跨过 3 个轮询周期，每一轮都 changed=false
    var phN = $$('#procList .proc-item.importing').length;
    chk('IMP4 ★★ changed=false 的轮询照样把「导入中」画出来（旧代码这里恒为 0）',
      phN === 1, phN);
    chk('IMP5 ★ 而且画的是**轮询带回来的**那份数据（不是本地的残留）',
      ($('#importText').textContent || '').indexOf('轮询带回来的.mp4') >= 0,
      $('#importText').textContent);

    window.VKB.call = origCall;
    P.setImportStatus({ active: false, total: 0, done: 0, pct: 0, name: '', error: null });
    P.updateProgress([]);
    await sleep(150);

    // ---------------- 摄像头：点一下直接调起，**没有中间浮层** ----------------
    // 套件跑在假链路（VKB_FAKE=1）下，open_camera_app 会明确拒绝调起
    // （不能真去开系统应用）。这正好把"失败要说清原因 + 才露降级入口"
    // 验掉。真调起 + 等人录在 _diag/e2e_camera.pyw 里手动跑。
    var bridgeCalls = [];
    var origCall = window.VKB.call;
    window.VKB.call = function (m) {
      bridgeCalls.push(m);
      return origCall.apply(window.VKB, arguments);
    };

    var C = window.VKBCamera;
    chk('T3a ★★ 中间浮层已经删掉了（DOM 里不存在 #camOverlay）',
      !$('#camOverlay') && C.state().overlayExists === false,
      !!$('#camOverlay'));
    chk('T3b ★★ 「取消等待」按钮已经删掉（DOM 里不存在 #camCancel）',
      !$('#camCancel') && C.state().cancelExists === false, !!$('#camCancel'));
    chk('T3b2 ★ 附属控件默认隐藏（只剩 ffmpeg 直录 / 秒数，调起失败才出现）',
      C.state().fallbackVisible === false && C.state().secsVisible === false,
      JSON.stringify(C.state()));

    $('#procCamera').click();
    await sleep(500);
    var cs = C.state();
    chk('T3c ★★ 点摄像头 -> 立刻发出 open_camera_app（没有中间层挡着）',
      bridgeCalls.indexOf('open_camera_app') >= 0, bridgeCalls.slice(-4));
    chk('T3d ★ 摄像头按钮上不再有「未接入」角标',
      ($('#procCamera').getAttribute('data-badge') || '') === '',
      $('#procCamera').getAttribute('data-badge'));
    chk('T3e ★ 调起失败要弹提示说清原因（不静默）',
      !$('#toast').classList.contains('hidden')
      && ($('#toast').textContent || '').indexOf('假链路') >= 0,
      $('#toast').textContent);
    chk('T3f ★ 失败后状态行也写明（底部那条，不只有 toast）',
      ($('#procStatus').textContent || '').indexOf('假链路') >= 0,
      $('#procStatus').textContent);
    chk('T3g ★ 降级入口只在调起失败后才露出来',
      cs.fallbackShown === true && C.state().fallbackVisible === true,
      JSON.stringify(C.state()));
    chk('T3h 降级录制秒数可调（不是写死）',
      $('#camSeconds') && parseInt($('#camSeconds').value, 10) > 0,
      $('#camSeconds') && $('#camSeconds').value);

    // 监视状态灌进来 -> 界面上**不该因此多出任何东西**（后台等待是实现细节）。
    // **必须同步读**：轮询每 120ms 会把真实（假链路下没有监视）的状态灌回来，
    // 一 await 就被覆盖 —— 这个坑在导入进度那条上踩过一次了。
    var statusBefore = $('#procStatus').textContent;
    P.setCameraStatus({ active: true, stage: 'waiting', found: [], photos: 0,
                        pct: 0, note: '等待录制…（相机应用运行中）',
                        dirs: ['D:\\asus\\Pictures\\Camera Roll'] });
    chk('T3i ★★ 监视在跑时界面上不出现任何常驻状态（状态行一字未动）',
      $('#procStatus').textContent === statusBefore
      && !$('#camCancel') && C.state().cancelExists === false,
      $('#procStatus').textContent);
    chk('T3j ★ 监视目录只进状态行的 tooltip（看得见才怪，但排查时能查）',
      ($('#procStatus').title || '').indexOf('Camera Roll') >= 0,
      $('#procStatus').title);
    P.setCameraStatus({ active: false, stage: 'done', found: [], photos: 0,
                        pct: 1, note: '已导入 1 段录制', dirs: [] });
    chk('T3k 监视结束后界面同样干净（没有留下任何痕迹）',
      $('#procStatus').textContent === statusBefore && !$('#camCancel'),
      $('#procStatus').textContent);

    // 导入完成的 event -> 排队弹命名框
    var firstId = (P.state().items && P.state().items.length)
      ? P.state().items[0].id : null;
    P.applyEvent({ seq: 987654, text: '已导入 1 段录制',
                   imported: [{ iid: firstId, mediaName: 'WIN_20260927_10_00_00_Pro.mp4' }] });
    await sleep(350);
    var dlgOpen = !!$('#dlgText') && $('#dlgText').open;
    chk('T3l ★ 录完导入后弹出命名框', dlgOpen === true, dlgOpen);
    if (dlgOpen) {
      $('#dlgTextInput').value = '新名字';
      $('#dlgTextOk').click();
      await sleep(300);
      chk('T3m 命名后框关闭、条目改名被调用',
        !$('#dlgText').open, '对话框还开着');
    } else {
      chk('T3m 命名后框关闭、条目改名被调用', false, '上一条已失败');
    }

    // ---------------- 降级录制必须先二次确认（ffmpeg 会独占麦克风）----------------
    // 假链路下 open_camera_app 会失败 -> 降级按钮已经露出来了 -> 直接在真浏览器里测
    chk('T3n 调起失败后降级按钮可见',
      !$('#camFallback').classList.contains('hidden'));

    $('#camFallback').click();
    await sleep(300);
    var cd = $('#dlgConfirm');
    var cmsg = $('#dlgConfirmMsg').textContent || '';
    chk('T5a ★ 点降级按钮先弹二次确认（不是直接就跑）', cd.open === true, cd.open);
    chk('T5b ★ 文案明确说了会独占麦克风',
      cd.open === true && cmsg.indexOf('麦克风') >= 0, cmsg.slice(0, 90));
    chk('T5c ★ 文案提醒了会影响的正是语音工具',
      cd.open === true && cmsg.indexOf('语音') >= 0, cmsg.slice(0, 90));
    chk('T5d ★ 确认按钮写「继续录制」而不是默认的「删除」',
      $('#dlgConfirmOk').textContent === '继续录制',
      $('#dlgConfirmOk').textContent);

    $('#dlgConfirmCancel').click();
    await sleep(350);
    chk('T5e ★★ 点取消 -> 完全没有调用 dshow（桥调用记录里没有它）',
      bridgeCalls.indexOf('cam_dshow_record') < 0, bridgeCalls);
    chk('T5f 取消后确认框关闭', $('#dlgConfirm').open === false);
    chk('T5g 取消后状态行说明没有占用麦克风',
      ($('#procStatus').textContent || '').indexOf('取消') >= 0,
      $('#procStatus').textContent);
    window.VKB.call = origCall;

    P.close();
  } catch (err) {
    chk('!! ui-panel 抛异常', false, (err && err.message) || String(err));
  }
  window.__RESULTS = R;
  window.__DONE = true;
})();
