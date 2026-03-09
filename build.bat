@echo off
setlocal
cd /d "%~dp0"

set "PY_EXE=.venv\Scripts\python.exe"

if not exist "%PY_EXE%" (
    py -3.11 -m venv .venv
    if errorlevel 1 goto :error
)

"%PY_EXE%" -m pip install --upgrade pip
if errorlevel 1 goto :error

"%PY_EXE%" -m pip install -r requirements.txt
if errorlevel 1 goto :error

taskkill /IM music_fetcher_pro.exe /F >nul 2>nul
if exist "dist\music_fetcher_pro.exe" (
    del /f /q "dist\music_fetcher_pro.exe" >nul 2>nul
)

"%PY_EXE%" -m PyInstaller --noconfirm --clean music_fetcher_pro.spec
if errorlevel 1 goto :error

echo.
echo Build succeeded.
echo EXE path: dist\music_fetcher_pro.exe
exit /b 0

:error
echo.
echo Build failed.
exit /b 1
