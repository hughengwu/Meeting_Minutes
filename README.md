# 会议记录

本地部署的会议语音转录系统。上传录音文件，自动完成语音识别和说话人分离，生成带时间戳的会议记录，支持音频同步高亮、在线编辑和导出。

## 技术栈

| 层级 | 组件 |
|------|------|
| 语音识别 | 可切换：FireRedASR-AED（默认）/ FunASR Paraformer-zh / FunASR SenseVoice（多语言） |
| 说话人分离 | cam++（内置，无需 HuggingFace Token） |
| 任务队列 | 进程内线程队列（标准库 threading + queue，单机单 GPU 场景无需 Celery/Redis） |
| 后端 | FastAPI + SQLite |
| 前端 | React + Tailwind CSS + Vite |
| 运行环境 | Windows 原生 或 WSL2 / Linux + NVIDIA CUDA |

---

## 环境要求

- Windows 10/11（原生 PowerShell 即可，也可用 WSL2/Linux）
- NVIDIA GPU，显存 ≥ 6 GB（推荐 8 GB+）
- CUDA 12.1 驱动
- 磁盘空间：模型约 1.6 GB，Python 依赖约 4 GB

---

## 首次安装

### 方式一：Windows 原生（PowerShell）

```powershell
# 若提示脚本被禁止运行，先执行一次：
# Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 1. 安装 ffmpeg / uv / Python 3.12 环境 / 前端依赖
.\setup.ps1

# 2. 下载 FunASR 模型（约 1.6 GB，仅需一次）
.\download_models.ps1
```

### 方式二：WSL2（Ubuntu）/ Linux

```bash
# 1. 安装系统依赖、Python 3.12 环境、前端依赖
./setup.sh

# 2. 下载 FunASR 模型（约 1.6 GB，仅需一次）
./download_models.sh
```

