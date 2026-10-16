@echo off
REM Create the conda environment and install dependencies. Run this once.
setlocal EnableExtensions
chcp 65001 >nul

set "ENV_NAME=whisper-subs"
set "PYTHON_VERSION=3.11"
set "PROJECT_DIR=%~dp0"

echo ============================================
echo  Whisper subtitle tool - environment setup
echo ============================================
echo.

REM ---- locate conda ----
set "CONDA_EXE=conda.exe"
where conda.exe >nul 2>&1
if errorlevel 1 (
  if exist "%ProgramData%\anaconda3\Scripts\conda.exe" set "CONDA_EXE=%ProgramData%\anaconda3\Scripts\conda.exe"
)
if errorlevel 1 (
  if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" set "CONDA_EXE=%USERPROFILE%\anaconda3\Scripts\conda.exe"
)
if errorlevel 1 (
  if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "CONDA_EXE=%USERPROFILE%\miniconda3\Scripts\conda.exe"
)
where "%CONDA_EXE%" >nul 2>&1
if errorlevel 1 (
  echo [ERROR] conda.exe was not found.
  echo         Install Anaconda or Miniconda, then run this file again.
  goto :fail
)
echo [1/4] conda: %CONDA_EXE%

REM ---- create environment if missing ----
"%CONDA_EXE%" env list | findstr /R /C:"^%ENV_NAME% " >nul 2>&1
if errorlevel 1 (
  echo [2/4] Creating conda env "%ENV_NAME%" with python %PYTHON_VERSION% ...
  "%CONDA_EXE%" create -n "%ENV_NAME%" -c conda-forge python=%PYTHON_VERSION% pip -y
  if errorlevel 1 (
    echo [ERROR] Failed to create the conda environment.
    echo         Check the message above, then run this file again.
    goto :fail
  )
) else (
  echo [2/4] conda env "%ENV_NAME%" already exists, skipping creation.
)

REM ---- install dependencies ----
echo [3/4] Installing dependencies from requirements.txt ...
"%CONDA_EXE%" run -n "%ENV_NAME%" python -m pip install --upgrade pip
"%CONDA_EXE%" run -n "%ENV_NAME%" python -m pip install -r "%PROJECT_DIR%requirements.txt"
if errorlevel 1 (
  echo [ERROR] Failed to install dependencies.
  goto :fail
)

REM ---- save the resolved versions ----
"%CONDA_EXE%" run -n "%ENV_NAME%" python -m pip freeze > "%PROJECT_DIR%requirements.lock.txt"
if errorlevel 1 (
  echo [WARN] Could not write requirements.lock.txt
)

REM ---- report versions ----
echo [4/4] Installed versions:
"%CONDA_EXE%" run -n "%ENV_NAME%" python --version
"%CONDA_EXE%" run -n "%ENV_NAME%" python -m pip show faster-whisper ctranslate2 yt-dlp imageio-ffmpeg opencc-python-reimplemented | findstr /R /C:"^Name:" /C:"^Version:"

echo.
echo Setup finished. Run setup_env.bat again after editing requirements.txt.
goto :done

:fail
echo.
echo Setup did not finish. Read the message above.
:done
echo.
pause
endlocal