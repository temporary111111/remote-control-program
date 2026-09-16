@echo off
REM Build script for remote-controlled.exe

echo Building remote-controlled.exe...

REM Check if PyInstaller is installed
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Clean previous builds
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM Build
echo Running PyInstaller...
pyinstaller remote-controlled.spec --clean

if errorlevel 1 (
    echo Build failed!
    exit /b 1
)

echo.
echo ========================================
echo Build successful!
echo Output: dist\remote-controlled.exe
echo ========================================
echo.
echo To test: dist\remote-controlled.exe
echo.
echo To distribute: copy dist\remote-controlled.exe to target machine
pause