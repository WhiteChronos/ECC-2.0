@echo off
setlocal
echo Validacao ECC-2.0 local. Execute como usuario normal, sem administrador.
"C:\Program Files\nodejs\node.exe" "%~dp0scripts\local-runtime.cjs" --smoke
set "result=%errorlevel%"
echo Codigo de saida: %result%
pause
exit /b %result%
