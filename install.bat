@echo off
echo ============================================
echo  RPA Tool - Installer
echo ============================================

:: --- Locate official CPython (skip Windows Store stub and MSYS2) ---
:: MSYS2 Python has wrong ABI tags for PyPI wheels — all heavy packages fall
:: back to source builds that fail on Windows. Use official CPython only.
set PYTHON=

:: 1. User-scope installs (python.org installer / winget --scope user) — newest first
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe
    echo [info] Found CPython 3.13 ^(user^): %LOCALAPPDATA%\Programs\Python\Python313\python.exe
    goto :found_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
    echo [info] Found CPython 3.12 ^(user^): %LOCALAPPDATA%\Programs\Python\Python312\python.exe
    goto :found_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe
    echo [info] Found CPython 3.11 ^(user^): %LOCALAPPDATA%\Programs\Python\Python311\python.exe
    goto :found_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe
    echo [info] Found CPython 3.10 ^(user^): %LOCALAPPDATA%\Programs\Python\Python310\python.exe
    goto :found_python
)

:: 2. System-scope installs (python.org installer / winget --scope machine)
if exist "C:\Python313\python.exe" (
    set PYTHON=C:\Python313\python.exe
    echo [info] Found CPython 3.13 ^(system^): C:\Python313\python.exe
    goto :found_python
)
if exist "C:\Python312\python.exe" (
    set PYTHON=C:\Python312\python.exe
    echo [info] Found CPython 3.12 ^(system^): C:\Python312\python.exe
    goto :found_python
)
if exist "C:\Python311\python.exe" (
    set PYTHON=C:\Python311\python.exe
    echo [info] Found CPython 3.11 ^(system^): C:\Python311\python.exe
    goto :found_python
)
if exist "C:\Python310\python.exe" (
    set PYTHON=C:\Python310\python.exe
    echo [info] Found CPython 3.10 ^(system^): C:\Python310\python.exe
    goto :found_python
)

:: 3. PATH python — only if it is not the Windows Store stub or MSYS2
python --version >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; exit(0 if 'WindowsApps' not in sys.executable and 'msys' not in sys.executable.lower() else 1)" >nul 2>&1
    if not errorlevel 1 (
        set PYTHON=python
        echo [info] Found CPython in PATH
        goto :found_python
    )
    echo [warn] python in PATH is the Windows Store stub or MSYS2 — skipping.
)

echo [ERROR] No official Python 3.10+ installation found.
echo         MSYS2 Python is incompatible with PyPI wheels and cannot be used.
echo         Install official CPython via winget (no admin required^):
echo           winget install Python.Python.3.12 --scope user
echo         Or download from: https://www.python.org/downloads/
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
