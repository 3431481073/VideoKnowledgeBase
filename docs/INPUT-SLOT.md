# INPUT-SLOT · VideoKnowledgeBase

> **我从哪拿** —— 按 `D:\MyProject\CLAUDE.md` §8.4。
> 配套：[OUTPUT-SLOT.md](OUTPUT-SLOT.md)（我往外给，方向相反）。细节依据见 [deps.md](deps.md) / [service.md](service.md)。

---

## 我从哪拿

| 锚点 | 拿什么 |
| --- | --- |
| D:\MyProject\_tools\ffmpeg\bin\ffmpeg.exe | `ffmpeg.exe` 可执行文件（`ffprobe.exe` 从同目录取） |
| D:\ffmpeg\bin\ffmpeg.exe | `ffmpeg.exe` 可执行文件（同上） |
| D:\MyProject\catcher\backend\tools\ffmpeg.exe | `ffmpeg.exe` 可执行文件（同上） |
| D:\models\faster-whisper-base | Whisper 模型文件（`model.bin` 等） |
| D:\models\faster-whisper-medium | Whisper 模型文件（`model.bin` 等） |

**上面这几条都是文件路径 —— 本项目不连任何数据库、不请求任何本机端口。**
⚠️ 还有三类输入**不是路径 / 端口**（DeepSeek API · 系统相机应用 · 用户给的源文件），
按 §8.4「锚点只写绝对路径或端口」的规定**不写进上面这张表**，全部记在下面 `## 详情` 第三节。

---

## 详情

### 一、`ffmpeg` —— 一条六级候选链（表里的三条是其中三级）

`src/media.py:106-119` 的 `find_ffmpeg()` 按优先级顺序找，**任一命中即用，全落空才返回 `None`**：

| 级 | 路径 | 现状 |
| --- | --- | --- |
| 1 | `<项目根>\tools\ffmpeg.exe` | 不存在（本项目自己的候选位） |
| 2 | `<bundle_root>\tools\ffmpeg.exe`（打包后 `_MEIPASS`） | 仅打包版 |
| 3 | **`D:\MyProject\_tools\ffmpeg\bin\ffmpeg.exe`** | **表里有** |
| 4 | **`D:\ffmpeg\bin\ffmpeg.exe`** | **表里有** |
| 5 | **`D:\MyProject\catcher\backend\tools\ffmpeg.exe`** | **表里有 · 路径写死** |
| 兜底 | `shutil.which("ffmpeg")` | PATH |

- **拿了什么**：`ffmpeg.exe`；**`ffprobe.exe` 只从"和 ffmpeg 同目录"里找**（代码里有注释解释为什么不能字符串替换路径）。
- **拿来干嘛**：`media.ensure_samples()` 生成 4 个测试样片；`media.probe_duration()` 读视频时长。
- **我假设它是什么样**：文件在该路径上、能执行、版本支持 `-f lavfi testsrc` 与 `ffprobe` 用法。
- **坏了会怎样**：⚠️ **半静默** —— 六级全落空时 `find_ffmpeg()` 返回 `None`；调用方**会明确报错**，
  但**不会说明是哪一级候选路径没命中**。

### 二、`D:\models\` 的 Whisper 模型

- **拿了什么**：模型文件（`model.bin` 等）。
- **怎么取**：路径**写死**在 `src/config.py:29-32` 的 `MODEL_PATHS`；运行时档位来自 `data/config.json` 的 `whisper_model`。
- **拿来干嘛**：`transcriber.get_model()` 加载到 **CUDA**（`DEVICE="cuda"` 硬编码，`COMPUTE_TYPE="int8_float16"`），本地转写。
- **我假设它是什么样**：① 路径存在；② `model.bin` 在里面；③ 显存够（`base` ≥ 800 MiB / `medium` ≥ 1200 MiB）；
  ④ 有 NVIDIA GPU + 可用的 `nvidia-smi`。
- **坏了会怎样**：✅ **明确报错、不崩、不静默降级** —— `get_model_info()` 返回
  `missing_files` / `vram_insufficient` / `unknown_model` + **人话提示**；转写功能不可用，其余功能正常。

> ⚠️ 两个路径都在 **`D:\MyProject` 之外**；[deps.md](deps.md) 里 `141.0 / 1459.7 MB` 是**代码注释值，不是实测**。
> ⚠️ **换机器必须改 `config.py`。**

### 三、不写进固定表的三类输入（非路径 / 端口，或未核）

#### 3.1 DeepSeek 清洗 API（外部网络，不是路径也不是端口）

- **从哪拿**：`https://api.deepseek.com/v1/chat/completions` —— `data/config.json` 的 `clean_url`（默认值在 `config.py` `DEFAULTS`）。
- **拿了什么**：`choices[0].message.content` —— 一段**纯文本正文**（无标题、无 JSON、无 Markdown 标记）。
- **拿来干嘛**：`ai_processor.process_segments()` 把 `*_segments.json` 拼成带时间戳的原文喂进去，取回正文，写成 `<base>_cleaned.txt`。
- **我假设它是什么样**：① `clean_api_key` **非空且有效**；② 网络可达；③ 返回结构是 `choices[0].message.content`；
  ④ 输入 ≤ **6000 字符**、输出 ≤ **4000 tokens**。
