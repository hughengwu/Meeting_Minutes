#!/bin/bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_DIR="$ROOT_DIR/.pids"
LOG_DIR="$ROOT_DIR/.logs"

mkdir -p "$PID_DIR" "$LOG_DIR"

source "$ROOT_DIR/venv/bin/activate"

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
uvicorn main:app --host 0.0.0.0 --port 8000 \
    > "$LOG_DIR/backend.log" 2>&1 &
echo $! > "$PID_DIR/backend.pid"

# ── Celery Worker ──────────────────────────────────────────
echo "[worker]  启动中 (GPU)..."
cd "$ROOT_DIR/backend"
PYTHONPATH="$ROOT_DIR/backend" celery -A worker worker --loglevel=info --concurrency=1 \
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
