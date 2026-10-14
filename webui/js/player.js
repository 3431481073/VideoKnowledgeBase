/* 播放器组件。主界面右上与处理浮层的裁剪预览各用一个实例。

   默认**不自动播**：点导图节点只是加载并停在第一帧。不自动播就不需要
   绕 Chromium 的自动播放策略，也就**不强制静音** —— 用户按播放键是
   一次真实交互，带声播放是被允许的。

   旋转按 url 记忆：同一个文件再看回来还是你上次转到的角度，
   竖直的视频不受影响。只改显示，不动文件。
*/
(function () {
  'use strict';

  function fmt(t) {
    if (!isFinite(t) || t < 0) t = 0;
    var m = Math.floor(t / 60), s = Math.floor(t % 60);
    return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
  }

  //: url -> 旋转圈数（0..3）。模块级共享，主播放器和裁剪预览看到同一个角度。
  var URL_ROT = {};

  function make(opts) {
    opts = opts || {};
    var video = opts.video;
    var playBtn = opts.playBtn;
    var seek = opts.seek;
    var timeLabel = opts.timeLabel;
    var volEl = opts.vol;
    var muteBtn = opts.muteBtn;
    var rotateBtn = opts.rotateBtn;
    var emptyEl = opts.empty;
    var stage = opts.stage || (video ? video.parentElement : null);

    var st = {
      url: '',
      range: null,          // {a, b} 区间预览
      loop: false,          // true = 在 [a,b] 内循环，不回调 onRangeEnd
      onRangeEnd: null,     // false = 跑到 b 就停，交给调用方切下一段
      volume: 0.8,
      muted: false,
      rot: 0,
      timer: null,
      _raf: null,
    };

    /* 区间循环用 rAF 判定，不用 timeupdate —— timeupdate 约 4 次/秒，
       用它判到点会冲出区间 250ms 左右，短区间听着就是"跑出去又跳回来"。
       rAF 精度 ~16ms。**只在播放中生效**：暂停时用户要能自由拖播放头
       去挑 A/B，这时不能把他拉回区间里。 */
    function startLoopWatch() {
      if (st._raf) return;
      var step = function () {
        if (video.paused || !st.loop || !st.range) { st._raf = null; return; }
        if (video.currentTime >= st.range.b) video.currentTime = st.range.a;
        st._raf = requestAnimationFrame(step);
      };
      st._raf = requestAnimationFrame(step);
    }
    function stopLoopWatch() {
      if (st._raf) { cancelAnimationFrame(st._raf); st._raf = null; }
    }

    function showEmpty(msg) {
      if (!emptyEl) return;
      emptyEl.textContent = msg;
      emptyEl.classList.remove('hidden');
    }
    function hideEmpty() {
      if (emptyEl) emptyEl.classList.add('hidden');
    }
    function syncIcon() {
      if (playBtn) playBtn.textContent = video.paused ? '▶' : '❚❚';
    }
    function syncTime() {
      if (seek) {
        seek.max = isFinite(video.duration) ? video.duration : 0;
        if (!seek.dataset.dragging) seek.value = video.currentTime || 0;
      }
      if (timeLabel) {
        timeLabel.textContent = fmt(video.currentTime) + ' / ' + fmt(video.duration);
      }
    }

    // ------------------------------------------------------------ 旋转
    /* 90/270 度时把元素设成「舞台高 × 舞台宽」：CSS 旋转不改变布局盒，
       转完之后它的外接矩形正好是「舞台宽 × 舞台高」，恰好铺满舞台。
       180 度不改变外接矩形，宽高保持 100%。 */
    function applyRotation() {
      if (!video || !stage) return 0;
      var ang = ((st.rot % 4) + 4) % 4 * 90;
      video.style.transformOrigin = 'center center';
      video.style.transform = ang ? 'rotate(' + ang + 'deg)' : '';
      if (ang === 90 || ang === 270) {
        video.style.width = stage.clientHeight + 'px';
        video.style.height = stage.clientWidth + 'px';
      } else {
        video.style.width = '';
        video.style.height = '';
      }
      if (rotateBtn) {
        rotateBtn.title = '旋转 90°（当前 ' + ang + '°）';
        rotateBtn.dataset.angle = String(ang);
      }
      return ang;
    }

    function setRotation(k) {
      st.rot = ((k % 4) + 4) % 4;
      if (st.url) URL_ROT[st.url] = st.rot;
      applyRotation();
    }

    // ---------------- 事件 ----------------
    video.addEventListener('loadedmetadata', function () {
      hideEmpty();
      if (!st._wantsPlay) video.currentTime = 0;   // 停在第一帧
      syncTime();
      clearInterval(st.timer);
      st.timer = setInterval(syncTime, 250);
    });
    video.addEventListener('timeupdate', function () {
      syncTime();
      if (!st.range) return;
      if (st.loop) {
        // 兜底：窗口被遮挡时 rAF 会被 Chromium 降频甚至暂停，这条
        // 保证循环照样成立（代价是最多 250ms 过冲）。rAF 仍是主路径。
        //
        // **必须判 paused**：暂停后拖动播放头也会触发 timeupdate，
        // 不判的话会把用户刚拖到的位置强行拉回区间里（实测踩过）。
        if (!video.paused && video.currentTime >= st.range.b) {
          video.currentTime = st.range.a;
        }
        return;
      }
      if (video.currentTime >= st.range.b) {
        video.pause();
        video.currentTime = st.range.a;
        if (st.onRangeEnd) st.onRangeEnd();
      }
    });
    video.addEventListener('play', function () {
      st._wantsPlay = true; syncIcon();
      if (st.loop) startLoopWatch();
    });
    video.addEventListener('pause', function () {
      st._wantsPlay = false; syncIcon(); stopLoopWatch();
    });
    video.addEventListener('ended', function () {
      st._wantsPlay = false; syncIcon(); stopLoopWatch();
    });
    video.addEventListener('error', function () {
      var c = video.error && video.error.code;
      showEmpty('视频加载失败（错误码 ' + c + '）');
    });

    if (playBtn) playBtn.addEventListener('click', function () { toggle(); });
    if (seek) {
      seek.addEventListener('input', function () {
        seek.dataset.dragging = '1';
        if (isFinite(video.duration)) video.currentTime = parseFloat(seek.value) || 0;
      });
      seek.addEventListener('change', function () { delete seek.dataset.dragging; });
    }
    if (volEl) {
      volEl.addEventListener('input', function () { setVolume(parseFloat(volEl.value)); });
    }
    // 音量图标默认不切换静音：规格要求点它是**展开/收起竖向滑块**，
    // 静音由滑块拖到 0 表达（图标会跟着变 🔇）。调用方若要旧行为，
    // 传 muteToggles: true 即可。
    if (muteBtn && opts.muteToggles === true) {
      muteBtn.addEventListener('click', toggleMute);
    }
    if (rotateBtn) {
      rotateBtn.addEventListener('click', function () { setRotation(st.rot + 1); });
    }

    function toggle() {
      if (!video.paused) { video.pause(); return; }
      // 交给调用方接管播放（合并页用它启动"顺序播放"）。
      // **必须在 !st.url 之前问** —— 合并页点播放键时播放器还没加载任何
      // 视频（url 为空），若先判 url 就直接返回了，钩子永远不触发。
      if (opts.beforePlay && opts.beforePlay(api) === false) return;
      if (!st.url) return;
      if (st.range && (video.currentTime < st.range.a || video.currentTime >= st.range.b)) {
        video.currentTime = st.range.a;
      }
      video.muted = st.muted;
      var p = video.play();
      if (p && p.catch) p.catch(function () {});
    }

    function setVolume(v) {
      if (!isFinite(v)) return;
      st.volume = Math.max(0, Math.min(1, v));
      video.volume = st.volume;
      if (volEl) volEl.value = st.volume;
      st.muted = st.volume === 0;
      video.muted = st.muted;
      if (muteBtn) {
        muteBtn.textContent = st.muted ? '🔇' : '🔊';
        muteBtn.classList.toggle('off', st.muted);
      }
    }

    function toggleMute() {
      if (st.muted || st.volume === 0) {
        setVolume(st.volume > 0 ? st.volume : 0.8);
      } else {
        video.muted = true;
        st.muted = true;
        if (muteBtn) {
          muteBtn.textContent = '🔇';
          muteBtn.classList.add('off');
        }
      }
    }

    // ---------------- 对外 ----------------
    var api = {
      /** 加载一个视频。url 为空则显示占位文案。
       *  默认停在第一帧、不自动播（规格：点视频默认暂停）。 */
      load: function (url, o) {
        o = o || {};
        st.range = null;
        st.loop = false;
        stopLoopWatch();
        st.url = url || '';
        st._wantsPlay = false;
        if (!st.url) {
          video.removeAttribute('src');
          video.load();
          showEmpty(o.emptyText || '没有可播放的视频');
          syncIcon();
          syncTime();
          return;
        }
        video.src = st.url;
        video.load();
        setVolume(st.volume);                 // 恢复用户音量与静音状态
        st.rot = URL_ROT[st.url] || 0;        // 这个文件上次转到的角度
        applyRotation();
        if (o.autoplay) {
          // 自动播必须静音（Chromium 策略）；用户按播放键时 toggle() 会恢复音量
          video.muted = true;
          st._wantsPlay = true;
          var p = video.play();
          if (p && p.catch) p.catch(function () {});
        } else {
          video.pause();
        }
        syncIcon();
      },
      clear: function (msg) { api.load('', { emptyText: msg }); },
      toggle: toggle,
      play: function () { if (video.paused) toggle(); },
      pause: function () { if (!video.paused) video.pause(); },
      setVolume: setVolume,
      toggleMute: toggleMute,
      volume: function () { return st.volume; },
      muted: function () { return video.muted; },
      rotate: function () { setRotation(st.rot + 1); },
      setRotation: setRotation,
      rotation: function () { return ((st.rot % 4) + 4) % 4 * 90; },
      /** 设定区间但**不播放**（裁剪页同步把手时用）。
       *  loop=true 时播放会在 [a,b] 内反复，loop=false 时跑到 b 就停并回调。 */
      setRange: function (a, b, loop) {
        st.range = { a: a, b: b };
        st.loop = !!loop;
        if (!st.loop) stopLoopWatch();
      },
      /** 只播 [a,b] 这段。loop=true 用来预览裁剪区间。 */
      playRange: function (a, b, loop) {
        if (!st.url) return;
        api.setRange(a, b, loop);
        video.currentTime = a;
        video.muted = st.muted;
        var p = video.play();
        if (p && p.catch) p.catch(function () {});
      },
      clearRange: function () { st.range = null; st.loop = false; stopLoopWatch(); },
      /** 区间播完时回调（合并预览要接着播下一段）。 */
      setRangeEndHandler: function (fn) { st.onRangeEnd = fn; },
      seekTo: function (t) { if (isFinite(video.duration)) video.currentTime = Math.min(t, video.duration); },
      currentTime: function () { return video.currentTime || 0; },
      duration: function () { return isFinite(video.duration) ? video.duration : 0; },
      hasVideo: function () { return !!st.url; },
      stage: function () { return stage; },
      state: function () {
        return {
          url: st.url,
          readyState: video.readyState,
          paused: video.paused,
          muted: video.muted,
          volume: video.volume,
          rotation: api.rotation(),
          range: st.range ? { a: st.range.a, b: st.range.b } : null,
          loop: st.loop,
          loopWatching: !!st._raf,
          currentTime: Math.round((video.currentTime || 0) * 100) / 100,
          duration: isFinite(video.duration) ? video.duration : 0,
          emptyVisible: emptyEl ? !emptyEl.classList.contains('hidden') : null,
        };
      },
    };
    showEmpty(opts.emptyText || '没有可播放的视频');
    return api;
  }

  window.VKBPlayer = { make: make, fmt: fmt };
})();
