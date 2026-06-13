@echo off
setlocal

set "APP_ROOT=%~dp0"
if "%APP_ROOT:~-1%"=="\" set "APP_ROOT=%APP_ROOT:~0,-1%"
set "PYTHON_BIN=%APP_ROOT%\python\windows\python.exe"

if not exist "%PYTHON_BIN%" (
  where python >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_BIN=python"
    echo Portable Python runtime not found at:
    echo   %APP_ROOT%\python\windows\python.exe
    echo Falling back to system Python for this local checkout.
  ) else (
    echo Portable Python runtime not found at:
    echo   %PYTHON_BIN%
    echo.
    echo This launcher expects src\ itself to be the portable app folder.
    echo A finished src bundle must include python\windows\ inside src\.
    echo No usable system python was found for fallback.
    echo.
    exit /b 1
  )
)

set "BOOK2MP3_APP_ROOT=%APP_ROOT%"
if defined PYTHONPATH (
  set "PYTHONPATH=%APP_ROOT%;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%APP_ROOT%"
)

if "%~1"=="--install-xtts" (
  set "XTTS_SETUP_SCRIPT="
  if exist "%APP_ROOT%\scripts\setup_xtts_runtime.py" set "XTTS_SETUP_SCRIPT=%APP_ROOT%\scripts\setup_xtts_runtime.py"
  if not defined XTTS_SETUP_SCRIPT if exist "%APP_ROOT%\..\scripts\setup_xtts_runtime.py" set "XTTS_SETUP_SCRIPT=%APP_ROOT%\..\scripts\setup_xtts_runtime.py"
  if not defined XTTS_SETUP_SCRIPT (
    echo XTTS-Setup-Skript nicht gefunden.
    exit /b 1
  )
  set "XTTS_RUNTIME_ROOT=%APP_ROOT%\runtime\xtts\windows\python"
  if not exist "%APP_ROOT%\runtime" if exist "%APP_ROOT%\..\runtime" set "XTTS_RUNTIME_ROOT=%APP_ROOT%\..\runtime\xtts\windows\python"
  echo Starte optionalen XTTS-Setup unter:
  echo   %XTTS_RUNTIME_ROOT%
  "%PYTHON_BIN%" "%XTTS_SETUP_SCRIPT%" "%XTTS_RUNTIME_ROOT%" --python "%PYTHON_BIN%" --torch-variant auto
  exit /b %ERRORLEVEL%
)

"%PYTHON_BIN%" -m book2mp3.main %*
