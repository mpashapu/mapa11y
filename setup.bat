@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
python --version >nul 2>&1 || (echo Python not found. Install Python 3.12 from python.org and tick "Add python.exe to PATH". & pause & exit /b 1)
echo Creating private Python environment in .venv ...
python -m venv .venv || (echo Could not create environment. & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || (echo Package install failed. & pause & exit /b 1)
echo Installing backup browser (Chromium) ...
python -m playwright install chromium
echo.
echo Setup complete. Next: double-click run-selftest.bat
pause
