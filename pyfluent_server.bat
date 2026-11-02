@echo off
setlocal enabledelayedexpansion
rem =====================================================================
rem  Start Fluent solver with gRPC listening (server side for pyfluent)
rem    double-click                 : normal start
rem    pyfluent_server.bat --check  : only report which fluent.exe is found
rem  If auto-detect fails:  set FLUENT_EXE=<full path to fluent.exe>
rem =====================================================================

set "EXE=%FLUENT_EXE%"
if defined FLUENT_EXE goto :have_exe

rem ---- auto-detect: <root>\<release>\v2xx\fluent\ntbin\win64\fluent.exe ----
set "EXE="
for %%R in ("D:\ANSYS" "C:\Program Files\ANSYS Inc" "C:\ANSYS Inc" "E:\ANSYS" "D:\Program Files\ANSYS Inc") do (
  if exist "%%~R" (
    for /d %%A in ("%%~R\*") do (
      for /d %%V in ("%%~A\v2*") do (
        if exist "%%~V\fluent\ntbin\win64\fluent.exe" set "EXE=%%~V\fluent\ntbin\win64\fluent.exe"
      )
      if exist "%%~A\fluent\ntbin\win64\fluent.exe" set "EXE=%%~A\fluent\ntbin\win64\fluent.exe"
    )
    for /d %%V in ("%%~R\v2*") do (
      if exist "%%~V\fluent\ntbin\win64\fluent.exe" set "EXE=%%~V\fluent\ntbin\win64\fluent.exe"
    )
  )
)

:have_exe
if not defined EXE (
  echo.
  echo [ERROR] fluent.exe not found. Either:
  echo   1^) run:  set FLUENT_EXE=D:\ANSYS\2024 R2\v242\fluent\ntbin\win64\fluent.exe
  echo      then start this bat again from that same window, or
  echo   2^) edit this file, put your path after the first "set" line below rem block.
  echo.
  pause
  exit /b 1
)
if /i "%~1"=="--check" (
  echo FOUND=!EXE!
  exit /b 0
)

set "SI=%~dp0serverinfo.txt"
if not exist "%~dp0_work" mkdir "%~dp0_work"
cd /d "%~dp0_work"
del "%SI%" >nul 2>&1

echo ============================================
echo  Fluent 2D solver / gRPC server (keep open)
echo  fluent      : !EXE!
echo  work dir    : %CD%
echo  server info : %SI%
echo  stop it from python with s.exit()
echo ============================================
echo.

"!EXE!" 2ddp -g -t2 -sifile="%SI%"

echo.
echo Fluent exited
pause