@echo off
REM ========================================
REM InterioNote PyInstaller build script
REM Double-click to build dist\InterioNote\InterioNote.exe
REM ========================================
setlocal

cd /d "%~dp0"

if not exist venv\Scripts\python.exe (
  echo [ERROR] venv not found. Please run dev.bat once first.
  pause
  exit /b 1
)

if not exist InterioNote.spec (
  echo [ERROR] InterioNote.spec not found in this folder.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  Building InterioNote with PyInstaller
echo  This will take 5-10 minutes on first run.
echo ============================================================
echo.

REM Stop any running InterioNote.exe (releases file locks on dist)
taskkill /F /IM InterioNote.exe 2>nul
timeout /t 1 /nobreak >nul

REM Clean previous build
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

venv\Scripts\python.exe -m PyInstaller --noconfirm InterioNote.spec
if errorlevel 1 (
  echo.
  echo [ERROR] Build failed. See messages above.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  Build complete.
echo  Result: dist\InterioNote\InterioNote.exe
echo  Folder size:
echo ============================================================
for /f "tokens=*" %%a in ('dir /s /a /-c "dist\InterioNote" ^| findstr /R "[0-9] File(s)"') do echo   %%a
echo.
echo Try running it now:
echo   dist\InterioNote\InterioNote.exe
echo.
pause
endlocal
