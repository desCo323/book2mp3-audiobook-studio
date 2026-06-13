@echo off
setlocal

set "APP_ROOT=%~dp0"
if "%APP_ROOT:~-1%"=="\" set "APP_ROOT=%APP_ROOT:~0,-1%"
set "PYTHONPATH_ENTRY=%APP_ROOT%\src"
if exist "%APP_ROOT%\book2mp3" set "PYTHONPATH_ENTRY=%APP_ROOT%"
set "PYTHON_RUNTIME_ROOT="
if exist "%APP_ROOT%\python\windows\python.exe" set "PYTHON_RUNTIME_ROOT=%APP_ROOT%\python\windows"
if not defined PYTHON_RUNTIME_ROOT if exist "%APP_ROOT%\src\python\windows\python.exe" set "PYTHON_RUNTIME_ROOT=%APP_ROOT%\src\python\windows"
if defined PYTHON_RUNTIME_ROOT (
  set "PYTHON_BIN=%PYTHON_RUNTIME_ROOT%\python.exe"
) else (
  set "PYTHON_BIN=%APP_ROOT%\python\windows\python.exe"
)

if not exist "%PYTHON_BIN%" (
  echo Portable Python runtime not found.
  echo Checked these locations:
  echo   %APP_ROOT%\python\windows\python.exe
  echo   %APP_ROOT%\src\python\windows\python.exe
  echo.
  echo This launcher supports both the finished bundle layout and the current source checkout.
  echo A finished release must include python\windows\ inside the app folder.
  echo The current repository layout expects src\python\windows\ when present.
  echo For development only, set BOOK2MP3_ALLOW_SYSTEM_PYTHON=1.
  echo.
  if "%BOOK2MP3_ALLOW_SYSTEM_PYTHON%"=="1" (
    set "PYTHON_BIN=python"
  ) else (
    exit /b 1
  )
)

set "BOOK2MP3_APP_ROOT=%APP_ROOT%"
set "BOOK2MP3_PERF_LOG=1"
if not defined BOOK2MP3_PERF_RUN_ID set "BOOK2MP3_PERF_RUN_ID=win-%RANDOM%"
if not defined BOOK2MP3_PERF_LOG_FILE set "BOOK2MP3_PERF_LOG_FILE=%APP_ROOT%\workspace\logs\performance.jsonl"
if defined PYTHONPATH (
  set "PYTHONPATH=%PYTHONPATH_ENTRY%;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%PYTHONPATH_ENTRY%"
)

"%PYTHON_BIN%" -m book2mp3.main %*
