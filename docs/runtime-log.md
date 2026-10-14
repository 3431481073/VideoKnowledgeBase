# runtime-log · VideoKnowledgeBase

> §1 里的「运行时的行为日志，**可关**」。
>
> # 结论：**本项目不写任何运行时日志文件。**
>
> 所以本文件记录的不是一份日志，而是**"这个空位"**：运行时输出去了哪、怎么看、为什么没有文件。
> **这不像是漏了 —— 是它本来就没有。**

---

## 一、证据

| 检查 | 结果 |
| --- | --- |
| `src\` 里有没有 `logging` | ❌ **零命中**（`logging.` / `getLogger` / `basicConfig` / `log_file` / `LOG_DIR` 全无） |
| 有没有 `logs\` 目录写入 | ❌ 代码里没人碰；`data\logs\` 是 2026-10-03 建的空目录 |
| 有没有 `.log` 文件产出 | ❌ 项目里没有 |
| `.gitignore` 里的 `*.log` | ⚠️ 那是**通用的那 8 行之一**，**不是本项目在写 log** —— 别被它误导 |

**运行时输出只有一种形式：`print(...)`。**

| 文件（当前入口链路） | `print(` 处数 |
| --- | --- |
| `src\app_web.py` | 7 |
| `src\config.py` | 2 |
| `src\store.py` | 2 |
| `src\transcriber.py` | 2 |
| `src\workspace.py`（老入口用） | 2 |

大多数是 `print(..., file=sys.stderr)` —— **错误类信息走 stderr，不是文件。**

---

## 二、运行时输出到哪 —— 取决于你怎么启动（见 [run.md](run.md) 第二节）

| 启动方式 | 输出能看到吗 |
| --- | --- |
| **双击 `启动视频知识库.vbs`（推荐）** | ❌ **完全看不到** —— `pythonw.exe` + 窗口样式 0，**没有控制台** |
| **双击 `启动视频知识库.bat`（排障用）** | ✅ **有黑框**，stdout / stderr 都在，退出后 `pause` 保屏 |
| 命令行 `venv\Scripts\python.exe src\app_web.py` | ✅ 终端里 |
| 加 `--debug` | ✅ 终端 + **DevTools**（前端 console 也打开） |

> 🔴 **`.vbs` 是"推荐的启动方式"**，代价就是**报错全看不见**。
> **出问题第一件事：改用 `.bat` 起一次。**

---

## 三、会打印什么（实际的内容）

| 来源 | 打印什么 | 什么时候 |
| --- | --- | --- |
| `src\app_web.py` | 屏幕工作区 / 窗口尺寸与定位、媒体挂载失败原因、样片错误、找不到界面文件、单实例已存在而退出 | 启动时；出问题时 |
| `src\store.py` | `workspace.json` / `knowledge_tree.json` **读取失败，按空处理** | JSON 损坏时 |
| `src\config.py` | `config.json` 读取失败 / 不是 JSON 对象 | 配置损坏时 |
| `src\transcriber.py` | 没找到 `nvidia-*` 包目录（cublas 缺失提示） | PATH 注入失败时 |
| `src\workspace.py`（老入口） | 加载 / 保存工作区失败 | 老 PySide6 版用 |

> ⚠️ **这些都不是行为日志** —— 是**出错时才响一句**的提示，没有时间戳、没有级别、不落盘、不追历史。
> **看不出"上一次跑发生了什么"，只能看出"这一次有没有报错"。**

### 另有一条**界面内**的"日志"（仍然不落盘）

`src\video_ops.py` 的一系列操作（裁剪、合并、选编码器）带一个 `log` 回调，
由 `src\jobs.py` 接住写进任务的 `warning` 字段 → **显示在前端界面上**（`jobs.py:307-308`、`394`）。
例：`"编码器: h264_nvenc（硬件）"`、`"h264_nvenc 执行失败，改用 libx264 重试"`。

**→ 这是给用户看的过程提示，关窗即失，同样不写文件。**

---

## 四、怎么"开" / 怎么"关"

| 想要 | 怎么做 |
| --- | --- |
| **打开输出** | 把启动方式从 `.vbs` 换成 **`.bat`**（有黑框、`pause` 保屏） |
| **要更详细** | `venv\Scripts\python.exe src\app_web.py --debug` —— 开 DevTools，看前端 console |
| **想抓成文件** | 当前**没有内置开关**。只能自己重定向：`venv\Scripts\python.exe src\app_web.py > vkb.log 2>&1` |
| **想少说话 / 关掉** | **没有日志文件可关。** `.vbs` 本来就什么都不显示 |

> ⚠️ **打包成 exe 后**：有没有控制台取决于 `build\build_exe.ps1` 的构建参数（**本次未核**）。
> **打包版丢了 stdout 的话，`print` 出来的东西就彻底看不到了** —— 要排障就跑源码版或 `.bat`。

---

## 五、为什么没有日志文件

1. **这个应用的"日志"落在 `data\` 的数据文件里** ——
   转写稿、清洗稿**在不在**，就是进度（`store.refresh_status()` 从磁盘推导状态，见 [OUTPUT-SLOT.md](OUTPUT-SLOT.md) 第五节坑 3）。
   **产物即状态**，不再另写一份。
2. 用户要的是"调起系统的、自己操作、拿结果"（见 [INPUT-SLOT.md](INPUT-SLOT.md) 第 6 项）——
   运行过程本身不是要留痕的东西。
3. **但它有个明确的代价**：🔴 **`.vbs` 启动 + 无日志文件 = 出问题什么都不剩**。
   真要排查，只能复现一次并改用 `.bat` / `--debug`。

---

## 六、相关

- 怎么启动、`.vbs` 与 `.bat` 的区别：[run.md](run.md) 第二节
- 有没有常驻服务 / 端口：[service.md](service.md)
- 数据落在哪：[data.md](data.md)
