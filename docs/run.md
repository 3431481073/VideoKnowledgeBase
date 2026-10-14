# 运行

> 命令都在**仓库根**跑。代码里既有 `__file__` 相对的路径（`config.py` / `knowledge_tree.py`），
> 也有 CWD 相关的部分 —— **保持从仓库根启动**。

---

## 一、三个入口 —— 裁决

**代码里有三个入口，文档互相矛盾。整理时定的裁决如下：**

| 入口 | 文件 | 裁决 | 依据 |
| --- | --- | --- | --- |
| **① 当前** | **`src/app_web.py`** | ✅ **这是现在用的** | **`启动视频知识库.bat` 与 `启动视频知识库.vbs` 启动的都是它** |
| ② | `src/app.py`（560 B） | 🟠 **历史入口**（PySide6 桌面版） | 它的 docstring 自称"新程序入口"、并写"或双击 启动视频知识库.bat" —— **但那两个脚本启动的是 `app_web.py`。docstring 是错的。** |
| ③ | `src/main.py`（35,742 B） | 🟠 **旧版** | 最早的 PySide6 版；`app.py` 的 docstring 说它"保持不动，回退用" |

**→ 日常用 ①。②③ 仍可独立运行，但属于历史。**

---

## 二、三种启动方式

| 方式 | 命令 / 动作 | 特点 |
| --- | --- | --- |
| **① 双击（推荐）** | `启动视频知识库.vbs` | **完全没有控制台窗口**。用 `pythonw.exe` + 窗口样式 0。**代价：看不到任何报错** |
| **② 双击（排障用）** | `启动视频知识库.bat` | 有黑框，**会显示 Python 的输出与错误**，退出后 `pause` 让你看清 |
| **③ 命令行** | `venv\Scripts\python.exe src\app_web.py` | 等价于 .bat |
| 加调试 | `... src\app_web.py --debug` | 打开 DevTools |
| 旧桌面版 | `venv\Scripts\python.exe src\main.py` | 回退用 |

> **`.vbs` 为什么存在**（它自己的注释写的）：`.bat` 会跑 `cmd.exe`，
> **双击它必然弹出黑框** —— 那个黑框不是 Python 子进程闪的，是批处理脚本自己的窗口。
> `.vbs` 用 `pythonw.exe` + 窗口样式 0 把它藏掉。
>
> ⚠️ **那个文件必须保持纯 ASCII** —— wscript 按系统 ANSI 码页读 `.vbs`，
> 非 ASCII 注释会被搞坏。**只有文件名是中文**（NTFS 上没问题）。

---

## 三、首次运行要配什么

### 1. `data/config.json`

**它是唯一配置源**（`src/config.py` 管默认值合并、旧键迁移、原子写入）。

默认内容（`config.py` 的 `DEFAULTS`）：

| 键 | 默认值 |
| --- | --- |
| `whisper_model` | `"medium"` |
| `clean_url` | `https://api.deepseek.com/v1/chat/completions` |
| `clean_model` | `"deepseek-chat"` |
| **`clean_api_key`** | 🔴 **`""`（空）—— 必须自己填**，否则 AI 清洗跑不了 |
| `clean_prompt` | 一段很长的中文校对提示词（在 `config.py` 里，可改） |

> **旧键 `api_key` 会自动迁移到 `clean_api_key`**（`load_config()` 里做了）。

### 2. Whisper 模型路径

