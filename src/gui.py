from __future__ import annotations
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
from datetime import datetime
import pyautogui

from .capture import ScreenCapture, Region
from .ocr import OCREngine
from .runner import AutomationRunner


class RegionSelector(tk.Toplevel):
    """Fullscreen transparent overlay for drawing a capture region."""

    def __init__(self, master, callback):
        super().__init__(master)
        self._callback = callback
        self._start_x = self._start_y = 0
        self._rect = None

        self.attributes("-fullscreen", True)
        self.attributes("-alpha", 0.25)
        self.attributes("-topmost", True)
        self.configure(bg="black", cursor="crosshair")

        self._canvas = tk.Canvas(self, bg="black", highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)

        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", lambda _: self.destroy())

    def _on_press(self, e):
        self._start_x, self._start_y = e.x_root, e.y_root
        if self._rect:
            self._canvas.delete(self._rect)

    def _on_drag(self, e):
        if self._rect:
            self._canvas.delete(self._rect)
        x0 = self._start_x - self.winfo_rootx()
        y0 = self._start_y - self.winfo_rooty()
        x1 = e.x
        y1 = e.y
        self._rect = self._canvas.create_rectangle(x0, y0, x1, y1, outline="red", width=2)

    def _on_release(self, e):
        x = min(self._start_x, e.x_root)
        y = min(self._start_y, e.y_root)
        w = abs(e.x_root - self._start_x)
        h = abs(e.y_root - self._start_y)
        self.destroy()
        if w > 5 and h > 5:
            self._callback(x, y, w, h)


