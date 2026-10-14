/* 只做一件事：把成品 exe 冒烟要点的三个控件的位置量出来。
   窗口尺寸/位置在开发态与 exe 完全一致，所以量一次即可。 */
(async function () {
  var R = [];
  function chk(name, cond, extra) {
    R.push({ name: name, pass: !!cond, extra: extra === undefined ? '' : String(extra) });
    window.__RESULTS = R;
  }
  var P = window.VKBProcess;
  P.open();
  await new Promise(function (r) { setTimeout(r, 600); });

  function rect(sel) {
    var e = document.querySelector(sel);
    if (!e) return null;
    var b = e.getBoundingClientRect();
    return { x: Math.round(b.left + b.width / 2), y: Math.round(b.top + b.height / 2),
             w: Math.round(b.width), h: Math.round(b.height) };
  }
  chk('btnProcess', !!rect('#btnProcess'), JSON.stringify(rect('#btnProcess')));
  chk('rowCheckbox', !!rect('#procList .proc-item .ci'), JSON.stringify(rect('#procList .proc-item .ci')));
  chk('btnCropMode', !!rect('#btnCropMode'), JSON.stringify(rect('#btnCropMode')));
  chk('page', P.state().page === 'list', P.state().page);
  P.close();
  window.__RESULTS = R;
  window.__DONE = true;
})();
