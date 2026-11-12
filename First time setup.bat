@echo off
title Sunrise Hospital - first time setup
cd /d "%~dp0"
if exist "data\sunrise.db" (
  echo.
  echo This laptop is already set up. Use "Start Sunrise.bat" every day.
  echo.
  pause
  exit /b
)
echo.
echo Starting a clean copy with no demo patients.
echo The window below shows ONE-TIME passwords for arjun and meera. Write them down.
echo.
set HOSPITAL_DEMO=0
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 app\server.py
) else (
  python app\server.py
)
pause
