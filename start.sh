#!/bin/bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_DIR="$ROOT_DIR/.pids"
LOG_DIR="$ROOT_DIR/.logs"

mkdir -p "$PID_DIR" "$LOG_DIR"

# 用 uv run 执行，环境由 uv 解析（本地 .venv / 集中式 ~/.uv_envs 都自动适配）。
#   --project "$ROOT_DIR"：锁定项目，不受调用方 cwd 影响
#   --no-sync           ：尊重手动维护的环境，不自动重建/改动
if ! command -v uv >/dev/null 2>&1; then
    echo "[error] 未找到 uv，请先安装（brew install uv）或将其加入 PATH"
    exit 1
fi

# 确定环境位置：优先集中式 ~/.uv_envs/<项目名>（与 ~/.zshrc 钩子命名一致）；
# 不存在则清掉变量，交给 uv 默认（项目本地 .venv）。显式设定，避免继承到
# 调用方 shell 里指向别的项目的 UV_PROJECT_ENVIRONMENT。
_proj_env="$HOME/.uv_envs/$(basename "$ROOT_DIR")"
if [ -x "$_proj_env/bin/python" ]; then
    export UV_PROJECT_ENVIRONMENT="$_proj_env"
    echo "[venv]    使用集中式环境 $_proj_env"
else
    unset UV_PROJECT_ENVIRONMENT
    echo "[venv]    使用 uv 默认环境（项目本地 .venv）"
fi

UV_RUN=(uv run --project "$ROOT_DIR" --no-sync)

export MODELSCOPE_CACHE="$ROOT_DIR/data/models"
export MODELSCOPE_OFFLINE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# ── Redis ──────────────────────────────────────────────────
if redis-cli ping &>/dev/null 2>&1; then
    echo "[redis]   已在运行"
else
    echo "[redis]   启动中..."
    redis-server \
        --daemonize yes \
        --logfile "$LOG_DIR/redis.log" \
        --pidfile "$PID_DIR/redis.pid"
fi

# ── Backend ────────────────────────────────────────────────
echo "[backend] 启动中 → http://localhost:8000"
cd "$ROOT_DIR/backend"
"${UV_RUN[@]}" uvicorn main:app --host 0.0.0.0 --port 8000 \
    > "$LOG_DIR/backend.log" 2>&1 &
echo $! > "$PID_DIR/backend.pid"

# ── Celery Worker ──────────────────────────────────────────
echo "[worker]  启动中 (GPU)..."
cd "$ROOT_DIR/backend"
PYTHONPATH="$ROOT_DIR/backend" "${UV_RUN[@]}" celery -A worker worker --loglevel=info --concurrency=1 \
    > "$LOG_DIR/worker.log" 2>&1 &
echo $! > "$PID_DIR/worker.pid"

# ── Frontend ───────────────────────────────────────────────
echo "[frontend] 启动中 → http://localhost:5173"
cd "$ROOT_DIR/frontend"
npm run dev -- --host 0.0.0.0 \
    > "$LOG_DIR/frontend.log" 2>&1 &
echo $! > "$PID_DIR/frontend.pid"

cd "$ROOT_DIR"

echo ""
echo "=============================="
echo "  前端:  http://localhost:5173"
echo "  后端:  http://localhost:8000"
echo "  日志目录: .logs/"
echo "=============================="
echo "停止服务: ./stop.sh  或  Ctrl+C"
echo ""

cleanup() {
    echo ""
    echo "正在停止所有服务..."
    kill "$(cat "$PID_DIR/backend.pid"  2>/dev/null)" 2>/dev/null || true
    kill "$(cat "$PID_DIR/worker.pid"   2>/dev/null)" 2>/dev/null || true
    kill "$(cat "$PID_DIR/frontend.pid" 2>/dev/null)" 2>/dev/null || true
    redis-cli shutdown 2>/dev/null || true
    rm -rf "$PID_DIR"
    echo "已停止"
    exit 0
}
trap cleanup INT TERM

wait
