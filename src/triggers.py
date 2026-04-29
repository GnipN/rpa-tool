from __future__ import annotations
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable


@dataclass
class TriggerRule:
    id: str
    name: str
    trigger_text: str
    match_mode: str  # "contains" | "exact" | "regex"
    script: dict
    enabled: bool
    # Optional image condition
    image_template_id: str | None = field(default=None)
    image_condition: str = field(default="found")  # "found" | "not found"
    # Timing: fire only at/after this datetime; "" = no restriction
    target_datetime: str = field(default="")      # "YYYY-MM-DD HH:MM"
    # Delay between fires (h:m:s)
    delay_h: int = field(default=0)
    delay_m: int = field(default=0)
    delay_s: int = field(default=0)
    # Runtime state — not persisted
    running: bool = field(default=False, repr=False)
    last_completed: float = field(default=0.0, repr=False)

    @property
    def delay_total_s(self) -> float:
        return self.delay_h * 3600 + self.delay_m * 60 + self.delay_s

    def matches(self, text: str, image_status: dict[str, bool] | None = None) -> bool:
        # Text condition — skipped when trigger_text is blank (image-only rule)
        if self.trigger_text.strip():
            if self.match_mode == "exact":
                text_ok = self.trigger_text.strip() == text.strip()
            elif self.match_mode == "regex":
                try:
                    text_ok = bool(re.search(self.trigger_text, text, re.IGNORECASE))
                except re.error:
                    text_ok = False
            else:  # contains
                text_ok = self.trigger_text.lower() in text.lower()
            if not text_ok:
                return False

        # Image condition (optional) — if no scan data yet, condition fails
        if self.image_template_id is not None:
            if image_status is None or self.image_template_id not in image_status:
                return False
            found = image_status[self.image_template_id]
            return found if self.image_condition == "found" else not found

        return True

    def can_fire(self) -> bool:
        """True when enabled, not running, target datetime reached, and delay elapsed."""
        if not self.enabled or self.running:
            return False
        # Specific datetime condition
        if self.target_datetime:
            try:
                target = datetime.strptime(self.target_datetime, "%Y-%m-%d %H:%M")
                if datetime.now() < target:
                    return False
            except ValueError:
                pass
        # Delay condition
        return time.monotonic() - self.last_completed >= self.delay_total_s

    def delay_remaining(self) -> float:
        """Seconds remaining in the post-fire delay (0 when elapsed or never fired)."""
        if self.last_completed == 0.0:
            return 0.0
        remaining = self.delay_total_s - (time.monotonic() - self.last_completed)
        return max(0.0, remaining)

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "name": self.name,
            "trigger_text": self.trigger_text,
            "match_mode": self.match_mode,
            "script": self.script,
            "enabled": self.enabled,
            "target_datetime": self.target_datetime,
            "delay_h": self.delay_h,
            "delay_m": self.delay_m,
            "delay_s": self.delay_s,
        }
        if self.image_template_id is not None:
            d["image_template_id"] = self.image_template_id
            d["image_condition"] = self.image_condition
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TriggerRule":
        # Migrate legacy cooldown (seconds) into delay_s if new fields absent
        legacy_s = int(float(d.get("cooldown", 0)))
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            name=d["name"],
            trigger_text=d["trigger_text"],
            match_mode=d.get("match_mode", "contains"),
            script=d["script"],
            enabled=bool(d.get("enabled", True)),
            image_template_id=d.get("image_template_id"),
            image_condition=d.get("image_condition", "found"),
            target_datetime=d.get("target_datetime", ""),
            delay_h=int(d.get("delay_h", 0)),
            delay_m=int(d.get("delay_m", 0)),
            delay_s=int(d.get("delay_s", legacy_s)),
        )


class TriggerStore:
    def __init__(self, config_path: Path):
        self._path = config_path
        self.rules: list[TriggerRule] = []
        self._log_cb: Callable[[str], None] | None = None
        self._load()

    # ── persistence ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self.rules = [TriggerRule.from_dict(r) for r in data]
            except Exception:
                self.rules = []

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps([r.to_dict() for r in self.rules], indent=2),
            encoding="utf-8",
        )

    # ── logging ────────────────────────────────────────────────────────────────

    def set_log_callback(self, cb: Callable[[str], None]) -> None:
        self._log_cb = cb

    def _log(self, msg: str) -> None:
        if self._log_cb:
            self._log_cb(msg)

    # ── evaluation ─────────────────────────────────────────────────────────────

    def evaluate(self, ocr_text: str, runner_factory: Callable,
                 image_status: dict[str, bool] | None = None) -> None:
        """Check all enabled rules against ocr_text (and image_status if set) and fire matches."""
        for rule in self.rules:
            if rule.matches(ocr_text, image_status) and rule.can_fire():
                self._fire(rule, runner_factory)

    def _fire(self, rule: TriggerRule, runner_factory: Callable) -> None:
        rule.running = True
        self._log(f"[{datetime.now().strftime('%H:%M:%S')}] ▶ Fired: {rule.name!r}")

        def run() -> None:
            runner = runner_factory(log_callback=lambda msg: self._log(f"  {msg}"))
            try:
                runner.run(rule.script, stop_flag=[False])
                self._log(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Done: {rule.name!r}")
            except Exception as exc:
                self._log(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Error in {rule.name!r}: {exc}")
            finally:
                rule.running = False
                rule.last_completed = time.monotonic()

        threading.Thread(target=run, daemon=True).start()