class OCRPanel(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=8)
        self._capture = ScreenCapture()  # stateless; new mss ctx per call
        self._ocr = OCREngine()
        self._region: Region | None = None
        self._loop_active = False
        self._reading = False
        self._loop_after_id = None
        self._loop_history: list[tuple[str, str]] = []
        self._build_ui()

    def _build_ui(self):
        # Row 1: region selector
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 4))
        self._region_var = tk.StringVar(value="No region selected")
        ttk.Label(top, textvariable=self._region_var).pack(side="left", expand=True, anchor="w")
        ttk.Button(top, text="Select Region", command=self._pick_region).pack(side="left", padx=4)
        self._read_btn = ttk.Button(top, text="Read Text", command=self._read_text, state="disabled")
        self._read_btn.pack(side="left")

        # Row 2: loop controls
        loop_row = ttk.Frame(self)
        loop_row.pack(fill="x", pady=(0, 4))
        ttk.Label(loop_row, text="Loop interval:").pack(side="left")
        self._interval_var = tk.StringVar(value="5.0")
        self._interval_spin = ttk.Spinbox(loop_row, from_=0.5, to=3600.0, increment=0.5,
                                          textvariable=self._interval_var, width=7, format="%.1f")
        self._interval_spin.pack(side="left", padx=(4, 2))
        ttk.Label(loop_row, text="sec").pack(side="left")
        self._start_loop_btn = ttk.Button(loop_row, text="Start Loop",
                                          command=self._start_loop, state="disabled")
        self._start_loop_btn.pack(side="left", padx=(10, 2))
        self._stop_loop_btn = ttk.Button(loop_row, text="Stop Loop",
                                         command=self._stop_loop, state="disabled")
        self._stop_loop_btn.pack(side="left")

        # Row 3: search bar
        search_row = ttk.Frame(self)
        search_row.pack(fill="x", pady=(0, 4))
        ttk.Label(search_row, text="Search:").pack(side="left", padx=(0, 4))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._highlight())
        self._search_entry = ttk.Entry(search_row, textvariable=self._search_var)
        self._search_entry.pack(side="left", fill="x", expand=True)
        self._match_label = ttk.Label(search_row, text="")
        self._match_label.pack(side="left", padx=(6, 0))

        # Output area
        self._output = scrolledtext.ScrolledText(self, wrap="word", height=20, font=("Consolas", 10))
        self._output.tag_configure("match", background="#ffff00", foreground="#000000")
        self._output.tag_configure("timestamp", foreground="#888888", font=("Consolas", 9))
        self._output.pack(fill="both", expand=True)

    def _pick_region(self):
        self.winfo_toplevel().iconify()
        self.after(300, lambda: RegionSelector(self, self._on_region))

    def _on_region(self, x, y, w, h):
        self.winfo_toplevel().deiconify()
        self._region = Region(x, y, w, h)
        self._region_var.set(f"Region: ({x}, {y})  {w}×{h}")
        self._read_btn.config(state="normal")
        self._start_loop_btn.config(state="normal")

    def _highlight(self):
        self._output.tag_remove("match", "1.0", "end")
        query = self._search_var.get()
        if not query:
            self._match_label.config(text="")
            return
        content = self._output.get("1.0", "end")
        count = 0
        start = 0
        while True:
            idx = content.lower().find(query.lower(), start)
            if idx == -1:
                break
            line = content.count("\n", 0, idx) + 1
            col = idx - content.rfind("\n", 0, idx) - 1
            end_col = col + len(query)
            self._output.tag_add("match", f"{line}.{col}", f"{line}.{end_col}")
            count += 1
            start = idx + len(query)
        self._match_label.config(
            text=f"{count} match{'es' if count != 1 else ''}" if count else "no matches"
        )

    def _read_text(self):
        if not self._region or self._reading:
            return
        self._reading = True
        self._read_btn.config(state="disabled")
        self._start_loop_btn.config(state="disabled")
        self._output.delete("1.0", "end")
        self._output.insert("end", "Reading… (first run loads OCR model)\n")
        self._do_capture()

    def _start_loop(self):
        if not self._region or self._reading:
            return
        self._loop_history.clear()
        self._output.delete("1.0", "end")
        self._loop_active = True
        self._reading = True
        self._read_btn.config(state="disabled")
        self._start_loop_btn.config(state="disabled")
        self._stop_loop_btn.config(state="normal")
        self._interval_spin.config(state="disabled")
        self._do_capture()

    def _stop_loop(self):
        self._loop_active = False
        if self._loop_after_id:
            self.after_cancel(self._loop_after_id)
            self._loop_after_id = None
            self._restore_controls()
        # if a read is in progress, _show_result will call _restore_controls

    def _restore_controls(self):
        self._stop_loop_btn.config(state="disabled")
        self._start_loop_btn.config(state="normal")
        self._read_btn.config(state="normal")
        self._interval_spin.config(state="normal")

    def _do_capture(self):
        def worker():
            try:
                img = self._capture.capture_region(self._region)
                text = self._ocr.read_text(img)
                result = text or "(no text detected)"
            except Exception as exc:
                result = f"[error] {exc}"
            self.after(0, lambda: self._show_result(result))
        threading.Thread(target=worker, daemon=True).start()

    def _show_result(self, text):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._reading = False

        if self._loop_active:
            self._loop_history.insert(0, (ts, text))
            if len(self._loop_history) > 25:
                self._loop_history = self._loop_history[:25]
            self._redraw_loop_output()
            try:
                interval_ms = max(100, int(float(self._interval_var.get()) * 1000))
            except ValueError:
                interval_ms = 5000
            self._loop_after_id = self.after(interval_ms, self._schedule_next_loop_read)
        else:
            # Single read: replace content
            self._output.delete("1.0", "end")
            self._output.insert("end", f"── {ts} ──\n", "timestamp")
            self._output.insert("end", text)
            self._restore_controls()
            self._highlight()

    def _redraw_loop_output(self):
        self._output.delete("1.0", "end")
        for i, (ts, text) in enumerate(self._loop_history):
            if i > 0:
                self._output.insert("end", "\n")
            self._output.insert("end", f"── {ts} ──\n", "timestamp")
            self._output.insert("end", text + "\n")
        self._output.see("1.0")
        self._highlight()

    def _schedule_next_loop_read(self):
        self._loop_after_id = None
        if self._loop_active:
            self._reading = True
            self._do_capture()
        else:
            self._restore_controls()


