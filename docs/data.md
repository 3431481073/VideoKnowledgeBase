# 数据

> **本项目的数据全在项目目录内的 `data\` 里。**
> **项目外只有 Whisper 模型（`D:\models\`），见第六节。**

> ⚠️ 注意：这**不是** `PLAYBOOK.md` 的「例外三」（项目内零数据）。**情况正好相反。**

---

## 一、`data\` 是什么（实测，2026-10-03）

`data\` 共 **4,633.87 MB / 42 文件** —— **占全项目的 69.9%**。

```
data/
├── media/                              🔴 **4,632.83 MB**  ← 13 个真人录像 + 4 样片 + speech_test
├── raw_transcripts/                         6 文件   ← Whisper 原始转写（.txt + _segments.json）
├── ai_processed/                            6 文件   ← AI 清洗后（_cleaned.txt + _meta.json）
├── knowledge_tree.json                  3,671 B     ← 🔴 手搭的那棵树
├── workspace.json                       4,524 B     ← 工作区状态（{items: [15]})
├── config.json                          1,585 B     ← 🔴 含凭据
├── backups/                                 4 文件   ← 🔴 4 个 zip，**只有 22~245 字节**
├── _backup_before_media_name_migration/     5 文件   ← 一次媒体改名迁移前的快照
├── merged_backup/                         （空）
├── _stale/                                （空）
└── input/ output/ store/ cache/ logs/     ← **2026-10-03 整理时新建，全空**（见第四节）
```

---

## 二、`data\media\` —— 用户的录像

**18 个文件。其中 13 个是真人录像（合计 4,632.83 MB）：**

| 文件 | 大小 |
| --- | --- |
| `VID20260809034148.mp4` | **1,276,556,625 B（1.19 GB）** |
| `VID20260803181910.mp4` | 923,864,421 B |
| `VID20260731063231.mp4` | **600,561,796 B** |
| `VID20260731063231_2.mp4` | **600,561,796 B** ← 🔴 **与上一个字节数完全相同** |
| `VID20260812024927.mp4` | 587,886,638 B |
| `VID20260812024737.mp4` | 265,603,630 B |
| `WIN20260928_00_52_21_Pro.mp4` | 213,659,297 B |
| `VID20260731135832.mp4` | 209,980,477 B |
| `VID20260731172420.mp4` | 83,519,818 B |
| `VID20260812025240.mp4` | 69,530,981 B |
| `VID20260731121358.mp4` | 19,749,143 B |
| `WIN20260928_00_01_09_Pro.mp4` · `WIN20260928_00_01_35_Pro.mp4` | 3,216,366 · 3,178,503 B |

**另 5 个不是用户的录像**：

| 文件 | 是什么 |
| --- | --- |
| `sample_01~04.mp4`（各 ~53 KB） | **ffmpeg 生成的测试样片**（`media.ensure_samples()` 用 `testsrc` 生成，带帧计数、hue 各不相同，便于肉眼验证裁剪是否生效） |
| `speech_test.mp4`（847,077 B） | 一段短的语音测试片 |

> ⚠️ **整理时把"样片"和"用户录像"认清楚了** —— 它们混在同一个目录里，
> **但那 4 个 `sample_*` 是程序自动生成的，删了会重建**，不是用户的内容。

> 🔴 **`VID20260731063231.mp4` 与 `VID20260731063231_2.mp4` 字节数完全相同（600,561,796）。**
> **疑似重复（可能占 573 MB）。本次没有做哈希比对**，所以只是"疑似"。
> **→ 不建议删任何一个** —— 见 [log.md](log.md) 未解决 2。

---

## 三、🔴🔴 那 4.63 GB 没有任何备份

**这是打开这个项目后第一件该处理的事。**

| 通道 | 覆盖到它了吗 |
| --- | --- |
| **`.git`** | ❌ **`.gitignore` 第 2 行就是 `data/`** |
| `data\backups\*.zip` | ❌ **4 个 zip 加起来不到 800 字节**（`backup_20260927_071211.zip` 22 B，其余各 245 B）—— 装不下任何东西 |
| 项目外 | ❌ 没有 |
| **→ 合计** | 🔴 **零备份** |

> **⚠️ 这里有一个很隐蔽的陷阱**：`.gitignore` 挡住 `data/` 是**对的**（4.63 GB 不该进 git），
> **但挡住之后，"有 git"就成了一种虚假的安全感** ——
> `git status` 是干净的，看起来一切正常，**而那 4.63 GB 其实一处副本都没有。**
>
> **→ 这条已经补进 `project_manager/docs/PLAYBOOK.md`**（见 [log.md](log.md)）。

### 数据是什么

用户的原话：「**我自己经常录的一些关于我自己人生的一些反思**，我会把它**可视化整理成结构**」。

**→ 这是他的人生记录。删了就没了。**

### 建议

| 做什么 | 说明 |
| --- | --- |
| 🔴 **把 `data\media\` 复制到项目外的存储** | 移动硬盘 / 云盘 / NAS —— **这是唯一的解法** |
| **至少把这几份小的备走** | `knowledge_tree.json`(3.7 KB) + `raw_transcripts\`(6 文件) + `ai_processed\`(6 文件) + `workspace.json`(4.5 KB) —— **合计约 39 KB**。**那棵人搭的树，是视频之外最不可再生的东西** |
| **不要备 `data\config.json`** | 含 API Key |

> **整理时做了什么**：这 39 KB 的小件**已经备进** `D:\MyProject\_rollback\videoknowledgebase_before_20261003\`，
> 并在 `_rollback\README.md` 里**明确写出"4.63 GB 的录像不在本备份里、且它没有任何备份"**。
> **大件没有动**（4.63 GB 放不进 `_rollback`）。详见 [log.md](log.md)。

---

## 四、🔴 `data\` 五区是空的 —— 这是刻意的

整理时在 `data\` 下建了 `input/ output/ store/ cache/ logs/` 五个空目录，
**但没有把任何真实数据搬进去**。

| 目录 | 现在 | 为什么不动 |
| --- | --- | --- |
| `data\media\` | 留原地 | 🔴 **搬它会打断那个目录联接**（见第五节），而且要改多处代码里的 `DATA_DIR` |
| `data\raw_transcripts\` · `ai_processed\` | 留原地 | 路径写在 `src/` 里 |
| `knowledge_tree.json` · `workspace.json` | 留原地 | `src/knowledge_tree.py` / `src/workspace.py` 按 `BASE_DIR/data/...` 定位 |
| `data\config.json` | 留原地 | 🔴 **含 API Key** —— 搬进 `data/store/` 等于让 Key 跟着走 |

**→ "`data/` 五区全空"是"决定不动"，不是"忘了搬"。**

> ⚠️ **而且这个项目的 `data\` 布局本身就是它的功能**：
> `config.py` 说「`data/config.json` 是唯一配置源」；
> `media.py` 说媒体目录必须能被 pywebview 的同源 HTTP 供上。
> **改布局 = 改行为**，违反 PLAYBOOK 〇.3「整理是搬家，不是重构」。

---

## 五、🔴 `webui\media` 是一个目录联接 —— 不可当普通目录搬

```
D:\MyProject\VideoKnowledgeBase\webui\media   →   D:\MyProject\VideoKnowledgeBase\data\media
                                          （Junction / ReparsePoint）