`setup.ps1` / `setup.sh` 自动完成：
- 安装 ffmpeg、git 等系统依赖（Windows 下通过 winget，Linux 下通过 apt）
- 安装 [uv](https://github.com/astral-sh/uv) 并创建 Python 3.12 虚拟环境（`.venv`）
- 安装所有 Python 依赖（含 PyTorch CUDA 12.1）
- 安装前端 Node.js 依赖

不再需要安装 Redis：任务队列已改为进程内线程队列（见下方"任务队列"说明），Windows 原生环境无需额外中间件。

---

## 启动 / 停止 / 重启

**Windows 原生：**

```powershell
.\start.ps1                  # 启动所有服务（后台进程，立即返回）
.\stop.ps1                   # 停止所有服务
.\stop.ps1; .\start.ps1      # 重启
```

**WSL2 / Linux：**

```bash
./start.sh                  # 启动所有服务
./stop.sh                   # 停止所有服务
./stop.sh && ./start.sh     # 重启
```

启动后访问：
- **前端**：http://localhost:5173
- **后端 API**：http://localhost:8000/docs

`start.sh` 会阻塞终端（Ctrl+C 或另开终端执行 `./stop.sh` 来停止）；`start.ps1` 则以后台进程启动后立即返回终端，用 `.\stop.ps1` 停止。两者日志都写入 `.logs/` 目录。

---

## 任务队列说明

音频转录是 CPU/GPU 密集型任务，需要在后台异步处理，避免阻塞上传请求。本项目在同一 Python 进程内用标准库 `threading` + `queue.Queue` 实现了一个单工作线程的任务队列（`backend/worker.py`），串行处理转录任务——这与原先 Celery 单 worker、`concurrency=1` 的效果一致，但去掉了 Redis 依赖，因此在 Windows 原生环境下也能直接运行（无需 WSL/Docker/Memurai 等）。

代价：转录任务和 API 服务共享同一进程，如果转录过程中发生底层崩溃（例如显卡驱动异常导致的 CUDA 段错误），会影响到整个后端进程，而不仅仅是转录任务本身。对于本项目单机单用户的使用场景，这个取舍是合理的；如果未来需要多机分布式处理，再引入 Celery/Redis（或云队列服务）会更合适。

---

## 模型管理

首页「模型管理」面板可以下载/切换语音识别模型：

- **FireRedASR-AED**（默认）：中文识别精度更高，从 HuggingFace 下载（约 350MB），显存需求约 8GB
- **Paraformer-zh**：阿里 FunASR，显存需求约 4GB，即 `download_models.sh`/`download_models.ps1` 下载的模型
- **SenseVoice 多语言**：支持中/英/日/韩/粤，非中文自动翻译成中文，显存需求约 4GB

未下载的模型无法被激活；上传音频时会先检查当前激活模型是否已下载。下载/激活状态保存在 `data/config.json` 和 `data/download_status/`（均为本机运行时数据，不纳入版本控制）。

---

## 使用流程

### 1. 上传录音

首页点击「上传音频」，选择文件后弹出确认框。

支持格式：`MP3` `WAV` `M4A` `FLAC` `OGG` `MP4` `MKV` `AVI` `MOV` `WEBM`（视频文件会自动提取音轨）

### 2. 填写会议背景（可选，推荐）

确认框中可填写热词，提升识别准确率：

- 参与者姓名（如：`张三 李四 王五`）
- 专业术语（如：`Kubernetes 微服务 ROI`）
- 会议背景（如：`Q2产品规划会议`）

空格或换行分隔均可。

### 3. 等待处理

转录在后台进行，页面实时显示进度和日志。GPU 处理速度约为音频时长的 1/5，首次加载模型额外需要 30–60 秒。

### 4. 查看和编辑结果

处理完成后自动跳转会议详情页：

- **音频播放器**：悬浮在页面顶部，滚动页面时始终可见
- **同步高亮**：播放时自动高亮当前段落并滚动跟随
- **点击跳转**：单击任意段落的时间戳或文字，音频跳转到对应位置
- **拖动进度条**：拖动播放进度条到任意位置
- **说话人重命名**：点击说话人标签（`SPEAKER_00` 等）修改为真实姓名
- **编辑文字**：双击任意段落直接编辑识别内容

### 5. 导出

详情页右上角支持导出为：
- **Markdown**：带格式的 `.md` 文件
- **纯文本**：`.txt` 文件
- **复制到剪贴板**

---

## 配置

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

可配置项：

```env
# FunASR 全局热词（也可在每次上传时单独填写）
FUNASR_HOTWORDS=
```

---

## 查看日志

```bash
tail -f .logs/backend.log    # FastAPI 后端 + 转录后台线程（含模型输出）
tail -f .logs/frontend.log   # Vite 前端
```

Windows 原生下用 `Get-Content -Wait -Tail 50 .logs\backend.log` 效果相同。每次转录另外还会写入 `data/logs/<meeting_id>.log`（详情页「处理日志」面板读取的就是这个文件）。

---

## 常见问题

**Q：上传后一直显示「等待处理」？**
服务重启后会自动恢复未完成任务。如仍无响应，检查 `.logs/backend.log` 是否有报错。

**Q：说话人分离效果差，所有人识别成同一个？**
上传时填写参与者姓名作为热词有助于改善。cam++ 在 3 人以上、说话风格差异明显时效果更好。

**Q：显存不足报错？**
在 `.env` 中加入 `CUDA_VISIBLE_DEVICES=-1` 强制使用 CPU（速度约慢 5 倍）。

**Q：如何重新处理已上传的录音？**
在详情页删除该记录后重新上传即可。

---

## 目录结构

```
├── backend/
│   ├── api/
│   │   ├── meetings.py     # 会议 CRUD、音频流、导出
│   │   ├── jobs.py         # 任务状态查询
│   │   └── models.py       # 模型列表/下载/切换接口
│   ├── main.py             # 上传接口、启动恢复逻辑
│   ├── pipeline.py         # 转录流水线（按激活模型分发）
│   ├── worker.py           # 进程内线程队列，异步执行转录/下载任务
│   ├── model_manager.py    # 模型注册表、下载状态、激活模型
│   ├── models.py           # SQLAlchemy 数据模型
│   └── database.py         # 数据库初始化与迁移
├── frontend/
│   └── src/
│       ├── api/index.js    # 后端接口封装
│       ├── pages/
│       │   ├── Home.jsx    # 会议列表 + 上传 + 模型管理入口
│       │   └── Meeting.jsx # 会议详情 + 播放器
│       └── components/
│           ├── AudioPlayer.jsx      # 音频播放器（支持拖动 seek）
│           ├── TranscriptBlock.jsx  # 单条转录段落
│           ├── ExportPanel.jsx      # 导出面板
│           ├── LogViewer.jsx        # 处理日志查看
│           ├── ProcessingStatus.jsx # 处理进度显示
│           └── ModelManager.jsx     # 模型下载/切换面板
├── data/                   # 运行时数据（gitignore）
│   ├── uploads/            # 上传的音频文件
│   ├── logs/               # 每次转录的处理日志
│   ├── models/             # ASR 模型缓存
│   ├── download_status/    # 各模型下载进度
│   ├── config.json         # 当前激活模型
│   └── meetings.db         # SQLite 数据库
├── pyproject.toml          # Python 依赖（uv 管理）
├── download_models.py      # 模型下载逻辑（被 .sh / .ps1 共用）
├── setup.sh / setup.ps1                # 一键安装（Linux/WSL / Windows 原生）
├── start.sh / start.ps1                # 启动所有服务
├── stop.sh / stop.ps1                  # 停止所有服务
└── download_models.sh / download_models.ps1  # 下载 FunASR 模型
```