_EXAMPLE_SCRIPTS = [
    (
        "Open Notepad and type",
        "Opens Notepad via the Run dialog, waits for the window, then types a message.",
        {
            "name": "Open Notepad and type",
            "steps": [
                {"type": "hotkey", "keys": ["win", "r"], "label": "Open Run dialog"},
                {"type": "wait", "seconds": 0.8},
                {"type": "type", "text": "notepad"},
                {"type": "press", "key": "enter"},
                {"type": "ocr_wait", "region": {"x": 0, "y": 0, "width": 1920, "height": 60},
                 "text": "Notepad", "timeout": 10, "label": "Wait for Notepad title bar"},
                {"type": "type", "text": "Hello from RPA Tool!", "unicode": True},
            ],
        },
    ),
    (
        "Click sequence",
        "Clicks a series of screen coordinates in order — useful for navigating menus or buttons.",
        {
            "name": "Click sequence",
            "steps": [
                {"type": "click", "x": 100, "y": 200, "label": "First button"},
                {"type": "wait", "seconds": 0.5},
                {"type": "click", "x": 300, "y": 400, "label": "Second button"},
                {"type": "wait", "seconds": 0.5},
                {"type": "double_click", "x": 500, "y": 300, "label": "Open item"},
            ],
        },
    ),
    (
        "Wait for text then click",
        "Waits until specific text appears on screen, then clicks it. Good for pages that load slowly.",
        {
            "name": "Wait for text then click",
            "steps": [
                {"type": "ocr_wait",
                 "region": {"x": 0, "y": 0, "width": 1920, "height": 1080},
                 "text": "Submit", "timeout": 15, "label": "Wait for Submit button to appear"},
                {"type": "ocr_click",
                 "region": {"x": 0, "y": 0, "width": 1920, "height": 1080},
                 "text": "Submit", "label": "Click Submit"},
            ],
        },
    ),
    (
        "Fill a form",
        "Clicks into form fields and types values, using Tab to move between fields.",
        {
            "name": "Fill a form",
            "steps": [
                {"type": "click", "x": 400, "y": 300, "label": "Click Name field"},
                {"type": "type", "text": "John Doe"},
                {"type": "press", "key": "tab"},
                {"type": "type", "text": "john@example.com"},
                {"type": "press", "key": "tab"},
                {"type": "type", "text": "password123"},
                {"type": "hotkey", "keys": ["enter"], "label": "Submit form"},
            ],
        },
    ),
    (
        "Hotkeys sequence",
        "Selects all text, copies it, switches to another window, and pastes.",
        {
            "name": "Hotkeys sequence",
            "steps": [
                {"type": "hotkey", "keys": ["ctrl", "a"], "label": "Select all"},
                {"type": "hotkey", "keys": ["ctrl", "c"], "label": "Copy"},
                {"type": "hotkey", "keys": ["alt", "tab"], "label": "Switch window"},
                {"type": "wait", "seconds": 0.5},
                {"type": "hotkey", "keys": ["ctrl", "v"], "label": "Paste"},
            ],
        },
    ),
    (
        "Assert text is visible",
        "Asserts that expected text exists on screen — fails the script if it is missing.",
        {
            "name": "Assert text is visible",
            "steps": [
                {"type": "ocr_assert",
                 "region": {"x": 0, "y": 0, "width": 1920, "height": 1080},
                 "text": "Success", "label": "Verify success message is shown"},
            ],
        },
    ),
    (
        "Scroll and read",
        "Scrolls down a page several times, pausing to let content load between scrolls.",
        {
            "name": "Scroll and read",
            "steps": [
                {"type": "scroll", "x": 960, "y": 540, "clicks": -5, "label": "Scroll down"},
                {"type": "wait", "seconds": 1},
                {"type": "scroll", "x": 960, "y": 540, "clicks": -5, "label": "Scroll down again"},
                {"type": "wait", "seconds": 1},
                {"type": "scroll", "x": 960, "y": 540, "clicks": 10, "label": "Scroll back to top"},
            ],
        },
    ),
    (
        "Save a file",
        "Triggers Save As via hotkey, types a filename, and confirms.",
        {
            "name": "Save a file",
            "steps": [
                {"type": "hotkey", "keys": ["ctrl", "shift", "s"], "label": "Open Save As dialog"},
                {"type": "wait", "seconds": 1},
                {"type": "type", "text": "my_output.txt"},
                {"type": "press", "key": "enter", "label": "Confirm save"},
            ],
        },
    ),
]


