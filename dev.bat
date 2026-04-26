@echo off
REM ==========================================
REM  InterioNote - development launcher
REM  Double-click this file (stay inside C:\InterioNote only).
REM  The window never closes automatically on error.
REM ==========================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title InterioNote (dev)

call :main
set "RC=%ERRORLEVEL%"
echo.
echo ==========================================
if "%RC%"=="0" (
    echo  App closed normally. Press any key to close this window.
) else (
    echo  Something went wrong ^(code %RC%^). See messages above.
    echo  Press any key to close this window.
)
echo ==========================================
pause >nul
endlocal
exit /b

:main
echo.
echo ==========================================
echo  InterioNote - dev launcher
echo ==========================================
echo.

REM --- Sanity: requirements.txt must exist here ---
if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found in this folder:
    echo   %CD%
    echo.
    echo  Run this file only from C:\InterioNote\dev.bat
    echo  Do NOT copy this file anywhere else.
    exit /b 1
)

REM --- Python detection ---
set "PYEXE="
py -3.12 --version >nul 2>&1 && set "PYEXE=py -3.12"
if not defined PYEXE (
    py -3.11 --version >nul 2>&1 && set "PYEXE=py -3.11"
)
if not defined PYEXE (
    echo [ERROR] Python 3.11 or 3.12 not found.
    echo.
    echo  Install from: https://www.python.org/downloads/release/python-3128/
    echo  During install, CHECK:
    echo    [x] Add python.exe to PATH
    echo    [x] py launcher
    exit /b 1
)
echo [OK] Python: %PYEXE%

REM --- venv create ---
if not exist "venv\Scripts\python.exe" (
    echo.
    echo [SETUP] Creating virtual environment...
    %PYEXE% -m venv venv
    if errorlevel 1 (
        echo [ERROR] venv creation failed.
        exit /b 1
    )
)

REM --- venv activate ---
call "venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] venv activation failed.
    echo   Try deleting the 'venv' folder inside C:\InterioNote and retry.
    exit /b 1
)

REM --- install / update if requirements.txt changed ---
set "NEED=0"
if not exist "venv\_req.cached" set "NEED=1"
if exist "venv\_req.cached" (
    fc /b requirements.txt "venv\_req.cached" >nul 2>&1
    if errorlevel 1 set "NEED=1"
)
if "!NEED!"=="1" (
    echo.
    echo [SETUP] Installing / updating dependencies...
    echo   Keep this window open. Do not press Ctrl+C.
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] pip install failed. Check network and retry.
        exit /b 1
    )
    copy /y requirements.txt "venv\_req.cached" >nul
    echo [OK] Dependencies ready.
)

REM --- Launch app (pywebview opens its own native window) ---
echo.
echo ==========================================
echo  Launching InterioNote...
echo  ^(A native app window will open shortly^)
echo  Close the app window to stop.
echo ==========================================
echo.
python InterioNote.py
exit /b 0
