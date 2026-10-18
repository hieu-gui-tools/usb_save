@echo off
chcp 65001 >nul
title Dong goi USB Save thanh file EXE

echo ======================================================
echo    DONG GOI UNG DUNG BANG PYINSTALLER (ONEFILE)
echo ======================================================
echo.

cd /d "%~dp0"

REM Kiem tra moi truong ao .venv
if not exist ".venv\Scripts\python.exe" (
    echo [Loi] Khong tim thay moi truong ao .venv!
    echo Vui long chay run.bat truoc de tao moi truong ao.
    pause
    exit /b 1
)

REM Kiem tra pyinstaller
if not exist ".venv\Scripts\pyinstaller.exe" (
    echo Dang cai dat PyInstaller vao moi truong ao...
    uv pip install --python .venv pyinstaller
    if errorlevel 1 (
        echo [Loi] Khong the cai dat PyInstaller!
        pause
        exit /b 1
    )
)

REM Tao icon neu chua co
if not exist "usb_icon.ico" (
    echo Dang tao usb_icon.ico tu usb_icon.png...
    .venv\Scripts\python.exe -c "from PIL import Image; img = Image.open('usb_icon.png'); img.save('usb_icon.ico', format='ICO', sizes=[(16,16), (32,32), (48,48), (64,64)])"
)

echo Dang tien hanh dong goi file EXE...
".venv\Scripts\pyinstaller.exe" --noconfirm --clean USBSave.spec

if errorlevel 1 (
    echo.
    echo ======================================================
    echo [Loi] Qua trinh dong goi that bai!
    echo ======================================================
    pause
    exit /b 1
)

echo.
echo ======================================================
echo [Thanh cong] File EXE da duoc tao tai: dist\USBSave.exe
echo ======================================================
pause