- **坏了会怎样**：Key 为空 → `ValueError("缺少清洗 API Key")`；HTTP/结构异常 → 抛错、该条任务失败。
  ⚠️ **超长音频会被静默腰斩**（`MAX_INPUT_CHARS=6000`，代码里标着 `TODO(M7)` 未修；界面会提示"本次会被截断"）。

**凭据**：`data/config.json` 的 `clean_api_key`（长度 35）。

> 🔴 **不是 `.env`，是 `data/config.json`** —— `data/` 被 `.gitignore` 挡住，**从未进过 git**（最近一次 commit 就是把硬编码 Key 拿掉）。
> **删文件 ≠ 吊销凭据**：真泄露了要去 DeepSeek 控制台作废重发。

#### 3.2 Windows 相机应用（系统应用，URI 不是路径）

- **从哪拿**：`microsoft.windows.camera:` URI（三级兜底：URI → `shell:AppsFolder\Microsoft.WindowsCamera_...` → 失败）；
  录制产物落在**系统相机胶卷目录**（运行时算出候选目录，**同时盯多个，不猜**）。
- **拿了什么**：新录制的 `mp4`。
- **拿来干嘛**：监视相机胶卷目录，文件稳定后 `store.import_media()` 复制进 `data/media/`（`origin="record"`）。
- **我假设它是什么样**：① 系统相机应用可调起；② 录制落在运行时候选目录里。
- **坏了会怎样**：三级调起全失败 → 报错，并有 ffmpeg `dshow` 降级路径（`camera.dshow_record`）；
  超时 / 没录到 → 明确提示（`"没等到录制…"`），不会静默。

> **为什么是"调起"而不是自己开摄像头**：用户明确要求 —— 像调文件资源管理器那样，调系统的东西，用户在里面操作，我们拿结果。

#### 3.3 用户给的视频源文件（路径由用户决定，不是固定池子）

- **从哪拿**：用户自己给的路径，例如 `D:\手机文件\8.12\VID20260731063231.mp4`（记在 `workspace.json` 的 `src` 字段里）。
- **拿了什么**：`mp4`（以及 `.webm/.mkv/.mov/.avi/.flv/.wmv`）。
- **拿来干嘛**：`store.import_media()` **复制**进 `data/media/`（重名自动加 `_2`）—— **是复制不是链接**，因为页面同源播放只认 `webui/media`。
- **我假设它是什么样**：能读、是浏览器 / ffmpeg 可解的视频容器。
- **坏了会怎样**：复制中断会清理 `.part` 临时文件并**抛错**，不留半截文件；源文件**不动**。

#### 3.4 ⚠️ `_shared\routes.yaml` 的 `whisper-root`（推测，未核）

- **从哪拿**：`_shared\routes.yaml` 里的一条 `whisper-root` 路由 → 指向 `_shared\models\asr\`（**那个目录是空的**）。
- **拿了什么 / 拿来干嘛**：**未知** —— 本项目**没有**从 `_shared` 读任何东西，代码里也没有这条路由的引用。
- **我假设它是什么样**：——（**没有依赖**，坏了也无所谓）。

> **这只是一条观察**：`D:\models\` 的 Whisper 模型**很可能就是那条路由想收编的东西** —— 但**这是推测**，
> 2026-10-03 与 2026-10-11 两次整理都未核（`D:\MyProject` 之外禁读）。见 [log.md](log.md) 未解决 3。

### 四、⚠️ 本项目**不**接受的东西（避免误接）

| 不会发生 | 说明 |
| --- | --- |
| **不读别人的 DB / 库文件** | 全项目零命中 |
| **不 import 别人的包** | 无 |
| **不依赖别的项目在跑** | 没有任何"对方必须先起来"的前置条件（见 [service.md](service.md) 第六节） |
| **不用 `.env`** | 凭据走 `data/config.json`；`.env` 不存在 |
| **不联网（除 DeepSeek 外）** | 转写是纯本地；`HF_ENDPOINT` 指向 `hf-mirror.com` 只是 `faster-whisper` 的默认值，不影响本地模型加载 |

### 五、失效模式汇总（坏了会怎样）

| 输入 | 坏了会怎样 |
| --- | --- |
| `ffmpeg`（各级全挂） | 样片不生成、时长读不到；**报错但不会指出是哪一级候选路径没命中** |
| Whisper 模型 / 显存 | **明确报错** + 人话提示；转写用不了，其余功能正常 |
| DeepSeek Key / 网络 | 清洗任务失败并抛错；**超长输入会被静默截断** |
| 相机应用 / 相机目录 | 调起失败有降级路径；没录到会明确提示 |
| 用户源文件 | 导入失败抛错，源文件不动、不留半截 |
