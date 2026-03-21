"""Quartz-based window capture with Retina coordinate translation.

Key invariant:
- Screenshots are in physical pixels (e.g. 5120x2880 on Retina 2x).
- Vision returns pixel coordinates in screenshot space.
- Mouse input needs point coordinates (pixels / scale_factor).
"""
from __future__ import annotations

from PIL import Image

from Quartz import (
    CGRectNull,
    CGRectMake,
    CGWindowListCopyWindowInfo,
    CGWindowListCreateImage,
    kCGNullWindowID,
    kCGWindowListOptionOnScreenOnly,
    kCGWindowListOptionIncludingWindow,
    kCGWindowImageDefault,
    kCGWindowImageBoundsIgnoreFraming,
)
import AppKit


def get_resolve_window_id() -> int | None:
    """Find DaVinci Resolve's main window ID via CGWindowListCopyWindowInfo."""
    window_list = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly, kCGNullWindowID
    )
    if not window_list:
        return None

    best = None
    best_area = 0

    for window in window_list:
        owner = window.get("kCGWindowOwnerName", "")
        if "DaVinci Resolve" not in owner:
            continue
        bounds = window.get("kCGWindowBounds")
        if not bounds:
            continue
        w = bounds.get("Width", 0)
        h = bounds.get("Height", 0)
        area = w * h
        # Pick the largest Resolve window (main window, not floating panels)
        if area > best_area:
            best_area = area
            best = window.get("kCGWindowNumber")

    return best


def get_display_scale_factor() -> float:
    """Get the backing scale factor of the main display (2.0 on Retina)."""
    screen = AppKit.NSScreen.mainScreen()
    if screen is None:
        return 2.0
    return screen.backingScaleFactor()


def _cgimage_to_pil(cg_image) -> Image.Image:
    """Convert a CGImage to a PIL Image."""
    from Quartz import (
        CGImageGetWidth,
        CGImageGetHeight,
        CGImageGetBytesPerRow,
        CGImageGetDataProvider,
        CGDataProviderCopyData,
    )

    width = CGImageGetWidth(cg_image)
    height = CGImageGetHeight(cg_image)
    bytes_per_row = CGImageGetBytesPerRow(cg_image)
    provider = CGImageGetDataProvider(cg_image)
    data = CGDataProviderCopyData(provider)

    img = Image.frombytes("RGBA", (width, height), bytes(data), "raw", "BGRA", bytes_per_row)
    return img.convert("RGB")


def capture_window(window_id: int) -> Image.Image:
    """Capture a window by ID, returning a PIL Image in physical pixels."""
    cg_image = CGWindowListCreateImage(
        CGRectNull,
        kCGWindowListOptionIncludingWindow,
        window_id,
        kCGWindowImageDefault | kCGWindowImageBoundsIgnoreFraming,
    )
    if cg_image is None:
        raise RuntimeError(
            "Failed to capture window. Check Screen Recording permission."
        )
    return _cgimage_to_pil(cg_image)


def capture_region(window_id: int, rect_points: tuple[float, float, float, float]) -> Image.Image:
    """Capture a cropped region of a window.

    rect_points: (x, y, width, height) in macOS point coordinates.
    """
    x, y, w, h = rect_points
    cg_image = CGWindowListCreateImage(
        CGRectMake(x, y, w, h),
        kCGWindowListOptionIncludingWindow,
        window_id,
        kCGWindowImageDefault | kCGWindowImageBoundsIgnoreFraming,
    )
    if cg_image is None:
        raise RuntimeError("Failed to capture window region.")
    return _cgimage_to_pil(cg_image)


def pixels_to_points(px: int, py: int, scale: float) -> tuple[float, float]:
    """Convert physical pixel coordinates to macOS point coordinates."""
    return px / scale, py / scale
