@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
call .venv\Scripts\activate.bat || (echo Run setup.bat first. & pause & exit /b 1)
python tests\selftest.py chrome
pause
