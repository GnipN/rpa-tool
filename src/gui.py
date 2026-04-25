from __future__ import annotations
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path

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
        self._capture = ScreenCapture()
        self._ocr = OCREngine()
        self._region: Region | None = None
        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 6))

        self._region_var = tk.StringVar(value="No region selected")
        ttk.Label(top, textvariable=self._region_var).pack(side="left", expand=True, anchor="w")
        ttk.Button(top, text="Select Region", command=self._pick_region).pack(side="left", padx=4)
        self._read_btn = ttk.Button(top, text="Read Text", command=self._read_text, state="disabled")
        self._read_btn.pack(side="left")

        self._output = scrolledtext.ScrolledText(self, wrap="word", height=20, font=("Consolas", 10))
        self._output.pack(fill="both", expand=True)

    def _pick_region(self):
        self.winfo_toplevel().iconify()
        self.after(300, lambda: RegionSelector(self, self._on_region))

    def _on_region(self, x, y, w, h):
        self.winfo_toplevel().deiconify()
        self._region = Region(x, y, w, h)
        self._region_var.set(f"Region: ({x}, {y})  {w}×{h}")
        self._read_btn.config(state="normal")

    def _read_text(self):
        if not self._region:
            return
        self._output.delete("1.0", "end")
        self._output.insert("end", "Reading… (first run loads OCR model)\n")
        self._read_btn.config(state="disabled")

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
        self._output.delete("1.0", "end")
        self._output.insert("end", text)
        self._read_btn.config(state="normal")


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

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        nb.add(OCRPanel(nb), text="  OCR Reader  ")
        nb.add(RunnerPanel(nb), text="  Automation Runner  ")

        self._status = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self._status, anchor="w", relief="sunken").pack(
            fill="x", side="bottom", padx=2, pady=2)
