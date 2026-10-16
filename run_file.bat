@echo off
REM Local video / audio subtitles.
REM Usage A: double-click this file, then paste one file or folder path per line
REM          (press Enter on an empty line to start).
REM Usage B: drag one or more local files onto this file.
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

if "%~1"=="" (
  echo ============================================
  echo  Paste a video or audio file path below.
  echo  One path per line, press Enter on an empty line to start.
  echo  Output folder: %PROJECT_DIR%output
  echo ============================================
  echo.
) else (
  echo Source   : local file ^(from drag and drop^)
  echo Output   : %PROJECT_DIR%output
  echo.
)

"%PYEXE%" "%PROJECT_DIR%transcribe.py" %*
set "EXITCODE=%ERRORLEVEL%"
goto :done

:fail
set "EXITCODE=1"
:done
echo.
echo Finished with exit code %EXITCODE%.
pause
endlocal & exit /b %EXITCODE%