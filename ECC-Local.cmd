@echo off
setlocal
"C:\Program Files\nodejs\node.exe" "%~dp0scripts\local-runtime.cjs"
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%
