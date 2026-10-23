@echo off
cd /d "%~dp0"
rem Starts the tracker with no command window (pythonw), then this window closes.
where pythonw >nul 2>nul && (start "" pythonw "%~dp0GameValueTracker.pyw" & exit /b)
python "%~dp0GameValueTracker.pyw"
