from __future__ import annotations
import json
import threading
import time
import uuid
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
from datetime import datetime
import pyautogui

from PIL import Image
from .capture import ScreenCapture, Region
from .ocr import OCREngine
from .runner import AutomationRunner
from .triggers import TriggerRule, TriggerStore
from .image_matcher import ImageMatcher, ImageTemplate, MatchResult, TemplateStore


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
    def __init__(self, master, on_loop_result=None, on_capture_complete=None):
        super().__init__(master, padding=8)
        self._capture = ScreenCapture()  # stateless; new mss ctx per call
        self._ocr = OCREngine()
        self._region: Region | None = None
        self._loop_active = False
        self._reading = False
        self._loop_after_id = None
        self._loop_history: list[tuple[str, str]] = []
        self._on_loop_result = on_loop_result
        self._on_capture_complete = on_capture_complete
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
        region = self._region  # snapshot so it can't change mid-capture
        def worker():
            region_img = None
            try:
                region_img = self._capture.capture_region(region)
                text = self._ocr.read_text(region_img)
                result = text or "(no text detected)"
            except Exception as exc:
                result = f"[error] {exc}"
            self.after(0, lambda t=result, ri=region_img: self._show_result(t, ri, region))
        threading.Thread(target=worker, daemon=True).start()

    def _show_result(self, text, region_img=None, region=None):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._reading = False

        if self._loop_active:
            self._loop_history.insert(0, (ts, text))
            if len(self._loop_history) > 25:
                self._loop_history = self._loop_history[:25]
            self._redraw_loop_output()
            if self._on_loop_result:
                self._on_loop_result(text)
            if self._on_capture_complete and region_img is not None and region is not None:
                self._on_capture_complete(region_img, region.x, region.y)
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
            if self._on_capture_complete and region_img is not None and region is not None:
                self._on_capture_complete(region_img, region.x, region.y)

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


