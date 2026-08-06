# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

本地部署的会议录音转文字 Web 应用，**仅面向 Windows 原生环境**（Windows 10/11 + NVIDIA GPU），所有脚本都是 PowerShell，不再维护 Linux/WSL 的 `.sh` 版本。核心能力：中文/多语言语音转文字、说话人分离、音频回放同步高亮、热词提示、多 ASR 模型可切换、字幕翻译成中文、SRT/VTT 字幕导出（原文/中文/双语）。

## 启动与开发

```powershell
.\setup.ps1              # 一次性安装（uv + Node.js + ffmpeg + 系统依赖）
.\download_models.ps1    # 首次下载默认模型（可选，也可在前端「模型管理」里下载）
.\start.ps1              # 启动所有服务（后台进程，立即返回）
.\stop.ps1               # 停止所有服务
```

服务地址：前端 `http://localhost:5173`，后端 API `http://localhost:8000`

### 单独启动某个服务（调试用）

```powershell
.\.venv\Scripts\Activate.ps1
$env:MODELSCOPE_CACHE = "$PWD\data\models"

# 后端（转录/下载任务的后台线程随 FastAPI 启动事件自动拉起，无需单独进程）
cd backend; uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 前端
cd frontend; npm run dev
```

### 查看运行日志

```powershell
Get-Content -Wait -Tail 50 .logs\backend.log   # 最重要：转录进度、模型加载、下载、错误信息
Get-Content -Wait -Tail 50 .logs\frontend.log
```

每次转录另有单独日志 `data/logs/{meeting_id}.log`，前端「处理日志」面板轮询展示。

## 技术栈

| 层 | 技术 |
|---|---|
| ASR + 说话人分离 | **FunASR**（paraformer-zh / SenseVoice + fsmn-vad + ct-punc + cam++）、**FireRedASR-AED**（默认，CER 更低） |
| 字幕翻译 | Google 免费接口 / Google Cloud Translation v2 / LM Studio 本地模型（OpenAI 兼容），仅用标准库 urllib 调用，无额外依赖 |
| 任务队列 | 进程内线程队列（标准库 `threading` + `queue`），单机单 GPU 场景无需 Celery/Redis |
| 后端 | FastAPI + SQLite |
| 前端 | React + Vite + Tailwind CSS |
| Python 环境 | **uv**（pyproject.toml），Python 3.12，虚拟环境在 `.venv/` |

## 架构要点

### 多模型管理

`backend/model_manager.py` 维护可选模型注册表（`MODELS` 字典）：

- `firered-aed`（默认）：小红书 FireRedASR-AED，中文 CER 更低，从 HuggingFace 下载
- `paraformer`：阿里 FunASR Paraformer-zh，与 `download_models.ps1` 下载的模型一致
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

热词（`hotword` 参数）用于提升专有名词识别率（仅 FunASR 系列模型支持）。模型下载任务（`enqueue_model_download()`）、字幕翻译任务（`enqueue_translate()`）与转录任务共用同一个后台线程队列，串行处理。

### 两种处理模式

`meetings.mode` 决定 `pipeline.process_audio(..., diarize=)`：

- `meeting`（默认）：原有流程，跑 cam++ 做说话人分离，`sentence_info` 给出句子边界
- `subtitle`（字幕模式）：`_process_subtitle()`，只用 fsmn-vad 切句（`max_single_segment_time=15s`）后逐段识别，**不加载 cam++**；FireRedASR 路径下还省掉了原本仅为拿句子边界而跑的整段 Paraformer。`speaker` 存 NULL，前端相应隐藏说话人 UI；VAD 段就是天然字幕边界，因此**不做 `_merge_segments`**（合并会拼出横跨几十秒的长字幕）

显存注意：`punc_ct-transformer_cn-en-common-vocab471067-large`（ct-punc）词表 47 万，embedding + 输出层就要 1.5GB 以上，是流水线里最大的一块。字幕模式下 SenseVoice 开 `use_itn` 自带标点，故不挂 ct-punc；paraformer 原始输出无标点才需要。字幕模式 `batch_size_s` 用 60（会议模式是 300），降低激活值峰值。

### 字幕翻译

`backend/translator.py` 提供三个后端（`PROVIDERS`）：`google_free`（默认，免 Key，国内需代理）、`google_v2`（官方接口 + API Key）、`lmstudio`（本机 OpenAI 兼容接口）。全部用标准库 `urllib` 请求，不引入新依赖；访问 localhost 的 LM Studio 时强制绕过代理。配置写在 `data/config.json` 的 `translation` 键下（与 `active_model` 同文件，双方都是「读整个 dict → 改自己那部分 → 写回」），`.env` 里的同名变量作为默认值。

翻译**不覆盖识别原文**：原文在 `utterances.text`，译文在 `utterances.text_zh`，因此翻译前后的字幕都能导出。已是目标语言的片段（`_needs_translation()` 判断）直接沿用原文，不发请求。`_translate_task()` 默认只补翻 `text_zh` 为空的片段，`force=True` 时全部重译。

SenseVoice 流水线里的本地 opus-mt 翻译同样写入 `text_zh`（历史上它会覆盖 `text`，已改）。

