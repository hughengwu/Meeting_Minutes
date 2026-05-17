# 会议记录

本地部署的会议语音转录系统。上传录音文件，自动完成语音识别和说话人分离，生成带时间戳的会议记录，支持音频同步高亮、在线编辑和导出。

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
- 磁盘空间：模型约 1.6 GB，Python 依赖约 4 GB

---

## 首次安装

在 WSL 终端中执行：

```bash
# 1. 安装系统依赖、Python 3.12 环境、前端依赖
./setup.sh

# 2. 下载 FunASR 模型（约 1.6 GB，仅需一次）
./download_models.sh
```

`setup.sh` 自动完成：
- 安装 ffmpeg、redis、git 等系统包
- 安装 [uv](https://github.com/astral-sh/uv) 并创建 Python 3.12 虚拟环境（`.venv`）
- 安装所有 Python 依赖（含 PyTorch CUDA 12.1）
- 安装前端 Node.js 依赖

---

## 启动 / 停止 / 重启

```bash
./start.sh                  # 启动所有服务
./stop.sh                   # 停止所有服务
./stop.sh && ./start.sh     # 重启
```

启动后访问：
- **前端**：http://localhost:5173
- **后端 API**：http://localhost:8000/docs

`start.sh` 会阻塞终端（Ctrl+C 或另开终端执行 `./stop.sh` 来停止）。日志写入 `.logs/` 目录。

---

## 使用流程

### 1. 上传录音

首页点击「上传音频」，选择文件后弹出确认框。

支持格式：`MP3` `WAV` `M4A` `FLAC` `OGG` `MP4` `WEBM`

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
# Redis 地址（默认本机，通常无需修改）
REDIS_URL=redis://localhost:6379/0

# FunASR 全局热词（也可在每次上传时单独填写）
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
服务重启后会自动恢复未完成任务。如仍无响应，检查 `.logs/worker.log` 是否有报错。

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
│   │   └── jobs.py         # 任务状态查询
│   ├── main.py             # 上传接口、启动恢复逻辑
│   ├── pipeline.py         # FunASR 转录流水线
│   ├── worker.py           # Celery 异步任务
│   ├── models.py           # SQLAlchemy 数据模型
│   └── database.py         # 数据库初始化与迁移
├── frontend/
│   └── src/
│       ├── api/index.js    # 后端接口封装
│       ├── pages/
│       │   ├── Home.jsx    # 会议列表 + 上传
│       │   └── Meeting.jsx # 会议详情 + 播放器
│       └── components/
│           ├── AudioPlayer.jsx      # 音频播放器（支持拖动 seek）
│           ├── TranscriptBlock.jsx  # 单条转录段落
│           ├── ExportPanel.jsx      # 导出面板
│           ├── LogViewer.jsx        # 处理日志查看
│           └── ProcessingStatus.jsx # 处理进度显示
├── data/                   # 运行时数据（gitignore）
│   ├── uploads/            # 上传的音频文件
│   ├── logs/               # 每次转录的处理日志
│   ├── models/             # FunASR 模型缓存
│   └── meetings.db         # SQLite 数据库
├── pyproject.toml          # Python 依赖（uv 管理）
├── setup.sh                # 一键安装
├── start.sh                # 启动所有服务
├── stop.sh                 # 停止所有服务
└── download_models.sh      # 下载 FunASR 模型
```
