@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo   AudioStory - Starting...
echo ========================================
echo.

:: Get script directory
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: Create logs directory
if not exist "logs" mkdir logs

:: Start Backend
echo [1/2] Starting Backend (FastAPI + SQLite)...
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

:: Copy .env if not exists (optional - API keys are normally set in Settings UI)
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo [INFO] Created .env from .env.example ^(optional overrides^)
    )
)

:: Start backend server (SQLite DB is created automatically; binds loopback)
echo      Starting FastAPI server on port 8000...
start "Backend-FastAPI" cmd /c "call venv\Scripts\activate.bat && python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
cd ..
echo [OK] Backend started

:: Start Frontend
echo.
echo [2/2] Starting Frontend (React + Vite)...
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
