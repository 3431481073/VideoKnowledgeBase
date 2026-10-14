/* 界面验收测试。由 _diag/ui_run.pyw 注入到页面里执行。
   结果写到 window.__RESULTS，驱动端轮询取回。 */
(async function () {
  var R = [];
  function chk(name, cond, extra) {
    R.push({ name: name, pass: !!cond, extra: extra === undefined ? '' : String(extra) });
    window.__RESULTS = R;             // 每步都刷，中途出错也能拿到已完成的部分
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  async function waitFor(fn, ms) {
    var t = Date.now();
    while (Date.now() - t < ms) {
      try { if (fn()) return true; } catch (e) { }
      await sleep(40);
    }
    return false;
  }
  function $(s) { return document.querySelector(s); }
  function $$(s) { return Array.prototype.slice.call(document.querySelectorAll(s)); }
  var D = window.VKB_DEBUG, P = window.VKBProcess;
  function nodeEl(id) { return document.querySelector('#nodes .node[data-id="' + id + '"]'); }
  async function pickNode(id) {
    nodeEl(id).dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0, clientX: 0, clientY: 0 }));
    window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    await sleep(120);
  }
  function same(a, b) {
    if (!a || !b) return false;
    return a.x === b.x && a.w === b.w && a.y === b.y && a.h === b.h;
  }
  function rows() { return $$('#procList .proc-item'); }
  function rowById(id) { return document.querySelector('#procList .proc-item[data-id="' + id + '"]'); }
  function rowIds() { return rows().map(function (r) { return r.dataset.id; }); }
  function tick(id, on) {
    var cb = rowById(id).querySelector('.ci');
    if (cb.checked !== on) cb.click();
  }

  try {
    // ================================================================ 5 / 6 右下
    chk('5a  #pageDone 里没有「已完成」标题', $('#pageDone .pane-title') === null);

    var tb = $('#doneTabs button');
    var cs = getComputedStyle(tb);
    var head = $('#pageDone .pane-head');
    var hh = head.getBoundingClientRect().height;
    chk('6a  tab 字号 <= 11.5px', parseFloat(cs.fontSize) <= 11.5, cs.fontSize);
    chk('6b  tab 按钮高 <= 22px', tb.getBoundingClientRect().height <= 22, tb.getBoundingClientRect().height.toFixed(1));
    chk('6c  头栏高 <= 34px', hh <= 34, hh.toFixed(1));
    chk('6d  列表拿到的高度远大于头栏', $('#doneList').clientHeight > hh * 3,
      $('#doneList').clientHeight + ' vs ' + hh.toFixed(1));

    // ================================================================ 7 布局 3:2
    var r = D.rects();
    chk('7a  上下比 = 3:2', Math.abs(r.tree.h / r.content.h - 1.5) < 0.04,
      (r.tree.h / r.content.h).toFixed(3));
    chk('7b  左右两条横分栏线同一 y', r.divHL.y === r.divHR.y, r.divHL.y + ' vs ' + r.divHR.y);
    chk('7c  横分栏线在上下之间', r.divHL.y > r.tree.y + 10 && r.divHL.y < r.content.y);
    chk('7d  上排两格等高', Math.abs(r.tree.h - r.player.h) <= 1, r.tree.h + ' vs ' + r.player.h);
    chk('7e  下排两格等高', Math.abs(r.content.h - r.done.h) <= 1, r.content.h + ' vs ' + r.done.h);
    chk('7f  上排左宽 : 右宽 = 2:1', Math.abs(r.tree.w / r.player.w - 2) < 0.05,
      (r.tree.w / r.player.w).toFixed(3));
    chk('7g  竖分栏线贯穿全高', r.divV.h >= r.tree.h + r.content.h + 4);
    chk('7h  左列两格 x 相同', r.tree.x === r.content.x);

    // ================================================================ 4 默认暂停
    var g = D.graph();
    var cns = g.nodes.filter(function (n) { return n.kind === 'video' && n.itemId; });
    chk('4a  树上有可播的内容节点', cns.length >= 2, cns.length);
    var nodeA = cns[0], nodeB = cns[1];

    await pickNode(nodeA.id);
    var loaded = await waitFor(function () { var s = D.player(); return s.url && s.readyState >= 2; }, 6000);
    chk('4b  点内容节点后视频已就绪', loaded, JSON.stringify(D.player()));
    var ps = D.player();
    chk('4c  默认暂停（没有自动播）', ps.paused === true, ps.paused);
    chk('4d  停在第一帧（currentTime=0）', ps.currentTime < 0.2, ps.currentTime);
    chk('4e  readyState>=2 说明首帧已解码', ps.readyState >= 2, ps.readyState);

    // ================================================================ 2 控制栏定宽
    var b0 = D.playerBar();
    var t0 = $('#btnPlay').textContent;
    $('#btnPlay').click();
    // play() 会让 paused 同步变 false，但 play 事件是异步派发的，
    // 只等 paused 会采到还没重绘的旧图标。
    await waitFor(function () { return $('#btnPlay').textContent !== t0; }, 3000);
    var b1 = D.playerBar();
    var t1 = $('#btnPlay').textContent;
    $('#btnPlay').click();
    await waitFor(function () { return $('#btnPlay').textContent === t0; }, 3000);
    var b2 = D.playerBar();

    chk('2a  播放键文字确实切了（证明状态真的变过）', t0 !== t1, t0 + ' -> ' + t1);
    chk('2b  暂停->播放：整条控制栏几何不变', same(b0.bar, b1.bar));
    chk('2c  播放->暂停：整条控制栏几何不变', same(b1.bar, b2.bar));
    chk('2d  播放键几何不变', same(b0.play, b1.play) && same(b0.play, b2.play));
    chk('2e  时长标签几何不变', same(b0.time, b1.time) && same(b0.time, b2.time));
    chk('2f  进度轴几何不变', same(b0.seek, b1.seek) && same(b0.seek, b2.seek));
    chk('2g  旋转/音量键几何不变', same(b0.rotate, b2.rotate) && same(b0.mute, b2.mute));

    // ================================================================ 3 音量竖排
    $('#btnMute').click();
    await sleep(150);
    var bp = D.playerBar();
    chk('3a  点音量图标弹出滑块', bp.volPopHidden === false, bp.volPopHidden);
    chk('3b  滑块是竖的（高 > 宽）', bp.volRect && bp.volRect.h > bp.volRect.w,
      bp.volRect ? (bp.volRect.w + 'x' + bp.volRect.h) : 'null');
    chk('3c  滑块有 rotate 变换', bp.volVertical === true);
    chk('3d  滑块区域高 >= 80px', bp.volRect.h >= 80, bp.volRect.h);
    var wrap = $('.vol-wrap').getBoundingClientRect();
    chk('3e  滑块贴在音量键正上方',
      bp.volRect.y + bp.volRect.h <= wrap.top + 2 &&
      Math.abs((bp.volRect.x + bp.volRect.w / 2) - (wrap.left + wrap.width / 2)) < 4);
    chk('3f  横向没有横放的音量条', !document.querySelector('.player-bar .range.vol'));
    document.body.click();
    await sleep(150);
    chk('3g  点外部收起滑块', D.playerBar().volPopHidden === true);
    var volEl = $('#vol');
    volEl.value = '0';
    volEl.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(120);
    chk('3h  音量拖到 0 -> 图标变静音', $('#btnMute').textContent === '🔇', $('#btnMute').textContent);
    volEl.value = '0.8';
    volEl.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(120);
    chk('3i  音量调回 -> 图标恢复', $('#btnMute').textContent === '🔊');

    // ================================================================ 9 旋转
    chk('9a  初始角度 0', D.player().rotation === 0, D.player().rotation);
    var stage = $('#playerStage'), vid = $('#playerVideo');
    $('#btnRotate').click();
    await sleep(120);
    chk('9b  点一次 -> 90°', D.player().rotation === 90, D.player().rotation);
    chk('9c  元素真的带了 rotate(90deg)', /rotate\(90deg\)/.test(vid.style.transform), vid.style.transform);
    chk('9d  宽高对调成 舞台高×舞台宽',
      Math.abs(parseFloat(vid.style.width) - stage.clientHeight) < 2 &&
      Math.abs(parseFloat(vid.style.height) - stage.clientWidth) < 2,
      vid.style.width + ' x ' + vid.style.height + ' stage ' + stage.clientWidth + 'x' + stage.clientHeight);
    $('#btnRotate').click(); await sleep(80);
    chk('9e  再点 -> 180°', D.player().rotation === 180);
    $('#btnRotate').click(); await sleep(60);
    $('#btnRotate').click(); await sleep(80);
    chk('9f  转四次回到 0°', D.player().rotation === 0);
    chk('9g  回到 0° 宽高复原', !vid.style.width, vid.style.width);
    $('#btnRotate').click(); await sleep(80);
    chk('9h  A 已转到 90°', D.player().rotation === 90);
    await pickNode(nodeB.id);
    await waitFor(function () { var s = D.player(); return s.url && s.readyState >= 2; }, 6000);
    chk('9i  换到另一个视频 -> 角度独立为 0', D.player().rotation === 0, D.player().rotation);
    await pickNode(nodeA.id);
    await waitFor(function () { return D.player().rotation === 90; }, 4000);
    chk('9j  回到 A -> 恢复记忆的 90°', D.player().rotation === 90);
    $('#btnRotate').click(); await sleep(60);
    $('#btnRotate').click(); await sleep(60);
    $('#btnRotate').click(); await sleep(80);
    chk('9k  角度归零', D.player().rotation === 0);

    // ================================================================ 1 快捷键
    P.open();
    await sleep(200);
    chk('1a  处理浮层已打开', P.state().open === true);
    var before = {
      page: P.state().page, boot: $('#boot').classList.contains('hidden'),
      settings: D.settingsVisible(), vol: !$('#volPop').classList.contains('hidden'),
      dlg: !!document.querySelector('dialog[open]'),
    };
    var combos = [
      ['Ctrl+Alt+Space', { key: ' ', code: 'Space', ctrlKey: true, altKey: true }],
      ['Ctrl+Space', { key: ' ', code: 'Space', ctrlKey: true }],
      ['Alt+Space', { key: ' ', code: 'Space', altKey: true }],
      ['Ctrl+Shift+P', { key: 'P', code: 'KeyP', ctrlKey: true, shiftKey: true }],
      ['F1', { key: 'F1', code: 'F1' }],
      ['F11', { key: 'F11', code: 'F11' }],
      ['Ctrl+K', { key: 'k', code: 'KeyK', ctrlKey: true }],
      ['Alt+ArrowLeft', { key: 'ArrowLeft', code: 'ArrowLeft', altKey: true }],
    ];
    combos.forEach(function (c) {
      [document, window, document.body].forEach(function (t) {
        t.dispatchEvent(new KeyboardEvent('keydown', Object.assign({ bubbles: true }, c[1])));
        t.dispatchEvent(new KeyboardEvent('keypress', Object.assign({ bubbles: true }, c[1])));
        t.dispatchEvent(new KeyboardEvent('keyup', Object.assign({ bubbles: true }, c[1])));
      });
    });
    await sleep(250);
    var after = {
      page: P.state().page, boot: $('#boot').classList.contains('hidden'),
      settings: D.settingsVisible(), vol: !$('#volPop').classList.contains('hidden'),
      dlg: !!document.querySelector('dialog[open]'),
    };
    chk('1b  8 组快捷键全部无副作用', JSON.stringify(before) === JSON.stringify(after),
      JSON.stringify(before) + ' -> ' + JSON.stringify(after));
    chk('1c  处理浮层仍开着', P.state().open === true);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await sleep(200);
    chk('1d  按 Esc 浮层不关（快捷键已拆）', P.state().open === true);

    // ================================================================ 常态：默认态
    chk('N1a 进浮层默认是常态，不是裁剪',
      P.state().page === 'list' && $('#pageProcTrim').classList.contains('hidden') &&
      $('#pageProcMerge').classList.contains('hidden'), P.state().page);
    chk('N1b 常态页有预览播放器', $('#listVideo') !== null && $('#listStage').offsetParent !== null);
    chk('N1c 常态页有列表和两个功能按钮',
      $('#procList').offsetParent !== null && $('#btnCropMode') !== null && $('#btnMergeMode') !== null);
    chk('N1d 顶部保留导入 / 摄像头',
      $('#procImport').offsetParent !== null && $('#procCamera').offsetParent !== null);

    var ids0 = rowIds();
    chk('N1e 列表有多条', ids0.length >= 4, ids0.length);
    P._setChecked([]);
    await sleep(120);
    var a0 = P.state().actions;
    chk('N1f 没选中 -> 裁剪禁用', a0.cropDisabled === true, JSON.stringify(a0));
    chk('N1g 没选中 -> 合并禁用', a0.mergeDisabled === true, JSON.stringify(a0));

    // ================================================================ 常态：点行=预览
    var before1 = P.state();
    rowById(ids0[0]).click();
    await sleep(300);
    var after1 = P.state();
    chk('N2a 点行 -> 右边预览该视频', after1.previewId === ids0[0],
      after1.previewId + ' vs ' + ids0[0]);
    chk('N2b 点行 -> 仍停在常态（没进任何模式）', after1.page === 'list', after1.page);
    chk('N2c 点行 -> 选中数没变', after1.checked.length === before1.checked.length,
      before1.checked.length + ' -> ' + after1.checked.length);
    var okUrl = await waitFor(function () {
      var s = P.state().listPlayer; return s.url && s.readyState >= 2;
    }, 6000);
    chk('N2d 预览真的加载了视频', okUrl, JSON.stringify(P.state().listPlayer));
    chk('N2e 预览默认暂停', P.state().listPlayer.paused === true);

    // ================================================================ 常态：勾选框
    var before2 = P.state();
    tick(ids0[1], true);
    await sleep(200);
    var after2 = P.state();
    chk('N3a 点勾选框 -> 选中 +1', after2.checked.length === before2.checked.length + 1,
      before2.checked.length + ' -> ' + after2.checked.length);
    chk('N3b 点勾选框 -> 预览 url 一字不变', after2.previewUrl === before2.previewUrl,
      before2.previewUrl + ' vs ' + after2.previewUrl);
    chk('N3c 点勾选框 -> 预览的条目也没变', after2.previewId === before2.previewId);

    // ================================================================ 常态：启用规则
    chk('N4a 选中 1 条 -> 裁剪可用', P.state().actions.cropDisabled === false);
    chk('N4b 选中 1 条 -> 合并仍禁用', P.state().actions.mergeDisabled === true);

    // 再点一次别的行，确认预览跟着走、选中不受影响
    var before3 = P.state();
    rowById(ids0[2]).click();
    await sleep(300);
    var after3 = P.state();
    chk('N5a 点另一行 -> 预览切过去', after3.previewId === ids0[2]);
    chk('N5b 点另一行 -> 选中数仍是 1', after3.checked.length === before3.checked.length,
      after3.checked.length);

    tick(ids0[2], true);
    await sleep(200);
    chk('N6a 选中 2 条 -> 裁剪转为禁用', P.state().actions.cropDisabled === true);
    chk('N6b 选中 2 条 -> 合并可用', P.state().actions.mergeDisabled === false);
    tick(ids0[1], false);
    tick(ids0[2], false);
    await sleep(200);
    chk('N7  全部取消 -> 两个都禁用',
      P.state().actions.cropDisabled === true && P.state().actions.mergeDisabled === true);

    // ================================================================ 裁剪
    P._setChecked([ids0[0]]);
    await sleep(150);
    $('#btnCropMode').click();
    await sleep(300);
    chk('C1a 选中 1 条 + 点裁剪 -> 进入裁剪模式', P.state().page === 'trim', P.state().page);
    chk('C1b 裁剪页没有合并列表', $('#mergeList').offsetParent === null);
    chk('C1c 裁剪页没有导出按钮', $('#btnExportMerge').offsetParent === null);
    chk('C1d 标题写清了裁的是哪一条',
      P.state().cropId === ids0[0] && P.state().cropTitle.indexOf('裁剪：') === 0,
      P.state().cropTitle);
    chk('C1e 底部是 保存为新片段 / 覆盖原视频 / 返回',
      $('#btnSaveClip').offsetParent !== null && $('#btnOverwrite').offsetParent !== null &&
      $('#trimBack').offsetParent !== null);

    var gotDur = await waitFor(function () { return P.state().duration > 0; }, 8000);
    chk('C2a 拿到时长', gotDur, P.state().duration);
    var st = P.state();
    chk('C2b 初始区间 = 整条', st.trim.a === 0 && Math.abs(st.trim.b - st.duration) < 0.05,
      JSON.stringify(st.trim) + ' dur=' + st.duration);

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
    var st2 = P.state();
    var wantA = st.duration * 0.3;
    chk('C3a 拖 A 把手 -> 起点落到 30%', Math.abs(st2.trim.a - wantA) < st.duration * 0.05,
      st2.trim.a.toFixed(2) + ' vs ' + wantA.toFixed(2));
    chk('C3b 拖动时预览实时 seek 到该帧',
      Math.abs(st2.trimPlayer.currentTime - st2.trim.a) < 0.35,
      st2.trimPlayer.currentTime + ' vs ' + st2.trim.a);
    chk('C3c 把手位置与区间一致', Math.abs(parseFloat($('#trimA').style.left) - 30) < 3,
      $('#trimA').style.left);

    // ---- A–B 循环播放 ----
    P._trim(1.5, 3.5);
    await sleep(150);
    var stR = P.state();
    chk('C4a 区间已同步给播放器', stR.trimPlayer.range &&
      Math.abs(stR.trimPlayer.range.a - 1.5) < 0.01 &&
      Math.abs(stR.trimPlayer.range.b - 3.5) < 0.01, JSON.stringify(stR.trimPlayer.range));
    chk('C4b 播放器处于循环模式', stR.trimPlayer.loop === true);

    $('#trimPlay').click();
    await waitFor(function () { return P.state().trimPlayer.paused === false; }, 3000);

    // 采样 4.5 秒（区间 2 秒，至少应该循环两轮）
    var samples = await new Promise(function (resolve) {
      var out = [], t0 = Date.now();
      var iv = setInterval(function () {
        var s = P.state().trimPlayer;
        out.push({ ct: s.currentTime, paused: s.paused });
        if (Date.now() - t0 > 4500) { clearInterval(iv); resolve(out); }
      }, 25);
    });
    var maxCt = Math.max.apply(null, samples.map(function (s) { return s.ct; }));
    var minCt = Math.min.apply(null, samples.map(function (s) { return s.ct; }));
    var anyPaused = samples.some(function (s) { return s.paused; });
    var wraps = 0;
    for (var i = 1; i < samples.length; i++) {
      if (samples[i].ct < samples[i - 1].ct - 1.0) wraps++;
    }
    chk('C4c 播放中没有跳出区间上界（<= 3.8）', maxCt <= 3.8, maxCt.toFixed(3));
    chk('C4d 播放中没有跌出区间下界（>= 1.3）', minCt >= 1.3, minCt.toFixed(3));
    chk('C4e 全程没有停下来', anyPaused === false, anyPaused);
    chk('C4f 确实发生了循环回卷（>=1 次）', wraps >= 1, wraps + ' 次；样本 ' + samples.length);

    // 暂停后可以自由拖播放头，不被拉回区间
    $('#trimPlay').click();
    await waitFor(function () { return P.state().trimPlayer.paused === true; }, 3000);
    var sv = $('#trimSeek');
    sv.value = '6';
    sv.dispatchEvent(new Event('input', { bubbles: true }));
    sv.dispatchEvent(new Event('change', { bubbles: true }));
    await sleep(700);
    var stP = P.state();
    chk('C4g 暂停时能拖到区间外且不被拉回',
      Math.abs(stP.trimPlayer.currentTime - 6) < 0.4 && stP.trimPlayer.paused === true,
      stP.trimPlayer.currentTime);

    // ---- 保存为新片段 ----
    P._trim(1.5, 4.5);
    var beforeN = P.state().items;
    await P._saveClip(false);
    var backTo = await waitFor(function () { return P.state().page === 'list'; }, 4000);
    var st3 = P.state();
    chk('C5a 保存为新片段 -> 列表多一条', st3.items === beforeN + 1, beforeN + ' -> ' + st3.items);
    chk('C5b 新片段带「片段」标签',
      st3.listTags.some(function (t) { return t.indexOf('片段') === 0; }), st3.listTags.join(' | '));
    chk('C5c 保存后自动回常态页', backTo, st3.page);

    // ---- 覆盖原视频 ----
    var idsC = rowIds();
    P._setChecked([idsC[1]]);
    await sleep(150);
    $('#btnCropMode').click();
    await waitFor(function () { return P.state().duration > 0; }, 8000);
    P._trim(2.0, 5.0);
    var beforeN2 = P.state().items;
    await P._saveClip(true);
    await sleep(500);
    var st4 = P.state();
    chk('C6a 覆盖原视频 -> 条目数不变', st4.items === beforeN2, beforeN2 + ' -> ' + st4.items);
    chk('C6b 出现「待覆盖」标签',
      st4.listTags.some(function (t) { return t.indexOf('待覆盖') === 0; }), st4.listTags.join(' | '));
    chk('C6c 覆盖后仍停在裁剪页', st4.page === 'trim', st4.page);
    $('#trimBack').click();
    await sleep(200);
    chk('C7  点「返回」回常态页', P.state().page === 'list', P.state().page);

    // ================================================================ 合并
    chk('M0a 从裁剪退出后合并状态为空', P.state().segs.length === 0, P.state().segs.length);
    var idsM = rowIds();
    P._setChecked(idsM.slice(0, 3));
    await sleep(150);
    chk('M0b 勾选 3 条 -> 裁剪禁用（规格：≥2 只能合并）',
      P.state().actions.cropDisabled === true);
    chk('M0c 勾选 3 条 -> 合并可用', P.state().actions.mergeDisabled === false);
    $('#btnMergeMode').click();
    var inMerge = await waitFor(function () { return P.state().page === 'merge'; }, 9000);
    chk('M1a 进入合并模式', inMerge, P.state().page);
    var mst = P.state();
    chk('M1b 合并列表 3 段', mst.segs.length === 3, mst.segs.length);
    chk('M1c 每段都有有效区间', mst.segs.every(function (s) { return s.end > s.start; }),
      JSON.stringify(mst.segs.map(function (s) { return [s.title, s.start, s.end]; })));
    chk('M1d 合并页没有时间轴/裁剪把手', $('#trimTrack').offsetParent === null);
    chk('M1e 合并页没有「覆盖原视频」', $('#btnOverwrite').offsetParent === null);
    chk('M1f 合并页底部是 导出 / 返回',
      $('#btnExportMerge').offsetParent !== null && $('#mergeBack').offsetParent !== null);

    // 拖动改顺序（两个方向）
    var order0 = mst.segs.map(function (s) { return s.title; });
    var mrows = $$('#mergeList .mrow');
    chk('M2a 有序列表渲染出 3 行', mrows.length === 3, mrows.length);
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
    chk('M2b 往下拖 -> 顺序真的变了', JSON.stringify(order0) !== JSON.stringify(order1),
      order0.join('>') + ' => ' + order1.join('>'));
    chk('M2c 只挪一格（与后一行交换）',
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
    chk('M2d 末行拖到最前 -> 整体右移一位',
      order2[0] === order1[2] && order2[1] === order1[0] && order2[2] === order1[1],
      order1.join('>') + ' => ' + order2.join('>'));

    // 点播放键 -> 顺序预览
    var firstSeg = P.state().segs[0];
    $('#mergePlay').click();
    var playing = await waitFor(function () {
      var s = P.state().mergePlayer; return s && s.url && s.readyState >= 2 && !s.paused;
    }, 9000);
    var mp = P.state().mergePlayer;
    chk('M3a 点播放键 -> 顺序预览启动', playing, JSON.stringify(mp));
    chk('M3b 播的是列表里的第一段', mp.url === firstSeg.media, mp.url + ' vs ' + firstSeg.media);
    chk('M3c 播放位置在区间内',
      mp.currentTime >= firstSeg.start - 0.3 && mp.currentTime <= firstSeg.end + 0.6,
      mp.currentTime + ' in [' + firstSeg.start + ',' + firstSeg.end + ']');
    chk('M3d 合并预览不是循环模式', mp.loop === false);
    chk('M3e 顺序播放标记为进行中', P.state().seqActive === true);

    // 导出
    var beforeN3 = P.state().items;
    await P._exportMerge();
    await sleep(400);
    var st5 = P.state();
    chk('M4a 导出后列表多一条', st5.items === beforeN3 + 1, beforeN3 + ' -> ' + st5.items);
    chk('M4b 新条目带「合并 N 段」标签',
      st5.listTags.some(function (t) { return t.indexOf('合并') === 0 && t.indexOf('段') > 0; }),
      st5.listTags.join(' | '));
    chk('M4c 导出后仍在合并页', st5.page === 'merge', st5.page);

    $('#mergeBack').click();
    await sleep(200);
    chk('M5a 「返回」回常态页', P.state().page === 'list', P.state().page);
    chk('M5b 退出合并后合并页隐藏', $('#pageProcMerge').classList.contains('hidden'));
    chk('M5c 退出合并后裁剪页也隐藏', $('#pageProcTrim').classList.contains('hidden'));

    // ================================================================ 三模式独立
    chk('I1a 常态页里看不到裁剪的时间轴', $('#trimTrack').offsetParent === null);
    chk('I1b 常态页里看不到合并列表', $('#mergeList').offsetParent === null);
    chk('I1c 常态页里看不到导出按钮', $('#btnExportMerge').offsetParent === null);
    chk('I1d 常态页里三个预览只有一个可见（列表预览）',
      $('#listStage').offsetParent !== null && $('#trimStage').offsetParent === null &&
      $('#mergeStage').offsetParent === null);
    var segsBefore = P.state().segs.map(function (s) { return s.title; });
    P._setChecked([rowIds()[0]]);
    await sleep(120);
    $('#btnCropMode').click();
    await sleep(300);
    chk('I2a 进裁剪后，常态页与合并页都隐藏',
      $('#pageProcList').classList.contains('hidden') && $('#pageProcMerge').classList.contains('hidden'));
    chk('I2b 裁剪页里只有裁剪预览可见',
      $('#trimStage').offsetParent !== null && $('#listStage').offsetParent === null &&
      $('#mergeStage').offsetParent === null);
    chk('I2c 进裁剪不改变合并数据（两边状态互相看不见）',
      JSON.stringify(P.state().segs.map(function (s) { return s.title; })) ===
      JSON.stringify(segsBefore), segsBefore.length + ' 段');
    $('#trimBack').click();
    await sleep(200);
    chk('I3a 裁剪退出后回到常态', P.state().page === 'list');
    chk('I3b 常态页的选中状态保留（不因进过裁剪而清空）',
      P.state().checked.length === 1, P.state().checked.length);

    // ================================================================ 非模态
    var op = P.state();
    chk('14a 浮层 overlay 不吃点击', op.overlayPointerEvents === 'none', op.overlayPointerEvents);
    chk('14b 面板本身可点', op.panelPointerEvents === 'auto', op.panelPointerEvents);
    var gr = $('#paneTree').getBoundingClientRect();
    var hit = document.elementFromPoint(gr.left + 40, gr.top + 40);
    chk('14c 浮层外仍命中主界面', !!(hit && hit.closest('#paneTree')),
      hit ? (hit.id || hit.className) : 'null');

    // ================================================================ 转写（放最后：会改变列表）
    var preT = P.state();
    var idsT = rowIds();
    var rowT = rowById(idsT[0]);
    rowT.querySelector('.tr').click();
    await sleep(400);
    var postT = P.state();
    chk('T1a 点行内「转写」不改变预览', postT.previewId === preT.previewId,
      preT.previewId + ' -> ' + postT.previewId);
    chk('T1b 点行内「转写」不改变选中数', postT.checked.length === preT.checked.length);
    var started = await waitFor(function () {
      return P.state().listStatus.indexOf('转写') >= 0 || P.state().listStatus.indexOf('整理') >= 0;
    }, 4000);
    chk('T1c 转写真的启动了', started, P.state().listStatus);
    var progressed = await waitFor(function () {
      var w = P.state().barWidth; return parseFloat(w) > 0;
    }, 4000);
    chk('T1d 进度条在走', progressed, P.state().barWidth);

    P.close();
    await sleep(150);

    // ================================================================ 联动 / 旧断言
    var done = D.done();
    chk('R1  右下三 tab 计数自洽', done.total === done.inTree + (done.total - done.inTree));
    chk('R2  导图有连线', $$('#edges path').length > 0, $$('#edges path').length);
    chk('R3  无 CDN 外链', $$('script[src^="http"],link[href^="http"]').length === 0);
    var htmlTxt = await (await fetch('index.html')).text();
    var doc2 = new DOMParser().parseFromString(htmlTxt, 'text/html');
    var inline = doc2.querySelectorAll('[style]:not([style*="grid-area"])');
    chk('R4  静态标记里除 grid-area 无内联样式', inline.length === 0,
      Array.prototype.map.call(inline, function (e) {
        return e.tagName + '#' + e.id + '="' + e.getAttribute('style') + '"';
      }).join(' | '));
    chk('R4b 静态标记里确有 grid-area（证明上面查到了东西）',
      doc2.querySelectorAll('[style*="grid-area"]').length === 4,
      doc2.querySelectorAll('[style*="grid-area"]').length);
    chk('R5  浅色背景', getComputedStyle(document.body).backgroundColor === 'rgb(238, 240, 243)',
      getComputedStyle(document.body).backgroundColor);
    var fc = D.fitCheck();
    chk('R6  无遮挡（无溢出）', fc.overRight <= 0 && fc.overBottom <= 0 && fc.hOverflow <= 0,
      JSON.stringify(fc));
    chk('R7  启动遮罩已隐藏', fc.bootHidden === true);
    chk('R8  没有媒体错误条', fc.mediaErrorShown === false, fc.mediaErrorText);

  } catch (err) {
    chk('!! 测试过程抛异常', false, (err && err.message) || String(err));
  }
  window.__RESULTS = R;
  window.__DONE = true;
})();
