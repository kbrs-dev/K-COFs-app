@echo off
setlocal enabledelayedexpansion
REM Double-click launcher for the KBRS Production Markup app (Windows).
cd /d "%~dp0"

set PYCMD=

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 --version >nul 2>nul
    if !ERRORLEVEL!==0 set PYCMD=py -3
)

if "%PYCMD%"=="" (
    where python >nul 2>nul
    if !ERRORLEVEL!==0 set PYCMD=python
)

if "%PYCMD%"=="" (
    echo Python 3 isn't installed.
    echo Get it free from https://www.python.org/downloads/
    echo IMPORTANT: on the install screen, check the box "Add python.exe to PATH"
    echo before clicking Install -- this launcher won't find Python without it.
    pause
    exit /b 1
)

%PYCMD% -c "import tkinter" >nul 2>nul
if not %ERRORLEVEL%==0 (
    echo Python's tkinter module is missing.
    echo Reinstall Python from python.org and make sure "tcl/tk and IDLE" is
    echo checked on the optional features screen.
    pause
    exit /b 1
)

REM Grab the latest version from GitHub first, if this folder is a git repo
REM and git is available. Never blocks launching the app if it fails (no
REM internet, git not installed, etc.).
if exist ".git" (
    where git >nul 2>nul
    if !ERRORLEVEL!==0 (
        echo Checking for updates...
        git pull --ff-only
    )
)

%PYCMD% -c "import reportlab, pypdf, PIL" >nul 2>nul
if not %ERRORLEVEL%==0 (
    echo First-time setup: installing free, open-source PDF/image libraries...
    %PYCMD% -m pip install --user --quiet reportlab pypdf Pillow
)

%PYCMD% -c "import tkinterdnd2" >nul 2>nul
if not %ERRORLEVEL%==0 (
    echo Installing free drag-and-drop support...
    %PYCMD% -m pip install --user --quiet tkinterdnd2
)

%PYCMD% -c "import pypdfium2" >nul 2>nul
if not %ERRORLEVEL%==0 (
    echo Installing free PDF-preview support...
    %PYCMD% -m pip install --user --quiet pypdfium2
)

%PYCMD% app.py
