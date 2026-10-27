@echo off
setlocal
title AWB Status Dashboard - keep this window open
cd /d "%~dp0"
echo.
echo  ==========================================================
echo     AWB Status Dashboard
echo     Keep this window open while you use the dashboard.
echo  ==========================================================
echo.

REM ---- 1. Find Python ---------------------------------------------------
set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY if exist "%PYEXE%" set PY="%PYEXE%"
if not defined PY for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set PY="%%D\python.exe"
if defined PY goto have_python

REM ---- 2. Not found: install it automatically ---------------------------
echo  Python is not installed on this computer. Installing it now...
echo  This happens only once and takes 1 to 3 minutes.
echo.
winget --version >nul 2>&1 || goto manual_python
winget install -e --id Python.Python.3.12 --scope user --silent --accept-source-agreements --accept-package-agreements
if not exist "%PYEXE%" goto manual_python
set PY="%PYEXE%"

:have_python
REM ---- 3. Desktop shortcut, first run only -------------------------------
if exist ".shortcut_created" goto start_app
set "LNK_TARGET=%~f0"
set "LNK_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\AWB Dashboard.lnk'); $s.TargetPath=$env:LNK_TARGET; $s.WorkingDirectory=$env:LNK_DIR; $s.IconLocation=$env:SystemRoot+'\System32\SHELL32.dll,13'; $s.Save()" >nul 2>&1
echo done> ".shortcut_created"
echo  A shortcut "AWB Dashboard" was added to your Desktop for next time.
echo.

:start_app
REM ---- 4. Start -----------------------------------------------------------
%PY% start.py %*
echo.
echo  The dashboard has stopped.
echo  If you see a [FAIL] line above, it explains what went wrong.
echo  Press any key to close this window.
pause >nul
exit /b

:manual_python
echo.
echo  [FAIL] Could not install Python automatically.
echo.
echo  Please install it yourself, one time:
echo    1. Your browser will now open the Python download page.
echo    2. Click the yellow "Download Python" button and run the downloaded file.
echo    3. IMPORTANT: tick "Add python.exe to PATH" at the bottom, then click "Install Now".
echo    4. When it finishes, double-click this file again.
echo.
start "" "https://www.python.org/downloads/windows/"
pause
exit /b 1
