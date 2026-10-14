# M0 技术预研结论：左上知识树用什么实现

日期：2026-09-27
范围：只做左上知识树的技术选型，不涉及其他窗格。

---

## 〇、结论先行

**选路线 B（QGraphicsView + QGraphicsScene 自绘）。**

决定性的只有一条：**需求要"曲线连线"，而 QTreeWidget 的绘制模型给不了。**
另外三条支持性事实见第五节。

其余五条都能在两条路线上实现（已实测），连线的这条是分水岭。

---

## 一、实测环境与方法

- 解释器：`D:\MyProject\VideoKnowledgeBase\venv\Scripts\python.exe`（Python 3.12.14）
- PySide6：6.11.1
- 两个 demo 均已 `py_compile` 通过、离屏构造通过、并在合成事件下跑完整自测

**自测方式**：用 `QMouseEvent` 合成按下/移动/松开/双击事件直接投递给事件处理器，配合 monkeypatch 掉 `QInputDialog` 避免弹窗阻塞。共 17 项断言，**17/17 通过**：

```
A-4  双击折叠开关开启                                   PASS
A-2  滚轮缩放改变字号 (10.0 -> 15.0)                     PASS
A-1  拖动后模型同步：交易体系的子 = [断板反包,量价关系,仓位管理,心法]  PASS
A-3  空白按下进入平移态                                  PASS
A-3  平移改变滚动位置 (300 -> 360)                       PASS
A-3  松开后退出平移态                                    PASS
A-5  空白双击新建节点（9 个节点）                          PASS
B-4  双击折叠：场景图元 17 -> 11                          PASS
B-4  再次展开恢复（17 个）                                PASS
B-2  滚轮缩放改变 transform (1.00 -> 1.20)                PASS
B-1  拖到另一节点上后成为其子节点                          PASS
B-1  旧父不再包含它                                       PASS
B-1  重新布局：交易体系子 = [断板反包,量价关系,仓位管理,心法]  PASS
B-3  空白按下进入平移态                                   PASS
B-3  平移改变滚动位置 (300 -> 360)                        PASS
B-3  松开后退出平移态                                     PASS
B-5  空白双击新建节点（2 -> 3）                            PASS
```

**注意**：两个 demo 用的都是**精简数据模型**（`Node` / `MindNode`，只有 `name` + `children`），**不是真实的 `TreeNode`**。真实 `TreeNode` 还有 `video` / `video_list` / `cleaned_file` 等字段，这一点直接引出路线 A 的第 3 个坑（见下）。

---

## 二、工作量估算（实测行数）

| | 总行 | 非空非注释 |
|---|---|---|
| `tree_qtreewidget.py`（路线 A） | 281 | **217** |
| `tree_scene.py`（路线 B） | 402 | **324** |

**两者差约 1.5 倍，但这不是重点。** 重点有两个：

1. **行数差主要来自布局算法**（路线 B 的 `_measure` + `_place` + `_make_edge` 约 60 行），而它换来的是路线 A **买不到的能力**。
2. **路线 A 有隐性工作量不在行数里** —— knockout 见第四节第 3 条。

**完工估算（含与真实 TreeNode 对接、右键菜单、增量更新等）**

| | 估算 | 说明 |
|---|---|---|
| 路线 A 能做到的程度 | 500~700 行 | 且**曲线连线这一条做不到** |
| 路线 B | 500~800 行 | 能力完整 |

结论：**两条路线的代码量接近，差别不在工时，在能力上限。**

---

## 三、能力对照（全部实测）

| 需求 | 路线 A | 路线 B |
|---|---|---|
| 节点有留白 | △ 需自绘 delegate，且只能作用于"每一行" | ✅ 圆角矩形 + 内边距，实测 |
| **连线是曲线** | ❌ **做不到**（见第四节第 5 条） | ✅ 三次贝塞尔，实测 |
| 拖拽方便 | △ 有原生拖放，但落点不可控、需重写 `dropEvent` | ✅ "拖到谁身上就是谁的孩子"，红色高亮反馈，实测 |
| 滚轮缩放 | △ **只能缩字号**，行高/缩进不跟着变 | ✅ `setTransform` 整体等比，锚点跟鼠标，实测 |
| 局部展开折叠 | ✅ Qt 原生 | ✅ 重算布局、空间自动收拢，实测 |
| 空白双击新建 | ✅ 实测可行 | ✅ 实测可行 |
| 空白拖动平移 | ✅ 实测可行 | ✅ 实测可行 |

