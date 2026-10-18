@echo off
setlocal
"C:\Program Files\nodejs\node.exe" "%~dp0scripts\economy-bridge.cjs" %*
exit /b %errorlevel%
