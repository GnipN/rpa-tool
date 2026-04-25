from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import mss
import mss.tools
from PIL import Image
import numpy as np


@dataclass
class Region:
    x: int
    y: int
    width: int
    height: int

    def to_mss_monitor(self) -> dict:
        return {"left": self.x, "top": self.y, "width": self.width, "height": self.height}

    def contains_point(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.width and self.y <= py < self.y + self.height


class ScreenCapture:
    def __init__(self) -> None:
        self._sct = mss.mss()

    def capture_region(self, region: Region) -> Image.Image:
        raw = self._sct.grab(region.to_mss_monitor())
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    def capture_fullscreen(self, monitor_index: int = 1) -> Image.Image:
        monitor = self._sct.monitors[monitor_index]
        raw = self._sct.grab(monitor)
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    def save(self, image: Image.Image, path: str) -> None:
        image.save(path)

    def to_numpy(self, image: Image.Image) -> np.ndarray:
        return np.array(image)

    @staticmethod
    def monitors() -> list[dict]:
        with mss.mss() as sct:
            return sct.monitors[1:]
