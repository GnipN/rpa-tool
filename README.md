# RPA Tool

A local Windows 11 desktop automation tool with OCR-based screen reading, JSON-driven mouse/keyboard scripting, and event-triggered automation. Runs entirely offline — no API calls at runtime.

## Features

- **Screen region OCR** — draw a region on screen and extract all text using a local EasyOCR model
- **OCR loop mode** — continuously re-read a region at a configurable interval; results shown newest-first with timestamps; history capped at 25 entries
- **Text search & highlight** — type in the search box to live-highlight matching text in OCR output
- **Triggers** — define text-match rules that automatically fire automation scripts when specific text appears during OCR loop reads; cooldown begins only after the triggered script fully completes
- **Mouse control** — click, double-click, right-click, drag, scroll at any screen coordinate
- **Keyboard control** — type text (including Unicode), send hotkeys, press individual keys
- **JSON automation scripts** — define sequences of actions with optional OCR conditions
- **OCR-aware steps** — wait for text to appear, click by text content, assert text is present
- **Example scripts** — built-in library of annotated example scripts loadable directly into the editor
- **Live mouse tracker** — always-visible status bar showing real-time cursor X/Y coordinates
- **Coordinate picker** — click anywhere on screen to capture exact coordinates and copy a ready-to-paste JSON snippet to the clipboard
- **GUI application** — three-tab tkinter interface: OCR Reader, Automation Runner, Triggers

## Requirements

