/* 摄像头：点一下**直接**调起系统相机应用。

   没有中间浮层（用户要求：点了就弹相机，越快越好）。这里的职责缩到三件：
     1. 点按钮 -> 调桥 open_camera_app
     2. 把结果显示出来（toast + 状态行走 process_dialog 那边）
     3. 录完导入的条目挨个弹命名框

   浮层删掉顺带修掉一个 bug：原来 open() 里有个 `if (!C.launched)` 闩锁，
   第一次成功后置 true 且只在取消时复位 —— 于是"关掉相机再点"就再也不发
   请求了。现在每次点都真发。

   附属控件（取消等待 / ffmpeg 直录 / 秒数）平时隐藏，由 applyStatus 按
   监视状态决定露不露。
*/
(function () {
  'use strict';

  var $ = function (s) { return document.querySelector(s); };

  var C = {
    nameQueue: [],        // 导入完待命名的条目 [{iid, mediaName}]
    naming: false,
    busy: false,          // 防连点：一次请求在途时不重复发
    fallbackShown: false,
  };

  function toast(m) {
    if (window.VKBApp && window.VKBApp.toast) window.VKBApp.toast(m);
  }

  function show(el, on) {
    var e = $(el);
    if (e) e.classList.toggle('hidden', !on);
  }

  // ------------------------------------------------------------------ 开
  function open() {
    if (C.busy) return;
    C.busy = true;
    VKB.call('open_camera_app').then(function (r) {
      C.busy = false;
      var cam = (r && r.camera) || {};
      if (r && r.ok) {
        // 成功：一句话提示，然后什么都不做（相机窗口已经在前台了）
        if (cam.frontOk === false) {
          toast('相机应用在后台，请点任务栏上的「相机」窗口');
        } else {
          toast('已打开系统相机应用 · 录完关掉它就会自动导入');
        }
        return;
      }
      // 失败：说清原因，并把降级入口露出来
      var why = cam.error || (r && r.error) || '调不起系统相机应用';
      toast('打不开系统相机：' + why);
      showFallback(why);
    }).catch(function (e) {
      C.busy = false;
      toast('调起异常：' + e.message);
      showFallback(e.message);
    });
  }

  /** 只有"调起失败"才露降级入口 —— 触发条件写死，不默认启用。
      **失败是异常事件，该说清楚；等待录制是常态，一个字都不显示。** */
  function showFallback(why) {
    C.fallbackShown = true;
    show('#camFallback', true);
    show('#camSeconds', true);
    if (window.VKBProcess && window.VKBProcess.status) {
      window.VKBProcess.status('调不起系统相机：' + why
                               + ' —— 可点「ffmpeg 直录」（会独占麦克风）');
    }
  }

  /** 降级录制。**必须先二次确认** —— ffmpeg 会独占麦克风，
      用户机器上可能挂着语音识别工具（语音悬浮球/讯飞听见），
      不打招呼就抢会让那些工具这段时间录不到声音。 */
  function fallbackRecord() {
    var secs = 10;
    var el = $('#camSeconds');
    if (el) {
      var v = parseInt(el.value, 10);
      if (v > 0) secs = Math.min(600, v);
    }
    var go = (window.VKBApp && window.VKBApp.askConfirm)
      ? window.VKBApp.askConfirm(
          '改用 ffmpeg 直接录',
          'ffmpeg 会**独占麦克风**，这段时间里你的语音工具'
          + '（比如语音悬浮球、讯飞听见）可能录不到声音。\n\n'
          + '要录 ' + secs + ' 秒，录制期间也没有画面可看。确定继续吗？',
          '继续录制', false)
      : Promise.resolve(false);
    go.then(function (yes) {
      if (!yes) {
        if (window.VKBProcess && window.VKBProcess.status) {
          window.VKBProcess.status('已取消（没有占用麦克风）');
        }
        return;
      }
      toast('正在用 ffmpeg 录制 ' + secs + ' 秒（没有画面可看）…');
      VKB.call('cam_dshow_record', secs).then(function (r) {
        if (!r || !r.ok) {
          toast('降级录制失败：' + ((r && r.error) || '未知'));
          return;
        }
        toast('已录制并加入列表');
        if (r.iid) queueNames([{ iid: r.iid, mediaName: r.mediaName }]);
      }).catch(function (e) { toast('降级录制异常：' + e.message); });
    });
  }

  // ------------------------------------------------------------------ 状态
  /** 由 app.js 的轮询灌进来（state.camera）。

      **这里刻意什么都不显示。** 后台在等录制文件这件事属于实现细节：
      录到了就导入并弹命名框，没录到就什么都不发生。界面上不出现任何
      "等待中/监视中"的常驻状态。唯一会说话的时机是**出错**（调起失败）。 */
  function applyStatus(cam) {
    if (!cam) return;
    if (cam.dirs && cam.dirs.length && window.VKBProcess) {
      window.VKBProcess.setCameraDirs(cam.dirs);   // 只进 tooltip，看不见
    }
    if (cam.error && cam.stage === 'error') {
      toast('摄像头：' + cam.error);
    }
    // 降级入口露过一次就一直露着（用户可能想再试），除非重启程序
    if (C.fallbackShown) {
      show('#camFallback', true);
      show('#camSeconds', true);
    }
  }

  // ------------------------------------------------------------------ 命名
  /** 导入完的条目挨个弹命名框。**取消命名不会丢条目** —— 条目早就进列表了，
      只是顶着相机给的原名，随时能双击改名。 */
  function queueNames(list) {
    C.nameQueue = C.nameQueue.concat(list || []);
    pumpNames();
  }

  function pumpNames() {
    if (C.naming || !C.nameQueue.length) return;
    var item = C.nameQueue.shift();
    C.naming = true;
    var ask = (window.VKBApp && window.VKBApp.askText)
      ? window.VKBApp.askText('保存录制视频', '视频名称',
                              (item.mediaName || '').replace(/\.[^.]+$/, ''))
      : Promise.resolve(null);
    ask.then(function (name) {
      C.naming = false;
      if (name) {
        VKB.call('rename_item', item.iid, name).then(function (r) {
          if (r && r.state && window.VKBApp) window.VKBApp.applyState(r.state);
          toast('已改名：' + name);
          pumpNames();
        });
      } else {
        pumpNames();          // 取消也要继续问下一个，不能卡住队列
      }
    });
  }

  /** 后台事件（导入完成）—— 由 process_dialog 的 applyEvent 转过来 */
  function applyEvent(ev) {
    if (ev && ev.imported && ev.imported.length) {
      queueNames(ev.imported);
    }
  }

  // ------------------------------------------------------------------ 初始化
  function init() {
    $('#camFallback').addEventListener('click', fallbackRecord);
  }

  window.VKBCamera = {
    init: init, open: open,
    applyStatus: applyStatus, applyEvent: applyEvent,
    state: function () {
      return {
        busy: C.busy,
        fallbackShown: C.fallbackShown,
        // 「取消等待」已删 —— 这个字段留着是给测试断言"它不存在"
        cancelExists: !!$('#camCancel'),
        fallbackVisible: $('#camFallback')
          ? !$('#camFallback').classList.contains('hidden') : false,
        secsVisible: $('#camSeconds')
          ? !$('#camSeconds').classList.contains('hidden') : false,
        // 浮层已经删了 —— 这个字段留着是给测试断言"它不存在"
        overlayExists: !!$('#camOverlay'),
        nameQueue: C.nameQueue.slice(),
        naming: C.naming,
      };
    },
    _queueNames: queueNames,
  };
})();
