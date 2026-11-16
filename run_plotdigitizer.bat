@echo off
setlocal
cd /d "%~dp0"
abaqus python "%~dp0run_plotdigitizer.py" %*
set "WINUX_PLOT_EXIT=%ERRORLEVEL%"
endlocal & exit /b %WINUX_PLOT_EXIT%
