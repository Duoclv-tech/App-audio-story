#!/bin/bash

echo "🚀 Starting AudioStory..."
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed!"
    exit 1
fi

# Start MySQL
echo -e "${BLUE}📦 Starting MySQL...${NC}"
cd docker
docker compose up -d mysql
echo -e "${YELLOW}⏳ Waiting for MySQL to be ready (10 seconds)...${NC}"
sleep 10
cd ..

# Check if MySQL is ready
echo -e "${GREEN}✅ MySQL is ready${NC}"
echo ""

# Create logs directory
mkdir -p logs

# Start Backend
echo -e "${BLUE}🔧 Starting Backend (FastAPI)...${NC}"
cd backend

# Create venv if not exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies
if [ ! -f "venv/.installed" ]; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
    touch venv/.installed
fi

# Copy .env if not exists
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    cp .env.example .env
    echo -e "${YELLOW}⚠️  Please configure .env file with your settings${NC}"
fi

# Start backend in background
echo "Starting FastAPI server..."
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 > ../logs/backend.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > ../backend.pid

cd ..
echo -e "${GREEN}✅ Backend started (PID: $BACKEND_PID)${NC}"
echo ""

# Start Frontend
echo -e "${BLUE}🎨 Starting Frontend (React)...${NC}"
cd frontend

# Install dependencies if not exists
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Start frontend in background
echo "Starting Vite dev server..."
npm run dev > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > ../frontend.pid

cd ..
echo -e "${GREEN}✅ Frontend started (PID: $FRONTEND_PID)${NC}"
echo ""

# Summary
echo "=========================================="
echo -e "${GREEN}✅ All services started successfully!${NC}"
echo "=========================================="
echo ""
echo "🌐 Frontend:  http://localhost:5173"
echo "🔧 Backend:   http://localhost:8000"
echo "📚 API Docs:  http://localhost:8000/docs"
echo "🏥 Health:    http://localhost:8000/health"
echo ""
echo "📊 Logs:"
echo "   Backend:  tail -f logs/backend.log"
echo "   Frontend: tail -f logs/frontend.log"
echo ""
echo "To stop all services, run: ./stop.sh"
echo "=========================================="
