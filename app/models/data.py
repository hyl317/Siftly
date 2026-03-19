from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LocalVideo:
    path: Path
    filename: str
    size_bytes: int
    width: int = 0
    height: int = 0
    duration: float = 0.0
    needs_transcode: bool = False
    needs_split: bool = False
    thumbnail_path: Path | None = None


@dataclass
class IndexedVideo:
    video_id: str
    name: str
    duration: float = 0.0
    created_at: str = ""
    thumbnail_path: Path | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class SearchResult:
    video_id: str
    video_name: str
    score: float
    start: float
    end: float
    thumbnail_url: str = ""
    metadata: dict = field(default_factory=dict)
