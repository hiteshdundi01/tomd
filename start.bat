@echo off
title TOMD — Convert Anything to Markdown
echo.
echo  ============================================
echo   TOMD — Convert Anything to Markdown
echo  ============================================
echo.

:: Activate virtual environment
call "%~dp0.venv\Scripts\activate.bat"

echo  Starting server at http://127.0.0.1:8000
echo  Press Ctrl+C to stop.
echo.

:: Open browser after a short delay
start "" /B cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000"

:: Start the server
python -m tomd.web.app
