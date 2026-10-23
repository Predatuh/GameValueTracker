@echo off
cd /d "%~dp0"
echo Installing build tools...
python -m pip install numpy pyinstaller
echo Building PS2ValueTracker.exe ...
python -m PyInstaller --onefile --noconsole --name PS2ValueTracker ps2_tracker.py
echo.
echo Done. Your app is in the "dist" folder: dist\PS2ValueTracker.exe
pause
