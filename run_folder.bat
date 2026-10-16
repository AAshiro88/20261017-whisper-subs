@echo off
REM Batch mode. Drop a folder onto this file, or run it with no argument
REM to process every media file inside the project "input" folder.
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

REM Avoid delayed expansion problems: decide the targets before echoing them.
if not "%~1"=="" goto :with_args
set "TARGETS=%PROJECT_DIR%input"
echo No folder given, using %TARGETS%
goto :run

:with_args
set "TARGETS=%*"

:run
echo Source   : folder batch mode
echo Output   : %PROJECT_DIR%output
echo.
"%PYEXE%" "%PROJECT_DIR%transcribe.py" %TARGETS%
set "EXITCODE=%ERRORLEVEL%"
goto :done

:fail
set "EXITCODE=1"
:done
echo.
echo Finished with exit code %EXITCODE%.
pause
endlocal & exit /b %EXITCODE%