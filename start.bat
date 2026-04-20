@echo off
setlocal

set "APP_ROOT=%~dp0"
if "%APP_ROOT:~-1%"=="\" set "APP_ROOT=%APP_ROOT:~0,-1%"
set "PYTHON_BIN=%APP_ROOT%\python\windows\python.exe"

if not exist "%PYTHON_BIN%" (
  echo Portable Python runtime not found at:
  echo   %PYTHON_BIN%
  echo.
  echo This launcher is for the self-contained desktop bundle.
  echo A finished release must include python\windows\ inside the app folder.
  echo For development only, set BOOK2MP3_ALLOW_SYSTEM_PYTHON=1.
  echo.
  if "%BOOK2MP3_ALLOW_SYSTEM_PYTHON%"=="1" (
    set "PYTHON_BIN=python"
  ) else (
    exit /b 1
  )
)

set "BOOK2MP3_APP_ROOT=%APP_ROOT%"
if defined PYTHONPATH (
  set "PYTHONPATH=%APP_ROOT%\src;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%APP_ROOT%\src"
)

"%PYTHON_BIN%" -m book2mp3.main %*
