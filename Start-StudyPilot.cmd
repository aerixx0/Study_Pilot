@echo off
setlocal
cd /d "%~dp0"
call "%~dp0python-ai-agent-ai-agent-studypilot\outputs\StudyPilot\Start-StudyPilot.cmd"
exit /b %errorlevel%
