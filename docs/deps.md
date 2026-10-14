# 依赖

**单栈项目** —— Python 后端 + 纯 HTML/CSS/JS 前端（**无 Node、无 `node_modules`**）。

---

## 一、结论先行

| 问题 | 答案 |
| --- | --- |
| **有第三方 Python 包吗** | **有，46 个** —— 但 **`requirements.txt` 在，全部钉版本** ✓（与 `Kindred` 相反） |
| **有模型文件吗** | **项目内没有** —— Whisper 模型在 `D:\models\`（**项目外**） |
| **对 `_shared/models/` 的贡献** | **零** |
| **对 `_shared/routes.yaml` 的贡献** | **零**（未追加任何路由） |
| **外部可执行依赖** | **有** —— `ffmpeg` / `ffprobe`（**含跨项目借用**） |
| **外部资源依赖** | **有** —— `D:\models\` 的 Whisper 模型 |
| **依赖其他项目吗** | **有** —— `catcher`（借 ffmpeg.exe） |
| **有项目依赖它吗** | **没有** |

---

## 二、Python 依赖 —— 46 个，且钉了版本

**`requirements.txt`（1,307 B）—— 46 个包，全部 `==` 钉版本，而且带注释解释**。

### 核心

| 包 | 版本 | 用途 |
| --- | --- | --- |
| **`faster-whisper`** | 1.2.1 | **ASR 转写** |
| `ctranslate2` | 4.8.1 | faster-whisper 的推理后端 |
| **`nvidia-cublas-cu12`** | 12.9.2.10 | 🔴 CUDA 运行时（见下） |
| `nvidia-cuda-runtime-cu12` | 12.9.79 | 同上 |
| `nvidia-cuda-nvrtc-cu12` | 12.9.86 | 同上 |
| `onnxruntime` | 1.28.0 | VAD 等 |
| **`PySide6`** | 6.11.1 | **旧桌面版**（`src/main.py` / `app.py` / `panes/`） |
| **`pywebview`** | 6.2.1 | **当前 Web 版**（`src/app_web.py`） |
| `bottle` | 0.13.4 | pywebview 的内置 HTTP 服务器 |
| `pythonnet` / `clr-loader` / `cffi` / `proxy-tools` | —— | pywebview 在 Windows 上用的 WebView2/.NET 后端 |
| `opencc-python-reimplemented` | 0.1.7 | **简繁转换**（`transcriber.py` 用 `OpenCC("t2s")`） |
| `requests` · `httpx` | 2.34.2 / 0.28.1 | DeepSeek 调用（`ai_processor.py`） |
| `imageio-ffmpeg` | 0.6.0 | ffmpeg 的 Python 包装（兜底） |
| `PyYAML` · `numpy` · `tqdm` · `tokenizers` · `huggingface_hub` / `hf-xet` | —— | 其余支撑 |

### 🔴 `requirements.txt` 里有一段注释值得单独引

```
# CUDA 运行时：ctranslate2 用普通 LoadLibrary 加载 cublas，只认 PATH，
# 所以 transcriber.py 会在 import faster_whisper 前把这些包的 bin 目录注入 PATH。
# 不需要 nvidia-cudnn-cu12 —— ctranslate2 4.8.1 自带 cudnn64_9.dll。
```

**对应代码在 `src/transcriber.py:26-52`**：`_setup_cuda_dll_path()` 在
`from faster_whisper import WhisperModel` **之前**执行 —— 里面有实测记录：
只调 `os.add_dll_directory()` **不管用**，会报 `Library cublas64_12.dll is not found or could not be loaded`；
**改成把那些目录塞进 `PATH` 就通了**。

### 构建期依赖

**`requirements-build.txt`（176 B）—— 只有 1 个包：**

```
pyinstaller==6.22.3
```

注释写明：「构建期依赖（只在打包 exe 时需要，应用运行不需要）」。

**→ 这个项目的依赖是分层清楚的**：运行 46 个 + 构建 1 个。

---

## 三、外部可执行依赖 —— ffmpeg

**`src/media.py:106-119` 的 `find_ffmpeg()` 是一个 5 级候选链：**

| 顺序 | 路径 | 性质 |
| --- | --- | --- |
| 1 | `<项目根>\tools\ffmpeg.exe` | 项目内（**当前不存在**） |
| 2 | `<bundle_root>\tools\ffmpeg.exe` | 打包后的 `_MEIPASS` 里 |
| 3 | `D:\MyProject\_tools\ffmpeg\bin\ffmpeg.exe` | 同盘 `_tools`（共享工具区） |
| 4 | `D:\ffmpeg\bin\ffmpeg.exe` | 🔴 **项目外** |
| 5 | **`D:\MyProject\catcher\backend\tools\ffmpeg.exe`** | 🔴 **跨项目借用** |
| 兜底 | `shutil.which("ffmpeg")` | PATH |

**`ffprobe.exe` 只从"和 ffmpeg 同目录"里找**（代码里有注释解释为什么不能字符串替换：
"路径里本身就有 `ffmpeg` 这个目录名，链式 replace 会把它也换掉"）。

**ffmpeg 用在哪**：生成测试样片（`ensure_samples()`）+ 读视频时长（`probe_duration()`）。

---

## 四、外部资源依赖 —— Whisper 模型

**`src/config.py:29-32`：**

```python
MODEL_PATHS = {
    "base":   r"D:\models\faster-whisper-base",      # 注释：实测 141.0 MB
    "medium": r"D:\models\faster-whisper-medium",    # 注释：实测 1459.7 MB
}
```

**两处都在 `D:\MyProject` 之外。**

> ⚠️ **规模是代码注释里的值，不是实测**（整理时禁读 `D:\MyProject` 之外）。
>
> ⚠️ **`_shared/routes.yaml` 里有一条 `whisper-root` 路由**（指向 `_shared/models/asr/`，**那个目录是空的**）。
> **`D:\models\` 很可能就是那条路由想收编的东西** —— 但**这是推测**，本次未核。
> 见 [log.md](log.md) 未解决 3。

**`get_model_info()`** 是个写得很好的门卫：加载前检查 `model.bin` 是否存在 →
用 `nvidia-smi` 探可用显存 → 不够就返回 `vram_insufficient` **并给出人话提示**，
**不崩、不静默降级**。

---

## 五、对外契约表

### ① 依赖方：**VideoKnowledgeBase** → `catcher`（借 ffmpeg）

| 列 | 内容 |
| --- | --- |
| **依赖方** | `VideoKnowledgeBase` |
| **依赖什么** | `D:\MyProject\catcher\backend\tools\ffmpeg.exe`（`src/media.py:114`，**候选链的最后一级**） |
| **断了会怎样** | ⚠️ **半静默** —— 前面 4 条候选 + PATH 兜底都找不到时，`find_ffmpeg()` 返回 `None`；调用方（生成样片 / 读时长）会**明确报错**，但**不会说"是 catcher 那边没了"** |
| **可配置吗** | ❌ 写死 |

> **这是本工程第三条「借 catcher 的东西」的边** —— 另两条是
> `video-workbench`（借 `catcher` 的 ffmpeg 二进制 + 只读它的 `app.db`，见地图）。
> **→ `catcher` 是这台机器上的"ffmpeg 提供者"。**

### ② 被依赖方

**没有被任何项目依赖。**

### ③ 另一条边：`VideoKnowledgeBase` → `_tools`

`D:\MyProject\_tools\ffmpeg\bin\ffmpeg.exe`（候选链第 3 级）。

---

## 六、凭据

| 检查 | 结果 |
| --- | --- |
| 位置 | **`data\config.json`** 的 `clean_api_key`（长度 35） |
| 类型 | DeepSeek API Key |
| **值** | **本文档不出现** |
| 已 gitignore | ✅ 是（`.gitignore` 的 `data/`） |
| 有没有泄露过 | ✅ **没有** |
| 代码里硬编码 | ✅ 零命中 |

**→ 这次的做法是标准的**：上一次 commit（`85f76ec`）专门把硬编码 key 改成了配置文件。

**⚠️ 一条操作提醒**：`data\config.json` 和 `data\knowledge_tree.json` **在同一个目录**，
**做备份时容易一锅端 —— 要显式排除 `config.json`。**

> 📌 **规则提醒**（来自 `github_operater\SPEC.md` 规则 3，已补进 PLAYBOOK 步骤 6）：
> **「删文件 ≠ 吊销凭据」** —— 万一将来泄露了，删 `config.json` 不够，
> **要去 DeepSeek 控制台作废重发。**（现在没泄露，所以不需要。）

---

## 七、环境位置

| 环境 | 位置 | 可重建？ |
| --- | --- | --- |
| **`venv/`** | 仓库根，**1,903.31 MB / 8,967 文件** | ✅ **可**（`requirements.txt` 钉了版本）—— 但要重下几个 GB 的 CUDA 包 |
| Whisper 模型 | **`D:\models\`**（项目外） | ⚠️ 要重新下载 |
| ffmpeg | 见第三节的候选链 | ✅ |
| `__pycache__/` | **575 文件 / 8.50 MB**，散在 `src\` `src\panes\` `_diag\` 等处 | ✅ 自动 |

> ⚠️ **`__pycache__` 里的 `.pyc` 是 `cpython-312`** —— 对应 **venv 的 Python 3.12.14**。
> **系统的 `python` 是 3.13.7。**
> **→ 任何涉及编译/运行这个项目的命令，都要用 `venv\Scripts\python.exe`，不要用 PATH 上的 `python`。**
> （整理时踩过：用 PATH 的 `python -m py_compile` 生成了 30 个 `cpython-313.pyc`，已清理。见 [log.md](log.md)。）
