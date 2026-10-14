/* pywebview 桥接封装。
   pywebview 注入 window.pywebview.api，并在页面加载后派发 pywebviewready 事件。
   所有 Python 侧方法都返回 Promise。 */
(function () {
  'use strict';

  const VKB = {
    api: null,
    ready: false,

    init(timeoutMs = 10000) {
      if (window.pywebview && window.pywebview.api) {
        this.api = window.pywebview.api;
        this.ready = true;
        return Promise.resolve(true);
      }
      return new Promise((resolve) => {
        let settled = false;
        const done = (ok) => { if (!settled) { settled = true; resolve(ok); } };
        window.addEventListener('pywebviewready', () => {
          this.api = window.pywebview.api;
          this.ready = true;
          done(true);
        }, { once: true });
        setTimeout(() => done(false), timeoutMs);
      });
    },

    call(method, ...args) {
      if (!this.api) return Promise.reject(new Error('bridge not ready'));
      return Promise.resolve(this.api[method](...args));
    },
  };

  window.VKB = VKB;
})();
