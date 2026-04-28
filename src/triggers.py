from __future__ import annotations
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

_TIME_RE = re.compile(
    r'\b(\d{1,2})[.:h](\d{2})\s*(am|pm)?\b'
    r'|\b(\d{1,2})\s*(am|pm)\b',
    re.IGNORECASE,
)


def _extract_time(text: str) -> str | None:
    """Return first time token found in text as 'HH:MM', or None."""
    m = _TIME_RE.search(text)
    if not m:
        return None
    if m.group(1) is not None:
        h, mi = int(m.group(1)), int(m.group(2))
        ampm = (m.group(3) or "").lower()
    else:
        h, mi = int(m.group(4)), 0
        ampm = (m.group(5) or "").lower()
    if ampm == "pm" and h != 12:
        h += 12
    elif ampm == "am" and h == 12:
        h = 0
    return f"{h % 24:02d}:{mi:02d}"


@dataclass
class TriggerRule:
    id: str
    name: str
    trigger_text: str
    match_mode: str  # "contains" | "exact" | "regex"
    script: dict
    cooldown: float  # seconds after script completes before the rule can fire again
    enabled: bool
    # Optional image condition — both must be set together (None = no image condition)
    image_template_id: str | None = field(default=None)
    image_condition: str = field(default="found")  # "found" | "not found"
    # Cooldown mode
    cooldown_mode: str = field(default="duration")   # "duration" | "until_time"
    cooldown_until_time: str = field(default="")     # "HH:MM" target for until_time mode
    auto_detect_time: bool = field(default=False)    # extract time from matched OCR line
    # Runtime state — not persisted
    running: bool = field(default=False, repr=False)
    last_completed: float = field(default=0.0, repr=False)
    last_fired_wall: float = field(default=0.0, repr=False)

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

        # Image condition (optional) — if no scan data yet, condition fails rather than
        # triggering spuriously on first read.
        if self.image_template_id is not None:
            if image_status is None or self.image_template_id not in image_status:
                return False
            found = image_status[self.image_template_id]
            return found if self.image_condition == "found" else not found

        return True

    def can_fire(self) -> bool:
        """True when enabled, not currently running, and cooldown has elapsed."""
        if not self.enabled or self.running:
            return False
        if self.cooldown_mode == "until_time":
            return self._until_time_ready()
        return time.monotonic() - self.last_completed >= self.cooldown

    def _until_time_ready(self) -> bool:
        if self.last_fired_wall == 0.0:
            return True  # never fired
        if not self.cooldown_until_time:
            return True  # no time configured; auto-detect will provide it on fire
        try:
            h, m = map(int, self.cooldown_until_time.split(":"))
        except Exception:
            return True
        last = datetime.fromtimestamp(self.last_fired_wall)
        now = datetime.now()
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= last:
            target = target + timedelta(days=1)
        return now >= target

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "name": self.name,
            "trigger_text": self.trigger_text,
            "match_mode": self.match_mode,
            "script": self.script,
            "cooldown": self.cooldown,
            "enabled": self.enabled,
            "cooldown_mode": self.cooldown_mode,
            "cooldown_until_time": self.cooldown_until_time,
            "auto_detect_time": self.auto_detect_time,
        }
        if self.image_template_id is not None:
            d["image_template_id"] = self.image_template_id
            d["image_condition"] = self.image_condition
        return d

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
            image_template_id=d.get("image_template_id"),
            image_condition=d.get("image_condition", "found"),
            cooldown_mode=d.get("cooldown_mode", "duration"),
            cooldown_until_time=d.get("cooldown_until_time", ""),
            auto_detect_time=bool(d.get("auto_detect_time", False)),
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
                 image_status: dict[str, bool] | None = None,
                 ocr_lines: list[str] | None = None) -> None:
        """Check all enabled rules against ocr_text (and image_status if set) and fire matches."""
        for rule in self.rules:
            if rule.matches(ocr_text, image_status) and rule.can_fire():
                matched_line = None
                if rule.auto_detect_time and rule.trigger_text.strip() and ocr_lines:
                    matched_line = next(
                        (ln for ln in ocr_lines
                         if rule.trigger_text.lower() in ln.lower()),
                        None,
                    )
                self._fire(rule, runner_factory, matched_line)

    def _fire(self, rule: TriggerRule, runner_factory: Callable,
              matched_line: str | None = None) -> None:
        if rule.auto_detect_time and matched_line:
            detected = _extract_time(matched_line)
            if detected:
                rule.cooldown_until_time = detected
                rule.cooldown_mode = "until_time"
                self._log(f"  ⏰ Cooldown until {detected} (auto-detected)")
        rule.running = True
        rule.last_fired_wall = time.time()
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
