@echo off
chcp 65001 >nul
title Uninstall PhotoCraft-RemoveBG
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" %*
echo.
pause
