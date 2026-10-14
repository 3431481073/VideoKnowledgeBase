# OUTPUT-SLOT · VideoKnowledgeBase

> **我往外给什么** —— 按 `D:\MyProject\CLAUDE.md` §8.4。
> **判据：消费者不读本项目源码，只看本文件，就能取到数据。**
>
> 配套：[INPUT-SLOT.md](INPUT-SLOT.md)（我从哪拿，方向相反）。背景见 [data.md](data.md)。

---

## 我往外给

| 锚点 | 是什么 |
| --- | --- |
| D:\MyProject\VideoKnowledgeBase\data\media | 视频本体（用户录像 / 录制 / 裁剪合并产物，mp4） |
| D:\MyProject\VideoKnowledgeBase\data\raw_transcripts | 原始转写（`<base>.txt` + `<base>_segments.json`，带时间戳分段） |
| D:\MyProject\VideoKnowledgeBase\data\ai_processed | 清洗稿 + 元信息（`<base>_cleaned.txt` + `<base>_meta.json`） |
| D:\MyProject\VideoKnowledgeBase\data\knowledge_tree.json | 🔴 手搭的知识树（单文件 JSON） |
| D:\MyProject\VideoKnowledgeBase\data\workspace.json | 条目清单（单文件 JSON） |
| D:\MyProject\VideoKnowledgeBase\data\backups | 覆盖原视频前的原文件备份 |
| D:\MyProject\VideoKnowledgeBase\data\_stale | 源视频被覆盖后的旧转写 / 清洗产物 |
| D:\MyProject\VideoKnowledgeBase\services.yaml | 服务声明（YAML，`services: []` + 一句理由） |

**只有文件，没有数据库、没有端口、没有 HTTP。** —— 上面每一个锚点都是**落地的池子**。

---

## 详情

### 一、产出的是一条三级流水线

**一个"个人视频知识库"的落地数据**：录像本体 + 一条三级产物链（转写 → 清洗 → **手搭的知识树**）。

```
data/media/<name>.mp4                                  ① 视频本体
   └─ Whisper 转写 → data/raw_transcripts/<base>.txt
                     data/raw_transcripts/<base>_segments.json   ② 带时间戳的原始转写
        └─ DeepSeek 清洗 → data/ai_processed/<base>_cleaned.txt
                           data/ai_processed/<base>_meta.json    ③ 清洗稿 + 元信息
              └─ 人手工搭树 → data/knowledge_tree.json         ④ 🔴 知识树（人的产出）
                    （节点用 itemId 指向）data/workspace.json  ⑤ 条目清单
```

- **`<base>` = 视频文件名去掉扩展名**（`src/store.py` 的 `base_of`）。
  例：`WIN_20260928_00_52_21_Pro.mp4` → `WIN_20260928_00_52_21_Pro`。
- 🔴 **④ 是本项目最不可再生的产出。** ②③ 可以重跑，④ **是人一根一根搭出来的** ——
  它就是这个项目的意义本身（见 [README.md](README.md) 第二节）。

**池子与形态：**

| # | 产出物 | 落在哪 | 形态 |
| --- | --- | --- | --- |
| ① | 视频本体（用户录像 / 录制 / 裁剪合并产物） | `data/media/<name>.mp4` | 二进制 mp4 |
| ② | 原始转写 | `data/raw_transcripts/<base>.txt` · `<base>_segments.json` | UTF-8 文本 + JSON |
| ③ | 清洗稿 + 元信息 | `data/ai_processed/<base>_cleaned.txt` · `<base>_meta.json` | UTF-8 文本 + JSON |
| ④ | **知识树** | `data/knowledge_tree.json` | 单文件 JSON |
| ⑤ | 条目清单（工作区） | `data/workspace.json` | 单文件 JSON |
| ⑥ | 覆盖前的原视频备份 | `data/backups/<stem>.<YYYYmmdd_HHMMSS>.<ext>` | 二进制 mp4 |
| ⑦ | 源视频被覆盖后的旧产物 | `data/_stale/<stem>.<时间戳>.<ext>` | 文本 / JSON |
| ⑧ | 服务声明 | `services.yaml` | YAML |

> ⚠️ **`data\config.json` 不是池子、也不是产出物** —— 它是**私有配置**，且含 DeepSeek API Key。
> **任何备份 / 搬运 / 引用，显式排除它。**（见 [data.md](data.md) 第七节）

### 二、字段表（各池子放了什么）

#### ④ `data/knowledge_tree.json` —— 知识树（**主产出**）

递归的节点树，**根节点恒为 `"个人空间"`**。每个节点（`src/store.py` 的 `_node_to_dict`）：

| 键 | 类型 | 含义 |
| --- | --- | --- |
| `name` | str | 节点名 |
| `kind` | `"video"` / `"topic"` | 内容节点 / 主题节点 |
| `children` | array | 子节点（同结构，递归） |
| `nid` | str | **持久节点 id**，`n` + 10 位 hex |
| `body` | str | 节点正文（用户写的话 **或** 该视频的清洗稿文本） |
| `itemId` | str \| null | 🔴 **指向 `workspace.json` 里的条目 `id`** —— 视频引用**走这里** |
| `collapsed` | bool | 界面折叠态 |
| `video` `video_list` `start` `end` `text` `cleaned_file` `topic_id` | —— | ⚠️ **老 PySide6 字段，当前恒为 `null` / `[]`**，见下文坑 2 |

**取一段视频怎么走**：`itemId` → `workspace.json` 的 `.items[].id` → 该条目的 `media_name` → `data/media/<media_name>`。

