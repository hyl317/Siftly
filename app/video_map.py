"""Persistent mapping of video_id -> {path, index_id}.

Stored as a JSON file in the project root so the gallery can find
local files for thumbnails and playback.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading

from app.config import PROJECT_ROOT, get_index_id

_MAP_PATH = PROJECT_ROOT / ".video_paths.json"
_lock = threading.Lock()


def _load() -> dict[str, dict]:
    if _MAP_PATH.exists():
        try:
            return json.loads(_MAP_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(data: dict):
    text = json.dumps(data, indent=2)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=_MAP_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            f.write(text)
        os.replace(tmp_path, _MAP_PATH)
    except Exception:
        os.unlink(tmp_path)
        raise


def set_path(video_id: str, local_path: str):
    with _lock:
        data = _load()
        data[video_id] = {"path": local_path, "index_id": get_index_id()}
        _save(data)


def get_path(video_id: str) -> str | None:
    entry = _load().get(video_id)
    if entry is None:
        return None
    return entry["path"]


def get_all() -> dict[str, str]:
    """Return {video_id: local_path} for all entries."""
    return {vid: entry["path"] for vid, entry in _load().items()}


def find_by_path(local_path: str) -> str | None:
    """Return video_id if this local path was already uploaded to the
    current index, else None."""
    current_index = get_index_id()
    for vid, entry in _load().items():
        if entry["path"] == local_path and entry["index_id"] == current_index:
            return vid
    return None
