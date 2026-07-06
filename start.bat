@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo   TruyenFull Processor - Starting...
echo ========================================
echo.

:: Get script directory
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: Check Docker
echo [1/4] Checking Docker...
docker --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not installed or not running!
    echo Please install Docker Desktop and start it.
    pause
    exit /b 1
)
echo [OK] Docker is available

:: Start MySQL
echo.
echo [2/4] Starting MySQL container...
cd docker
docker compose up -d mysql
if errorlevel 1 (
    echo [ERROR] Failed to start MySQL container!
    pause
    exit /b 1
)
cd ..
echo [OK] MySQL container started
echo      Waiting 10 seconds for MySQL to be ready...
timeout /t 10 /nobreak >nul

:: Create logs directory
if not exist "logs" mkdir logs

:: Start Backend
echo.
echo [3/4] Starting Backend (FastAPI)...
cd backend

:: Create venv if not exists
if not exist "venv" (
    echo      Creating virtual environment...
    python -m venv venv
)

:: Check if dependencies installed
if not exist "venv\.installed" (
    echo      Installing dependencies...
    call venv\Scripts\activate.bat
    pip install -r requirements.txt -q
    echo. > venv\.installed
) else (
    call venv\Scripts\activate.bat
)

:: Copy .env if not exists
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo [WARNING] Created .env file - please configure it!
    )
)

:: Start backend server
echo      Starting FastAPI server on port 8000...
start "Backend-FastAPI" cmd /c "call venv\Scripts\activate.bat && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
cd ..
echo [OK] Backend started

:: Start Frontend
echo.
echo [4/4] Starting Frontend (React + Vite)...
cd frontend

:: Install dependencies if not exists
if not exist "node_modules" (
    echo      Installing npm dependencies...
    call npm install
)

:: Start frontend server
echo      Starting Vite dev server on port 5173...
start "Frontend-React" cmd /c "npm run dev"
cd ..
echo [OK] Frontend started

:: Summary
echo.
echo ==========================================
echo   All services started successfully!
echo ==========================================
echo.
echo   Frontend:  http://localhost:5173
echo   Backend:   http://localhost:8000
echo   API Docs:  http://localhost:8000/docs
echo   Health:    http://localhost:8000/health
echo.
echo   To stop all services, run: stop.bat
echo ==========================================
echo.
pause
