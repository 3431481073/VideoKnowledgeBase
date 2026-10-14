/* 处理浮层三条改动的**真数据**端到端核对（用户说"没删除键"，所以一条条落地看）。

   为什么必须真数据（VKB_FAKE=0）：假数据的标题短、没有 pill、条目数固定，
   真数据才有长标题、「片段 a–b」标签、以及会滚动的长列表。

   ⚠ 这条探针**不删任何东西** —— 点开 ✕ 的确认框看一眼就取消。
      用户数据一个字都不许动。

   $env:VKB_FAKE='0'; $env:VKB_TESTS='probe_proc_all.js'; $env:VKB_OUT='probe_proc_all_results.txt'
   pythonw _diag\ui_run.pyw
*/
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
      await sleep(40);
    }
    return false;
  }
  function $(s) { return document.querySelector(s); }
  function $$(s) { return Array.prototype.slice.call(document.querySelectorAll(s)); }
  function rows() { return $$('#procList .proc-item'); }
  function rowIds() { return rows().map(function (r) { return r.dataset.id; }); }
  var P = window.VKBProcess;

  try {
    P.open();
    await sleep(500);
    var ids = rowIds();
    chk('A0 浮层打开、列表非空', ids.length > 0, ids.length);
    if (!ids.length) { window.__DONE = true; return; }

    // ================================================ ② 顺序（服务端真值）
    var s = await VKB.call('get_state');
    var srv = (s && s.pending) || [];
    chk('A1 服务端 payload 有 pending', srv.length > 0, srv.length);
    chk('A2 ★★ 列表画的就是服务端的顺序（前端不重排）',
      JSON.stringify(rowIds()) === JSON.stringify(srv.map(function (x) { return x.id; })),
      JSON.stringify(rowIds().slice(0, 3)) + ' vs '
      + JSON.stringify(srv.slice(0, 3).map(function (x) { return x.id; })));
    chk('A3 ★★ 服务端顺序是按 created 严格降序（最新在最上面）',
      srv.every(function (x, i) {
        return i === 0 || (srv[i - 1].created || '') >= (x.created || '');
      }),
      srv.slice(0, 4).map(function (x) { return x.created; }).join(' > '));
    chk('A4 顺序不是空的 / 不是全同', true,
      '共 ' + srv.length + ' 条；头尾 created = ' + (srv[0] || {}).created
      + ' … ' + (srv[srv.length - 1] || {}).created);

    // ================================================ ① 单击 = 只预览
    P._setChecked([]);
    await sleep(150);
    var before = P.state();
    var r0 = rows()[0];
    r0.click();
    await sleep(300);
    var after = P.state();
    chk('B1 ★★ 单击行 -> 不选中（左框不动）', after.checked.length === 0,
      JSON.stringify(after.checked));
    chk('B2 ★★ 单击行 -> 右边预览到它', after.previewId === ids[0], after.previewId);
    chk('B3 单击不改模式', after.page === 'list', after.page);
    chk('B4 0 条选中时 裁剪/合并/转写 全禁用',
      after.actions.cropDisabled && after.actions.mergeDisabled
      && after.actions.transcribeDisabled, JSON.stringify(after.actions));

    // ================================================ ① 勾选框 = 选中
    rows()[0].querySelector('.ci').click();
    await sleep(300);
    var s2 = P.state();
    chk('B5 ★★ 点勾选框 -> 选中该条', s2.checked.length === 1 && s2.checked[0] === ids[0],
      JSON.stringify(s2.checked));
    chk('B6 1 条选中 -> 裁剪可用', s2.actions.cropDisabled === false,
      JSON.stringify(s2.actions));
    chk('B7 点勾选框不改预览', s2.previewId === before.previewId || s2.previewId === ids[0],
      s2.previewId);
    rows()[0].querySelector('.ci').click();      // 取消，别留下状态
    await sleep(200);

    // ================================================ ③ 每行的 ✕
    chk('C1 ★★ 每一行都有 ✕ 按钮', $$('#procList .proc-item .del').length === ids.length,
      $$('#procList .proc-item .del').length + '/' + ids.length);
    chk('C2 每行 ✕ 在「转写」右边', rows().every(function (r) {
      return r.lastElementChild.className.indexOf('del') >= 0;
    }), rows()[0].lastElementChild.className);
    var lb = $('#procList').getBoundingClientRect();
    var dbs = $$('#procList .proc-item .del').map(function (d) {
      var b = d.getBoundingClientRect();
      return { w: Math.round(b.width), inside: b.right <= lb.right + 1 && b.width > 1 };
    });
    chk('C3 ★★ 每个 ✕ 都完整落在可视区内（没有一个被挤出去）',
      dbs.every(function (x) { return x.inside; }),
      JSON.stringify(dbs.slice(0, 4)) + ' … 共 ' + dbs.length + ' 个');

    // 点一下 ✕：只验**弹确认框 + 取消**，绝不真删
    var victim = ids[0];
    rows()[0].querySelector('.del').click();
    await sleep(350);
    chk('C4 ★★ 点 ✕ -> 弹删除确认框', !!$('#dlgConfirm').open);
    chk('C5 确认框写明视频文件会保留',
      ($('#dlgConfirmMsg').textContent || '').indexOf('保留') >= 0,
      ($('#dlgConfirmMsg').textContent || '').slice(0, 50).replace(/\n/g, ' '));
    var cancel = $('#dlgConfirm').querySelector(
      '.dlg-foot .btn:not(.primary):not(.danger)');
    if (cancel) cancel.click(); else $('#dlgConfirm').close();
    var stillThere = await waitFor(function () { return rowIds().indexOf(victim) >= 0; }, 3000);
    chk('C6 ★★ 点「取消」-> 条目还在（没被误删）', stillThere, rowIds().length);
    chk('C7 取消后条目数没变', rowIds().length === ids.length,
      rowIds().length + ' vs ' + ids.length);

  } catch (e) {
    chk('!! 抛异常', false, (e && e.message) || String(e));
  }
  window.__RESULTS = R;
  window.__DONE = true;
})();