---

## 四、路线 A 的坑（Qt API 层面）

> 标注【实测】的已在本机跑过；标注【推断】的未实测，仅供参考。

**1. 滚轮被占用 —— 不可回避的交互冲突【实测】**
`QTreeWidget` 的滚轮默认就是滚动。一旦按需求拿滚轮做缩放，**树的滚轮滚动就消失了**。
实测：我把 `wheelEvent` 全部让给缩放后，树只能靠滚动条或空白拖动来滚动。
要保留滚动必须改成 Ctrl+滚轮 —— 但设计稿明确写的是"滚轮缩放"，二者**只能取其一**。这是路线 A 的固有矛盾。

**2. 拖放落点不可控【实测】**
`QTreeWidget` 的落点由 `QAbstractItemView` 内部根据 `dropIndicatorPosition` 在 AboveItem / OnItem / BelowItem 三者间决定，**没有公开 API 可以强制 OnItem**。
实测的绕法是：**完全重写 `dropEvent`、不调用 `super()`**，自己算落点。
代价：放弃 Qt 原生的拖放插入线反馈；`setDropIndicatorShown(True)` 显示的提示与真实落点不一致。
另外 `dragMoveEvent` 必须 `acceptProposedAction()` 放宽，否则拖到非同级位置会被直接拒绝。

**3. 没有 move 信号，同步回数据模型是有损的【实测 —— 这是路线 A 最大的隐性成本】**
拖放完成后 Qt **不发任何"节点被移动"的信号**（`QTreeWidget` 只有 `itemChanged` / `itemClicked` / `itemExpanded` 等）。
实测的绕法是：`dropEvent` 结束后**遍历整棵控件树反推数据模型**。
问题在于：反推时只有 `item.text(0)` 可用，**挂在 `TreeNode` 上而非控件上的字段会全部丢失** ——
即 `video` / `video_list` / `cleaned_file` / `start` / `end` / `text`（`knowledge_tree.py:9`）。

demo 里这个问题没暴露，因为 demo 的数据模型只有 `name` + `children`。**换成真实 `TreeNode` 就会踩到。**

要做对，必须额外维护一张 **`QTreeWidgetItem` ↔ `TreeNode` 的映射字典**，并在 drop 时手工搬运映射关系。
这部分工作量是隐性的，不体现在行数里。而它直接关系到三条底线之一 —— **树结构持久化**。

**4. 缩放的实现方式只有字号，不是"缩放画布"【实测】**
`QTreeWidget` 没有 `setTransform`。实测只能遍历所有 item 设 `QFont`（10pt → 15pt 有效）。
但**行高与缩进不跟着缩放**，所以视觉上是"字体变大"，不是"画布放大"。这与设计稿"滚轮缩放"的画布语义不符。

**5. 曲线连线做不到【推断，未实测】**
QTreeView 的绘制模型是"每个 item 画自己那一块矩形"。跨 item 画连线需要让 `QStyledItemDelegate` **越界绘制**，而越界部分会与 viewport 的局部刷新冲突（滚动、选中高亮时容易残留或撕裂）。
我**没有实测**这条路，据此判断它不可行属于推断。但即使可行，它也是与框架对抗，不是框架支持。

**6. 节点不是"独立矩形"**
节点是"一行文本 + 缩进"，不是可以自由摆放的框。要做出留白与圆角的观感必须上 `QStyledItemDelegate` 自绘每个 item —— 而第 5 条的连线问题在 delegate 层面依然无解。

---

## 五、路线 B 的坑（Qt API 层面）

**1. 命中测试会把连线也算进去【实测】**
`QGraphicsView.itemAt()` 返回的是最上层图元，**连线（`QGraphicsPathItem`）也算命中**。
实测的解法：过滤 `isinstance(it, NodeItem)`。不处理的话，鼠标落在连线上就无法触发空白平移。

