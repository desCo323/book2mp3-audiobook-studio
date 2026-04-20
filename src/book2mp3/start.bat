@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%I in ("%SCRIPT_DIR%\..") do set "APP_ROOT=%%~fI"
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
    echo This launcher lives in src\book2mp3\ but expects src\ to be the app folder.
    echo A finished portable layout must include python\windows\ inside src\.
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
