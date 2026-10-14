/* 只量几何：处理浮层每一行的「✕」到底有没有、在不在看得见的地方。

   背景：用户说"没有删除键"，但服务供的 process_dialog.js 里明明有 deleteRow，
   套件（假数据）里 DEL1「每行都有 ✕」也是 PASS。所以问题只可能在**渲染几何**：
   行太窄（列表只有 232px），✕ 被挤出可视区 / 被裁掉。

   这条探针**必须跑真数据**（VKB_FAKE=0）—— 假数据的标题短、没有 pill，
   真数据的标题长、还有「片段 a–b」的 pill，正是会把行撑爆的那种。

   跑法：
     $env:VKB_FAKE='0'; $env:VKB_TESTS='probe_proc_del.js'; $env:VKB_OUT='probe_proc_del_results.txt'
     pythonw _diag\ui_run.pyw
*/
(async function () {
  var R = [];
  function chk(name, cond, extra) {
    R.push({ name: name, pass: !!cond, extra: extra === undefined ? '' : String(extra) });
    window.__RESULTS = R;
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function $(s) { return document.querySelector(s); }
  function $$(s) { return Array.prototype.slice.call(document.querySelectorAll(s)); }
  function r2(n) { return Math.round(n); }

  try {
    window.VKBProcess.open();
    await sleep(500);

    var list = $('#procList');
    var rows = $$('#procList .proc-item');
    chk('D0 浮层打开且有行', rows.length > 0, rows.length);
    if (!rows.length) { window.__DONE = true; return; }

    var lb = list.getBoundingClientRect();
    chk('D1 列表容器尺寸', true, '宽 ' + r2(lb.width) + 'px（clientWidth '
      + list.clientWidth + '）');

    // ---- 1. 有没有 ----
    var dels = $$('#procList .proc-item .del');
    chk('D2 每行都渲染出了 .del 元素', dels.length === rows.length,
      dels.length + '/' + rows.length + ' 行');

    // ---- 2. 在不在看得见的地方 ----
    var row = rows[0];
    var d0 = row.querySelector('.del');
    chk('D3 ✕ 是行内最后一个子元素',
      row.lastElementChild === d0,
      row.children.length + ' 个子元素，最后一个是 .' + row.lastElementChild.className);
    var db = d0.getBoundingClientRect();
    chk('D4 ✕ 尺寸非零（不是 display:none / 0 宽）',
      db.width > 1 && db.height > 1, r2(db.width) + '×' + r2(db.height));

    // ★★ 核心判据：✕ 的右边缘**没有超出列表可视区**。
    // 列表是 overflow:auto 的 —— 超出去就得横向滚才看得见 = 用户说"没有"。
    chk('D5 ★★ ✕ 完整落在列表可视区内',
      db.right <= lb.right + 1 && db.left >= lb.left - 1,
      '✕ 左' + r2(db.left) + ' 右' + r2(db.right) + ' / 可视区 ' + r2(lb.left)
      + '–' + r2(lb.right));

    // ---- 3. 行有没有被撑爆 ----
    chk('D6 列表没有横向溢出', list.scrollWidth <= list.clientWidth + 1,
      list.scrollWidth + ' vs ' + list.clientWidth);
    var over = rows.filter(function (r) { return r.scrollWidth > r.clientWidth + 1; });
    chk('D7 没有行横向溢出', over.length === 0, over.length + ' 行溢出');

    // ---- 4. 每块占多宽（给报告看）----
    var detail = rows.slice(0, 3).map(function (r) {
      var n = r.querySelector('.nm');
      var p = r.querySelector('.pill');
      var t = r.querySelector('.tr');
      var d = r.querySelector('.del');
      var cb = r.querySelector('.ci');
      return {
        行宽: r2(r.getBoundingClientRect().width),
        勾选框: r2(cb.getBoundingClientRect().width),
        名字: r2(n.getBoundingClientRect().width),
        标签: p ? r2(p.getBoundingClientRect().width) : 0,
        转写: r2(t.getBoundingClientRect().width),
        叉号: r2(d.getBoundingClientRect().width),
        叉号右边缘: r2(d.getBoundingClientRect().right),
        列表右边缘: r2(lb.right),
      };
    });
    chk('D8 前三行的宽度明细', true, JSON.stringify(detail, null, 0));

    // ---- 5. 有没有 pill（真数据才有，假数据没有）----
    chk('D9 这一份数据里带 pill 的行数', true,
      $$('#procList .proc-item .pill').length + ' 行带标签');

    // ---- 6. 名字长度（撑行的元凶）----
    var names = rows.map(function (r) { return r.querySelector('.nm').textContent; });
    chk('D10 最长标题', true, Math.max.apply(null, names.map(function (s) {
      return s.length; })) + ' 字；平均 '
      + r2(names.reduce(function (a, s) { return a + s.length; }, 0) / names.length) + ' 字');

  } catch (e) {
    chk('!! 抛异常', false, (e && e.message) || String(e));
  }
  window.__RESULTS = R;
  window.__DONE = true;
})();
