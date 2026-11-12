@echo off
title Sunrise Hospital - reset a password
cd /d "%~dp0"
echo.
echo Use this only if a full-access doctor has forgotten their password.
echo (Everyone else: a full-access doctor resets it in Settings.)
echo.
set /p U=Username to reset: 
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 app\server.py --reset-password %U%
) else (
  python app\server.py --reset-password %U%
)
pause