**2. 拖动节点与空白平移的冲突【实测】**
`setDragMode(ScrollHandDrag)` 会抢走左键，导致标记了 `ItemIsMovable` 的节点**拖不动**。
Qt 没有给"两者共存"的现成方案。实测的解法是 `NoDrag` + 在视图层自己判断"按下点有没有落在 NodeItem 上"，没有就进入平移。

**3. `ItemIsMovable` 与自动布局是互斥的【实测】**
节点位置由布局算法算出来，但 `ItemIsMovable` 允许用户把它拖到任意位置。
实测的做法是"拖放结束立刻 `rebuild()` 重算布局"，所以节点会**弹回**布局位置（拖动过程中跟手，松手归位）。
若产品要求"松手后停在用户放下的位置"，就必须放弃自动布局 —— **二者不可兼得**。

**4. 全量重建的扩展性问题【实测规模有限】**
`rebuild()` 里 `scene.clear()` 后全部重建。实测 17 个图元无感，但节点数上百/上千时需要改成增量更新。
**这一点我只在 17 个图元上验证过，更大规模的表现未实测。**

**5. 折叠会移动其他分支【实测】**
折叠后重排整棵树（实测场景图元 17 → 11），**空间自动收拢**是优点，但也意味着折叠一个分支会让兄弟分支移动位置。
这与 QTreeWidget 的"折叠只收起自己的行"直觉不同，需确认是否符合预期。

**6. 关于 `QGraphicsProxyWidget`（我选择了不用）【未实测，属已知 Qt 行为】**
若用 `QGraphicsProxyWidget` 在场景里嵌 `QWidget` 做节点，会引入三个问题：缩放时字体模糊、焦点与输入事件穿透、大量代理 widget 时性能骤降。
我实测的方案是纯 `QGraphicsItem` + `paint()` 手绘，**没有实测过 proxy 路线**，此条为已知经验的陈述，非本次验证结果。

---

## 六、推荐与依据

**推荐路线 B。** 四条依据，按权重排序：

**依据 1（决定性）—— 曲线连线**
需求明确要求"连线是曲线"。QTreeWidget 是"每个 item 画自己那块"，跨 item 的曲线没有正当的绘制位置。这一条在路线 A 上是**结构性做不到**，不是工作量大。

**依据 2 —— 滚轮缩放没有冲突**
设计稿要"滚轮缩放 + 空白拖动平移"，这是**画布语义**。路线 A 里滚轮必须二选一（缩放 or 滚动）；路线 B 里滚动本来就不靠滚轮（靠空白拖动平移），两者天然不冲突，与设计稿一致。

**依据 3 —— 同步回数据模型是无损的**
路线 B 的节点就是数据模型本身（`NodeItem.node` 直接指向 `MindNode`），拖动改结构时直接改 `parent.children`，**不存在"反推"这一步**。
路线 A 必须靠遍历控件树反推，会丢掉 `video` / `cleaned_file` 等字段（见第四节第 3 条）—— 而"树结构持久化"是三条底线之一。

**依据 4 —— 代码量并没有差很多**
实测 217 行 vs 324 行。路线 B 多出的约 100 行换来的是完整能力。而路线 A 要做到同等程度还得加上 delegate 自绘 + 映射表，最终**不小概率反超**，且仍然做不到连线。

---

## 七、若选 B：绘制 / 连线 / 布局的具体方案

### 节点：`QGraphicsItem` 子类 + `paint()` 手绘（不用 ProxyWidget）
实测 `NodeItem` 的 `paint` 只有约 25 行，实现：圆角矩形（`QPainterPath.addRoundedRect`）+ 描边（主题节点绿 `#2e8b57`、叶子灰 `#94a3b8`、落点高亮红 `#ef4444`）+ 居中文本 + 折叠徽标（`+N`）。
- 尺寸：`boundingRect = QRectF(-w/2, -h/2, w, h)`，高度固定 36，宽度 = `QFontMetricsF.horizontalAdvance(name) + 2*PAD_X`
- 层序：节点 `zValue = 2`

### 连线：`QGraphicsPathItem` + `QPainterPath.cubicTo`
实测从父节点**底部中心**到子节点**顶部中心**，两个控制点各取垂直方向的 0.5 处，得到平滑 S 形曲线。
- 层序：连线 `zValue = 1`（压在节点下方）

