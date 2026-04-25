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
    cooldown: float  # seconds after script completes before the rule can fire again
    enabled: bool
    # Runtime state — not persisted
    running: bool = field(default=False, repr=False)
    last_completed: float = field(default=0.0, repr=False)

    def matches(self, text: str) -> bool:
        if self.match_mode == "exact":
            return self.trigger_text.strip() == text.strip()
        elif self.match_mode == "regex":
            try:
                return bool(re.search(self.trigger_text, text, re.IGNORECASE))
            except re.error:
                return False
        else:  # contains
            return self.trigger_text.lower() in text.lower()

    def can_fire(self) -> bool:
        """True when enabled, not currently running, and cooldown since last completion has elapsed."""
        if not self.enabled or self.running:
            return False
        return time.monotonic() - self.last_completed >= self.cooldown

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "trigger_text": self.trigger_text,
            "match_mode": self.match_mode,
            "script": self.script,
            "cooldown": self.cooldown,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TriggerRule":
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            name=d["name"],
            trigger_text=d["trigger_text"],
            match_mode=d.get("match_mode", "contains"),
            script=d["script"],
            cooldown=float(d.get("cooldown", 0)),
            enabled=bool(d.get("enabled", True)),
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

    def evaluate(self, ocr_text: str, runner_factory: Callable) -> None:
        """Check all enabled rules against ocr_text and fire any that match and can fire."""
        for rule in self.rules:
            if rule.matches(ocr_text) and rule.can_fire():
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