class ExampleScriptsDialog(tk.Toplevel):
    def __init__(self, master, load_callback):
        super().__init__(master)
        self.title("Example Scripts")
        self.geometry("820x520")
        self.minsize(600, 380)
        self.resizable(True, True)
        self.grab_set()

        self._load_callback = load_callback
        self._build_ui()
        self._listbox.selection_set(0)
        self._on_select()

    def _build_ui(self):
        # Main horizontal pane
        pane = ttk.PanedWindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        # Left: list of example names
        list_frame = ttk.LabelFrame(pane, text="Examples", padding=4)
        self._listbox = tk.Listbox(list_frame, selectmode="single", activestyle="dotbox",
                                   font=("Segoe UI", 10), width=28, exportselection=False)
        for name, _, _ in _EXAMPLE_SCRIPTS:
            self._listbox.insert("end", f"  {name}")
        self._listbox.pack(fill="both", expand=True)
        self._listbox.bind("<<ListboxSelect>>", lambda _: self._on_select())
        pane.add(list_frame, weight=1)

        # Right: description + JSON preview
        right_frame = ttk.Frame(pane, padding=(4, 0, 0, 0))
        self._desc_var = tk.StringVar()
        ttk.Label(right_frame, textvariable=self._desc_var, wraplength=480,
                  justify="left").pack(anchor="w", pady=(0, 6))
        self._preview = scrolledtext.ScrolledText(right_frame, wrap="none",
                                                  font=("Consolas", 9), state="disabled")
        self._preview.pack(fill="both", expand=True)
        pane.add(right_frame, weight=2)

        # Bottom button row
        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btn_row, text="Load into Editor", command=self._load).pack(side="left")
        ttk.Button(btn_row, text="Close", command=self.destroy).pack(side="right")

    def _on_select(self):
        sel = self._listbox.curselection()
        if not sel:
            return
        _, desc, script = _EXAMPLE_SCRIPTS[sel[0]]
        self._desc_var.set(desc)
        text = json.dumps(script, indent=2)
        self._preview.config(state="normal")
        self._preview.delete("1.0", "end")
        self._preview.insert("end", text)
        self._preview.config(state="disabled")

    def _load(self):
        sel = self._listbox.curselection()
        if not sel:
            return
        _, _, script = _EXAMPLE_SCRIPTS[sel[0]]
        self._load_callback(json.dumps(script, indent=2))
        self.destroy()


