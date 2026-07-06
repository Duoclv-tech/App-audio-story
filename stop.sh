#!/bin/bash

echo "🛑 Stopping TruyenFull Processor..."
echo ""

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

stop_by_pidfile() {
    local pidfile="$1"
    local label="$2"
    [ -f "$pidfile" ] || return 1
    local pid
    pid=$(cat "$pidfile" 2>/dev/null)
    rm -f "$pidfile"
    [ -z "$pid" ] && return 1
    if kill -0 "$pid" 2>/dev/null; then
        # kill the whole process group so uvicorn --reload children and vite die too
        kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
        sleep 1
        if kill -0 "$pid" 2>/dev/null; then
            kill -KILL -"$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
        fi
        echo -e "${GREEN}✅ $label stopped (PID $pid)${NC}"
        return 0
    fi
    return 1
}

stop_by_port() {
    local port="$1"
    local label="$2"
    local pids
    if command -v lsof &>/dev/null; then
        pids=$(lsof -ti :"$port" 2>/dev/null)
    elif command -v fuser &>/dev/null; then
        pids=$(fuser -n tcp "$port" 2>/dev/null | tr -s ' ' '\n')
    fi
    [ -z "$pids" ] && return 1
    echo "$pids" | xargs -r kill -TERM 2>/dev/null
    sleep 1
    pids=$(lsof -ti :"$port" 2>/dev/null)
    [ -n "$pids" ] && echo "$pids" | xargs -r kill -KILL 2>/dev/null
    echo -e "${GREEN}✅ $label on port $port stopped${NC}"
    return 0
}

# Backend
echo -e "${BLUE}[1/3] Stopping Backend...${NC}"
stop_by_pidfile "backend.pid" "Backend" || stop_by_port 8000 "Backend" \
    || echo -e "${YELLOW}⚠️  Backend not running${NC}"

# Frontend
echo -e "${BLUE}[2/3] Stopping Frontend...${NC}"
stop_by_pidfile "frontend.pid" "Frontend" || stop_by_port 5173 "Frontend" \
    || echo -e "${YELLOW}⚠️  Frontend not running${NC}"

# MySQL
echo -e "${BLUE}[3/3] Stopping MySQL container...${NC}"
if command -v docker &>/dev/null; then
    (cd docker && docker compose down >/dev/null 2>&1) \
        && echo -e "${GREEN}✅ MySQL stopped${NC}" \
        || echo -e "${YELLOW}⚠️  Failed to stop MySQL (already down?)${NC}"
else
    echo -e "${YELLOW}⚠️  Docker not found — skipping MySQL${NC}"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}✅ All services stopped!${NC}"
echo "=========================================="