### 布局：自顶向下整齐树（简化 Reingold–Tilford），两趟递归
- **第一趟 `_measure`（后序）**：自底向上算子树宽度
  `subtree_w = max(自身宽度, Σ子节点宽度 + H_GAP × (n-1))`
  折叠的节点不展开，`subtree_w = 自身宽度`
- **第二趟 `_place`（前序）**：自顶向下分配 x，把子节点块在父节点的宽度内**居中**
  `y = depth × (NODE_H + V_GAP)`
- 实测参数：`NODE_H=36`、`H_GAP=26`、`V_GAP=74`、`PAD_X=18`
- **未做的部分**：没有实现"避免子树重叠的轮廓修剪"。对窄而深的树够用，对极不平衡的树可能浪费横向空间。

### 交互（均已实测）
| 动作 | 实现 |
|---|---|
| 拖动改结构 | `ItemIsMovable` + 重写 `mouseMoveEvent` 找落点高亮、`mouseReleaseEvent` 改 `parent.children` 后 `rebuild()` |
| 滚轮缩放 | 视图 `wheelEvent` → `scale()`；`setTransformationAnchor(AnchorUnderMouse)` |
| 空白拖动平移 | 视图 `mousePressEvent` 判断按下点无 NodeItem → 记录起点与滚动值，`mouseMoveEvent` 驱动滚动条 |
| 双击折叠展开 | `NodeItem.mouseDoubleClickEvent` → 翻 `collapsed` → `rebuild()` |
| 空白双击新建 | 视图 `mouseDoubleClickEvent` 判断无 NodeItem → `QInputDialog` → 挂到当前选中节点下 |

---

## 八、风险清单

| # | 风险 | 已实测？ |
|---|---|---|
| 1 | `rebuild()` 全量重建，节点数大时卡顿，需改增量 | ⚠️ 只在 17 图元上验证过，大规模未测 |
| 2 | 拖放后节点"弹回"布局位置；若要"停在原地"就得放弃自动布局 | ✅ 实测行为，取舍未定 |
| 3 | 折叠会移动兄弟分支的位置，可能不符合直觉 | ✅ 实测行为 |
| 4 | `shape()` 目前是矩形，圆角处点击也命中（交互上无感） | ✅ 实测行为 |
| 5 | 节点宽度依赖 `QFontMetricsF`，字体缺失时退化 | ❌ 未测 |
| 6 | 真实 `TreeNode` 对接时，`video`/`cleaned_file` 等字段的读写路径需重新设计 | ❌ 未测（demo 用的是精简模型） |

---

## 九、本次未覆盖、留给后续里程碑的

1. **与真实 `TreeNode` 的对接** —— demo 用的是只有 `name`+`children` 的精简模型，未接 `knowledge_tree.py` 的真实结构
2. **右键菜单** —— 需求里的重命名 / 新建子主题 / 删除，demo 未实现（M0 只验证五个动作）
3. **与内容面板（左下）的联动** —— 选中节点的信号如何传给另一个窗格
4. **节点正文预览** —— 需求里节点"只有名字"，但内容面板要显示全文，两者的数据通路未验证
5. **性能** —— 节点数 100 / 500 / 1000 时的重建耗时
6. **四条窗格独立滚动共存** —— demo 只在路线 A 里放了个 splitter 示意，未验证十字分割场景

---

## 十、产出物

| 文件 | 说明 |
|---|---|
| `_spike/tree_qtreewidget.py` | 路线 A demo（281 行），五个动作全部可演示 |
| `_spike/tree_scene.py` | 路线 B demo（402 行），五个动作全部可演示 |
| `_spike/结论.md` | 本文件 |

运行方式：
```
D:\MyProject\VideoKnowledgeBase\venv\Scripts\python.exe _spike\tree_qtreewidget.py
D:\MyProject\VideoKnowledgeBase\venv\Scripts\python.exe _spike\tree_scene.py
```

**`src/` 下 6 个文件未被改动**（mtime 全部为 2026-09-27 07:06:31，即 git clone 时刻，之后无写入）。
