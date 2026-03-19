from pathlib import Path
from app.config import VIDEO_EXTENSIONS


def scan_folder(folder: Path) -> list[Path]:
    """Return sorted list of video files in folder (non-recursive)."""
    if not folder.is_dir():
        return []
    return sorted(
        p for p in folder.iterdir()
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTENSIONS
        and not p.name.startswith("._")
    )
