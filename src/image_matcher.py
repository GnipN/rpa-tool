from __future__ import annotations
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


@dataclass
class ImageTemplate:
    id: str
    name: str
    path: str  # absolute path to the template image file
    threshold: float = 0.8
    match_mode: str = "color"  # "color" | "grayscale"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "threshold": self.threshold,
            "match_mode": self.match_mode,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ImageTemplate":
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            name=d["name"],
            path=d["path"],
            threshold=float(d.get("threshold", 0.8)),
            match_mode=d.get("match_mode", "color"),
        )


@dataclass
class MatchResult:
    template_id: str
    template_name: str
    center_x: int
    center_y: int
    confidence: float
    x: int
    y: int
    width: int
    height: int


class ImageMatcher:
    def find_template(
        self,
        screen: Image.Image,
        template: Image.Image,
        template_id: str,
        template_name: str,
        threshold: float = 0.8,
        match_mode: str = "color",
    ) -> list[MatchResult]:
        if match_mode == "grayscale":
            screen_arr = cv2.cvtColor(np.array(screen.convert("RGB")), cv2.COLOR_RGB2GRAY)
            tmpl_arr = cv2.cvtColor(np.array(template.convert("RGB")), cv2.COLOR_RGB2GRAY)
            mask = None
            method = cv2.TM_CCOEFF_NORMED
        else:
            # Color mode: match across R, G, B channels so same-shape images with
            # different colors are distinguished.
            screen_arr = np.array(screen.convert("RGB"))
            # Transparent templates (RGBA PNG): use alpha as a binary mask so only
            # visible pixels drive the match.
            if template.mode == "RGBA":
                tmpl_rgba = np.array(template.convert("RGBA"))
                tmpl_arr = tmpl_rgba[:, :, :3]
                mask = (tmpl_rgba[:, :, 3] >= 128).astype(np.uint8) * 255
                method = cv2.TM_CCORR_NORMED  # only normalized method with mask support
            else:
                tmpl_arr = np.array(template.convert("RGB"))
                mask = None
                method = cv2.TM_CCOEFF_NORMED

        th, tw = tmpl_arr.shape[:2]
        sh, sw = screen_arr.shape[:2]

        if tw > sw or th > sh:
            return []

        result = cv2.matchTemplate(screen_arr, tmpl_arr, method,
                                   mask=mask if mask is not None else None)
        ys, xs = np.where(result >= threshold)

        raw: list[MatchResult] = []
        for x, y in zip(xs.tolist(), ys.tolist()):
            raw.append(MatchResult(
                template_id=template_id,
                template_name=template_name,
                center_x=x + tw // 2,
                center_y=y + th // 2,
                confidence=float(result[y, x]),
                x=x, y=y, width=tw, height=th,
            ))

        return self._nms(raw, min_dist=(tw + th) // 4)

    def _nms(self, results: list[MatchResult], min_dist: int) -> list[MatchResult]:
        """Keep highest-confidence match when two detections are within min_dist pixels."""
        results = sorted(results, key=lambda r: r.confidence, reverse=True)
        kept: list[MatchResult] = []
        for r in results:
            if all(
                abs(r.center_x - k.center_x) >= min_dist or abs(r.center_y - k.center_y) >= min_dist
                for k in kept
            ):
                kept.append(r)
        return kept


class TemplateStore:
    def __init__(self, config_path: Path):
        self._path = config_path
        self.templates: list[ImageTemplate] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self.templates = [ImageTemplate.from_dict(t) for t in data]
            except Exception:
                self.templates = []

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps([t.to_dict() for t in self.templates], indent=2),
            encoding="utf-8",
        )
