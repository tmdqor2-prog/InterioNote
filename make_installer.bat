@echo off
REM ========================================
REM  InterioNote — Inno Setup installer build
REM  Double-click this to produce: Output\InterioNoteSetup-<version>.exe
REM  Phase 7B-2
REM ========================================
setlocal

cd /d "%~dp0"

REM --- 1) Phase 7B-2 v2: 두 dist 가 모두 있어야 함 (CPU + GPU 선택형 인스톨러) ---
if not exist "dist-cpu\InterioNote\InterioNote.exe" (
  echo [ERROR] dist-cpu\InterioNote\InterioNote.exe not found.
  echo.
  echo build-installer.bat 를 실행해서 CPU + GPU 두 dist 를 모두 빌드하세요.
  pause
  exit /b 1
)
if not exist "dist-gpu\InterioNote\InterioNote.exe" (
  echo [ERROR] dist-gpu\InterioNote\InterioNote.exe not found.
  echo.
  echo build-installer.bat 를 실행해서 CPU + GPU 두 dist 를 모두 빌드하세요.
  pause
  exit /b 1
)

REM --- 2) Inno Setup ISCC.exe 위치 찾기 ---
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
REM 사용자가 비표준 경로에 설치했을 수 있음
if "%ISCC%"=="" if exist "%ProgramFiles%\InterioNote\ISCC.exe" set "ISCC=%ProgramFiles%\InterioNote\ISCC.exe"
if "%ISCC%"=="" if exist "%ProgramFiles(x86)%\InterioNote\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\InterioNote\ISCC.exe"
REM 환경변수 INNO_SETUP_DIR 로도 지정 가능
if "%ISCC%"=="" if not "%INNO_SETUP_DIR%"=="" if exist "%INNO_SETUP_DIR%\ISCC.exe" set "ISCC=%INNO_SETUP_DIR%\ISCC.exe"

if "%ISCC%"=="" (
  echo [ERROR] Inno Setup 6 not found.
  echo.
  echo Please install from https://jrsoftware.org/isdl.php
  echo Or set INNO_SETUP_DIR environment variable to its install folder.
  pause
  exit /b 1
)

echo Using compiler: %ISCC%
echo.

REM --- 2.5) v3.5.2: version_for_iss.iss 생성 (.iss 의 #include 대상) ---
if exist "venv\Scripts\python.exe" (
  echo Generating version_for_iss.iss from app\version.json...
  "venv\Scripts\python.exe" write_iss_version.py
  if errorlevel 1 (
    echo [ERROR] version_for_iss.iss generation failed.
    pause
    exit /b 1
  )
) else (
  if not exist "version_for_iss.iss" (
    echo [ERROR] venv not found and version_for_iss.iss missing.
    echo         Run dev.bat once OR create version_for_iss.iss manually.
    pause
    exit /b 1
  )
)

REM --- 3) 컴파일 ---
echo ============================================================
echo  Compiling installer...  (5-10 minutes for first run, due to lzma2 ultra)
echo ============================================================
"%ISCC%" /Qp InterioNoteSetup.iss
if errorlevel 1 (
  echo.
  echo [ERROR] Inno Setup compile failed.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  Installer built successfully.
echo  Output: %~dp0Output\
echo ============================================================
dir /b Output\*.exe 2>nul
echo.
pause
endlocal
