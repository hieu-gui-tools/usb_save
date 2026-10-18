@echo off
chcp 65001 >nul
title USB Detector & Notifier

echo ======================================================
echo    KHỞI ĐỘNG ỨNG DỤNG PHÁT HIỆN USB & THÔNG BÁO
echo ======================================================
echo.

cd /d "%~dp0"

REM Kiểm tra môi trường ảo .venv
if not exist ".venv\Scripts\python.exe" (
    echo [1/2] Chưa tìm thấy môi trường ảo .venv, đang tiến hành thiết lập bằng uv...
    uv venv --python 3.12 .venv
    if errorlevel 1 (
        echo [Lỗi] Không thể tạo môi trường ảo bằng uv. Vui lòng cài đặt uv hoặc python.
        pause
        exit /b 1
    )
    echo [2/2] Cài đặt các thư viện cần thiết từ requirements.txt...
    uv pip install --python .venv -r requirements.txt
    if errorlevel 1 (
        echo [Lỗi] Cài đặt thư viện thất bại.
        pause
        exit /b 1
    )
)

echo Đang khởi động ứng dụng...
start "" ".venv\Scripts\python.exe" main.py %*
exit /b 0
