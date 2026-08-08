@echo off
chcp 65001 >nul

echo ========================================
echo   AudioStory - Stopping...
echo ========================================
echo.

:: Get script directory
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: Kill Backend (uvicorn on port 8000)
echo [1/2] Stopping Backend...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo [OK] Backend stopped

:: Kill Frontend (vite on port 5173)
echo [2/2] Stopping Frontend...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
:: Also kill node processes from frontend
taskkill /F /FI "WINDOWTITLE eq Frontend-React*" >nul 2>&1
echo [OK] Frontend stopped

echo.
echo ==========================================
echo   All services stopped!
echo ==========================================
echo.
pause
