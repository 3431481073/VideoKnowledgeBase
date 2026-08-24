# VideoKnowledgeBase

个人视频知识库管理系统。

## 功能
- 导入视频，批量转写
- 批量 AI 整理，生成标题和清洁原文
- 知识树手动构建、合并、拆分
- 视频连续播放
- 自动备份

## 安装
1. 创建虚拟环境：`python -m venv venv`
2. 激活：`venv\Scripts\activate`（Windows）
3. 安装依赖：`pip install -r requirements.txt`

## 运行
`python src/main.py`

注意：需要将 `transcriber.py` 中的 `MODEL_PATH` 修改为你本地的 Whisper 模型路径。