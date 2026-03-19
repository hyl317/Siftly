"""Service layer for DaVinci Resolve scripting API integration."""
from __future__ import annotations

import os
import sys

# Our internal label → actual Resolve project setting key
_FOLDER_SETTING_KEYS = {
    "projectMediaLocation": "projectMediaLocation",
    "cacheFilesLocation": "perfCacheClipsLocation",
    "galleryStillsLocation": "colorGalleryStillsLocation",
}


def _get_resolve():
    """Connect to a running DaVinci Resolve instance.

    Sets environment variables and imports the Resolve scripting module
    from Resolve's install path (not pip).

    Returns the Resolve scripting object.
    Raises ImportError if the module cannot be found.
    Raises ConnectionError if Resolve is not running.
    """
    resolve_script_dir = (
        "/Library/Application Support/Blackmagic Design"
        "/DaVinci Resolve/Developer/Scripting"
    )
    modules_dir = os.path.join(resolve_script_dir, "Modules")

    os.environ.setdefault("RESOLVE_SCRIPT_API", resolve_script_dir)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", (
        "/Applications/DaVinci Resolve/DaVinci Resolve.app"
        "/Contents/Libraries/Fusion/fusionscript.so"
    ))

    if modules_dir not in sys.path:
        sys.path.insert(0, modules_dir)

    try:
        import DaVinciResolveScript as dvr  # type: ignore[import-not-found]
    except ImportError:
        raise ImportError(
            "DaVinci Resolve scripting module not found. "
            "Ensure DaVinci Resolve (Studio) is installed."
        )

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise ConnectionError(
            "Cannot connect to DaVinci Resolve. "
            "Ensure Resolve is running (with or without -nogui)."
        )
    return resolve


def get_working_folder_defaults(project) -> dict[str, str]:
    """Read current working folder paths from a Resolve project.

    Returns a dict mapping our internal label to the current path value.
    """
    defaults: dict[str, str] = {}
    for our_key, resolve_key in _FOLDER_SETTING_KEYS.items():
        val = project.GetSetting(resolve_key)
        if val:
            defaults[our_key] = val
    return defaults


def create_project_with_timeline(
    project_name: str,
    otio_path: str,
    timeline_name: str = "Highlights",
    frame_rate: str = "25",
    width: int = 3840,
    height: int = 2160,
    working_folders: dict[str, str] | None = None,
) -> None:
    """Create a DaVinci Resolve project and import an OTIO timeline.

    Raises ValueError if project name already exists.
    Raises RuntimeError if timeline import fails.
    """
    resolve = _get_resolve()

    project_manager = resolve.GetProjectManager()
    project = project_manager.CreateProject(project_name)
    if project is None:
        raise ValueError(
            f"Could not create project '{project_name}'. "
            "A project with that name may already exist."
        )

    project.SetSetting("timelineFrameRate", frame_rate)
    project.SetSetting("timelineResolutionWidth", str(width))
    project.SetSetting("timelineResolutionHeight", str(height))

    if working_folders:
        for our_key, path in working_folders.items():
            resolve_key = _FOLDER_SETTING_KEYS.get(our_key)
            if resolve_key and path:
                project.SetSetting(resolve_key, path)

    media_pool = project.GetMediaPool()
    timeline = media_pool.ImportTimelineFromFile(otio_path, {
        "timelineName": timeline_name,
        "importSourceClips": True,
    })
    if timeline is None:
        raise RuntimeError(
            "Failed to import timeline from OTIO file. "
            "Check that source media paths are accessible."
        )
