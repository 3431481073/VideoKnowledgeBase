# -*- coding: utf-8 -*-
"""持久层：真实数据 <-> 界面模型。

分工：**store 只管磁盘，不管界面**。它把 workspace.json / knowledge_tree.json /
四个产物文件读成 ui_model 的对象，或者反过来写回去。界面态（选中、折叠、
处理进度）不在这里。

文件约定沿用老程序（不另起一套）：
    data/workspace.json                        条目清单
    data/knowledge_tree.json                   知识树
    data/media/<name>                          视频本体
    data/raw_transcripts/<base>.txt            原始转写
    data/raw_transcripts/<base>_segments.json  带时间戳分段
    data/ai_processed/<base>_cleaned.txt       清洗稿
    data/ai_processed/<base>_meta.json         元信息

两条硬规矩：
  1. **raw/<base>.txt 只写一次**。老程序在清洗完成后把清洗稿写回了 raw 文件，
     原始转写被冲掉（main.py:705-710）。这里 write_raw/write_cleaned 各管各的。
  2. 所有写盘都是**原子写**（同目录临时文件 + os.replace），
     长任务中途关窗口也不会留下半截文件。
"""

import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime

import config as app_config
from ui_model import UINode, UIItem

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
MEDIA_DIR = os.path.join(DATA_DIR, "media")
RAW_DIR = os.path.join(DATA_DIR, "raw_transcripts")
AI_DIR = os.path.join(DATA_DIR, "ai_processed")
#: 「覆盖原视频」前的原文件备份。**先备份成功才动手**，备份失败就中止。
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
#: 源视频被覆盖后，基于旧内容的转写/清洗产物挪到这里（不删除，可回溯）
STALE_DIR = os.path.join(DATA_DIR, "_stale")
WORKSPACE_FILE = os.path.join(DATA_DIR, "workspace.json")
TREE_FILE = os.path.join(DATA_DIR, "knowledge_tree.json")

VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov", ".avi", ".flv", ".wmv")

#: 列表里显示的摘要取多少字（不全量读大文件）
SUMMARY_CHARS = 400


def fake_mode():
    """VKB_FAKE=1 -> 走 mock_data；否则走真实数据。"""
    return os.environ.get("VKB_FAKE", "").strip() == "1"


def ensure_dirs():
    for d in (DATA_DIR, MEDIA_DIR, RAW_DIR, AI_DIR, BACKUP_DIR, STALE_DIR):
        os.makedirs(d, exist_ok=True)


# --------------------------------------------------------------------------
# 原子写
# --------------------------------------------------------------------------
def _atomic_write_text(path, text):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".vkb-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


#: 每个文件最多留几份历史版本
BACKUP_KEEP = 5


def _rotate_backup(path):
    """把现有文件轮成 `<名>.bak-<时间戳>`，只保留最近 BACKUP_KEEP 份。

    为什么值得每次写都轮：用户数据是**唯一一份**。上一版留在盘上，
    「少了一条」「少了转写稿」都能一眼比对、一键回退。
    （实测教训：一次重打包把整个 data\\ 删了，盘上没有任何历史可回。）

    命名沿用项目已有惯例 `<文件>.bak-YYYYmmdd-HHMMSS`
    （Workbench 的 tools.json.bak-20260927-162123 就是这个形状）。

    **注意边界**：这是"上一版"级别的保护 —— 防写坏、防被覆盖、防某次改动丢东西。
    它挡不住**整个目录被删**（.bak 和本体在同一个目录里）；
    那一路靠 build\\build_exe.ps1 把 data\\ 挪出输出目录来防。

    任何失败都只是放弃这一次轮转，**绝不让它把正常的保存搞失败**。
    """
    if not os.path.isfile(path):
        return
    d = os.path.dirname(path)
    base = os.path.basename(path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(d, "%s.bak-%s" % (base, stamp))
    n = 2
    while os.path.exists(dst):                 # 同一秒内连写两次也不许互相踩
        dst = os.path.join(d, "%s.bak-%s_%d" % (base, stamp, n))
        n += 1
    try:
        shutil.copy2(path, dst)
    except Exception:                                   # noqa: BLE001
        return
    try:
        olds = sorted((f for f in os.listdir(d)
                       if f.startswith(base + ".bak-")), reverse=True)
        for f in olds[BACKUP_KEEP:]:
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass
    except OSError:
        pass


def _atomic_write_json(path, obj):
    _atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))


