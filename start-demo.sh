#!/usr/bin/env bash
# FieldOps demo startup — starts backend on :8001 and frontend on :5173
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "==> Starting FieldOps backend on :8001..."
cd "$ROOT/backend"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 &
BACKEND_PID=$!

echo "==> Waiting for backend..."
for i in $(seq 1 20); do
  if curl -s http://127.0.0.1:8001/health >/dev/null 2>&1; then
    echo "    Backend ready."
    break
  fi
  sleep 0.5
done

echo "==> Starting FieldOps frontend on :5173..."
cd "$ROOT/frontend"
VITE_API_BASE_URL=http://127.0.0.1:8001 npm run dev -- --host 127.0.0.1 --port 5173 &
FRONTEND_PID=$!

echo ""
echo "======================================"
echo "  FIELDOPS RUNNING"
echo "  Frontend: http://127.0.0.1:5173"
echo "  Backend:  http://127.0.0.1:8001"
echo "======================================"
echo "  Press Ctrl+C to stop both servers."
echo ""

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
