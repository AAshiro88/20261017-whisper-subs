@echo off
REM Drop one or more YouTube / Bilibili URLs onto this file to create subtitles.
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
  echo [ERROR] No URL given.
  echo         Drag a YouTube or Bilibili link onto this file.
  goto :fail
)

echo Source   : URL
echo Output   : %PROJECT_DIR%output
echo.
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