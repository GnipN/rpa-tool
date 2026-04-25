from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from PIL import Image
import numpy as np


@dataclass
class TextResult:
    text: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x, y, w, h

    def __str__(self) -> str:
        return self.text


class OCREngine:
    def __init__(self, languages: list[str] | None = None) -> None:
        self._languages = languages or ["en"]
        self._reader = None

    def _ensure_loaded(self) -> None:
        if self._reader is None:
            import easyocr
            self._reader = easyocr.Reader(self._languages, gpu=False)

    def read_image(self, image: Image.Image) -> list[TextResult]:
        self._ensure_loaded()
        arr = np.array(image)
        raw = self._reader.readtext(arr)
        results: list[TextResult] = []
        for (bbox_points, text, conf) in raw:
            xs = [p[0] for p in bbox_points]
            ys = [p[1] for p in bbox_points]
            x, y = int(min(xs)), int(min(ys))
            w, h = int(max(xs) - x), int(max(ys) - y)
            results.append(TextResult(text=text.strip(), confidence=conf, bbox=(x, y, w, h)))
        return results

    def read_text(self, image: Image.Image) -> str:
        return " ".join(r.text for r in self.read_image(image) if r.text)

    def find_text(self, image: Image.Image, query: str, case_sensitive: bool = False) -> list[TextResult]:
        results = self.read_image(image)
        q = query if case_sensitive else query.lower()
        return [r for r in results if (r.text if case_sensitive else r.text.lower()) == q]

    def contains_text(self, image: Image.Image, query: str, case_sensitive: bool = False) -> bool:
        results = self.read_image(image)
        q = query if case_sensitive else query.lower()
        return any(q in (r.text if case_sensitive else r.text.lower()) for r in results)