```

**它是运行时由 `media.ensure_link()` 用 `mklink /J` 创建的**（**不提交进仓库**）。

**为什么必须这么做**（`media.py` 的 docstring 全是实测结论）：

1. pywebview 的页面来源是 **`http://127.0.0.1:<随机端口>/`**，**不是 `file://`**；
2. 从那个页面加载 `file:///D:/....mp4` 会被 **WebView2 拒绝**：
   `MEDIA_ELEMENT_ERROR: Media load rejected by URL safety check`；
3. **同源 HTTP 可以**，而且 Range 也通（206 / accept-ranges / seeked 全部实测通过）；
4. **但那个内置服务器只供窗口 URL 所在的目录（`webui/`）**。

→ 所以用目录联接把 `data/media` 挂到 `webui/media` 下 —— **视频同源可播**，
bottle 的 `static_file` 原生处理 Range，**一行服务器代码都不用写**。

**⚠️ 三个坑：**

| 坑 | 说明 |
| --- | --- |
| **移动 `data\media\`** | 联接**不会报错，只是指向空** —— **失效是静默的** |
| **删掉联接、建一个真的 `webui\media` 目录** | 视频全播不了，**报错不会提到联接** |
| **打包时留着它** | `build_exe.ps1` 会**先删掉它**（并断言它确实是联接），否则 PyInstaller 会把 4.63 GB 打进 exe |

**`mklink /J` 不需要管理员权限。**

---

## 六、项目外

| 位置 | 是什么 | 规模 |
| --- | --- | --- |
| **`D:\models\faster-whisper-base`** | Whisper 模型 | 代码注释写"实测 141.0 MB" |
| **`D:\models\faster-whisper-medium`** | Whisper 模型 | 代码注释写"实测 1459.7 MB" |

**两处都在 `D:\MyProject` 之外** —— 整理时**禁读，只报了路径**。
**上面那两个数字是 `config.py` 注释里写的，不是实测。**

> **删掉会怎样**：`get_model_info()` 会报 `missing_files`，并提示"请先下载该模型，
> 或把 `whisper_model` 改成 base/medium"。**不崩，但转写用不了。**

---

## 七、凭据

| 检查 | 结果 |
| --- | --- |
| 位置 | **`data\config.json`** 的 **`clean_api_key`** 字段（长度 35） |
| 类型 | DeepSeek API Key（配 `clean_url` = `https://api.deepseek.com/v1/chat/completions`） |
| **值** | **本文档不出现** |
| `.env` | ❌ 不存在 |
| 代码里硬编码 | ✅ **零命中** —— 上一次 commit 就是 `85f76ec Remove hardcoded API key, use config file` |
| **已 gitignore** | ✅ **是**（`.gitignore` 第 2 行的 `data/` 覆盖了它） |
| **有没有泄露过** | ✅ **没有** —— 它从未进过 git |

**→ 按 PLAYBOOK 步骤 6 的「凭据在项目内」分支，本项目已经做对了。**

**整理时**：**未改动、未搬动、未放进任何备份**（`_rollback` 那份备份里刻意排除了 `config.json`）。

> ⚠️ **一条操作提醒**：`data\config.json` **和** `data\knowledge_tree.json` **在同一个目录里**。
> **做备份时容易一锅端** —— **要显式排除 `config.json`**。
