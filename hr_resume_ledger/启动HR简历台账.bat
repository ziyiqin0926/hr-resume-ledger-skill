@echo off
chcp 65001 >nul
cd /d "%~dp0"
title HR简历筛选台账
echo 正在启动 HR 简历筛选台账...
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 app.py
) else (
  python app.py
)
pause
