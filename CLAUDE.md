# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

本地部署的会议录音转文字 Web 应用，运行在 WSL2 + NVIDIA GPU 上。核心能力：中文语音转文字、说话人分离、音频回放同步高亮、热词提示。

## 启动与开发

```bash
# 一次性安装（uv + Node.js + 系统依赖）
./setup.sh

# 首次下载模型（FunASR 模型，约 2GB）
./download_models.sh

# 启动所有服务（Redis / FastAPI / Celery worker / Vite）
./start.sh

# 停止所有服务
./stop.sh
```

服务地址：前端 `http://localhost:5173`，后端 API `http://localhost:8000`

### 单独启动某个服务（调试用）

```bash
source .venv/bin/activate
export MODELSCOPE_CACHE="$(pwd)/data/models"

# 后端
cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Worker
cd backend && PYTHONPATH="$(pwd)/backend" celery -A worker worker --loglevel=info --concurrency=1

# 前端
cd frontend && npm run dev
```

### 查看运行日志

```bash
tail -f .logs/worker.log    # 最重要：转录进度、模型加载、错误信息
tail -f .logs/backend.log
tail -f .logs/frontend.log
```

## 技术栈

| 层 | 技术 |
|---|---|
| ASR + 说话人分离 | **FunASR**（paraformer-zh + fsmn-vad + ct-punc + cam++） |
| 后端 | FastAPI + Celery + Redis + SQLite |
| 前端 | React + Vite + Tailwind CSS |
| Python 环境 | **uv**（pyproject.toml），Python 3.12，虚拟环境在 `.venv/` |

## 架构要点

### 处理流水线

```
上传音频 → FastAPI 写文件 → Celery 任务入队
    ↓
Worker（GPU）：FunASR AutoModel.generate()
    → paraformer-zh 转录
    → fsmn-vad 语音活动检测
    → ct-punc 标点还原
    → cam++ 说话人分离
    → _merge_segments() 合并碎片段
    ↓
结果写入 SQLite utterances 表
每阶段进度 → data/logs/{meeting_id}.log
```

所有模型在一次 `AutoModel.generate()` 调用中完成，无需拼接多个步骤。热词（`hotword` 参数）直接传入 FunASR 以提升专有名词识别率。

### 数据流

- `DATA_DIR`（`database.py` 导出）是全局路径锚点，`worker.py` 和 `api/meetings.py` 都从它构建子路径
- 模型缓存：`data/models/`（通过 `MODELSCOPE_CACHE` 环境变量指定，`start.sh` 设置）
- 音频文件：`data/uploads/{meeting_id}{ext}`
- 处理日志：`data/logs/{meeting_id}.log`（Worker 写入，前端轮询展示）
- 数据库：`data/meetings.db`（SQLite）

### 数据库 Schema

`Meeting` 表有 `hotwords` 列（后加），`database.py` 的 `init_db()` 用 `ALTER TABLE` 做迁移兼容，无需手动跑迁移脚本。

### 音频回放与字幕同步

`AudioPlayer` 通过 `forwardRef` 暴露 `seek(time)` 方法，`Meeting.jsx` 持有 `audioPlayerRef`。`currentTime` state 驱动 `activeId` 计算（当前播放位置落在哪个 utterance 区间）；`TranscriptBlock` 接收 `isActive` prop 做高亮，并将自己的 DOM ref 注册到父组件的 `blockRefs` map 中用于自动滚动。用户手动滚动时 `autoScroll` 暂停 3 秒后恢复。

### 音频流式传输

`api/meetings.py` 中 `GET /{meeting_id}/audio` 手动实现了 HTTP Range 请求（206 Partial Content），让浏览器能任意跳转而不必下载整个文件。

### 任务恢复

`main.py` 的 `_recover_pending_jobs()` 在后端启动时把数据库里所有 `pending/processing` 状态的任务重新入 Celery 队列，解决服务重启导致任务丢失的问题。

## 环境变量（`.env`）

```
HF_TOKEN=          # HuggingFace token（当前 FunASR 流程不需要，保留备用）
REDIS_URL=redis://localhost:6379/0
HF_ENDPOINT=https://hf-mirror.com
```

`MODELSCOPE_CACHE` 由 `start.sh` 在 shell 层设置，不放在 `.env` 里。

## 前端 API 约定

所有请求通过 `frontend/src/api/index.js` 发出，base URL 为 `/api`（Vite dev 模式代理到 `localhost:8000`）。关键接口：

- `POST /api/upload` — 接收 `file`（multipart）和 `hotwords`（form field）
- `GET /api/meetings/{id}/audio` — 支持 Range 请求的音频流
- `GET /api/meetings/{id}/logs` — 返回 `{ lines: string[] }`，前端每 2 秒轮询
- `GET /api/jobs/{id}` — 返回 `{ status, progress, error_message }`

`error_message` 字段在处理中被复用为当前阶段描述文字（非错误时），`ProcessingStatus` 组件直接展示该字段。
