# Installation Troubleshooting Log

Problems encountered and solutions applied during the initial installation of RPA Tool on Windows 11.

---

## Problem 1 — `install.bat` not recognized when run from PowerShell

**Symptom**
```
cmd : 'install.bat' is not recognized as an internal or external command
```

**Cause**
Running `cmd /c install.bat` from PowerShell without a working directory set, or with a relative path that PowerShell doesn't resolve to the batch file's directory.

**Solution**
Pass the full absolute path to `cmd /c`:
```powershell
cmd /c "c:\projects\claude-cont-tasks\rpa-tool\install.bat"
```

---

## Problem 2 — Python not found (`install.bat` fails at Python check)

**Symptom**
```
[ERROR] Python not found. Install Python 3.10+ from https://python.org and re-run.
```

**Cause**
`where python` on Windows 11 finds `C:\Users\<user>\AppData\Local\Microsoft\WindowsApps\python.exe`, which is a **Windows Store redirect stub** — not a real Python installation. The stub outputs an error message and exits with a non-zero code when invoked.

Even though MSYS2 Python was present at `C:\msys64\ucrt64\bin\python.exe`, the original `install.bat` only called `python --version` which hit the stub first.

**Solution — Step 1 (short-term)**
Updated `install.bat` to check known real Python locations in priority order, skipping the Store stub:

```batch
:: 1. MSYS2 UCRT64
if exist "C:\msys64\ucrt64\bin\python.exe" set PYTHON=C:\msys64\ucrt64\bin\python.exe

:: 2. Official CPython user-scope install (python.org / winget)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" ...

:: 3. Standard PATH python — only if it actually works
python --version >nul 2>&1 && set PYTHON=python
```

**Solution — Step 2 (permanent)**
Installed official CPython 3.12.10 via winget (user scope, no admin/UAC required):
```powershell
winget install Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
```

---

## Problem 3 — `install.bat` blocked waiting for keypress (non-interactive)

**Symptom**
The background process hung indefinitely with the message:
```
Press any key to continue . . .
```

**Cause**
The original `install.bat` used `pause` after every error and at the end. When run non-interactively (from PowerShell background task, CI, etc.) `pause` blocks forever.

**Solution**
Removed all `pause` calls from `install.bat`. Errors now print a message and `exit /b 1` immediately.

---

## Problem 4 — PyQt6 build fails: `qmake` not found

**Symptom**
```
sipbuild.pyproject.PyProjectOptionException
raise PyProjectOptionException('qmake', ...)
error: metadata-generation-failed
```

**Cause**
PyQt6 6.7.0 has no pre-built wheel for the MSYS2 Python ABI (`mingw_ucrt_x86_64`). pip fell back to building from source, which requires Qt's `qmake` tool — not present on this machine.

**Solution**
Replaced PyQt6 entirely with **tkinter**, which is bundled inside every standard Python installation and requires no separate install or build tools. Rewrote `src/gui.py` accordingly.

```diff
- PyQt6==6.7.0
+ # tkinter is built into Python — no entry needed
```

---

## Problem 5 — numpy / Pillow / pyautogui build from source and fail

**Symptom**
```
ERROR: Failed to build 'numpy' when installing backend dependencies for numpy
  cmake: ssl.SSLCertVerificationError: certificate verify failed
```

**Cause**
MSYS2 Python 3.12 uses the ABI tag `cp312-cp312-mingw_ucrt_x86_64`. PyPI provides pre-built wheels only for the standard Windows tag `cp312-cp312-win_amd64`. Since no matching wheel was found, pip tried to compile from source, which pulled in `cmake` and `ninja` as build dependencies. The `cmake` wheel itself then failed to bootstrap because MSYS2's SSL certificate store couldn't verify PyPI's TLS certificate.

**Root Cause**
MSYS2 Python is not a drop-in replacement for official CPython on Windows for PyPI package installation. Its non-standard ABI causes widespread source-build fallbacks.

**Solution**
Deleted the MSYS2-based venv and rebuilt it using the newly installed official CPython 3.12.10:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
Remove-Item -Recurse -Force "rpa-tool\.venv"
& $py -m venv "rpa-tool\.venv"
& "rpa-tool\.venv\Scripts\python.exe" -m pip install -r requirements.txt
```

All packages then resolved to `cp312-cp312-win_amd64.whl` pre-built wheels and installed without compilation.

---

## Final Working Installation Steps

```powershell
# 1. Install official Python (one-time, skip if already installed)
winget install Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements

# 2. Create venv using official CPython
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -m venv "c:\projects\claude-cont-tasks\rpa-tool\.venv"

# 3. Install dependencies
& "c:\projects\claude-cont-tasks\rpa-tool\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "c:\projects\claude-cont-tasks\rpa-tool\.venv\Scripts\python.exe" -m pip install -r requirements.txt
```

After this, `run.bat` launches the application directly.

---

## Packages Successfully Installed

| Package | Version | Notes |
|---|---|---|
| mss | 9.0.1 | Screen capture |
| Pillow | 10.3.0 | Image processing |
| easyocr | 1.7.1 | Local OCR engine |
| torch | 2.11.0 | easyocr dependency |
| torchvision | 0.26.0 | easyocr dependency |
| opencv-python-headless | 4.11.0.86 | easyocr dependency |
| pyautogui | 0.9.54 | Mouse & keyboard control |
| pynput | 1.7.7 | Keyboard listener |
| numpy | 1.26.4 | Array processing |
| scipy | 1.17.1 | easyocr dependency |
| scikit-image | 0.26.0 | easyocr dependency |
| tkinter | built-in | GUI (no install needed) |

---

## Key Lessons

- **Never use MSYS2 Python for PyPI-heavy projects on Windows.** Its ABI tags don't match PyPI wheels; source builds break on SSL or missing build tools.
- **The Windows Store Python stub is not Python.** `where python` finding it is a false positive — always test with `python --version` and check the exit code.
- **PyQt6 requires Qt build tools when no wheel matches.** tkinter is a zero-friction alternative for desktop GUIs that works on every Python installation.
- **Remove `pause` from batch files used in automation.** Use `exit /b 1` for errors instead.
