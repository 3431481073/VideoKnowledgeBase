@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   VideoKnowledgeBase
echo   import video / transcribe / AI clean / tree
echo ============================================
echo.
echo Starting, please wait...
echo.
"%~dp0venv\Scripts\python.exe" "%~dp0src\app_web.py"
echo.
echo --------------------------------------------
echo Exited with code %errorlevel%
echo If there is an error, screenshot the text above.
echo --------------------------------------------
pause
