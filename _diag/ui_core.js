/* ui-core：布局 / 播放器控制栏 / 音量 / 旋转 / 快捷键 / 右下外观 / 非模态。
   改 UI 文案或元素位置时跑这一套就够（目标 ~4 秒）。 */
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
  function nodeEl(id) { return document.querySelector('#nodes .node[data-id="' + id + '"]'); }
  async function pickNode(id) {
    nodeEl(id).dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0, clientX: 0, clientY: 0 }));
    window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    await sleep(100);
  }
  function same(a, b) {
    if (!a || !b) return false;
    return a.x === b.x && a.w === b.w && a.y === b.y && a.h === b.h;
  }

  try {
    // ---------------- 右下外观 ----------------
    chk('5a  #pageDone 里没有「已完成」标题', $('#pageDone .pane-title') === null);
    chk('5b  整页没有「已完成」这四个字', document.body.innerText.indexOf('已完成') < 0
      || $$('.pane-title').every(function (e) { return e.textContent !== '已完成'; }));

    var tb = $('#doneTabs button');
    var cs = getComputedStyle(tb);
    var head = $('#pageDone .pane-head');
    var hh = head.getBoundingClientRect().height;
    chk('6a  tab 字号 <= 11.5px', parseFloat(cs.fontSize) <= 11.5, cs.fontSize);
    chk('6b  tab 按钮高 <= 22px', tb.getBoundingClientRect().height <= 22,
      tb.getBoundingClientRect().height.toFixed(1));
    chk('6c  头栏高 <= 34px', hh <= 34, hh.toFixed(1));
    chk('6d  列表拿到的高度远大于头栏', $('#doneList').clientHeight > hh * 3,
      $('#doneList').clientHeight + ' vs ' + hh.toFixed(1));

    // ---------------- UI 删减（5-11）----------------
    chk('U1  右上没有「播放器」标题', $$('#panePlayer .pane-title').length === 0);
    chk('U2  右上没有顶部横条', $$('#panePlayer .pane-head').length === 0);
    chk('U3  右上没有提示小字', $('#playerHint') === null);
    chk('U4  左上没有「导图」标题', $$('#paneTree .pane-title').length === 0);
    chk('U5  左上没有顶部横条', $$('#paneTree .pane-head').length === 0);
    chk('U6  左上没有提示文字', $('#paneTree .pane-hint') === null
      && document.querySelector('#paneTree').innerText.indexOf('拖动改结构') < 0);
    chk('U7  左下没有顶部横条', $$('#paneContent .pane-head').length === 0);
    var stageBg = getComputedStyle($('#playerStage')).backgroundColor;
    chk('U8  播放器格没有黑底', stageBg !== 'rgb(16, 22, 29)' && stageBg !== 'rgb(0, 0, 0)', stageBg);
    chk('U9  播放器格里没有常驻文字',
      !$('#playerEmpty') || getComputedStyle($('#playerEmpty')).display === 'none'
      || $('#playerEmpty').textContent.trim() === '',
      $('#playerEmpty') ? $('#playerEmpty').textContent : 'no el');

    // ---------------- 布局 3:2 ----------------
    var r = D.rects();
    chk('7a  上下比 = 3:2', Math.abs(r.tree.h / r.content.h - 1.5) < 0.04,
      (r.tree.h / r.content.h).toFixed(3));
    chk('7b  左右两条横分栏线同一 y', r.divHL.y === r.divHR.y, r.divHL.y + ' vs ' + r.divHR.y);
    chk('7c  横分栏线在上下之间', r.divHL.y > r.tree.y + 10 && r.divHL.y < r.content.y);
    chk('7d  上排两格等高', Math.abs(r.tree.h - r.player.h) <= 1);
    chk('7e  下排两格等高', Math.abs(r.content.h - r.done.h) <= 1);
    chk('7f  上排左宽 : 右宽 = 2:1', Math.abs(r.tree.w / r.player.w - 2) < 0.05,
      (r.tree.w / r.player.w).toFixed(3));
    chk('7g  竖分栏线贯穿全高', r.divV.h >= r.tree.h + r.content.h + 4);
    chk('7h  左列两格 x 相同', r.tree.x === r.content.x);

    // ---------------- 默认暂停 ----------------
    var g = D.graph();
    var cns = g.nodes.filter(function (n) { return n.kind === 'video' && n.itemId; });
    chk('4a  树上有可播的内容节点', cns.length >= 2, cns.length);
    var nodeA = cns[0], nodeB = cns[1];

    await pickNode(nodeA.id);
    var loaded = await waitFor(function () { var s = D.player(); return s.url && s.readyState >= 2; }, 5000);
    chk('4b  点内容节点后视频已就绪', loaded, JSON.stringify(D.player()));
    var ps = D.player();
    chk('4c  默认暂停（没有自动播）', ps.paused === true, ps.paused);
    chk('4d  停在第一帧（currentTime=0）', ps.currentTime < 0.2, ps.currentTime);
    chk('4e  readyState>=2 说明首帧已解码', ps.readyState >= 2, ps.readyState);

    // ---------------- 控制栏定宽 ----------------
    var b0 = D.playerBar();
    var t0 = $('#btnPlay').textContent;
    $('#btnPlay').click();
    await waitFor(function () { return $('#btnPlay').textContent !== t0; }, 2500);
    var b1 = D.playerBar();
    var t1 = $('#btnPlay').textContent;
    $('#btnPlay').click();
    await waitFor(function () { return $('#btnPlay').textContent === t0; }, 2500);
    var b2 = D.playerBar();

    chk('2a  播放键文字确实切了（证明状态真的变过）', t0 !== t1, t0 + ' -> ' + t1);
    chk('2b  暂停->播放：整条控制栏几何不变', same(b0.bar, b1.bar));
    chk('2c  播放->暂停：整条控制栏几何不变', same(b1.bar, b2.bar));
    chk('2d  播放键几何不变', same(b0.play, b1.play) && same(b0.play, b2.play));
    chk('2e  时长标签几何不变', same(b0.time, b1.time) && same(b0.time, b2.time));
    chk('2f  进度轴几何不变', same(b0.seek, b1.seek) && same(b0.seek, b2.seek));
    chk('2g  旋转/音量键几何不变', same(b0.rotate, b2.rotate) && same(b0.mute, b2.mute));

    // ---------------- 音量竖排 ----------------
    $('#btnMute').click();
    await sleep(120);
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
    await sleep(120);
    chk('3g  点外部收起滑块', D.playerBar().volPopHidden === true);
    var volEl = $('#vol');
    volEl.value = '0';
    volEl.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(100);
    chk('3h  音量拖到 0 -> 图标变静音', $('#btnMute').textContent === '🔇', $('#btnMute').textContent);
    volEl.value = '0.8';
    volEl.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(100);
    chk('3i  音量调回 -> 图标恢复', $('#btnMute').textContent === '🔊');

    // ---------------- 旋转 ----------------
    chk('9a  初始角度 0', D.player().rotation === 0, D.player().rotation);
    var stage = $('#playerStage'), vid = $('#playerVideo');
    $('#btnRotate').click(); await sleep(100);
    chk('9b  点一次 -> 90°', D.player().rotation === 90, D.player().rotation);
    chk('9c  元素真的带了 rotate(90deg)', /rotate\(90deg\)/.test(vid.style.transform));
    chk('9d  宽高对调成 舞台高×舞台宽',
      Math.abs(parseFloat(vid.style.width) - stage.clientHeight) < 2 &&
      Math.abs(parseFloat(vid.style.height) - stage.clientWidth) < 2,
      vid.style.width + ' x ' + vid.style.height);
    $('#btnRotate').click(); await sleep(60);
    chk('9e  再点 -> 180°', D.player().rotation === 180);
    $('#btnRotate').click(); await sleep(50);
    $('#btnRotate').click(); await sleep(60);
    chk('9f  转四次回到 0°', D.player().rotation === 0);
    chk('9g  回到 0° 宽高复原', !vid.style.width);
    $('#btnRotate').click(); await sleep(60);
    chk('9h  A 已转到 90°', D.player().rotation === 90);
    await pickNode(nodeB.id);
    await waitFor(function () { var s = D.player(); return s.url && s.readyState >= 2; }, 5000);
    chk('9i  换到另一个视频 -> 角度独立为 0', D.player().rotation === 0);
    await pickNode(nodeA.id);
    await waitFor(function () { return D.player().rotation === 90; }, 3000);
    chk('9j  回到 A -> 恢复记忆的 90°', D.player().rotation === 90);
    $('#btnRotate').click(); await sleep(50);
    $('#btnRotate').click(); await sleep(50);
    $('#btnRotate').click(); await sleep(60);
    chk('9k  角度归零', D.player().rotation === 0);

    // ---------------- 快捷键 ----------------
    P.open();
    await sleep(150);
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
        t.dispatchEvent(new KeyboardEvent('keyup', Object.assign({ bubbles: true }, c[1])));
      });
    });
    await sleep(200);
    var after = {
      page: P.state().page, boot: $('#boot').classList.contains('hidden'),
      settings: D.settingsVisible(), vol: !$('#volPop').classList.contains('hidden'),
      dlg: !!document.querySelector('dialog[open]'),
    };
    chk('1b  8 组快捷键全部无副作用', JSON.stringify(before) === JSON.stringify(after),
      JSON.stringify(before) + ' -> ' + JSON.stringify(after));
    chk('1c  处理浮层仍开着', P.state().open === true);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await sleep(150);
    chk('1d  按 Esc 浮层不关（快捷键已拆）', P.state().open === true);

    // ---------------- 非模态 ----------------
    var op = P.state();
    chk('14a 浮层 overlay 不吃点击', op.overlayPointerEvents === 'none', op.overlayPointerEvents);
    chk('14b 面板本身可点', op.panelPointerEvents === 'auto', op.panelPointerEvents);
    var gr = $('#paneTree').getBoundingClientRect();
    var hit = document.elementFromPoint(gr.left + 40, gr.top + 40);
    chk('14c 浮层外仍命中主界面', !!(hit && hit.closest('#paneTree')));
    P.close();
    await sleep(100);

    // ---------------- 底色 / 遮挡 ----------------
    var fc = D.fitCheck();
    chk('R5  浅色背景', getComputedStyle(document.body).backgroundColor === 'rgb(238, 240, 243)',
      getComputedStyle(document.body).backgroundColor);
    chk('R6  无遮挡（无溢出）', fc.overRight <= 0 && fc.overBottom <= 0 && fc.hOverflow <= 0,
      JSON.stringify(fc));
    chk('R7  启动遮罩已隐藏', fc.bootHidden === true);
    chk('R8  没有媒体错误条', fc.mediaErrorShown === false, fc.mediaErrorText);
  } catch (err) {
    chk('!! ui-core 抛异常', false, (err && err.message) || String(err));
  }
  window.__RESULTS = R;
  window.__DONE = true;
})();