- Windows 11 (Windows 10 also supported)
- Python 3.10 or later — download from [python.org](https://www.python.org/downloads/) or via winget:
  ```
  winget install Python.Python.3.12
  ```
- ~1.5 GB disk space (Python packages + EasyOCR model downloaded on first run)

> **Note:** Use the official Python installer from python.org or winget. MSYS2/Conda Python builds have incompatible wheel tags and will fail to install several dependencies.

## Installation

1. Clone or download this repository
2. Double-click `install.bat`

The installer will:
- Detect Python automatically (supports both standard CPython and MSYS2 layouts)
- Create an isolated virtual environment in `.venv/`
- Install all dependencies from `requirements.txt`
- Generate `run.bat` to launch the app

## Running the App

```
run.bat
```

Or directly:

```
.venv\Scripts\python.exe main.py
```

The first OCR read downloads the EasyOCR English model (~300 MB). This is a one-time download cached in `%USERPROFILE%\.EasyOCR\`.

## Usage

### OCR Reader tab

1. Click **Select Region** — the screen dims and you draw a rectangle with your mouse
2. Click **Read Text** — the selected area is captured and all text is extracted and displayed
3. Type in the **Search** box to highlight matching text in the output in real time

#### Loop mode

1. Set the interval (seconds) in the spinner next to **Start Loop**
2. Click **Start Loop** — the region is re-captured and re-read repeatedly at that interval
3. Each result is prepended with a date/time timestamp and shown newest-first; up to 25 results are kept
4. Click **Stop Loop** to halt; any active trigger rules continue to be evaluated on each read while the loop runs

### Automation Runner tab

1. Click **Open Script…** and choose a `.json` automation file, or paste JSON directly into the editor
2. Click **Examples** to browse the built-in example script library and load any script into the editor
3. Click **Run** — each step executes in sequence with live log output
4. Click **Stop** to abort mid-run

### Triggers tab

Triggers let you fire automation scripts automatically when OCR detects specific text.

1. Click **Add** to create a trigger rule:
   - **Name** — a label shown in the rule list
   - **Trigger text** — the text to watch for in each OCR read
   - **Match mode** — `contains` (default), `exact`, or `regex`
   - **Cooldown (s)** — minimum wait after the triggered script *finishes* before the same rule can fire again (set to `0` for no cooldown)
   - **Enabled** — toggle the rule on or off without deleting it
   - **Script** — the automation JSON to run when the trigger fires; use **Pick Example…** or **Load from file…** to populate it
2. Select a rule and click **Edit** or **Delete** to modify or remove it
3. Click **Toggle Enable** to enable or disable the selected rule without opening the editor
4. The **Status** column shows `idle`, `running`, or `cooling (Xs)` in real time
5. The trigger log at the bottom shows fire events and any script output

Rules are saved automatically to `config/triggers.json`.

### Bottom toolbar

The toolbar at the bottom of the window is always visible regardless of window size.

- **Mouse pos** — updates every 50 ms with the current cursor screen coordinate
- **Pick Coordinate** — click this button, then click anywhere on screen; the coordinate is captured and a JSON snippet (e.g. `{"x": 123, "y": 456}`) is copied to the clipboard
- **Copy JSON** — copies the last picked coordinate JSON again at any time

### Tips for finding coordinates

Use **Pick Coordinate** while building automation scripts to get exact click targets:
1. Click **Pick Coordinate**
2. Move to the element you want to click and click it
3. Paste the copied JSON directly into your script step

## Automation Script Format

Scripts are JSON files with a `name`, optional `description`, and a `steps` array.

```json
{
  "name": "My automation",
  "description": "Optional description",
  "steps": [ ... ]
}
```

### Step types

| Type | Required fields | Description |
|---|---|---|
| `click` | `x`, `y` | Left-click at screen coordinate |
| `double_click` | `x`, `y` | Double-click at coordinate |
| `right_click` | `x`, `y` | Right-click at coordinate |
| `type` | `text` | Type a string (`"unicode": true` for non-ASCII) |
| `hotkey` | `keys` | Press a key combination, e.g. `["ctrl", "c"]` |
| `press` | `key` | Press a single key, e.g. `"enter"`, `"tab"`, `"escape"` |
| `wait` | `seconds` | Pause for N seconds |
| `scroll` | `x`, `y`, `clicks` | Scroll at coordinate (positive = up) |
| `ocr_click` | `region`, `text` | Capture region, find text, click its centre |
| `ocr_wait` | `region`, `text`, `timeout` | Wait until text appears in region (seconds) |
| `ocr_assert` | `region`, `text` | Assert text exists in region, fail if not found |

#### Common optional fields (all step types)

| Field | Default | Description |
|---|---|---|
| `label` | `""` | Human-readable description shown in the run log |
| `delay_before` | `0` | Seconds to wait before this step |
| `delay_after` | `0` | Seconds to wait after this step |

#### Region format (used by `ocr_*` steps)

```json
"region": { "x": 0, "y": 0, "width": 1920, "height": 60 }
```

Coordinates are in screen pixels from the top-left corner of the primary monitor.

### Example script

```json
{
  "name": "Open Notepad and type",
  "steps": [
    { "type": "hotkey", "keys": ["win", "r"], "label": "Open Run dialog" },
    { "type": "wait", "seconds": 0.8 },
    { "type": "type", "text": "notepad" },
    { "type": "press", "key": "enter" },
    {
      "type": "ocr_wait",
      "region": { "x": 0, "y": 0, "width": 1920, "height": 60 },
      "text": "Notepad",
      "timeout": 10,
      "label": "Wait for Notepad title bar"
    },
    { "type": "type", "text": "Hello from RPA Tool!", "unicode": true }
  ]
}
```

## Project Structure

```
rpa-tool/
├── main.py                        # Entry point
├── requirements.txt               # Python dependencies
├── install.bat                    # One-click installer (Windows)
├── src/
│   ├── capture.py                 # Screen region capture (mss + Pillow)
│   ├── ocr.py                     # OCR engine (EasyOCR, runs locally)
│   ├── controller.py              # Mouse and keyboard control (pyautogui + pynput)
│   ├── runner.py                  # JSON script executor
│   ├── triggers.py                # TriggerRule dataclass and TriggerStore
│   └── gui.py                     # tkinter GUI (OCR Reader, Automation Runner, Triggers tabs)
└── config/
    ├── example_automation.json    # Example script: open Notepad and type
    └── triggers.json              # Persisted trigger rules (auto-created)
```

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| mss | 9.0.1 | Fast screen capture |
| Pillow | 12.2.0 | Image processing |
| easyocr | 1.7.1 | Local OCR engine (PyTorch-based) |
| pyautogui | 0.9.54 | Mouse and keyboard automation |
| pynput | 1.7.7 | Unicode keyboard input + coordinate picker |
| numpy | 1.26.4 | Array operations |
| tkinter | built-in | GUI (no install needed) |

## Safety & Failsafe

`pyautogui` failsafe is enabled by default — move the mouse to the **top-left corner of the screen** (coordinate 0, 0) at any time during a running script to immediately abort with a `FailSafeException`.

## Troubleshooting

See [INSTALL_TROUBLESHOOTING.md](INSTALL_TROUBLESHOOTING.md) for a log of problems encountered during initial setup and their solutions, including:

- Windows Store Python stub intercepting `python` command
- MSYS2 Python ABI incompatibility with PyPI wheels
- PyQt6 requiring `qmake` build tool (replaced with tkinter)
- SSL certificate errors during source builds

## License

MIT — see [LICENSE](LICENSE).
