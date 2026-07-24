# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

本地部署的会议录音转文字 Web 应用，运行在 Windows 原生 或 WSL2/Linux + NVIDIA GPU 上。核心能力：中文/多语言语音转文字、说话人分离、音频回放同步高亮、热词提示、多 ASR 模型可切换。

## 启动与开发

**Windows 原生（PowerShell）：**

```powershell
.\setup.ps1              # 一次性安装（uv + Node.js + ffmpeg + 系统依赖）
.\download_models.ps1    # 首次下载默认模型（可选，也可在前端「模型管理」里下载）
.\start.ps1               # 启动所有服务（后台进程，立即返回）
.\stop.ps1                # 停止所有服务
```

**WSL2 / Linux：**

```bash
./setup.sh
./download_models.sh
./start.sh                  # 阻塞终端，Ctrl+C 或另开终端 ./stop.sh 停止
./stop.sh
```

服务地址：前端 `http://localhost:5173`，后端 API `http://localhost:8000`

### 单独启动某个服务（调试用，WSL/Linux 示例）

```bash
source .venv/bin/activate
export MODELSCOPE_CACHE="$(pwd)/data/models"

# 后端（转录/下载任务的后台线程随 FastAPI 启动事件自动拉起，无需单独进程）
cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 前端
cd frontend && npm run dev
```

### 查看运行日志

```bash
tail -f .logs/backend.log   # 最重要：转录进度、模型加载、下载、错误信息
tail -f .logs/frontend.log
```

Windows 下用 `Get-Content -Wait -Tail 50 .logs\backend.log`。每次转录另有单独日志 `data/logs/{meeting_id}.log`，前端「处理日志」面板轮询展示。

## 技术栈

| 层 | 技术 |
|---|---|
| ASR + 说话人分离 | **FunASR**（paraformer-zh / SenseVoice + fsmn-vad + ct-punc + cam++）、**FireRedASR-AED**（默认，CER 更低） |
| 任务队列 | 进程内线程队列（标准库 `threading` + `queue`），单机单 GPU 场景无需 Celery/Redis |
| 后端 | FastAPI + SQLite |
| 前端 | React + Vite + Tailwind CSS |
| Python 环境 | **uv**（pyproject.toml），Python 3.12，虚拟环境在 `.venv/` |

## 架构要点

### 多模型管理

`backend/model_manager.py` 维护可选模型注册表（`MODELS` 字典）：

- `firered-aed`（默认）：小红书 FireRedASR-AED，中文 CER 更低，从 HuggingFace 下载
- `paraformer`：阿里 FunASR Paraformer-zh，与 `download_models.sh/.ps1` 下载的模型一致
- `sensevoice-multilingual`：FunASR SenseVoice Small，支持中/英/日/韩/粤，非中文自动翻译（额外下载 opus-mt-en-zh）

当前激活模型记录在 `data/config.json`（运行时生成，已 gitignore），各模型下载进度记录在 `data/download_status/{model_id}.json`（同样 gitignore，机器本地状态，不提交）。`backend/api/models.py` 暴露 `GET /api/models/`、`POST /api/models/{id}/download`、`POST /api/models/active`，前端 `ModelManager.jsx` 组件调用这些接口。上传接口会先检查当前激活模型是否已下载，未下载则拒绝并提示。

### 处理流水线

```
上传音频/视频 → FastAPI 写文件 → enqueue_task() 入队（内存线程队列）
    ↓
worker 线程（GPU）：
    → 视频文件先用 ffmpeg 提取音轨为 WAV
    → pipeline.py 按当前激活模型分发（FireRedASR / FunASR paraformer / SenseVoice）
    → 说话人分离（cam++）
    → _merge_segments() 合并碎片段
    ↓
结果写入 SQLite utterances 表
每阶段进度 → data/logs/{meeting_id}.log
```

热词（`hotword` 参数）用于提升专有名词识别率（仅 FunASR 系列模型支持）。模型下载任务（`enqueue_model_download()`）与转录任务共用同一个后台线程队列，串行处理。

### 数据流

- `DATA_DIR`（`database.py` 导出）是全局路径锚点，`worker.py`、`model_manager.py`、`api/meetings.py` 都从它构建子路径
- 模型缓存：`data/models/`（通过 `MODELSCOPE_CACHE` 环境变量指定，`start.sh`/`start.ps1` 设置）
- 音频文件：`data/uploads/{meeting_id}{ext}`
- 处理日志：`data/logs/{meeting_id}.log`（worker 写入，前端轮询展示）
- 数据库：`data/meetings.db`（SQLite）

### 数据库 Schema

`Meeting` 表有 `hotwords` 列（后加），`database.py` 的 `init_db()` 用 `ALTER TABLE` 做迁移兼容，无需手动跑迁移脚本。

### 音频回放与字幕同步

`AudioPlayer` 通过 `forwardRef` 暴露 `seek(time)` 方法，`Meeting.jsx` 持有 `audioPlayerRef`。`currentTime` state 驱动 `activeId` 计算（当前播放位置落在哪个 utterance 区间）；`TranscriptBlock` 接收 `isActive` prop 做高亮，并将自己的 DOM ref 注册到父组件的 `blockRefs` map 中用于自动滚动。用户手动滚动时 `autoScroll` 暂停 3 秒后恢复。

### 音频流式传输

`api/meetings.py` 中 `GET /{meeting_id}/audio` 手动实现了 HTTP Range 请求（206 Partial Content），让浏览器能任意跳转而不必下载整个文件。

### 任务恢复

`main.py` 的 `_recover_pending_jobs()` 在后端启动时把数据库里所有 `pending/processing` 状态的任务重新入队（内存线程队列），解决服务重启导致任务丢失的问题。由于队列在进程内存中，服务重启会清空排队中但未开始的任务——这正是该函数存在的原因。

## 环境变量（`.env`）

```
HF_TOKEN=          # HuggingFace token（当前流程不需要，保留备用）
HF_ENDPOINT=https://hf-mirror.com   # 国内下载模型可换镜像
```

`MODELSCOPE_CACHE` 由 `start.sh`/`start.ps1` 在启动时设置，不放在 `.env` 里。

## 前端 API 约定

所有请求通过 `frontend/src/api/index.js` 发出，base URL 为 `/api`（Vite dev 模式代理到 `localhost:8000`）。关键接口：

- `POST /api/upload` — 接收 `file`（multipart）和 `hotwords`（form field）
- `GET /api/meetings/{id}/audio` — 支持 Range 请求的音频流
- `GET /api/meetings/{id}/logs` — 返回 `{ lines: string[] }`，前端每 2 秒轮询
- `GET /api/jobs/{id}` — 返回 `{ status, progress, error_message }`
- `GET /api/models/` — 模型列表及下载/激活状态
- `POST /api/models/{id}/download` — 触发模型下载（异步，进度轮询 `GET /api/models/{id}/status`）
- `POST /api/models/active` — 切换激活模型（需已下载）

`error_message` 字段在处理中被复用为当前阶段描述文字（非错误时），`ProcessingStatus` 组件直接展示该字段。
