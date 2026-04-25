from __future__ import annotations
import time
import pyautogui
from pynput.keyboard import Controller as KeyboardController, Key

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


class Controller:
    def __init__(self) -> None:
        self._kb = KeyboardController()

    # --- Mouse ---

    def move(self, x: int, y: int, duration: float = 0.2) -> None:
        pyautogui.moveTo(x, y, duration=duration)

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1, duration: float = 0.2) -> None:
        pyautogui.click(x, y, button=button, clicks=clicks, duration=duration)

    def double_click(self, x: int, y: int, duration: float = 0.2) -> None:
        pyautogui.doubleClick(x, y, duration=duration)

    def right_click(self, x: int, y: int, duration: float = 0.2) -> None:
        pyautogui.rightClick(x, y, duration=duration)

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> None:
        pyautogui.moveTo(x1, y1, duration=0.1)
        pyautogui.dragTo(x2, y2, duration=duration, button="left")

    def scroll(self, x: int, y: int, clicks: int) -> None:
        pyautogui.scroll(clicks, x=x, y=y)

    # --- Keyboard ---

    def type_text(self, text: str, interval: float = 0.02) -> None:
        pyautogui.typewrite(text, interval=interval)

    def type_unicode(self, text: str) -> None:
        self._kb.type(text)

    def hotkey(self, *keys: str) -> None:
        pyautogui.hotkey(*keys)

    def press_key(self, key: str) -> None:
        pyautogui.press(key)

    # --- Utility ---

    def wait(self, seconds: float) -> None:
        time.sleep(seconds)

    def mouse_position(self) -> tuple[int, int]:
        return pyautogui.position()
