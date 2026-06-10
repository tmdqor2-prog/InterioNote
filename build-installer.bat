@echo off
REM ============================================================
REM  Phase 7B-2 v2 -- InterioNote installer full build
REM  Double-click runs:
REM    1) Swap venv to CPU mode, build dist-cpu
REM    2) Swap venv to GPU mode, build dist-gpu
REM    3) Compile single Inno Setup installer (CPU + GPU types)
REM  Total time: ~30 minutes.
REM  Output: Output\InterioNoteSetup-<version>.exe
REM  After run: venv is restored to GPU mode.
REM
REM  NOTE: This file is ASCII-only on purpose.
REM        Korean inside .bat breaks under cp949 cmd parsing.
REM ============================================================
setlocal

cd /d "%~dp0"

set "VENV_PY=venv\Scripts\python.exe"
set "VENV_PIP=venv\Scripts\pip.exe"

if not exist "%VENV_PY%" (
  echo [ERROR] venv not found.
  echo Run dev.bat once to create venv, then retry.
  pause & exit /b 1
)

echo.
echo ============================================================
echo  Phase 7B-2 v2 -- InterioNote installer full build
echo ============================================================
echo.
echo This script will automatically perform (about 30 minutes):
echo   1. Swap venv to CPU mode, build dist-cpu
echo   2. Swap venv to GPU mode, build dist-gpu
echo   3. Compile single Inno Setup installer
echo.
echo WARNING: Do not close this window mid-run.
echo          If closed, venv may end up in CPU state.
echo          Recovery commands shown at the end.
echo.
pause

REM ----- Step 1: swap venv to CPU mode -----
echo.
echo === [1/5] Swap venv to CPU mode (~3 min)...
"%VENV_PIP%" uninstall -y torch torchaudio nvidia-cublas-cu12 nvidia-cudnn-cu12 2>nul
"%VENV_PIP%" install --quiet --disable-pip-version-check torch==2.4.1 torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 ( echo [ERROR] CPU torch install failed & goto :err )
echo [OK] venv now in CPU mode

REM ----- Step 2: build dist-cpu -----
echo.
echo === [2/5] Build dist-cpu (PyInstaller, ~5-10 min)...
if exist dist rmdir /s /q dist
if exist dist-cpu rmdir /s /q dist-cpu
if exist build rmdir /s /q build
"%VENV_PY%" -m PyInstaller InterioNote.spec --clean --noconfirm
if errorlevel 1 ( echo [ERROR] dist-cpu PyInstaller failed & goto :restore_gpu_and_err )
move dist dist-cpu >nul
if errorlevel 1 ( echo [ERROR] dist rename failed & goto :restore_gpu_and_err )
echo [OK] dist-cpu done

REM ----- Step 3: swap venv to GPU mode -----
echo.
echo === [3/5] Swap venv to GPU mode (~5 min)...
"%VENV_PIP%" uninstall -y torch torchaudio 2>nul
"%VENV_PIP%" install --quiet --disable-pip-version-check torch==2.4.1 torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cu121
if errorlevel 1 ( echo [ERROR] GPU torch install failed & goto :err )
"%VENV_PIP%" install --quiet --disable-pip-version-check nvidia-cublas-cu12 nvidia-cudnn-cu12
if errorlevel 1 ( echo [ERROR] CUDA pip packages install failed & goto :err )
echo [OK] venv now in GPU mode

REM ----- Step 4: build dist-gpu -----
echo.
echo === [4/5] Build dist-gpu (PyInstaller, ~5-10 min)...
if exist dist rmdir /s /q dist
if exist dist-gpu rmdir /s /q dist-gpu
if exist build rmdir /s /q build
"%VENV_PY%" -m PyInstaller InterioNote.spec --clean --noconfirm
if errorlevel 1 ( echo [ERROR] dist-gpu PyInstaller failed & goto :err )
move dist dist-gpu >nul
if errorlevel 1 ( echo [ERROR] dist rename failed & goto :err )
echo [OK] dist-gpu done

REM ----- Step 5: compile installer -----
echo.
echo === [5/6] Compile installer with Inno Setup (~5-10 min)...

REM v3.5.2: write_iss_version.py reads app\version.json and generates
REM         version_for_iss.iss which InterioNoteSetup.iss #includes.
REM         Keeps installer filename in sync with version.json automatically.
"%VENV_PY%" write_iss_version.py
if errorlevel 1 ( echo [ERROR] write_iss_version failed & goto :err )

call make_installer.bat
if errorlevel 1 ( echo [ERROR] installer compile failed & goto :err )

REM ----- Step 6: build quick-update zip (Phase 8D) -----
echo.
echo === [6/6] Build quick-update zip (Phase 8D, fast)...
"%VENV_PY%" build_update_zip.py
if errorlevel 1 ( echo [ERROR] update zip build failed & goto :err )

echo.
echo ============================================================
echo  ALL DONE
echo ============================================================
echo.
echo Outputs in C:\InterioNote\Output\:
dir /b Output\*.exe Output\*.zip Output\*.json 2>nul
echo.
echo venv state: GPU mode (dev.bat works as before for you)
echo.
echo Verification:
echo   1. Double-click Output\InterioNoteSetup-X.Y.Z.exe
echo   2. Pick CPU-only or GPU mode in component page
echo   3. Should install to %%LOCALAPPDATA%%\Programs\InterioNote\
echo   4. Launch from start menu / desktop shortcut
echo   5. pywebview window should appear
echo.
echo For GitHub Release upload BOTH:
echo   - InterioNoteSetup-X.Y.Z.exe       (full installer ~1.6GB)
echo   - InterioNote-update-X.Y.Z.zip      (quick update ~5MB)
echo.
pause
exit /b 0

:restore_gpu_and_err
echo.
echo === Trying to restore venv to GPU mode ...
"%VENV_PIP%" uninstall -y torch torchaudio 2>nul
"%VENV_PIP%" install --quiet --disable-pip-version-check torch==2.4.1 torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cu121
"%VENV_PIP%" install --quiet --disable-pip-version-check nvidia-cublas-cu12 nvidia-cudnn-cu12
goto :err

:err
echo.
echo ============================================================
echo  BUILD FAILED
echo ============================================================
echo.
echo Check log above. Verify venv state with:
echo.
echo   venv\Scripts\python.exe -c "import torch; print('cuda:', torch.cuda.is_available())"
echo.
echo - cuda: True   = GPU mode (good, dev.bat works)
echo - cuda: False  = CPU mode (run these to restore GPU):
echo.
echo   venv\Scripts\pip.exe install torch==2.4.1 torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cu121
echo   venv\Scripts\pip.exe install nvidia-cublas-cu12 nvidia-cudnn-cu12
echo.
pause
exit /b 1
