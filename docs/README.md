# VideoKnowledgeBase（视频知识库）

> ## 🔴 先说一件最要紧的事
>
> **这个项目里有一个个人视频知识库** —— 用户"关于自己人生的反思"录像，**13 个文件、4.63 GB**。
>
> **它没有任何备份。**
>
> - `.gitignore` 第 2 行就是 `data/` → **不在版本控制里**
> - `data/backups/` 里有 4 个"自动备份"zip，**但只有 22~245 字节**（等于空的）
> - 项目外没有
>
> **→ 详见 [data.md](data.md) 第三节。把录像复制到项目外的存储，是打开这个项目后第一件该做的事。**

---

**个人视频知识库管理系统。** Python + pywebview，本地 Whisper 转写 + DeepSeek 清洗。

---

## 一、它是什么

**一条五步的流水线**：

```
① 导入视频       把手机录的 / 摄像头录的 mp4 放进 data/media/
② Whisper 转写   faster-whisper（本地 GPU）→ data/raw_transcripts/（带时间戳的分段）
③ AI 清洗        DeepSeek → data/ai_processed/（去同音字错误、修断句）
④ 🔴 手动搭知识树  用户在界面上，一根一根把内容搭成一棵结构树
⑤ 连续播放       点树上的节点 → 播那个视频的 start→end 段
```

## 二、🔴 「手动」是卖点，不是妥协

**第 ④ 步是这个项目和别的知识库工具的本质区别。**

| | 全自动流水线（如 `energy-recovery`） | **本项目** |
| --- | --- | --- |
| 结构从哪来 | AI 抽原子、聚类、生成 | 🔴 **人一根一根搭出来的** |
| 自动化到哪一步为止 | 到最后一步 | **止于"清洗完的稿子"** |
| 人的角色 | 读结果、复习 | 🔴 **结构本身就是人做的** |
| 核心资产 | 生成的卡片与复习记录 | 🔴 **人做的那棵树** |

**它的功能表里写作「知识树手动构建、合并、拆分」** ——
**"手动"两个字写在功能描述里，是卖点。**

> **`energy-recovery` 的价值在"自动化"里；这个项目的价值在"手动"里。**
> **那棵树不是"AI 整理的成果"，是用户自己想清楚一件事的过程留痕。**
> **把它自动化掉，就等于把这个项目取消掉。**

**树上的每个节点能挂什么**（`src/knowledge_tree.py` 的 `TreeNode`）：

| 字段 | 含义 |
| --- | --- |
| `name` / `children` | 节点名 + 子节点（递归 —— 就是树） |
| **`video`** / **`video_list`** | 主视频 / 多个视频（**合并节点**） |
| **`start` / `end`** | 🔴 **视频里的时间段（秒）** |
| `text` / `cleaned_file` | 该节点的文本 / 指向 `ai_processed/` 里的清洗稿 |
| `topic_id` | 主题标识 |

**操作**：空白双击建节点 · 拖到别的节点上改父 · 双击折叠 · 滚轮缩放 · 空白拖动平移 · 合并（`video_list`）· 拆分（`remove_video_from_tree`）。

## 三、形态一览

| 项 | 值 |
| --- | --- |
| **形态** | **Windows 桌面应用**（pywebview + WebView2），**单实例** |
| **常驻服务** | **无独立服务** —— 但 pywebview 会起一个**内部 HTTP 服务器（随机端口）**，见 [service.md](service.md) |
| **数据** | 全在项目内的 `data/`，**被 `.gitignore` 挡住**（见上） |
| **平台** | **仅 Windows** —— 依赖 pywebview 的 edgechromium 后端、`mklink /J`、Win32 窗口 API |
| **版本控制** | ✅ 有 `.git`，remote = `github.com/3431481073/VideoKnowledgeBase`（**2 个 commit，30+ 条未提交**） |
| **状态** | **保留项目，用户说"我自己经常录"** |

## 四、🔴 三个入口 —— 裁决如下

代码里有三个入口，**文档互相矛盾**。整理时做了裁决：

| 入口 | 文件 | 裁决 | 依据 |
| --- | --- | --- | --- |
| **① 当前** | **`src/app_web.py`** | ✅ **这是现在用的** | **`启动视频知识库.bat` 和 `.vbs` 启动的都是它** |
| ② | `src/app.py`（560 B） | 🟠 **历史入口** | PySide6 桌面版。它的 docstring **自称"新程序入口"并说"或双击 启动视频知识库.bat"** —— **但那两个脚本启动的是 `app_web.py`，不是它**。**docstring 是错的。** |
| ③ | `src/main.py`（35,742 B） | 🟠 **旧版** | 最早的 PySide6 桌面版；`app.py` 的 docstring 说它"保持不动，回退用" |

> **⚠️ 另外一处 docstring 也是错的**：`app_web.py` 说自己是"**单进程、无本地服务器、无端口**"，
> 但 `src/media.py` 说"pywebview 的页面来源是 **`http://127.0.0.1:<随机端口>/`**"。
> **`media.py` 是对的** —— 它解释了为什么必须用目录联接（WebView2 拒绝从 `file://` 页面加载 `file:///` 视频）。
> 详见 [service.md](service.md)。

## 五、架构

