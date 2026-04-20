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

"%PYTHON_BIN%" -m book2mp3.main %*