#### ⑤ `data/workspace.json` —— 条目清单

```json
{ "items": [ { ... }, ... ] }
```

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | str | 条目 id，`i` + 10 位 hex（= 树节点的 `itemId`） |
| `name` | str | 显示名（**用户可改**，不一定是文件名） |
| `media_name` | str | 🔴 **`data/media/` 下的真实文件名** —— 取视频用它，不要用 `name` |
| `created` | str | `"YYYY-MM-DD HH:MM"` |
| `src` | str | 导入来源路径（可为 `""`） |
| `clips` | array | 裁剪来源：`[{"media": "media/xxx.mp4", "start": 17.002, "end": 81.837}]`（秒） |
| `origin` | str | `source`（导入） / `record`（录制） / `clip`（裁剪） |
| `overwrite` | bool | 是否覆盖过原视频 |

#### ② `data/raw_transcripts/<base>_segments.json` —— 带时间戳分段

```json
[ { "start": 0.91, "end": 6.91, "text": "地狱之歌特别讲了各种各样不死的怪物" }, ... ]
```

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `start` / `end` | float | **秒**，相对该视频起点 |
| `text` | str | 该段文字（**已转简体**，`OpenCC("t2s")`） |

同目录 `<base>.txt` = 这些 `text` **直接拼接**（无时间戳、无分隔）。

#### ③ `data/ai_processed/<base>_meta.json` —— 元信息

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `title` | str | 标题（**新 UI 里不再使用**，取视频文件名） |
| `media_name` | str | 对应 `data/media/` 下的文件名 |
| `video_path` | str | 源路径（可为 `""`） |
| `cleaned_file` | str | **清洗稿的绝对路径** |
| `created_time` | int | 源文件创建时间（epoch 秒；取不到为 `0`） |
| `modified_at` | str | `"YYYY-MM-DD HH:MM:SS"` |

同目录 `<base>_cleaned.txt` = DeepSeek 产出的**纯正文**（无标题、无时间戳、无 Markdown 标记）。

#### ⑥⑦ 备份与陈旧产物

- `data/backups/<stem>.<时间戳>.<ext>` —— `store.backup_media()` 在**覆盖原视频前**的复制，**先备份成功才动手**。
- `data/_stale/<stem>.<时间戳>.<ext>` —— 源视频被覆盖后，旧转写/清洗产物挪到这里（**不删除**，可回溯）。

> 时间戳格式：`backups/` 用 `%Y%m%d_%H%M%S`，`_stale/` 同系。**同名冲突会自动加 `_2` / `_3`**，不会互相覆盖。

#### ⑧ `services.yaml` —— 服务声明

顶层 `services:` 数组，本项目是 `services: []` + 一句理由（没有常驻服务）。详见 [service.md](service.md)。

### 三、怎么取

| 想要 | 怎么取 |
| --- | --- |
| 树 / 条目 / 分段 / 元信息 | **只读打开对应 JSON**。UTF-8 **无 BOM**，`indent=2` |
| 转写 / 清洗正文 | 读 UTF-8 文本文件 |
| 视频 | 直接读 `data/media/<media_name>` |
| 服务声明 | 读 YAML 文件 |

- **没有锁、没有写占位**：写方全是原子写（同目录临时文件 + `os.replace`），
  **外部随时读都不会读到半截文件**。
- ⚠️ **不要走 `webui\media\` 取视频** —— 那是指向 `data/media` 的**目录联接，运行时才创建，仓库里不存在**
  （见 [data.md](data.md) 第五节）。
- **要拿出去消费**：直接把 `data\` 下的文件复制走即可（**排除 `config.json`**）。

### 四、⚠️ 取的时候要注意（不读源码就会踩的坑）

1. 🔴 **`knowledge_tree.json` 有两个写者，格式分新旧。**
   - 当前写者：`src/store.py` —— 上面第二节那套（含 `kind/nid/body/itemId/collapsed`）。
   - 旧写者：`src/knowledge_tree.py`（PySide6 版入口 `src/main.py`）——
     只认 `name/children/video/video_list/start/end/text/cleaned_file/topic_id`。
   - **用旧入口打开一次再保存，`kind/nid/body/itemId/collapsed` 会被整段抹掉。**
   - **→ 消费者只能依赖两版都有的字段（`name` / `children`）；新字段当"可能不存在"处理。**

2. 🔴 **不要从 `video` / `start` / `end` / `text` / `cleaned_file` 取数据。**
   这些老字段**当前恒为 `null` / `[]`**（`store.py` 为了兼容旧程序仍会写它们，但从不填值）。
   **视频引用现在只在 `itemId` 里**（见上文第二节）。

3. ⚠️ **状态不落盘，靠"文件在不在"推导。**
   `transcribed` / `ai_processed` **不在任何 JSON 里** —— `store.refresh_status()` 看产物文件是否存在。
   **→ 改了 `data/media/<name>` 的文件名，对应产物会因为 base 对不上而"凭空消失"。**

4. ⚠️ **`name` 与 `media_name` 是两回事。** 前者会被用户改名，后者才是磁盘上的真文件名。
   **取视频永远用 `media_name`。**

5. 🔴 **这些产出没有备份。** `data/` 被 `.gitignore` 挡住，`data/backups/*.zip`（旧程序留下的）是空的
   —— **包括那 4.63 GB 用户录像在内，一处副本都没有**。见 [data.md](data.md) 第三节。

6. 🔴 **录像是个人的、私密的**（用户自述："我自己经常录的一些关于我自己人生的一些反思"）。
   引用 / 复制 / 外发之前想清楚去处。
