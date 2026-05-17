#!/bin/bash
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_DIR="$ROOT_DIR/.pids"

echo "停止服务..."
kill "$(cat "$PID_DIR/backend.pid"  2>/dev/null)" 2>/dev/null && echo "  backend  停止" || true
kill "$(cat "$PID_DIR/worker.pid"   2>/dev/null)" 2>/dev/null && echo "  worker   停止" || true
kill "$(cat "$PID_DIR/frontend.pid" 2>/dev/null)" 2>/dev/null && echo "  frontend 停止" || true
redis-cli shutdown 2>/dev/null && echo "  redis    停止" || true
rm -rf "$PID_DIR"
echo "完成"
