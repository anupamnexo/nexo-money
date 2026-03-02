@echo off
REM ============================================
REM Nexo.money MVP - Quick Start (Windows)
REM ============================================

echo.
echo   Nexo.money MVP
echo   Corporate Cards for Indian SMEs
echo.

cd /d "%~dp0"

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Please install Python 3.8+ first.
    pause
    exit /b 1
)

echo Installing tornado...
pip install tornado --quiet 2>nul

echo Initializing database with demo data...
if exist nexo.db del nexo.db

echo.
echo   Landing Page:  http://localhost:8080
echo   Dashboard App: http://localhost:8080/app
echo.
echo   Demo Login:
echo     Email:    priya.shah@technova.com
echo     Password: demo123
echo.
echo   Press Ctrl+C to stop the server
echo   -----------------------------------------
echo.

python app.py --seed
pause