def _read_text(path, limit=None):
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(limit) if limit else f.read()
    except Exception:
        return ""


# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
def base_of(name):
    stem, _dot, _ext = name.rpartition(".")
    return stem if stem else name


def media_path(name):
    return os.path.join(MEDIA_DIR, name)


def _stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_media(name):
    """把 data/media/<name> 备份到 data/backups/。返回备份路径。

    **失败就抛**，调用方必须中止后续动作 —— 「覆盖原视频」是唯一会动用户
    原文件的操作，先备份成功再动手，没有例外。
    """
    src = media_path(name)
    if not os.path.isfile(src):
        raise FileNotFoundError("要备份的文件不存在：%s" % src)
    ensure_dirs()
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    dst = os.path.join(BACKUP_DIR, "%s.%s%s" % (stem, _stamp(), ("." + ext) if ext else ""))
    n = 2
    while os.path.exists(dst):                 # 同一秒内连着覆盖两次也不许互相踩
        dst = os.path.join(BACKUP_DIR, "%s.%s_%d%s"
                           % (stem, _stamp(), n, ("." + ext) if ext else ""))
        n += 1
    shutil.copy2(src, dst)
    if os.path.getsize(dst) != os.path.getsize(src):
        raise IOError("备份大小对不上：%s" % dst)
    return dst


def archive_artifacts(base):
    """把 base 名下的转写/清洗产物挪进 data/_stale/（带时间戳后缀）。

    为什么要挪而不是留着：条目状态（transcribed / ai_processed）是**从磁盘
    推导**的（refresh_status 看文件在不在）。源视频被覆盖后内容变了，旧清洗稿
    继续显示就是错的；但直接删掉又不可回溯。挪走两头都顾上。

    返回被挪走的文件数。
    """
    files = [raw_txt_path(base), seg_path(base),
             cleaned_path(base), meta_path(base)]
    moved = 0
    ensure_dirs()
    stamp = _stamp()
    for p in files:
        if not os.path.isfile(p):
            continue
        stem, dot, ext = os.path.basename(p).rpartition(".")
        dst = os.path.join(STALE_DIR, "%s.%s.%s" % (stem, stamp, ext or "bin"))
        os.replace(p, dst)
        moved += 1
    _BODY_CACHE.clear()                        # 正文缓存里可能还留着旧内容
    return moved


def media_url(name):
    return "media/" + name


def raw_txt_path(base):
    return os.path.join(RAW_DIR, base + ".txt")


def seg_path(base):
    return os.path.join(RAW_DIR, base + "_segments.json")


def cleaned_path(base):
    return os.path.join(AI_DIR, base + "_cleaned.txt")


def meta_path(base):
    return os.path.join(AI_DIR, base + "_meta.json")


def has_raw(base):
    return os.path.isfile(raw_txt_path(base)) and os.path.isfile(seg_path(base))


def has_cleaned(base):
    return os.path.isfile(cleaned_path(base)) and os.path.isfile(meta_path(base))


# --------------------------------------------------------------------------
# 产物读写
# --------------------------------------------------------------------------
def write_raw(base, segments):
    """写原始转写。**只该被调用一次**，清洗不会覆盖它。

    覆盖前把上一版轮成 `.bak` —— 重转写会盖掉上一次的稿子，
    那是花时间算出来的成果，不能无声丢掉。
    """
    text = "".join(seg.get("text", "") for seg in segments)
    _rotate_backup(raw_txt_path(base))
    _atomic_write_text(raw_txt_path(base), text)
    _rotate_backup(seg_path(base))
    _atomic_write_json(seg_path(base), segments)