`_needs_no_translation()` 判断「已经是中文、不必发请求」时**必须先查假名/谚文**（`_NON_ZH_SCRIPT_RE`）：日文汉字与中文汉字码位完全相同，只统计汉字占比会把汉字密集的日文整句误判成中文而跳过翻译（实测「誤って川に転落した七歳。」汉字占 6/11 = 0.55，恰好越过 0.5 阈值）。纯汉字无假名的日文（如「七歳」）无法区分，只能接受。同一盲点在 `_looks_untranslated()` 里也要堵：译文里残留假名/谚文即视为没翻干净。

**LM Studio 后端的防漏翻处理**（小参数量本地模型常见失效模式，改动前踩过）：

- 系统提示词里**刻意不写**「原文已是目标语言就原样返回」——那等于给模型开了照抄的口子；已是目标语言的片段在 `translate_texts()` 里就被挑掉了，真正发出去的每条都必须产出译文
- 请求带 `response_format` 的 JSON Schema（约束成 `{"translations": [...]}` 且 `minItems=maxItems=条数`）和 `chat_template_kwargs.enable_thinking=false`；不认这两个字段的服务会返回 4xx，`_lmstudio_once()` 检测到后去掉可选参数重发一次
- 混合推理模型（qwen3 系列）的 `<think>` 块会混进 `content`，里面的方括号会让 JSON 提取错位：`_strip_reasoning()` 先剥离；未闭合的 `<think>`（输出被截断）直接判为无译文。`_extract_json_arrays()` 做括号配对扫描而不是 `find("[")`/`rfind("]")`
- `_looks_untranslated()` 校验每条译文：空 / 原样回抄 / 目标是中文却一个汉字都没有 → 单条重发一次；仍不行就**留 None（留空），绝不把原文写进 `text_zh`**，否则会被当成"已翻译"永久固化，再点「翻译」也不会补翻。单个词的片段（`Kubernetes`、`API`）原样返回属于正确译法，不算漏翻
- `_LMSTUDIO_BATCH = 4`（原来是 8）：本地推理没有额度成本，条数少漏翻率明显更低

`backend/subtitle.py` 负责 SRT/VTT 生成：`build_cues()` 按显示宽度（CJK 记 2）和时长约束切分过长片段，英文断在词边界；双语字幕不切分（两种语言切分后容易错位）。

### 数据流

- `DATA_DIR`（`database.py` 导出）是全局路径锚点，`worker.py`、`model_manager.py`、`api/meetings.py` 都从它构建子路径
- 模型缓存：`data/models/`（通过 `MODELSCOPE_CACHE` 环境变量指定，`start.ps1` 设置）
- 音频文件：`data/uploads/{meeting_id}{ext}`
- 处理日志：`data/logs/{meeting_id}.log`（worker 写入，前端轮询展示）
- 数据库：`data/meetings.db`（SQLite）

### 数据库 Schema

后加的列都在 `database.py` 的 `init_db()` 里用 `ALTER TABLE` 做迁移兼容（`migrations` 列表，逐表检查列是否存在），无需手动跑迁移脚本：`meetings.hotwords`、`meetings.auto_translate`、`utterances.text_zh`、`jobs.kind`。

`jobs.kind` 区分 `transcribe` / `translate`，历史行由 SQLite 的 `ADD COLUMN ... DEFAULT 'transcribe'` 自动回填；查询转录任务时仍用 `or_(Job.kind == "transcribe", Job.kind.is_(None))` 兜底。`main.py::_recover_pending_jobs()` 按 `kind` 分派重新入队。

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

`MODELSCOPE_CACHE` 由 `start.ps1` 在启动时设置，不放在 `.env` 里。

## 前端 API 约定

所有请求通过 `frontend/src/api/index.js` 发出，base URL 为 `/api`（Vite dev 模式代理到 `localhost:8000`）。关键接口：

- `POST /api/upload` — 接收 `file`（multipart）、`hotwords`、`translate`（form field，`"1"` 表示转录后自动翻译）
- `GET /api/meetings/{id}/audio` — 支持 Range 请求的音频流
- `GET /api/meetings/{id}/logs` — 返回 `{ lines: string[] }`，前端每 2 秒轮询
- `GET /api/jobs/{id}` — 返回 `{ status, progress, error_message }`
- `GET /api/models/` — 模型列表及下载/激活状态
- `POST /api/models/{id}/download` — 触发模型下载（异步，进度轮询 `GET /api/models/{id}/status`）
- `POST /api/models/active` — 切换激活模型（需已下载）
- `POST /api/meetings/{id}/translate` — 发起字幕翻译（body `{force}`），进度看会议详情里的 `translate_job`
- `GET /api/meetings/{id}/export?format=srt|vtt|markdown|text&lang=original|zh|bilingual&speaker=0|1` — 返回 `{ content, title, filename }`
- `GET|POST /api/translation/settings`、`POST /api/translation/test`、`GET /api/translation/lmstudio/models` — 翻译服务配置与自检

`error_message` 字段在处理中被复用为当前阶段描述文字（非错误时），`ProcessingStatus` 组件直接展示该字段。