class RunnerPanel(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=8)
        self._script: dict | None = None
        self._stop_flag: list[bool] = [False]
        self._thread: threading.Thread | None = None
        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 6))

        self._file_var = tk.StringVar(value="No script loaded")
        ttk.Label(top, textvariable=self._file_var).pack(side="left", expand=True, anchor="w")
        ttk.Button(top, text="Examples", command=self._show_examples).pack(side="left", padx=(0, 4))
        ttk.Button(top, text="Open Script…", command=self._open_file).pack(side="left", padx=4)
        self._run_btn = ttk.Button(top, text="Run", command=self._run, state="disabled")
        self._run_btn.pack(side="left", padx=2)
        self._stop_btn = ttk.Button(top, text="Stop", command=self._stop, state="disabled")
        self._stop_btn.pack(side="left")

        pane = ttk.PanedWindow(self, orient="vertical")
        pane.pack(fill="both", expand=True)

        editor_frame = ttk.LabelFrame(pane, text="Script (JSON)", padding=4)
        self._editor = scrolledtext.ScrolledText(editor_frame, wrap="none", height=18, font=("Consolas", 10))
        self._editor.pack(fill="both", expand=True)
        pane.add(editor_frame, weight=2)

        log_frame = ttk.LabelFrame(pane, text="Run Log", padding=4)
        self._log = scrolledtext.ScrolledText(log_frame, wrap="word", height=8, font=("Consolas", 9),
                                               state="disabled")
        self._log.pack(fill="both", expand=True)
        pane.add(log_frame, weight=1)

    def _show_examples(self):
        ExampleScriptsDialog(self, self._load_example)

    def _load_example(self, json_text: str):
        self._editor.delete("1.0", "end")
        self._editor.insert("end", json_text)
        self._file_var.set("(example script)")
        self._run_btn.config(state="normal")

    def _open_file(self):
        path = filedialog.askopenfilename(title="Open Automation Script",
                                          filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")])
        if not path:
            return
        text = Path(path).read_text(encoding="utf-8")
        self._editor.delete("1.0", "end")
        self._editor.insert("end", text)
        self._script = json.loads(text)
        self._file_var.set(Path(path).name)
        self._run_btn.config(state="normal")

    def _append_log(self, line: str):
        self._log.config(state="normal")
        self._log.insert("end", line + "\n")
        self._log.see("end")
        self._log.config(state="disabled")

    def _run(self):
        try:
            self._script = json.loads(self._editor.get("1.0", "end"))
        except json.JSONDecodeError as e:
            messagebox.showerror("Invalid JSON", str(e))
            return

        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")
        self._stop_flag[0] = False
        self._run_btn.config(state="disabled")
        self._stop_btn.config(state="normal")

        def worker():
            runner = AutomationRunner(log_callback=lambda msg: self.after(0, lambda m=msg: self._append_log(m)))
            try:
                runner.run(self._script, stop_flag=self._stop_flag)
            except Exception as exc:
                self.after(0, lambda: self._append_log(f"[error] {exc}"))
            self.after(0, self._on_done)

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

    def _stop(self):
        self._stop_flag[0] = True

    def _on_done(self):
        self._run_btn.config(state="normal")
        self._stop_btn.config(state="disabled")


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RPA Tool")
        self.geometry("960x680")
        self.minsize(700, 500)

        self._build_toolbar()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        nb.add(OCRPanel(nb), text="  OCR Reader  ")
        nb.add(RunnerPanel(nb), text="  Automation Runner  ")

        self._poll_mouse()

    def _build_toolbar(self):
        self._last_json = ""
        bar = ttk.Frame(self, relief="sunken", padding=(6, 3))
        bar.pack(fill="x", side="bottom", padx=2, pady=(2, 2))

        # Live mouse position
        self._mouse_var = tk.StringVar(value="Mouse  X=—  Y=—")
        ttk.Label(bar, textvariable=self._mouse_var, width=22, anchor="w",
                  font=("Consolas", 9)).pack(side="left")

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)

        # Coordinate picker
        ttk.Button(bar, text="Pick Coordinate", command=self._pick_coordinate).pack(side="left")

        self._coord_var = tk.StringVar(value="")
        self._coord_label = ttk.Label(bar, textvariable=self._coord_var,
                                      font=("Consolas", 9), anchor="w")
        self._coord_label.pack(side="left", padx=(10, 0))

        ttk.Button(bar, text="Copy JSON", command=self._copy_last_json).pack(side="right")

    def _poll_mouse(self):
        try:
            pos = pyautogui.position()
            self._mouse_var.set(f"Mouse  X={pos.x}  Y={pos.y}")
        except Exception:
            pass
        self.after(50, self._poll_mouse)

    def _pick_coordinate(self):
        self._coord_var.set("Click anywhere on screen…")
        self._last_json = ""
        self.iconify()
        self.after(300, self._start_pick_listener)

    def _start_pick_listener(self):
        from pynput import mouse as _mouse

        def on_click(x, y, button, pressed):
            if pressed and button == _mouse.Button.left:
                self.after(0, lambda: self._on_coord_captured(int(x), int(y)))
                return False  # stop listener

        _mouse.Listener(on_click=on_click).start()

    def _on_coord_captured(self, x, y):
        self.deiconify()
        self._last_json = json.dumps({"type": "click", "x": x, "y": y})
        self._copy_to_clipboard(self._last_json)
        self._coord_var.set(f"({x}, {y})  — JSON copied")

    def _copy_last_json(self):
        if self._last_json:
            self._copy_to_clipboard(self._last_json)
            self._coord_var.set(self._coord_var.get().split("—")[0] + "— JSON copied")

    def _copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)

