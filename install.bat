@echo off
echo ============================================
echo  RPA Tool - Installer
echo ============================================

:: --- Locate a real Python (skip Windows Store stub) ---
set PYTHON=

:: 1. MSYS2 UCRT64 (common on Windows developer machines)
if exist "C:\msys64\ucrt64\bin\python.exe" (
    set PYTHON=C:\msys64\ucrt64\bin\python.exe
    echo [info] Found MSYS2 Python: %PYTHON%
    goto :found_python
)

:: 2. Standard CPython in PATH — test it actually works
python --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON=python
    goto :found_python
)

echo [ERROR] No working Python found.
echo         Install Python 3.10+ from https://python.org or via winget:
echo           winget install Python.Python.3.12
exit /b 1

:found_python

echo [1/3] Creating virtual environment...
if exist ".venv\bin\python.exe"     goto :venv_ok
if exist ".venv\Scripts\python.exe" goto :venv_ok
"%PYTHON%" -m venv .venv
if errorlevel 1 ( echo [ERROR] venv creation failed. & exit /b 1 )

:venv_ok
:: Detect venv layout (Unix bin\ vs Windows Scripts\)
set VENV_PY=
if exist ".venv\Scripts\python.exe" set VENV_PY=.venv\Scripts\python.exe
if exist ".venv\bin\python.exe"     set VENV_PY=.venv\bin\python.exe
if "%VENV_PY%"=="" ( echo [ERROR] Cannot locate python.exe inside venv. & exit /b 1 )
echo [info] Using venv: %VENV_PY%

echo [2/3] Installing dependencies...
"%VENV_PY%" -m pip install --upgrade pip
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 ( echo [ERROR] pip install failed. & exit /b 1 )

echo [3/3] Creating launcher (run.bat)...
(
    echo @echo off
    echo "%~dp0%VENV_PY%" "%~dp0main.py"
) > run.bat

echo.
echo ============================================
echo  Done! Run the app with:  run.bat
echo ============================================