**模型**不在**项目里**，在 `D:\models\`（**`MyProject` 之外**）：

```python
# src/config.py:29-32
MODEL_PATHS = {
    "base":   r"D:\models\faster-whisper-base",      # 注释：实测 141.0 MB
    "medium": r"D:\models\faster-whisper-medium",    # 注释：实测 1459.7 MB
}
```

**→ 换机器要改这里。** `get_model_info()` 会在加载前检查 `model.bin` 是否存在、
再用 `nvidia-smi` 探显存够不够，**不够就明确报错而不是崩**。

### 3. ⚠️ `README.txt` 里的一句话已经过期

> 原文：「注意：需要将 **`transcriber.py` 中的 `MODEL_PATH`** 修改为你本地的 Whisper 模型路径。」

**`transcriber.py` 里根本没有 `MODEL_PATH` 这个常量。**
模型路径现在在 **`src/config.py` 的 `MODEL_PATHS`**，运行时档位来自 **`data/config.json` 的 `whisper_model`**。

（原件已移入 [README.txt](README.txt) 留档，**一字未改**。）

---

## 四、依赖与运行环境

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**46 个包，钉版本**，见 [deps.md](deps.md)。

**关于 CUDA**（`requirements.txt` 里的原注释）：

> ctranslate2 用**普通 `LoadLibrary`** 加载 cublas，**只认 PATH**，
> 所以 `transcriber.py` 会在 `import faster_whisper` **之前**把这些包的 `bin` 目录注入 PATH。
> **不需要 `nvidia-cudnn-cu12`** —— ctranslate2 4.8.1 自带 `cudnn64_9.dll`。

**转写的实测参数**（`transcriber.py`）：`DEVICE = "cuda"`，`COMPUTE_TYPE = "int8_float16"`。
代码里有取舍记录：`int8_float16` 显存 1053 MiB / 推理 9.2s，
`float16` 显存 1981 MiB / 推理 10.1s —— **选了前者**（显存只要 53%，推理还快 9%）。

---

## 五、打包

```powershell
powershell -ExecutionPolicy Bypass -File build\build_exe.ps1 -Mode onefile
powershell -ExecutionPolicy Bypass -File build\build_exe.ps1 -Mode onedir
```

**⚠️ `build_exe.ps1` 必须 UTF-8 带 BOM 保存**（它自己的注释解释了：PS 5.1 会按 GBK 解码无 BOM 的脚本）。

**它做了三件事**（都值得知道）：

1. 从 `$PSScriptRoot` 推导项目根、校验 `venv\Scripts\python.exe` / `src\app_web.py` / `webui\` 都在；
2. 🔴 **打包前先删掉 `webui\media` 那个目录联接** ——
   否则 PyInstaller 的 `--add-data webui;webui` 会**跟着联接把整个媒体目录打进 exe**。
   **它会先断言那是个联接（不是联接就拒绝删除）**，删完再提示。
   **→ 打包之后，下次启动应用时会重新创建联接。**
3. 调 PyInstaller，产物落在 `build\dist_<mode>\`，spec 写在 `build\`。

**onefile vs onedir —— 脚本里有结论**：

> 本轮界面只用假数据、不 import 转写/清洗后端，所以 onefile 只有十几 MB、启动几秒，**单文件分发方便**。
>
> 但接入真实转写后，PyInstaller 会把整条引擎链一起打进去：
> `ctranslate2` + `cublas64_12.dll`(97.8MB) + `cublasLt64_12.dll`(637.7MB) + `cudart`/`nvrtc` +
> `onnxruntime` + `faster-whisper` **≈ 1.4 GB**。
> **onefile 每次启动都要把这 1.4 GB 解压到临时目录，启动会慢到不可接受**（而且反复写盘）。
> **onedir 不需要解压，直接就地加载。**
>
> **所以：本轮交付 onefile；接引擎那一轮改成 `-Mode onedir`。**

> 🔴 **2026-10-03 整理时删掉了 `build\dist_*` 和 `build\work_*`（82.87 MB）** ——
> 它们是 PyInstaller 产物，**可以重跑脚本得到**。
> **`build_exe.ps1` 与 `.spec` 保留**（脚本搬不走 —— 它靠 `$PSScriptRoot` 定位项目根）。

---

## 六、已知限制

| # | 限制 | 依据 |
| --- | --- | --- |
| 1 | **仅 Windows** | pywebview 的 edgechromium 后端、`mklink /J`、`SystemParametersInfoW`、Win32 相机 API |
| 2 | **需要 NVIDIA GPU + CUDA** | `transcriber.py` 里 `DEVICE = "cuda"` 是**硬编码的** |
| 3 | 🔴 **用户录像零备份** | `.gitignore` 挡住 `data/`；`backups/*.zip` 是空的。**见 [data.md](data.md)** |
| 4 | **`webui\media` 是目录联接，不可当普通目录搬** | 移动 `data/media` → 联接不报错、只是指向空 |
| 5 | **三个入口、两处 docstring 与事实不符** | 见本文第一节 |
| 6 | **`README.txt` 里关于 `MODEL_PATH` 的那句已过期** | 见本文第三节 |
| 7 | **`VideoKnowledgeBase.spec` 里是写死的绝对路径** | `D:/MyProject/VideoKnowledgeBase/...` —— 跟机器绑定（每次构建重写） |
| 8 | **`_diag/` 与 `_spike/`（已搬空）没有明确的长期定位** | 见 [log.md](log.md) 未解决 |
| 9 | **30+ 条 git 未提交，含多个未跟踪的新文件** | 见 [log.md](log.md) 未解决 |

---

## 七、⚠️ 整理时**没有**验证的东西

**2026-10-03 的整理是纯静态的 —— 一次代码都没跑。**
所以下面这些**都没验证过**，只是从代码读出来的：

- 三种入口**是否真的能起来**
- 依赖是否完整（46 个包够不够）
- `data/config.json` 里那个 API Key **是否仍然有效**（要联网）
- Whisper 模型**是否真的在 `D:\models\`**（那在 `MyProject` 之外，整理时禁读；文档里引用的 141.0 / 1459.7 MB **是代码注释里的值，不是实测**）
- 那棵知识树**打开后是否正常**（`knowledge_tree.json` 只读确认了存在与大小，没解析内容）

**→ 如果以后要动这个项目，第一件事应该是"双击 `启动视频知识库.bat`，确认还能起"。**