def read_raw(base):
    return _read_text(raw_txt_path(base))


def read_segments(base):
    if not os.path.isfile(seg_path(base)):
        return []
    try:
        with open(seg_path(base), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def write_cleaned(base, cleaned_text, meta):
    """写清洗稿与 meta。**绝不碰 raw/ 下的文件。**

    覆盖前同样轮转 .bak：重跑清洗（哪怕只是换了个 prompt）会盖掉上一稿，
    上一稿可能正是用户满意的版本。
    """
    _rotate_backup(cleaned_path(base))
    _atomic_write_text(cleaned_path(base), cleaned_text or "")
    _rotate_backup(meta_path(base))
    _atomic_write_json(meta_path(base), meta or {})


def read_cleaned(base):
    return _read_text(cleaned_path(base))


def read_meta(base):
    if not os.path.isfile(meta_path(base)):
        return {}
    try:
        with open(meta_path(base), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def make_meta(display_name, media_name, src_path, cleaned_file):
    created = 0
    if src_path and os.path.exists(src_path):
        try:
            created = os.path.getctime(src_path)
        except OSError:
            created = 0
    return {
        "title": display_name or media_name,
        "media_name": media_name,
        "video_path": src_path or "",
        "cleaned_file": cleaned_file,
        "created_time": created,
        "modified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# --------------------------------------------------------------------------
# 导入
# --------------------------------------------------------------------------
def unique_media_name(name):
    """重名加序号：a.mp4 -> a_2.mp4 -> a_3.mp4"""
    if not os.path.exists(media_path(name)):
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    for n in range(2, 10000):
        cand = f"{stem}_{n}.{ext}" if ext else f"{stem}_{n}"
        if not os.path.exists(media_path(cand)):
            return cand
    return name


def import_media(src_path, on_progress=None):
    """把视频复制进 data/media/。返回落地的文件名。

    为什么是复制而不是链接：页面同源播放只认 webui/media（= data/media 的联接），
    符号链接需要开发者模式、硬链接不能跨盘，两条都不稳。复制是唯一确定的做法，
    顺带让后续裁剪/合并的产物都落在同一处，路径模型统一。
    """
    ensure_dirs()
    name = unique_media_name(os.path.basename(src_path))
    dst = media_path(name)
    total = os.path.getsize(src_path) or 1
    done = 0
    fd, tmp = tempfile.mkstemp(dir=MEDIA_DIR, prefix=".import-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as out, open(src_path, "rb") as inp:
            while True:
                chunk = inp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(min(1.0, done / total))
        os.replace(tmp, dst)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return name


# --------------------------------------------------------------------------
# 条目清单
# --------------------------------------------------------------------------
def refresh_status(item):
    """从磁盘推导两个状态位 —— 不落盘、不重复存。"""
    b = item.base
    item.transcribed = has_raw(b)
    item.ai_processed = has_cleaned(b)
    return item


def resolve_media_name(rec):
    """老记录没有 media_name，推一个出来。**不猜** —— 推不出来就原样用显示名。

    优先级：
      1. 记录里的 name 本身就是 data/media 下的真实文件 -> 用它
      2. 否则看 src 的 basename 是不是真实文件 -> 用它
      3. 都不成立 -> 返回 None（调用方原样保留显示名）

    实测这条规则正好接回用户的真实数据：
      name="怪物和人类的十大发"（改过名，磁盘上没有这个文件）
      src="D:\\手机文件\\8.12\\VID20260731063231.mp4" -> basename 命中 media 下的真实文件
    """
    name = rec.get("name") or ""
    if name and os.path.isfile(media_path(name)):
        return name
    src = rec.get("src") or ""
    if src:
        cand = os.path.basename(src)
        if cand and os.path.isfile(media_path(cand)):
            return cand
    return None


#: 上次 load_items 有没有补出 media_name（补出来了就要写回磁盘）
_migrated = False


def needs_migration():
    return _migrated


def _item_from_record(rec):
    global _migrated
    name = rec.get("name") or ""
    if not rec.get("media_name"):
        _migrated = True
    mn = rec.get("media_name") or resolve_media_name(rec)
    it = UIItem(name, rec.get("created") or "",
                media=media_url(mn or name), src=rec.get("src") or "",
                media_name=mn or name)
    it.iid = rec.get("id") or new_iid()
    it.origin = rec.get("origin") or "source"
    it.overwrite = bool(rec.get("overwrite"))
    # 老记录没有这个键 = 没出队（默认留在队列里）—— 向后兼容，不用迁移
    it.dequeued = bool(rec.get("dequeued"))
    clips = rec.get("clips")
    if isinstance(clips, list):
        it.clips = [dict(c) for c in clips if isinstance(c, dict)]
    refresh_status(it)
    # 只读开头几百字做摘要，不把整个清洗稿读进来
    src_txt = cleaned_path(it.base) if it.ai_processed else raw_txt_path(it.base)
    it.text = _read_text(src_txt, SUMMARY_CHARS)
    return it


def load_items():
    """读 workspace.json -> [UIItem]。文件缺失就是空列表（不自动建）。"""
    global _migrated
    _migrated = False
    ensure_dirs()
    if not os.path.isfile(WORKSPACE_FILE):
        return []
    try:
        with open(WORKSPACE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[store] workspace.json 读取失败，按空处理: {e}")
        return []
    recs = data.get("items") if isinstance(data, dict) else None
    if not isinstance(recs, list):
        return []
    out = []
    for r in recs:
        if isinstance(r, dict) and r.get("name"):
            out.append(_item_from_record(r))
    return out


def save_items(items):
    recs = []
    for it in items:
        recs.append({
            "id": it.iid,
            "name": it.video_name,
            # 真实文件名单独存 —— 改名不会把它带走（见 ui_model.UIItem 的说明）
            "media_name": it.media_name,
            "created": it.created,
            "src": it.src or "",
            "clips": it.clips or [],
            "origin": it.origin,
            "overwrite": bool(it.overwrite),
            #: 出队标记。**只影响显不显示在预处理队列里**，不删任何东西。
            #: 显式落盘（而不是"没出队就不写"）—— 和 overwrite 一致，
            #: 读回去一眼能看出这条是自己出队的，还是从来没进过队列。
            "dequeued": bool(getattr(it, "dequeued", False)),
        })
    _rotate_backup(WORKSPACE_FILE)          # 先把上一版留住，再覆盖
    _atomic_write_json(WORKSPACE_FILE, {"items": recs})


def add_item(name, src_path="", created=None, origin="source", clips=None,
             media_name=None):
    """新条目落盘。返回 UIItem。"""
    it = UIItem(name, created or datetime.now().strftime("%Y-%m-%d %H:%M"),
                media=media_url(media_name or name), src=src_path,
                media_name=media_name or name)
    it.iid = new_iid()
    it.origin = origin
    it.clips = [dict(c) for c in (clips or [])]
    refresh_status(it)
    return it


#: 单条正文缓存：正文可能几十上百 KB，而 snapshot() 每次变更都会取一遍
_BODY_CACHE = {}


def _cached_text(path):
    if not os.path.isfile(path):
        return ""
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return _read_text(path)
    hit = _BODY_CACHE.get(key)
    if hit is not None:
        return hit
    t = _read_text(path)
    _BODY_CACHE.clear()          # 只留最近一条，避免无限增长
    _BODY_CACHE[key] = t
    return t


def read_body(item, limit=200000):
    """正文：有清洗稿用清洗稿，否则退回原始转写。"""
    if item.ai_processed:
        t = _cached_text(cleaned_path(item.base))
        if t.strip():
            return t[:limit]
    return _read_text(raw_txt_path(item.base), limit)


# --------------------------------------------------------------------------
# 知识树
# --------------------------------------------------------------------------
def new_nid():
    """节点持久 id。前缀 n + 10 位 hex，与假链路的 n1/n2 不会撞。"""
    return "n" + uuid.uuid4().hex[:10]


def new_iid():
    return "i" + uuid.uuid4().hex[:10]


_new_nid = new_nid


def _node_from_dict(d):
    is_virtual = bool(d.get("virtual"))
    n = UINode(d.get("name") if is_virtual else (d.get("name") or "未命名"),
               "video" if (d.get("kind") == "video" or d.get("video")) else "topic",
               body=d.get("body") or "",
               item_id=d.get("itemId") or d.get("item_id"))
    n.nid = d.get("nid") or _new_nid()
    n.collapsed = bool(d.get("collapsed"))
    n.virtual = is_virtual
    for c in d.get("children") or []:
        if isinstance(c, dict):
            n.add(_node_from_dict(c))
    return n


def _node_to_dict(n):
    d = {
        "name": n.name,
        "kind": n.kind,
        "children": [_node_to_dict(c) for c in n.children],
        # 老字段：让老的 PySide6 代码还能读这份文件
        "video": None,
        "video_list": [],
        "start": None,
        "end": None,
        "text": None,
        "cleaned_file": None,
        "topic_id": None,
        # 新字段
        "nid": n.nid,
        "body": n.body or "",
        "itemId": n.item_id,
        "collapsed": bool(n.collapsed),
    }
    if getattr(n, "virtual", False):
        # 只给**隐形根**写这一个标记 —— 别的节点一个字节都不加，文件保持干净
        # （老 PySide6 代码读到时只是看到一个名字为空的根，不影响它）
        d["virtual"] = True
    return d


def _blank_root():
    """一个空的**隐形根**（多根）。名字为空、virtual=True，界面上不画它。"""
    root = UINode("")
    root.virtual = True
    root.nid = _new_nid()
    return root


def load_tree():
    """读知识树，返回**隐形根**：

      · 返回的那个根 `virtual=True`，**不出现在界面上**；
      · 它的 `children` 才是用户看到的**顶层节点** —— 可以有多个（"多根"）。

    文件缺失 / 读坏 -> 一个空的隐形根（**不写盘** —— 老 load_tree 会写）。

    【老文件迁移】老格式里文件的根是**真节点**（比如「个人空间」）。读到时在它
    上面套一层隐形根，它就降级成"顶层节点之一" —— **一个节点都不丢**。
    迁移只在内存里做，本函数自己不写盘；等界面第一次改东西时自然落盘
    （不然就成了"打开一次改一次文件"）。
    """
    if not os.path.isfile(TREE_FILE):
        return _blank_root()
    try:
        with open(TREE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            inner = _node_from_dict(data)
            if inner.virtual:
                return inner
            root = _blank_root()
            root.add(inner)
            return root
    except Exception as e:
        print(f"[store] knowledge_tree.json 读取失败，用空树: {e}")
    return _blank_root()


def save_tree(root):
    _rotate_backup(TREE_FILE)               # 先把上一版留住，再覆盖
    _atomic_write_json(TREE_FILE, _node_to_dict(root))


def assign_missing_nids(root):
    """给没有持久 id 的节点补上（老文件第一次被新界面打开时）。"""
    changed = False
    for n in root.walk():
        if not n.nid:
            n.nid = _new_nid()
            changed = True
    return changed


# --------------------------------------------------------------------------
# 设置（真源是 data/config.json，这里只是转一手）
# --------------------------------------------------------------------------
def load_settings():
    return app_config.load_config()


def save_settings(values):
    """**合并写**：必须先 load 拿全量再改，否则会清掉别的键。"""
    cfg = app_config.load_config()
    for k, v in (values or {}).items():
        cfg[k] = v
    app_config.save_config(cfg)
    return app_config.load_config()


def reset_settings():
    """恢复默认值：把 DEFAULTS 合并写回去。"""
    cfg = app_config.load_config()
    cfg.update(app_config.DEFAULTS)
    app_config.save_config(cfg)
    return app_config.load_config()