```
┌─ 界面   webui/  （纯 HTML/CSS/JS，8 文件）
│    index.html · style.css · js/{app,bridge,graph,player,camera,process_dialog}.js
│    webui/media  ← 🔴 **目录联接**，指向 data/media（运行时由 mklink /J 创建）
│
├─ 宿主   src/app_web.py   pywebview 开一个 WebView2 窗口，Python↔JS 走 js_api
│    · 单实例闸（src/single_instance.py）
│    · 窗口尺寸收敛到屏幕工作区（有实测注释：1920x1200@150% → 工作区 1280x752）
│    · 串行任务队列（src/jobs.py，daemon 线程）
│
└─ 后端   src/  （Python）
     transcriber.py   faster-whisper，CUDA，int8_float16
     ai_processor.py  DeepSeek 清洗（提示词在 config.py）
     knowledge_tree.py / store.py / workspace.py   树的读写
     video_ops.py / camera.py / camera_app.py      视频操作与录制
     media.py         媒体目录联接 + 样片生成 + ffmpeg 探测
     config.py        data/config.json 是唯一配置源
```

**旧桌面版**：`src/main.py` + `src/panes/`（6 个 PySide6 面板）+ `src/main_window.py` + `src/knowledge_browser.py`（46,964 B）。

## 六、目录

```
VideoKnowledgeBase/
├── docs/            ← 本目录
├── data/            ← 🔴 用户数据（在被 .gitignore 挡着的目录里 —— 但它就是数据目录）
│   ├── media/       🔴 **4.63 GB 用户录像** + 4 个样片 + speech_test.mp4
│   ├── raw_transcripts/ · ai_processed/     转写与清洗产物
│   ├── knowledge_tree.json                   🔴 手搭的那棵树
│   ├── workspace.json · config.json         工作区状态 / 配置（**含 API Key**）
│   ├── backups/                              4 个 zip，但都是空的
│   ├── _backup_before_media_name_migration/  一次迁移前快照
│   ├── merged_backup/ · _stale/              空
│   └── input/ output/ store/ cache/ logs/    ← **整理时新建，全空**（见 data.md 第四节）
├── src/             Python 主程序（30 个 .py）
├── webui/           前端（8 文件）+ **media/（目录联接）**
├── build/           ⚠️ **只剩构建脚本** —— PyInstaller 产物已删（见下）
├── _diag/           诊断与测试集（93 文件，含 6 个 unittest + 6 个 e2e + 4 个 UI 测试）
├── misc/spike/      知识树实现的技术预研代码（2 个 .py）
├── venv/            1.9 GB（**有 requirements.txt** ✓）
├── requirements.txt · requirements-build.txt
├── 启动视频知识库.bat · 启动视频知识库.vbs
└── .gitignore
```

### ⚠️ `build/` 现在只剩两个文件 —— 这是 2026-10-03 整理的结果

原来 `build/` 是 **82.87 MB**：四个 PyInstaller 目录（`dist_onedir/` `dist_onefile/` `work_onedir/` `work_onefile/`）+ 两个文件。

**整理时删掉了那四个目录（82.87 MB），保留了这两个文件：**

| 文件 | 为什么保留 |
| --- | --- |
| **`build_exe.ps1`**（4,409 B） | 🔴 **它是构建脚本本身，不是产物。** 手写的，含大段实测知识（onefile vs onedir 的取舍、`webui\media` 联接的防护逻辑）。**而且它用 `$PSScriptRoot` 推导项目根、把输出写回 `<root>\build\` —— 所以它必须待在 `build\` 里，搬不走。** |
| `VideoKnowledgeBase.spec`（1,024 B） | PyInstaller 的 spec，**每次构建时由脚本重写**（里面是写死的绝对路径） |

**→ 所以 `.gitignore` 里加的是 `build/dist_*/` 和 `build/work_*/`，而不是 `build/`**
（写成 `build/` 会把构建脚本一起忽略掉）。

## 七、文档索引

| 文档 | 内容 |
| --- | --- |
| [README.md](README.md) | 本文件 |
| [run.md](run.md) | 三种启动方式 · **三入口裁决** · 模型路径 · 首次配置 · 打包 · 已知限制 |
| [data.md](data.md) | **数据全在项目内** · 🔴 **零备份** · 目录联接 · 树与产物的格式 |
| [deps.md](deps.md) | Python 46 包 · 外部 ffmpeg（**含 catcher**）· 外部 Whisper 模型 · 凭据 |
| [service.md](service.md) | 无独立服务 · **pywebview 内部随机端口** · 单实例闸 |
| [log.md](log.md) | 变更记录（只追加） |
| [runtime-log.md](runtime-log.md) | **无运行时日志文件** · 输出只在 stderr · `.vbs` 看不到、`.bat` 看得到 |
| [INPUT-SLOT.md](INPUT-SLOT.md) | **我从哪拿**（§8.4）：池子锚点表 + 详情（ffmpeg 候选链 · 项目外的 Whisper 模型 · DeepSeek API · 系统相机 · 用户源文件） |
| [OUTPUT-SLOT.md](OUTPUT-SLOT.md) | **我往外给**（§8.4）：池子锚点表 + 详情（录像 → 转写 → 清洗 → 🔴 **手搭的知识树**，含字段表与消费须知） |
| [README.txt](README.txt) | **原件留档** —— ⚠️ 里面有一句已经过期（见 run.md） |
| [spike-知识树选型.md](spike-知识树选型.md) | **技术选型结论**：为什么知识树用 QGraphicsView 而不是 QTreeWidget（17/17 断言通过） |
