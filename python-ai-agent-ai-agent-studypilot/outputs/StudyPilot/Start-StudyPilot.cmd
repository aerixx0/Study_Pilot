@echo off
setlocal
cd /d "%~dp0"
set "STUDYPILOT_PYTHON=%~dp0.venv\Scripts\python.exe"
if exist "%STUDYPILOT_PYTHON%" goto run
rem Reuse the prepared runtime in this development workspace, if present.
if exist "%~dp0..\..\work\.venv\Scripts\python.exe" (
    set "STUDYPILOT_PYTHON=%~dp0..\..\work\.venv\Scripts\python.exe"
    goto run
)
echo First launch: preparing Python environment. Internet is required.
where py >nul 2>nul
if errorlevel 1 (
    python -m venv .venv
) else (
    py -3 -m venv .venv
)
if errorlevel 1 goto failed
"%STUDYPILOT_PYTHON%" -m pip install -r requirements-local.txt
if errorlevel 1 goto failed
:run
"%STUDYPILOT_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 goto failed
"%STUDYPILOT_PYTHON%" -c "import streamlit" >nul 2>nul
if not errorlevel 1 goto launch
"%STUDYPILOT_PYTHON%" -m pip install -r requirements-local.txt
if errorlevel 1 goto failed
:launch
"%STUDYPILOT_PYTHON%" start_studypilot.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Could not start StudyPilot. Install Python 3.11+ and check the messages above.
pause
exit /b 1
