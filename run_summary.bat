@echo off
REM Transcribe one or multiple video/audio files and summarize them with Ollama.
REM Usage A: double-click this file to open the Windows file picker (multi-select supported).
REM Usage B: drag one or more video/audio files (or folders) onto this file.
REM Model and local/remote Ollama settings are configured in config.json.
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PROJECT_DIR=%~dp0"

set "PYEXE=%USERPROFILE%\.conda\envs\whisper-subs\python.exe"
if not exist "%PYEXE%" set "PYEXE=%ProgramData%\anaconda3\envs\whisper-subs\python.exe"
if not exist "%PYEXE%" (
  echo [ERROR] Python environment "whisper-subs" was not found.
  echo         Run setup_env.bat first.
  goto :fail
)

echo ============================================
echo  Whisper Transcribe + Ollama Summary
echo  Config : %PROJECT_DIR%config.json
echo  Output : ^<input_dir^>\^<input_filename^>\
echo ============================================
echo.

"%PYEXE%" "%PROJECT_DIR%summarize_videos.py" %*
set "EXITCODE=%ERRORLEVEL%"
goto :done

:fail
set "EXITCODE=1"
:done
echo.
echo Finished with exit code %EXITCODE%.
pause
endlocal & exit /b %EXITCODE%
