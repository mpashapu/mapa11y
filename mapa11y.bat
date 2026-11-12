@echo off
REM Usage: mapa11y sample ^| mapa11y discover orgs ^| mapa11y discover apps ^| mapa11y audit ^| mapa11y summarize
cd /d "%~dp0"
set PYTHONUTF8=1
call .venv\Scripts\activate.bat || (echo Run setup.bat first. & exit /b 1)
python -m mapa11y.%*
