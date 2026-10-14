/* 导图。左→右布局：深度决定横向列，兄弟沿纵向排开，
   父节点的纵向位置 = 首末子节点的中点。连线是三次贝塞尔。
   节点是绝对定位的 div，连线在 SVG 里，整体靠 transform 做缩放与平移。 */
(function () {
  'use strict';

  const NODE_MIN_W = 92;
  const H_GAP = 62;      // 列间距
  const V_GAP = 16;      // 同列上下间距
  const MIN_SCALE = 0.3;
  const MAX_SCALE = 2.6;

  // 缩放手感：一格滚轮（deltaY=100）走 5.5%，原先固定 12% 太跳。
  const ZOOM_PER_NOTCH = 1.055;
  // 单次事件允许的最大 deltaY，防某些鼠标一记 300+ 造成巨跳。
  const DELTA_CLAMP = 150;
  // rAF 平滑：每帧把 scale 朝 targetScale 推进 22%。
  const ZOOM_LERP = 0.22;

  const Graph = {
    // 回调，由 app.js 注入
    onSelect: null,
    onReparent: null,
    onToggle: null,
    onContext: null,
    onBlankDblClick: null,

    tree: null,
    selectedId: null,
    scale: 1, panX: 40, panY: 40,
    targetScale: 1,               // 滚轮只改它，rAF 再把 scale 平滑追上去
    _anchorX: 0, _anchorY: 0,     // 缩放锚点（视口坐标）
    _rafId: null,
    _recs: [],            // 当前可见节点（含布局结果）
    _byId: {},

    mount(viewport, canvas, edges, nodes) {
      // 幂等：重复 mount 会让事件监听器注册多份，一次双击触发两次 toggle
      // 互相抵消，表现为"双击没反应"。这类 bug 很隐蔽，所以这里设防。
      if (this._mounted) return;
      this._mounted = true;
      this.elViewport = viewport;
      this.elCanvas = canvas;
      this.elEdges = edges;
      this.elNodes = nodes;
      this._bindViewport();
    },

    // ---------------------------------------------------------------- 渲染
    /** render(forest, ...) —— 收的是**顶层节点的数组**（多根）。
     *  以前收单个根：那是"一个统一根"的年代；现在顶层可以有好几棵树并列。 */
    render(forest) {
      this.tree = forest;
      const list = [];
      (forest || []).forEach(root => this._collect(root, 0, null, list));
      this._recs = list;
      this._byId = {};
      list.forEach(r => { this._byId[r.data.id] = r; });

      // 1) 先建元素（要量真实宽度，必须先入 DOM）
      this.elNodes.innerHTML = '';
      list.forEach(rec => {
        const el = document.createElement('div');
        el.className = 'node'
          + (rec.data.kind === 'topic' ? ' topic' : '')
          + (rec.data.collapsed ? ' collapsed' : '')
          + (rec.data.id === this.selectedId ? ' selected' : '');
        el.textContent = rec.data.name;
        el.dataset.id = rec.data.id;
        rec.el = el;
        this.elNodes.appendChild(el);
      });

      // 2) 量宽度
      list.forEach(rec => {
        rec.w = Math.max(NODE_MIN_W, rec.el.offsetWidth);
        rec.h = rec.el.offsetHeight;
      });

      // 3) 算布局
      this._layout(list);

      // 4) 落位
      let maxX = 0, maxY = 0;
      list.forEach(rec => {
        rec.el.style.setProperty('--x', rec.cx + 'px');
        rec.el.style.setProperty('--y', rec.cy + 'px');
        maxX = Math.max(maxX, rec.cx + rec.w / 2);
        maxY = Math.max(maxY, rec.cy + rec.h / 2);
      });

      // 5) 连线
      this._drawEdges(list, maxX, maxY);
      this._applyTransform();
    },

    _collect(node, depth, parentId, out) {
      out.push({ data: node, depth: depth, parentId: parentId });
      if (!node.collapsed) {
        node.children.forEach(c => this._collect(c, depth + 1, node.id, out));
      }
    },

    _layout(list) {
      const colW = {};
      list.forEach(r => { colW[r.depth] = Math.max(colW[r.depth] || 0, r.w); });
      const colX = {};
      let cur = 0;
      Object.keys(colW).map(Number).sort((a, b) => a - b).forEach(d => {
        colX[d] = cur;
        cur += colW[d] + H_GAP;
      });

      let cursor = 0;
      const place = (rec) => {
        const kids = list.filter(r => r.parentId === rec.data.id);
        if (rec.data.collapsed || kids.length === 0) {
          rec.cy = cursor + rec.h / 2;
          cursor += rec.h + V_GAP;
        } else {
          kids.forEach(place);
          rec.cy = (kids[0].cy + kids[kids.length - 1].cy) / 2;   // 垂直居中于子节点之间
        }
        rec.cx = colX[rec.depth] + rec.w / 2;
      };
      // 多根：每个"没有父节点"的都是顶层，依次从上往下摆。
      // （以前是 place(list[0]) —— 单根年代的写法，只摆一棵树。）
      list.filter(r => r.parentId === null).forEach(place);
    },

    _drawEdges(list, maxX, maxY) {
      const svg = this.elEdges;
      svg.setAttribute('width', Math.ceil(maxX + 300));
      svg.setAttribute('height', Math.ceil(maxY + 300));
      const parts = [];
      list.forEach(rec => {
        if (!rec.parentId) return;
        const p = this._byId[rec.parentId];
        if (!p) return;
        const x1 = p.cx + p.w / 2, y1 = p.cy;
        const x2 = rec.cx - rec.w / 2, y2 = rec.cy;
        const dx = (x2 - x1) * 0.5;
        parts.push(`<path d="M${x1.toFixed(1)},${y1.toFixed(1)} C${(x1 + dx).toFixed(1)},${y1.toFixed(1)} ${(x2 - dx).toFixed(1)},${y2.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}"/>`);
      });
      svg.innerHTML = parts.join('');
    },

    _applyTransform() {
      this.elCanvas.style.transform =
        `translate(${this.panX}px, ${this.panY}px) scale(${this.scale})`;
    },

    // ---------------------------------------------------------------- 缩放动画
    _startZoomAnim() {
      if (this._rafId) return;                 // 已经在跑就只更新目标值
      const step = () => {
        const diff = this.targetScale - this.scale;
        if (Math.abs(diff) < 0.0008) {         // 收敛，停 rAF 不空转
          this._applyScale(this.targetScale);
          this._rafId = null;
          return;
        }
        this._applyScale(this.scale + diff * ZOOM_LERP);
        this._rafId = requestAnimationFrame(step);
      };
      this._rafId = requestAnimationFrame(step);
    },

    _applyScale(ns) {
      if (ns <= 0) return;
      const f = ns / this.scale;
      // 保持锚点下的画布点不动
      this.panX = this._anchorX - (this._anchorX - this.panX) * f;
      this.panY = this._anchorY - (this._anchorY - this.panY) * f;
      this.scale = ns;
      this._applyTransform();
    },

    setSelected(id) {
      this.selectedId = id;
      this.elNodes.querySelectorAll('.node').forEach(el => {
        el.classList.toggle('selected', el.dataset.id === id);
      });
    },

    resetView() {
      if (this._rafId) { cancelAnimationFrame(this._rafId); this._rafId = null; }
      this.scale = 1; this.targetScale = 1; this.panX = 40; this.panY = 40;
      this._applyTransform();
    },

    // ---------------------------------------------------------------- 视口交互
    _bindViewport() {
      const vp = this.elViewport;
      let panning = false, lastX = 0, lastY = 0, moved = false;

      vp.addEventListener('wheel', (e) => {
        e.preventDefault();
        const rect = vp.getBoundingClientRect();
        // 锚点：鼠标当前位置（缩放时让它下面的画布点保持不动）
        this._anchorX = e.clientX - rect.left;
        this._anchorY = e.clientY - rect.top;
        // 按 deltaY 比例算步长，鼠标一格与触控板小步手感一致
        const dy = Math.max(-DELTA_CLAMP, Math.min(DELTA_CLAMP, e.deltaY));
        const next = this.targetScale * Math.pow(ZOOM_PER_NOTCH, -dy / 100);
        this.targetScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, next));
        this._startZoomAnim();
      }, { passive: false });

      vp.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        if (e.target.closest('.node')) return;
        panning = true; moved = false;
        lastX = e.clientX; lastY = e.clientY;
        vp.classList.add('panning');
        this.hideContext();
        e.preventDefault();
      });

      window.addEventListener('mousemove', (e) => {
        if (!panning) return;
        this.panX += e.clientX - lastX;
        this.panY += e.clientY - lastY;
        lastX = e.clientX; lastY = e.clientY;
        moved = true;
        this._applyTransform();
      });

      window.addEventListener('mouseup', () => {
        if (panning) { panning = false; vp.classList.remove('panning'); }
      });

      // 空白双击 -> 新建节点
      vp.addEventListener('dblclick', (e) => {
        if (e.target.closest('.node')) return;
        if (this.onBlankDblClick) this.onBlankDblClick(this.selectedId);
      });

      // 节点上的交互走事件委托
      this.elNodes.addEventListener('mousedown', (e) => {
        const el = e.target.closest('.node');
        if (!el || e.button !== 0) return;
        this._startNodeDrag(el, e);
      });
      this.elNodes.addEventListener('dblclick', (e) => {
        const el = e.target.closest('.node');
        if (!el) return;
        e.stopPropagation();
        if (this.onToggle) this.onToggle(el.dataset.id);
      });
      this.elNodes.addEventListener('contextmenu', (e) => {
        const el = e.target.closest('.node');
        if (!el) return;
        e.preventDefault();
        if (this.onContext) this.onContext(el.dataset.id, e.clientX, e.clientY);
      });
    },

    _startNodeDrag(el, e) {
      const id = el.dataset.id;
      if (this.onSelect) this.onSelect(id);
      const vp = this.elViewport;
      const rect = vp.getBoundingClientRect();
      let dragging = false, targetEl = null;
      const startX = e.clientX, startY = e.clientY;
      el.classList.add('dragging');

      const toCanvas = (cx, cy) => ({
        x: (cx - rect.left - this.panX) / this.scale,
        y: (cy - rect.top - this.panY) / this.scale,
      });

      const onMove = (ev) => {
        if (!dragging && Math.abs(ev.clientX - startX) + Math.abs(ev.clientY - startY) < 4) return;
        dragging = true;
        const p = toCanvas(ev.clientX, ev.clientY);
        el.style.setProperty('--x', p.x + 'px');
        el.style.setProperty('--y', p.y + 'px');

        const under = document.elementFromPoint(ev.clientX, ev.clientY);
        const t = under && under.closest ? under.closest('.node') : null;
        if (targetEl && targetEl !== t) targetEl.classList.remove('drop-target');
        targetEl = null;
        if (t && t !== el) { t.classList.add('drop-target'); targetEl = t; }
      };

      const onUp = () => {
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
        el.classList.remove('dragging');
        if (targetEl) targetEl.classList.remove('drop-target');
        if (dragging) {
          if (targetEl && this.onReparent) this.onReparent(id, targetEl.dataset.id);
          else this.render(this.tree);          // 没落到有效目标上 -> 弹回布局位置
        }
      };

      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
      e.preventDefault();
    },

    hideContext() {
      const m = document.getElementById('ctxMenu');
      if (m) m.classList.add('hidden');
    },

    // ---------------------------------------------------------------- 调试快照
    debug() {
      return {
        scale: this.scale,
        targetScale: this.targetScale,
        panX: this.panX, panY: this.panY,
        count: this._recs.length,
        selectedId: this.selectedId,
        nodes: this._recs.map(r => ({
          id: r.data.id, name: r.data.name, kind: r.data.kind,
          itemId: r.data.itemId || null,       // 内容节点才有；文字/主题为 null
          depth: r.depth, collapsed: !!r.data.collapsed,
          cx: Math.round(r.cx), cy: Math.round(r.cy),
          w: Math.round(r.w), h: Math.round(r.h),
          children: r.data.children.length,
        })),
      };
    },
  };

  window.VKBGraph = Graph;
})();
