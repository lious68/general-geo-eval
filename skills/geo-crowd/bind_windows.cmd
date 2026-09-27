@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
echo GEO device binding - run on your own Windows PC.
echo This only binds this PC. AstraFlow still needs permission to run local tools.
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 scripts\client.py doctor
  py -3 scripts\client.py bind
) else (
  python scripts\client.py doctor
  python scripts\client.py bind
)
echo.
echo If binding failed, do not start tasks. Read the error above.
pause
