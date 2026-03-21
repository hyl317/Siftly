"""Mouse and keyboard input simulation with Resolve focus management.

Every input action ensures DaVinci Resolve is frontmost before proceeding.
Uses pyautogui which operates in macOS point coordinates, so all pixel
coordinates from Vision must be divided by the display scale factor first.
"""
from __future__ import annotations

import subprocess
import time

import pyautogui

# Keep failsafe enabled — user can move mouse to screen corner to abort
pyautogui.FAILSAFE = True
# Reduce default pause between pyautogui actions
pyautogui.PAUSE = 0.05


def ensure_resolve_frontmost(timeout: float = 2.0) -> bool:
    """Activate DaVinci Resolve and wait for it to become frontmost.

    Returns True if Resolve is frontmost within the timeout.
    """
    subprocess.run(
        ["osascript", "-e", 'tell application "DaVinci Resolve" to activate'],
        capture_output=True, timeout=5,
    )
    # Wait for focus to settle
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of '
             'first application process whose frontmost is true'],
            capture_output=True, text=True, timeout=5,
        )
        if "DaVinci Resolve" in result.stdout:
            time.sleep(0.3)  # Warm-up delay for UI to be ready
            return True
        time.sleep(0.1)
    return False


def click_point(px: int, py: int, scale_factor: float):
    """Click at pixel coordinates, converting to macOS points first.

    Args:
        px, py: Physical pixel coordinates (from screenshot / Vision).
        scale_factor: Display scale factor (2.0 on Retina).
    """
    ensure_resolve_frontmost()
    pt_x = px / scale_factor
    pt_y = py / scale_factor
    pyautogui.click(pt_x, pt_y)


def click_element(element, scale_factor: float):
    """Click a UIElement at its center coordinates."""
    click_point(element.x, element.y, scale_factor)


def press_key(key: str, modifiers: list[str] | None = None):
    """Press a key with optional modifiers after ensuring Resolve is focused.

    Args:
        key: Key to press (e.g. 's', '6', 'return').
        modifiers: List of modifier keys (e.g. ['alt'], ['shift'], ['command']).
    """
    ensure_resolve_frontmost()
    if modifiers:
        # Map common names to pyautogui names
        mod_map = {
            "alt": "option",
            "opt": "option",
            "cmd": "command",
            "ctrl": "ctrl",
            "shift": "shift",
            "command": "command",
            "option": "option",
        }
        mapped = [mod_map.get(m.lower(), m.lower()) for m in modifiers]
        pyautogui.hotkey(*mapped, key)
    else:
        pyautogui.press(key)


def drag(
    start_px: int, start_py: int,
    end_px: int, end_py: int,
    scale_factor: float,
    duration: float = 0.5,
):
    """Drag from one pixel position to another.

    Useful for color wheels, sliders, and other drag-based controls.
    """
    ensure_resolve_frontmost()
    sx, sy = start_px / scale_factor, start_py / scale_factor
    ex, ey = end_px / scale_factor, end_py / scale_factor
    pyautogui.moveTo(sx, sy)
    pyautogui.mouseDown()
    pyautogui.moveTo(ex, ey, duration=duration)
    pyautogui.mouseUp()
