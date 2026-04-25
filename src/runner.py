from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Callable

from .capture import ScreenCapture, Region
from .ocr import OCREngine
from .controller import Controller


class StepError(Exception):
    pass


class AutomationRunner:
    """
    Executes an automation script loaded from a JSON config file.

    Supported step types:
      click          — click at absolute (x, y)
      double_click   — double-click at (x, y)
      right_click    — right-click at (x, y)
      type           — type a string (supports unicode)
      hotkey         — press a key combination, e.g. ["ctrl", "c"]
      press          — press a single key
      wait           — sleep for N seconds
      scroll         — scroll at (x, y) by N clicks
      ocr_click      — capture region, find text, click its centre
      ocr_wait       — wait until text appears in region (with timeout)
      ocr_assert     — assert text exists in region (raises on failure)
    """

    def __init__(self, log_callback: Callable[[str], None] | None = None) -> None:
        self._capture = ScreenCapture()
        self._ocr = OCREngine()
        self._ctrl = Controller()
        self._log = log_callback or print

    def load(self, path: str | Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def run(self, script: dict, stop_flag: list[bool] | None = None) -> None:
        steps = script.get("steps", [])
        self._log(f"[runner] Starting '{script.get('name', 'unnamed')}' — {len(steps)} steps")
        for i, step in enumerate(steps):
            if stop_flag and stop_flag[0]:
                self._log("[runner] Stopped by user.")
                return
            self._log(f"[runner] Step {i + 1}/{len(steps)}: {step.get('type')} — {step.get('label', '')}")
            self._execute(step)
        self._log("[runner] Done.")

    def run_file(self, path: str | Path, stop_flag: list[bool] | None = None) -> None:
        self.run(self.load(path), stop_flag)

    def _execute(self, step: dict) -> None:
        t = step.get("type", "")
        delay_before = step.get("delay_before", 0)
        delay_after = step.get("delay_after", 0)

        if delay_before:
            time.sleep(delay_before)

        if t == "click":
            self._ctrl.click(step["x"], step["y"], button=step.get("button", "left"))

        elif t == "double_click":
            self._ctrl.double_click(step["x"], step["y"])

        elif t == "right_click":
            self._ctrl.right_click(step["x"], step["y"])

        elif t == "type":
            text = step["text"]
            if step.get("unicode", False):
                self._ctrl.type_unicode(text)
            else:
                self._ctrl.type_text(text, interval=step.get("interval", 0.02))

        elif t == "hotkey":
            self._ctrl.hotkey(*step["keys"])

        elif t == "press":
            self._ctrl.press_key(step["key"])

        elif t == "wait":
            time.sleep(step.get("seconds", 1))

        elif t == "scroll":
            self._ctrl.scroll(step["x"], step["y"], step.get("clicks", 3))

        elif t == "ocr_click":
            region = Region(**step["region"])
            img = self._capture.capture_region(region)
            matches = self._ocr.find_text(img, step["text"], case_sensitive=step.get("case_sensitive", False))
            if not matches:
                raise StepError(f"ocr_click: text '{step['text']}' not found in region")
            bx, by, bw, bh = matches[0].bbox
            cx = region.x + bx + bw // 2
            cy = region.y + by + bh // 2
            self._ctrl.click(cx, cy)

        elif t == "ocr_wait":
            region = Region(**step["region"])
            timeout = step.get("timeout", 30)
            interval = step.get("interval", 1)
            deadline = time.time() + timeout
            while time.time() < deadline:
                img = self._capture.capture_region(region)
                if self._ocr.contains_text(img, step["text"]):
                    return
                time.sleep(interval)
            raise StepError(f"ocr_wait: text '{step['text']}' not found within {timeout}s")

        elif t == "ocr_assert":
            region = Region(**step["region"])
            img = self._capture.capture_region(region)
            if not self._ocr.contains_text(img, step["text"]):
                raise StepError(f"ocr_assert: text '{step['text']}' not found in region")

        else:
            raise StepError(f"Unknown step type: '{t}'")

        if delay_after:
            time.sleep(delay_after)
