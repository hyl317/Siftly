"""macOS TCC permission checks for visual automation.

Three permissions are required:
- Accessibility: allows simulating mouse/keyboard input
- Screen Recording: allows capturing other apps' windows
- Automation: allows sending AppleScript commands to Resolve
"""
from __future__ import annotations

import subprocess


def check_accessibility() -> bool:
    """Check if Accessibility permission is granted (needed for input simulation)."""
    try:
        from ApplicationServices import AXIsProcessTrusted
        return AXIsProcessTrusted()
    except ImportError:
        return False


def check_screen_recording() -> bool:
    """Check if Screen Recording permission is granted.

    Captures the full screen and checks if the result is non-null.
    When screen recording is denied, CGWindowListCreateImage returns None
    for the full-screen capture.
    """
    try:
        from Quartz import (
            CGWindowListCreateImage,
            CGRectInfinite,
            kCGNullWindowID,
            kCGWindowListOptionOnScreenOnly,
            kCGWindowImageDefault,
        )

        image = CGWindowListCreateImage(
            CGRectInfinite,
            kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID,
            kCGWindowImageDefault,
        )
        return image is not None
    except ImportError:
        return False


def check_automation() -> bool:
    """Check if Automation permission is granted for DaVinci Resolve.

    Runs a harmless AppleScript command targeting Resolve. Error -1743
    means the user denied automation access.
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", 'tell application "DaVinci Resolve" to get name'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0 and "-1743" in result.stderr:
            return False
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_all() -> dict[str, bool]:
    """Check all required permissions.

    Returns a dict with keys 'accessibility', 'screen_recording', 'automation'.
    """
    return {
        "accessibility": check_accessibility(),
        "screen_recording": check_screen_recording(),
        "automation": check_automation(),
    }


def request_accessibility():
    """Open System Settings to the Accessibility pane."""
    subprocess.Popen([
        "open", "x-apple.systempreferences:com.apple.preference.security"
        "?Privacy_Accessibility",
    ])
