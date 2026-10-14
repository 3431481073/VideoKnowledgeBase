# 服务

## 一、结论：**没有独立常驻服务**

`services.yaml` 写的是 `services: []`。

- **没有进程会自己起来** —— 没有自启、没有守护、没有计划任务
- **没有对外提供的服务** —— 用户双击启动，关窗即退出
- **崩了重开即可**

---

## 二、⚠️ 但运行时**有一个 pywebview 的内部 HTTP 服务器**

**这不是本项目起的服务** —— 是 **pywebview / WebView2 的内部机制**。

```
src/app_web.py
   └─ webview.create_window(url=webui/index.html, ...)
        └─ pywebview 起一个内部 HTTP 服务器  →  127.0.0.1:<随机高位端口>
             页面来源 = http://127.0.0.1:<port>/
```

**为什么它必须存在**（`src/media.py` 的 docstring 全是实测）：

1. pywebview 的页面来源是 `http://127.0.0.1:<随机端口>/`，**不是 `file://`**；
2. 从那个页面加载 `file:///D:/....mp4` 会被 **WebView2 拒绝**：
   `MEDIA_ELEMENT_ERROR: Media load rejected by URL safety check`；
3. **同源 HTTP 可以**，而且 Range 也通（206 / accept-ranges / seeked 全部实测通过）；
4. **但那个内置服务器只供窗口 URL 所在的目录（`webui/`）**。

**→ 所以有了 `webui\media` 那个指向 `data\media` 的目录联接**（见 [data.md](data.md) 第五节）。

> ### 🔴 两处 docstring 自相矛盾，以 `media.py` 为准
>
> | 文件 | 说法 |
> | --- | --- |
> | `src/app_web.py` 的 docstring | 「**单进程、无本地服务器、无端口**：pywebview 在同一个进程里开一个 WebView2 窗口加载本地 HTML」 |
> | **`src/media.py` 的 docstring** | 「pywebview 的页面来源是 **`http://127.0.0.1:<随机端口>/`**，**不是 `file://`**」 |
>
> **`media.py` 是对的** —— 它的整段解释（WebView2 的 URL 安全检查、Range 请求、为什么要用联接）
> **只有在一个真实 HTTP 服务器存在时才讲得通**。
> **`app_web.py` 那句"无端口"是错的。**
>
> **→ 已列进 [log.md](log.md) 未解决 5。整理时未改代码。**

---

## 三、端口表

| 端口 | 谁 | 绑定 | 常驻 | 说明 |
| --- | --- | --- | --- | --- |
| **随机高位** | **pywebview 内部 HTTP 服务器** | `127.0.0.1` | ❌ | 只在应用运行时存在。**随机、每次不同** |

**本项目自己不监听任何端口。**
**没有固定端口、没有计划任务、没有自启项。**

**实测（2026-10-03 整理时）**：**无进程、无监听**。

---

## 四、单实例闸

**`src/single_instance.py`** —— `app_web.py` 的 `main()` **第一件事**就是调它：

```python
import single_instance
why = single_instance.acquire()
if why is not None:
    ...
    return 0
```

**代码里的理由（原文）**：

> 为什么放在最前面：两个实例会**同时写 `data/workspace.json` 互相覆盖**；
> 而且用户很容易点到**跑着旧代码**的那个窗口
> （实测踩过：用户点「摄像头」半天没反应，因为他开的是改动之前的实例）。

**测试驱动可以靠环境变量 `VKB_NO_SINGLE_INSTANCE=1` 跳过这一道。**

**→ 所以这个应用"同时只能有一个实例"** —— 这不是服务，是一条运行时约束。

---

## 五、内部任务队列（也不是服务）

`src/jobs.py` 的 `JobQueue` —— **串行任务队列，daemon 线程**：

```python
queue_ = jobs.JobQueue()
queue_.start()
state.jobs = queue_
```

**关窗即随进程退出。** 用来跑转写、AI 清洗这类长任务（前端能显示进度、能取消）。

**→ 它不监听端口、不对外暴露，不是服务。**

---

## 六、外部前置条件

**没有。**

本项目**不依赖任何别的项目在跑**。
（对照：`github_operater` 硬依赖 `Note` 的 17321 接口 —— 本项目没有这类依赖。）

> ⚠️ 但它**依赖项目外的东西**：`D:\models\` 的 Whisper 模型 + `ffmpeg`（含从 `catcher` 借）
> —— 见 [deps.md](deps.md) 第三、四节。**那些是资源依赖，不是"有服务在跑"。**
