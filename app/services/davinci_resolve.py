"""Service layer for DaVinci Resolve scripting API integration."""
from __future__ import annotations

import os
import sys
from pathlib import Path

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


def list_projects() -> list[str]:
    """Return a list of project names in the current database folder."""
    resolve = _get_resolve()
    pm = resolve.GetProjectManager()
    return pm.GetProjectListInCurrentFolder() or []


def list_timelines(project_name: str) -> list[str]:
    """Load a project and return its timeline names.

    Restores the previously active project afterward.
    """
    resolve = _get_resolve()
    pm = resolve.GetProjectManager()
    prev_project = pm.GetCurrentProject()
    prev_name = prev_project.GetName() if prev_project else None

    project = pm.LoadProject(project_name)
    if project is None:
        raise ValueError(f"Could not load project '{project_name}'.")

    names = []
    count = project.GetTimelineCount()
    for i in range(1, count + 1):
        tl = project.GetTimelineByIndex(i)
        if tl:
            names.append(tl.GetName())

    # Restore previous project
    if prev_name and prev_name != project_name:
        pm.LoadProject(prev_name)

    return names


def append_to_timeline(
    project_name: str,
    timeline_name: str,
    clips: list[dict],
) -> int:
    """Append highlight clips to an existing timeline in a Resolve project.

    Each clip dict must have: video_id, start, end, and a local_path.
    If timeline_name doesn't exist, a new timeline is created.
    Source media is imported into the media pool if not already present.

    Returns the number of clips appended.
    """
    from app import video_map

    resolve = _get_resolve()
    pm = resolve.GetProjectManager()
    project = pm.LoadProject(project_name)
    if project is None:
        raise ValueError(f"Could not load project '{project_name}'.")

    media_pool = project.GetMediaPool()

    # Find or create the timeline
    timeline = None
    count = project.GetTimelineCount()
    for i in range(1, count + 1):
        tl = project.GetTimelineByIndex(i)
        if tl and tl.GetName() == timeline_name:
            timeline = tl
            break
    if timeline is None:
        timeline = media_pool.CreateEmptyTimeline(timeline_name)
        if timeline is None:
            raise RuntimeError(f"Could not create timeline '{timeline_name}'.")

    project.SetCurrentTimeline(timeline)

    # Get timeline frame rate for time-to-frame conversion
    fps_raw = project.GetSetting("timelineFrameRate") or 25
    # May be float or string like "29.97 DF"
    if isinstance(fps_raw, str):
        fps = float(fps_raw.replace("DF", "").strip())
    else:
        fps = float(fps_raw)

    # Collect unique local paths and import into media pool
    path_set: dict[str, str] = {}  # local_path -> video_id
    for clip in clips:
        vid = clip.get("video_id", "")
        local_path = video_map.get_path(vid)
        if local_path and Path(local_path).exists():
            path_set[local_path] = vid

    if not path_set:
        raise RuntimeError("No local media files found for the selected clips.")

    # Check which files are already in the media pool
    existing_names: dict[str, object] = {}  # filename -> MediaPoolItem
    root_folder = media_pool.GetRootFolder()
    _collect_pool_items(root_folder, existing_names)

    # Import files not yet in pool
    to_import = []
    for local_path in path_set:
        fname = Path(local_path).name
        if fname not in existing_names:
            to_import.append(local_path)

    if to_import:
        imported = media_pool.ImportMedia(to_import)
        if imported:
            for mpi in imported:
                existing_names[mpi.GetName()] = mpi

    # Build clip info list and append to timeline
    appended = 0
    for clip in clips:
        vid = clip.get("video_id", "")
        local_path = video_map.get_path(vid)
        if not local_path:
            continue
        fname = Path(local_path).name
        mpi = existing_names.get(fname)
        if not mpi:
            continue

        start_sec = clip.get("start", 0.0)
        end_sec = clip.get("end", 0.0)
        start_frame = int(start_sec * fps)
        end_frame = int(end_sec * fps)

        result = media_pool.AppendToTimeline([{
            "mediaPoolItem": mpi,
            "startFrame": start_frame,
            "endFrame": end_frame,
        }])
        if result:
            appended += len(result)

    return appended


def _collect_pool_items(folder, result: dict):
    """Recursively collect all MediaPoolItems in a folder tree."""
    for clip in (folder.GetClipList() or []):
        name = clip.GetName()
        if name:
            result[name] = clip
    for sub in (folder.GetSubFolderList() or []):
        _collect_pool_items(sub, result)