class TriggerRuleDialog(tk.Toplevel):
    """Modal dialog to create or edit a single trigger rule."""

    def __init__(self, master, rule: TriggerRule | None, callback,
                 template_store: TemplateStore | None = None):
        super().__init__(master)
        self.title("Edit Rule" if rule else "Add Rule")
        self.geometry("660x660")
        self.minsize(520, 540)
        self.resizable(True, True)
        self.grab_set()
        self._rule = rule
        self._callback = callback
        # Build [(display_name, id_or_None), ...] for the image template picker
        self._tmpl_opts: list[tuple[str, str | None]] = [("(none)", None)]
        if template_store:
            self._tmpl_opts += [(t.name, t.id) for t in template_store.templates]
        self._build_ui()
        if rule:
            self._populate(rule)

    def _build_ui(self):
        form = ttk.Frame(self, padding=10)
        form.pack(fill="both", expand=True)

        for label, attr, widget_fn in [
            ("Name:", "_name_var", lambda r: ttk.Entry(r, textvariable=self._name_var)),
            ("Trigger text:", "_text_var", lambda r: ttk.Entry(r, textvariable=self._text_var)),
        ]:
            row = ttk.Frame(form)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=16, anchor="w").pack(side="left")
            setattr(self, attr, tk.StringVar())
            widget_fn(row).pack(side="left", fill="x", expand=True)

        row = ttk.Frame(form)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="Match mode:", width=16, anchor="w").pack(side="left")
        self._mode_var = tk.StringVar(value="contains")
        ttk.Combobox(row, textvariable=self._mode_var,
                     values=["contains", "exact", "regex"],
                     state="readonly", width=12).pack(side="left")

        row = ttk.Frame(form)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="Cooldown:", width=16, anchor="w").pack(side="left")
        self._cooldown_var = tk.StringVar(value="0")
        ttk.Spinbox(row, from_=0, to=3600, increment=1,
                    textvariable=self._cooldown_var, width=8).pack(side="left")
        ttk.Label(row, text="sec after script completes (0 = fire again as soon as done)").pack(
            side="left", padx=(6, 0))

        row = ttk.Frame(form)
        row.pack(fill="x", pady=3)
        self._enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Enabled", variable=self._enabled_var).pack(side="left")

        # ── Image condition ────────────────────────────────────────────────────
        img_frame = ttk.LabelFrame(form, text="Image Condition (optional)", padding=(8, 4))
        img_frame.pack(fill="x", pady=(6, 0))

        row = ttk.Frame(img_frame)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="Template:", width=16, anchor="w").pack(side="left")
        self._img_tmpl_var = tk.StringVar(value="(none)")
        tmpl_names = [name for name, _ in self._tmpl_opts]
        self._img_tmpl_cb = ttk.Combobox(row, textvariable=self._img_tmpl_var,
                                          values=tmpl_names, state="readonly", width=26)
        self._img_tmpl_cb.pack(side="left")
        self._img_tmpl_cb.bind("<<ComboboxSelected>>", self._on_img_tmpl_changed)

        row = ttk.Frame(img_frame)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="Condition:", width=16, anchor="w").pack(side="left")
        self._img_cond_var = tk.StringVar(value="found")
        self._img_cond_cb = ttk.Combobox(row, textvariable=self._img_cond_var,
                                          values=["found", "not found"],
                                          state="disabled", width=12)
        self._img_cond_cb.pack(side="left")
        ttk.Label(row, text="  (evaluated on each OCR read alongside text condition)").pack(
            side="left", padx=(4, 0))

        # ── Script editor ──────────────────────────────────────────────────────
        script_frame = ttk.LabelFrame(form, text="Script (JSON)", padding=4)
        script_frame.pack(fill="both", expand=True, pady=(8, 0))

        btn_row = ttk.Frame(script_frame)
        btn_row.pack(fill="x", pady=(0, 4))
        ttk.Button(btn_row, text="Load from file…", command=self._load_file).pack(side="left", padx=(0, 4))
        ttk.Button(btn_row, text="Pick Example…", command=self._pick_example).pack(side="left")

        self._script_editor = scrolledtext.ScrolledText(script_frame, wrap="none",
                                                        font=("Consolas", 9), height=10)
        self._script_editor.pack(fill="both", expand=True)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_row, text="OK", command=self._ok, width=10).pack(side="left")
        ttk.Button(btn_row, text="Cancel", command=self.destroy, width=10).pack(side="right")

    def _on_img_tmpl_changed(self, _=None):
        has_tmpl = self._selected_img_template_id() is not None
        self._img_cond_cb.config(state="readonly" if has_tmpl else "disabled")

    def _selected_img_template_id(self) -> str | None:
        name = self._img_tmpl_var.get()
        return next((tid for n, tid in self._tmpl_opts if n == name), None)

    def _populate(self, rule: TriggerRule):
        self._name_var.set(rule.name)
        self._text_var.set(rule.trigger_text)
        self._mode_var.set(rule.match_mode)
        self._cooldown_var.set(str(int(rule.cooldown)))
        self._enabled_var.set(rule.enabled)
        self._script_editor.delete("1.0", "end")
        self._script_editor.insert("end", json.dumps(rule.script, indent=2))
        # Image condition
        if rule.image_template_id:
            matched = next((n for n, tid in self._tmpl_opts if tid == rule.image_template_id), None)
            if matched:
                self._img_tmpl_var.set(matched)
                self._img_cond_var.set(rule.image_condition)
                self._img_cond_cb.config(state="readonly")

    def _load_file(self):
        path = filedialog.askopenfilename(title="Open Script",
                                          filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")])
        if path:
            self._script_editor.delete("1.0", "end")
            self._script_editor.insert("end", Path(path).read_text(encoding="utf-8"))

    def _pick_example(self):
        def load(json_text):
            self._script_editor.delete("1.0", "end")
            self._script_editor.insert("end", json_text)
        ExampleScriptsDialog(self, load)

    def _ok(self):
        name = self._name_var.get().strip()
        trigger_text = self._text_var.get().strip()
        if not name:
            messagebox.showerror("Validation", "Name is required.", parent=self)
            return
        if not trigger_text:
            messagebox.showerror("Validation", "Trigger text is required.", parent=self)
            return
        try:
            script = json.loads(self._script_editor.get("1.0", "end"))
        except json.JSONDecodeError as exc:
            messagebox.showerror("Invalid JSON", str(exc), parent=self)
            return
        try:
            cooldown = max(0.0, float(self._cooldown_var.get()))
        except ValueError:
            cooldown = 0.0

        img_tmpl_id = self._selected_img_template_id()
        rule = TriggerRule(
            id=self._rule.id if self._rule else str(uuid.uuid4()),
            name=name,
            trigger_text=trigger_text,
            match_mode=self._mode_var.get(),
            script=script,
            cooldown=cooldown,
            enabled=self._enabled_var.get(),
            image_template_id=img_tmpl_id,
            image_condition=self._img_cond_var.get() if img_tmpl_id else "found",
        )
        # Preserve runtime state when editing
        if self._rule:
            rule.running = self._rule.running
            rule.last_completed = self._rule.last_completed
        self._callback(rule)
        self.destroy()


class TriggersPanel(ttk.Frame):
    def __init__(self, master, store: TriggerStore, template_store: TemplateStore | None = None):
        super().__init__(master, padding=8)
        self._store = store
        self._template_store = template_store
        self._build_ui()
        self._refresh_tree()
        self._poll_status()

    def _build_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 4))
        ttk.Button(toolbar, text="Add Rule", command=self._add).pack(side="left", padx=(0, 2))
        ttk.Button(toolbar, text="Edit Rule", command=self._edit).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Delete Rule", command=self._delete).pack(side="left", padx=2)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="Toggle Enable", command=self._toggle).pack(side="left")
        ttk.Button(toolbar, text="Save", command=self._store.save).pack(side="right")

        pane = ttk.PanedWindow(self, orient="vertical")
        pane.pack(fill="both", expand=True)

        tree_frame = ttk.LabelFrame(pane, text="Rules", padding=4)
        cols = ("enabled", "name", "match", "text", "image", "cooldown", "status")
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                  selectmode="browse", height=8)
        self._tree.heading("enabled",  text="On")
        self._tree.heading("name",     text="Name")
        self._tree.heading("match",    text="Match")
        self._tree.heading("text",     text="Trigger Text")
        self._tree.heading("image",    text="Image")
        self._tree.heading("cooldown", text="Cooldown")
        self._tree.heading("status",   text="Status")
        self._tree.column("enabled",   width=35,  anchor="center", stretch=False)
        self._tree.column("name",      width=140)
        self._tree.column("match",     width=75,  anchor="center", stretch=False)
        self._tree.column("text",      width=175)
        self._tree.column("image",     width=80,  anchor="center", stretch=False)
        self._tree.column("cooldown",  width=70,  anchor="center", stretch=False)
        self._tree.column("status",    width=110, anchor="center", stretch=False)
        self._tree.tag_configure("disabled", foreground="#999999")
        self._tree.tag_configure("running",  background="#fff3cd")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<Double-1>", lambda _: self._edit())
        pane.add(tree_frame, weight=2)

        log_frame = ttk.LabelFrame(pane, text="Trigger Log", padding=4)
        log_tb = ttk.Frame(log_frame)
        log_tb.pack(fill="x", pady=(0, 4))
        ttk.Button(log_tb, text="Clear", command=self._clear_log).pack(side="right")
        self._log = scrolledtext.ScrolledText(log_frame, wrap="word", font=("Consolas", 9),
                                              state="disabled", height=8)
        self._log.pack(fill="both", expand=True)
        pane.add(log_frame, weight=1)

    # ── log ────────────────────────────────────────────────────────────────────

    def append_log(self, msg: str):
        """Thread-safe: marshals to main thread via after()."""
        self.after(0, lambda: self._do_append_log(msg))

    def _do_append_log(self, msg: str):
        self._log.config(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.config(state="disabled")

    def _clear_log(self):
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")

    # ── tree ───────────────────────────────────────────────────────────────────

    def _refresh_tree(self):
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        for rule in self._store.rules:
            self._tree.insert("", "end", iid=rule.id,
                              values=self._row_values(rule),
                              tags=(self._row_tag(rule),))

    def _row_values(self, rule: TriggerRule) -> tuple:
        if rule.image_template_id:
            img_str = "✓ img" if rule.image_condition == "found" else "✗ img"
        else:
            img_str = "—"
        return (
            "✓" if rule.enabled else "✗",
            rule.name,
            rule.match_mode,
            rule.trigger_text,
            img_str,
            f"{rule.cooldown:.0f}s",
            self._status_text(rule),
        )

    def _row_tag(self, rule: TriggerRule) -> str:
        if not rule.enabled:
            return "disabled"
        if rule.running:
            return "running"
        return ""

    def _status_text(self, rule: TriggerRule) -> str:
        if not rule.enabled:
            return "disabled"
        if rule.running:
            return "running…"
        if rule.last_completed > 0 and not rule.can_fire():
            remaining = rule.cooldown - (time.monotonic() - rule.last_completed)
            return f"cooling {remaining:.0f}s"
        return "idle"

    def _poll_status(self):
        for rule in self._store.rules:
            if self._tree.exists(rule.id):
                self._tree.item(rule.id,
                                values=self._row_values(rule),
                                tags=(self._row_tag(rule),))
        self.after(500, self._poll_status)

    # ── selection ──────────────────────────────────────────────────────────────

    def _selected_rule(self) -> TriggerRule | None:
        sel = self._tree.selection()
        if not sel:
            return None
        return next((r for r in self._store.rules if r.id == sel[0]), None)

    # ── actions ────────────────────────────────────────────────────────────────

    def _add(self):
        TriggerRuleDialog(self, None, self._on_saved, self._template_store)

    def _edit(self):
        rule = self._selected_rule()
        if rule:
            TriggerRuleDialog(self, rule, self._on_saved, self._template_store)

    def _delete(self):
        rule = self._selected_rule()
        if not rule:
            return
        if messagebox.askyesno("Delete Rule", f"Delete rule {rule.name!r}?", parent=self):
            self._store.rules.remove(rule)
            self._store.save()
            self._tree.delete(rule.id)

    def _toggle(self):
        rule = self._selected_rule()
        if rule:
            rule.enabled = not rule.enabled
            self._store.save()

    def _on_saved(self, rule: TriggerRule):
        existing = next((r for r in self._store.rules if r.id == rule.id), None)
        if existing:
            self._store.rules[self._store.rules.index(existing)] = rule
        else:
            self._store.rules.append(rule)
        self._store.save()
        self._refresh_tree()


class EditTemplateDialog(tk.Toplevel):
    """Modal dialog to edit an ImageTemplate's name and match threshold."""

    def __init__(self, master, template: ImageTemplate, callback):
        super().__init__(master)
        self.title("Edit Template")
        self.geometry("360x185")
        self.resizable(False, False)
        self.grab_set()
        self._template = template
        self._callback = callback
        self._build_ui()

    def _build_ui(self):
        form = ttk.Frame(self, padding=10)
        form.pack(fill="both", expand=True)

        row = ttk.Frame(form)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Name:", width=12, anchor="w").pack(side="left")
        self._name_var = tk.StringVar(value=self._template.name)
        ttk.Entry(row, textvariable=self._name_var).pack(side="left", fill="x", expand=True)

        row = ttk.Frame(form)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Threshold:", width=12, anchor="w").pack(side="left")
        self._thresh_var = tk.StringVar(value=f"{self._template.threshold:.2f}")
        ttk.Spinbox(row, from_=0.50, to=1.00, increment=0.05, format="%.2f",
                    textvariable=self._thresh_var, width=8).pack(side="left")
        ttk.Label(row, text="  (0.50 – 1.00)").pack(side="left")

        row = ttk.Frame(form)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Match mode:", width=12, anchor="w").pack(side="left")
        self._mode_var = tk.StringVar(value=self._template.match_mode)
        ttk.Combobox(row, textvariable=self._mode_var,
                     values=["color", "grayscale"],
                     state="readonly", width=12).pack(side="left")

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_row, text="OK", command=self._ok, width=10).pack(side="left")
        ttk.Button(btn_row, text="Cancel", command=self.destroy, width=10).pack(side="right")

    def _ok(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showerror("Validation", "Name is required.", parent=self)
            return
        try:
            threshold = max(0.50, min(1.00, float(self._thresh_var.get())))
        except ValueError:
            threshold = 0.8
        self._template.name = name
        self._template.threshold = threshold
        self._template.match_mode = self._mode_var.get()
        self._callback(self._template)
        self.destroy()


class ImagePatternPanel(ttk.Frame):
    """Tab for managing template images and viewing per-template match results."""

    def __init__(self, master, store: TemplateStore):
        super().__init__(master, padding=8)
        self._store = store
        self._matcher = ImageMatcher()
        self._last_results: dict[str, str] = {}
        self._match_status: dict[str, bool] = {}  # template_id → found (True/False)
        self._log_history: list[str] = []  # newest first, capped at 25
        self._build_ui()
        self._refresh_tree()

    def _build_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 4))
        ttk.Button(toolbar, text="Add Image…", command=self._add).pack(side="left", padx=(0, 2))
        ttk.Button(toolbar, text="Remove", command=self._remove).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Edit", command=self._edit).pack(side="left", padx=2)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="Scan Now", command=self._scan_now).pack(side="left")

        pane = ttk.PanedWindow(self, orient="vertical")
        pane.pack(fill="both", expand=True)

        tree_frame = ttk.LabelFrame(pane, text="Templates", padding=4)
        cols = ("name", "mode", "threshold", "result")
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                  selectmode="browse", height=8)
        self._tree.heading("name",      text="Name")
        self._tree.heading("mode",      text="Mode")
        self._tree.heading("threshold", text="Threshold")
        self._tree.heading("result",    text="Last Match")
        self._tree.column("name",      width=180)
        self._tree.column("mode",      width=80,  anchor="center", stretch=False)
        self._tree.column("threshold", width=80,  anchor="center", stretch=False)
        self._tree.column("result",    width=320)
        self._tree.tag_configure("missing", foreground="#cc0000")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<Double-1>", lambda _: self._edit())
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        pane.add(tree_frame, weight=2)

        self._path_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._path_var, font=("Consolas", 8),
                  anchor="w", foreground="#666666").pack(fill="x", pady=(2, 0))

        log_frame = ttk.LabelFrame(pane, text="Scan Log", padding=4)
        log_tb = ttk.Frame(log_frame)
        log_tb.pack(fill="x", pady=(0, 4))
        ttk.Button(log_tb, text="Clear", command=self._clear_log).pack(side="right")
        self._log = scrolledtext.ScrolledText(log_frame, wrap="word", font=("Consolas", 9),
                                              state="disabled", height=8)
        self._log.pack(fill="both", expand=True)
        pane.add(log_frame, weight=1)

    def _on_select(self, _=None):
        tmpl = self._selected_template()
        self._path_var.set(f"Path: {tmpl.path}" if tmpl else "")

    def _refresh_tree(self):
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        for tmpl in self._store.templates:
            exists = Path(tmpl.path).exists()
            result_str = self._last_results.get(tmpl.id, "—") if exists else "⚠ file missing"
            self._tree.insert("", "end", iid=tmpl.id,
                              values=(tmpl.name, tmpl.match_mode, f"{tmpl.threshold:.2f}", result_str),
                              tags=("missing",) if not exists else ())

    def _update_result_column(self):
        for tmpl in self._store.templates:
            if self._tree.exists(tmpl.id):
                exists = Path(tmpl.path).exists()
                result_str = self._last_results.get(tmpl.id, "—") if exists else "⚠ file missing"
                self._tree.set(tmpl.id, "result", result_str)

    # ── log ─────────────────────────────────────────────────────────────────────

    def _append_log(self, msg: str):
        self._log_history.insert(0, msg)
        if len(self._log_history) > 25:
            self._log_history = self._log_history[:25]
        self._redraw_log()

    def _redraw_log(self):
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        for i, entry in enumerate(self._log_history):
            if i > 0:
                self._log.insert("end", "\n")
            self._log.insert("end", entry)
        self._log.see("1.0")
        self._log.config(state="disabled")

    def _clear_log(self):
        self._log_history.clear()
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")

    # ── selection ────────────────────────────────────────────────────────────────

    def _selected_template(self) -> ImageTemplate | None:
        sel = self._tree.selection()
        if not sel:
            return None
        return next((t for t in self._store.templates if t.id == sel[0]), None)

    # ── actions ──────────────────────────────────────────────────────────────────

    def _add(self):
        paths = filedialog.askopenfilenames(
            title="Add Template Images",
            filetypes=[("Image Files", "*.png *.jpg *.jpeg *.bmp *.tiff *.webp"),
                       ("All Files", "*.*")],
        )
        if not paths:
            return
        added = 0
        for raw_path in paths:
            path = str(Path(raw_path))
            if any(t.path == path for t in self._store.templates):
                continue
            try:
                Image.open(path).verify()
            except Exception as exc:
                messagebox.showerror("Invalid Image",
                                     f"{Path(path).name}:\n{exc}", parent=self)
                continue
            self._store.templates.append(ImageTemplate(
                id=str(uuid.uuid4()),
                name=Path(path).name,
                path=path,
                threshold=0.8,
            ))
            added += 1
        if added:
            self._store.save()
            self._refresh_tree()

    def _remove(self):
        tmpl = self._selected_template()
        if not tmpl:
            return
        if messagebox.askyesno("Remove Template", f"Remove {tmpl.name!r}?", parent=self):
            self._store.templates.remove(tmpl)
            self._store.save()
            self._tree.delete(tmpl.id)
            self._last_results.pop(tmpl.id, None)
            self._path_var.set("")

    def _edit(self):
        tmpl = self._selected_template()
        if tmpl:
            EditTemplateDialog(self, tmpl, self._on_edited)

    def _on_edited(self, tmpl: ImageTemplate):
        self._store.save()
        self._refresh_tree()

    def _scan_now(self):
        def worker():
            try:
                screenshot = ScreenCapture().capture_fullscreen()
            except Exception as exc:
                self.after(0, lambda: self._append_log(f"[error] capture failed: {exc}"))
                return
            self._match_and_display(screenshot, 0, 0)
        threading.Thread(target=worker, daemon=True).start()

    # ── matching ─────────────────────────────────────────────────────────────────

    def run_matching(self, img: Image.Image, offset_x: int, offset_y: int) -> None:
        """Called from OCRPanel after each read; offset is the region's top-left screen coord."""
        if not self._store.templates:
            return
        threading.Thread(target=self._match_and_display, args=(img, offset_x, offset_y),
                         daemon=True).start()

    def _match_and_display(self, img: Image.Image, offset_x: int = 0, offset_y: int = 0) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        new_results: dict[str, str] = {}
        new_status: dict[str, bool] = {}
        log_lines: list[str] = [f"[{ts}] Scan (region offset: {offset_x}, {offset_y})"]

        for tmpl in list(self._store.templates):
            p = Path(tmpl.path)
            if not p.exists():
                new_results[tmpl.id] = "⚠ file missing"
                log_lines.append(f"  {tmpl.name}: ⚠ file not found")
                continue
            try:
                tmpl_img = Image.open(p)
                matches = self._matcher.find_template(
                    img, tmpl_img,
                    template_id=tmpl.id,
                    template_name=tmpl.name,
                    threshold=tmpl.threshold,
                    match_mode=tmpl.match_mode,
                )
            except Exception as exc:
                new_results[tmpl.id] = f"error: {exc}"
                log_lines.append(f"  {tmpl.name}: error — {exc}")
                continue

            if matches:
                m = matches[0]
                # Translate match coords from region-relative to absolute screen coords
                abs_cx = m.center_x + offset_x
                abs_cy = m.center_y + offset_y
                extra = f"  +{len(matches) - 1} more" if len(matches) > 1 else ""
                new_results[tmpl.id] = f"({abs_cx}, {abs_cy})  conf={m.confidence:.2f}{extra}"
                new_status[tmpl.id] = True
                log_lines.append(
                    f"  {tmpl.name}: center=({abs_cx}, {abs_cy}) conf={m.confidence:.2f}{extra}"
                )
            else:
                new_results[tmpl.id] = "not found"
                new_status[tmpl.id] = False
                log_lines.append(f"  {tmpl.name}: not found")

        log_msg = "\n".join(log_lines)
        self.after(0, lambda nr=new_results, ns=new_status, lm=log_msg: self._on_match_done(nr, ns, lm))

    def _on_match_done(self, new_results: dict[str, str], new_status: dict[str, bool], log_msg: str) -> None:
        self._last_results.update(new_results)
        self._match_status.update(new_status)
        self._append_log(log_msg)
        self._update_result_column()

    def get_match_status(self) -> dict[str, bool]:
        """Return the last known found/not-found result per template ID."""
        return dict(self._match_status)


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RPA Tool")
        self.geometry("960x680")
        self.minsize(700, 500)

        self._build_toolbar()

        config_dir = Path(__file__).parent.parent / "config"
        self._trigger_store = TriggerStore(config_dir / "triggers.json")
        self._template_store = TemplateStore(config_dir / "image_templates.json")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        self._image_panel = ImagePatternPanel(nb, self._template_store)
        triggers_panel = TriggersPanel(nb, self._trigger_store, self._template_store)
        ocr_panel = OCRPanel(nb,
                             on_loop_result=self._on_loop_result,
                             on_capture_complete=self._image_panel.run_matching)

        nb.add(ocr_panel,            text="  OCR Reader  ")
        nb.add(RunnerPanel(nb),      text="  Automation Runner  ")
        nb.add(triggers_panel,       text="  Triggers  ")
        nb.add(self._image_panel,    text="  Image Patterns  ")

        self._trigger_store.set_log_callback(triggers_panel.append_log)

        self._poll_mouse()

    def _on_loop_result(self, text: str):
        self._trigger_store.evaluate(text, AutomationRunner,
                                     image_status=self._image_panel.get_match_status())

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

