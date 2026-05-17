# 会议记录

本地部署的会议语音转录系统。上传录音文件，自动完成语音识别、说话人分离，生成带时间戳的会议记录，支持导出 Markdown / 纯文本。

## 技术栈

| 层级 | 组件 |
|------|------|
| 语音识别 | FunASR Paraformer-zh（中文优化） |
| 说话人分离 | cam++（内置，无需 HuggingFace Token） |
| 任务队列 | Celery + Redis |
| 后端 | FastAPI + SQLite |
| 前端 | React + Tailwind CSS + Vite |
| 运行环境 | WSL2 + NVIDIA CUDA |

---

## 环境要求

- Windows + WSL2（Ubuntu）
- NVIDIA GPU，显存 ≥ 6 GB（推荐 8 GB+）
- CUDA 12.1 驱动（Windows 侧安装即可）
- 磁盘空间：模型约 1.6 GB，项目依赖约 4 GB

---

## 首次安装

在 WSL 终端中执行：

```bash
# 1. 安装系统依赖、uv、Python 3.12、前端依赖
./setup.sh

# 2. 下载 FunASR 模型（约 1.6 GB，仅需一次）
./download_models.sh
```

`setup.sh` 会自动完成：
- 安装 ffmpeg、redis、git 等系统包
- 安装 [uv](https://github.com/astral-sh/uv) 并创建 Python 3.12 虚拟环境（`.venv`）
- 安装所有 Python 依赖（含 PyTorch CUDA 12.1）
- 安装前端 Node.js 依赖

---

## 启动 / 停止 / 重启

```bash
./start.sh    # 启动所有服务
./stop.sh     # 停止所有服务
./stop.sh && ./start.sh   # 重启
```

启动后访问：
- **前端**：http://localhost:5173
- **后端 API**：http://localhost:8000

`start.sh` 会阻塞终端（按 Ctrl+C 或另开终端执行 `./stop.sh` 来停止）。

---

## 使用流程

### 1. 上传录音

点击右上角「上传音频」按钮，或将文件拖入页面。

支持格式：`MP3` `WAV` `M4A` `FLAC` `OGG` `MP4` `WEBM`

### 2. 填写会议背景（可选，推荐填写）

上传前会弹出确认框，可以填写：

- 参与者姓名（如：`张三 李四 王五`）
- 专业术语（如：`Kubernetes 微服务 ROI`）
- 会议背景描述（如：`Q2产品规划会议`）

热词和背景文字混写即可，空格或换行分隔。填写后识别准确率明显提升。

### 3. 等待处理

处理过程在后台运行，页面实时显示进度和日志。GPU 处理速度约为音频时长的 1/5。

首次加载模型需要额外 30–60 秒。

### 4. 查看结果

处理完成后自动跳转到会议详情页，包含：

- **音频播放器**：可随时回听原始录音
- **转录内容**：按说话人分段，显示时间戳
- **说话人重命名**：点击说话人标签（`SPEAKER_00` 等）可修改为真实姓名
- **编辑文字**：点击任意段落可直接编辑识别内容

### 5. 导出

详情页右上角支持：
- **Markdown**：带格式的 `.md` 文件
- **纯文本**：`.txt` 文件
- **复制**：直接复制到剪贴板

---

## 配置说明

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

`.env` 中的可配置项：

```env
# Redis 地址（默认本机，一般不需要修改）
REDIS_URL=redis://localhost:6379/0

# FunASR 全局热词（可选，也可在每次上传时单独填写）
FUNASR_HOTWORDS=
```

---

## 查看日志

```bash
tail -f .logs/backend.log    # FastAPI 后端
tail -f .logs/worker.log     # Celery 转录任务（含模型输出）
tail -f .logs/frontend.log   # Vite 前端
```

---

## 常见问题

**Q：上传后一直显示「等待处理」？**
重启服务后，系统会自动恢复之前未完成的任务。如仍未响应，检查 `.logs/worker.log` 是否有报错。

**Q：说话人分离效果差，所有人都是同一个？**
在上传时填写热词（参与者姓名）有助于区分。cam++ 对 3 人以上、说话风格差异明显的场景效果更好。

**Q：显存不足报错？**
在 `.env` 中加入 `CUDA_VISIBLE_DEVICES=-1` 强制使用 CPU（速度变慢约 5 倍）。

**Q：如何重新处理已上传的录音？**
目前需要删除记录后重新上传。

---

## 目录结构

```
├── backend/          # FastAPI 后端
│   ├── main.py       # 上传接口、启动恢复逻辑
│   ├── pipeline.py   # FunASR 转录流水线
│   ├── worker.py     # Celery 任务
│   ├── models.py     # 数据库模型
│   └── api/          # 会议、任务 API 路由
├── frontend/         # React 前端
│   └── src/
│       ├── pages/    # Home（列表）、Meeting（详情）
│       └── components/
├── data/             # 运行时数据（gitignore）
│   ├── uploads/      # 上传的音频文件
│   ├── logs/         # 每个会议的处理日志
│   └── meetings.db   # SQLite 数据库
├── pyproject.toml    # Python 依赖（uv 管理）
├── setup.sh          # 一键安装
├── start.sh          # 启动所有服务
├── stop.sh           # 停止所有服务
└── download_models.sh # 下载 FunASR 模型
```
