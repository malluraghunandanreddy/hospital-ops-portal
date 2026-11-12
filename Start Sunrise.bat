@echo off
title Sunrise Hospital - keep this window open
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 app\server.py
) else (
  python app\server.py
)
echo.
echo Sunrise Hospital has stopped. If you did not close it yourself, check that Python is installed (see README).
pause
