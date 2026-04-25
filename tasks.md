# RPA Tool — Scaffold Tasks

## Project Structure
- [x] Create project directory structure (`rpa-tool/`, `src/`, `config/`)

## Dependencies
- [x] Create `requirements.txt` with all project dependencies

## Source Modules
- [x] Create `src/__init__.py` — package init
- [x] Create `src/capture.py` — screen region capture (select area, screenshot)
- [x] Create `src/ocr.py` — OCR text extraction from screen regions
- [x] Create `src/controller.py` — mouse and keyboard control
- [x] Create `src/runner.py` — automation sequence runner (reads JSON config, executes steps)
- [x] Create `src/gui.py` — main GUI application (region picker, rule editor, run panel)

## Configuration
- [x] Create `config/example_automation.json` — example automation script with comments

## Entry Point & Setup
- [x] Create `main.py` — application entry point
- [x] Create `install.bat` — one-click dependency installer for Windows

## New Features
- [x] Add search field to OCR Reader tab GUI
- [x] Live-highlight matched text in OCR output as user types in search field
- [x] Add live mouse position tracker to status bar
- [x] Add coordinate picker — click anywhere to capture X/Y and copy JSON snippet to clipboard
- [x] Add Example Scripts button to Automation Runner tab
- [x] Build example scripts dialog — browsable list with JSON preview and "Load into Editor" action
- [x] Add looping read text with configurable interval, Start/Stop buttons to OCR Reader tab
- [x] Show date and time timestamp on each OCR read result
