@echo off
setlocal
cd /d "%~dp0"
if not exist "out\bdo" mkdir "out\bdo"
echo.>>"out\bdo\crash.log"
echo [%date% %time%] Launching pyside_bdo_gui.py>>"out\bdo\crash.log"
".venv\Scripts\python.exe" "pyside_bdo_gui.py" >>"out\bdo\crash.log" 2>&1
echo [%date% %time%] Process exited with code %ERRORLEVEL%>>"out\bdo\crash.log"
endlocal
