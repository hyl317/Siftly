"""Static DaVinci Resolve UI knowledge — shortcuts and region hints.

This module contains no API calls. It provides keyboard shortcuts and
approximate UI region hints that serve as optimization for the Vision
system. Vision always has final say on actual element positions.
"""
from __future__ import annotations

from app.automation import input_control

# Page keyboard shortcuts: key, [modifiers]
PAGE_SHORTCUTS: dict[str, tuple[str, list[str]]] = {
    "media":    ("2", ["shift"]),
    "cut":      ("3", ["shift"]),
    "edit":     ("4", ["shift"]),
    "fusion":   ("5", ["shift"]),
    "color":    ("6", ["shift"]),
    "fairlight": ("7", ["shift"]),
    "deliver":  ("8", ["shift"]),
}

# Node manipulation shortcuts (Color page)
NODE_SHORTCUTS: dict[str, tuple[str, list[str]]] = {
    "serial_after":  ("s", ["alt"]),
    "serial_before": ("s", ["shift", "alt"]),
    "parallel":      ("p", ["alt"]),
    "layer":         ("l", ["alt"]),
    "outside":       ("o", ["alt"]),
}

# Approximate crop regions as percentage of window: (x%, y%, w%, h%)
# These are optimization hints — Vision is the source of truth.
REGION_HINTS: dict[str, tuple[float, float, float, float]] = {
    "color_toolbar":   (0.0,  0.45, 0.05, 0.10),
    "node_graph":      (0.50, 0.70, 0.50, 0.30),
    "viewer":          (0.05, 0.0,  0.90, 0.45),
    "color_wheels":    (0.0,  0.50, 0.50, 0.50),
    "timeline":        (0.0,  0.75, 1.0,  0.25),
}


def switch_to_page(page: str):
    """Switch Resolve to a page using its keyboard shortcut.

    Raises KeyError if the page name is not recognized.
    """
    key, modifiers = PAGE_SHORTCUTS[page]
    input_control.press_key(key, modifiers)


def add_node(node_type: str = "serial_after"):
    """Add a node using its keyboard shortcut.

    Raises KeyError if the node type is not recognized.
    """
    key, modifiers = NODE_SHORTCUTS[node_type]
    input_control.press_key(key, modifiers)


def get_crop_rect(
    region: str,
    window_w: int,
    window_h: int,
) -> tuple[int, int, int, int]:
    """Convert a region hint to pixel coordinates.

    Args:
        region: Key from REGION_HINTS.
        window_w: Window width in pixels.
        window_h: Window height in pixels.

    Returns:
        (x, y, width, height) in pixels.
    """
    rx, ry, rw, rh = REGION_HINTS[region]
    return (
        int(rx * window_w),
        int(ry * window_h),
        int(rw * window_w),
        int(rh * window_h),
    )
