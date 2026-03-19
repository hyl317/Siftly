import subprocess
from pathlib import Path

from app.config import PREP_DIR, MAX_FILE_SIZE_BYTES, MAX_RESOLUTION_HEIGHT
from app.utils.thumbnails import probe_video


MIN_DURATION = 4.0       # seconds
MAX_DURATION = 3600.0    # 1 hour
MIN_HEIGHT = 360
MAX_HEIGHT = 2160        # 4K
MAX_ASPECT_RATIO = 2.4    # longer/shorter must be <= 2.4


class VideoValidationError(ValueError):
    """Raised when a video doesn't meet Twelve Labs requirements."""
    pass


def validate_video(info: dict, filename: str = ""):
    """Check Twelve Labs requirements. Raises VideoValidationError on failure."""
    errors = []
    duration = info.get("duration", 0)
    width = info.get("width", 0)
    height = info.get("height", 0)

    if duration < MIN_DURATION:
        errors.append(f"Too short ({duration:.1f}s) — minimum is {MIN_DURATION}s")
    if duration > MAX_DURATION:
        m = int(duration // 60)
        errors.append(f"Too long ({m}m) — maximum is 60 minutes")

    if height > 0:
        if height < MIN_HEIGHT:
            errors.append(f"Resolution too low ({width}x{height}) — minimum is 360p")
        if height > MAX_HEIGHT:
            errors.append(f"Resolution too high ({width}x{height}) — maximum is 4K")

    if width > 0 and height > 0:
        longer = max(width, height)
        shorter = min(width, height)
        ratio = longer / shorter
        if ratio > MAX_ASPECT_RATIO:
            errors.append(f"Aspect ratio too extreme ({width}x{height}, {ratio:.1f}:1) — max is 2.4:1")

    if errors:
        prefix = f"{filename}: " if filename else ""
        raise VideoValidationError(prefix + "; ".join(errors))


def needs_transcode(width: int, height: int) -> bool:
    return height > MAX_RESOLUTION_HEIGHT and height > 0


def needs_split(file_path: Path) -> bool:
    return file_path.stat().st_size > MAX_FILE_SIZE_BYTES


def transcode_720p(input_path: Path, progress_callback=None) -> Path:
    """Transcode video to 720p. Returns path to transcoded file."""
    PREP_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PREP_DIR / f"{input_path.stem}_720p.mp4"

    if output_path.exists():
        output_path.unlink()

    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-vf", "scale=-2:720",
        "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=None)
    if result.returncode != 0:
        stderr_lines = (result.stderr or "").strip().splitlines()
        detail = "\n".join(stderr_lines[-5:]) if stderr_lines else "Unknown ffmpeg error"
        raise RuntimeError(f"Transcode failed (exit {result.returncode}):\n{detail}")

    if not output_path.exists():
        raise FileNotFoundError(
            f"Transcode produced no output. ffmpeg may not support this file format.\n"
            f"Input: {input_path.name}"
        )

    return output_path


def split_video(input_path: Path, progress_callback=None) -> list[Path]:
    """Split video into chunks under MAX_FILE_SIZE_BYTES. Returns list of chunk paths."""
    PREP_DIR.mkdir(parents=True, exist_ok=True)
    file_size = input_path.stat().st_size
    info = probe_video(input_path)
    duration = info["duration"]

    if duration <= 0:
        return [input_path]

    chunk_duration = int(duration * (MAX_FILE_SIZE_BYTES / file_size))
    chunk_duration = max(chunk_duration, 10)  # at least 10 seconds

    output_pattern = str(PREP_DIR / f"{input_path.stem}_part%03d.mp4")
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-c", "copy",
        "-f", "segment",
        "-segment_time", str(chunk_duration),
        "-reset_timestamps", "1",
        output_pattern,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=None)
    if result.returncode != 0:
        stderr_lines = (result.stderr or "").strip().splitlines()
        detail = "\n".join(stderr_lines[-5:]) if stderr_lines else "Unknown ffmpeg error"
        raise RuntimeError(f"Split failed (exit {result.returncode}):\n{detail}")

    chunks = sorted(PREP_DIR.glob(f"{input_path.stem}_part*.mp4"))
    if not chunks:
        raise FileNotFoundError(f"Split produced no output chunks for: {input_path.name}")

    return chunks


def prepare_video(input_path: Path, progress_callback=None) -> list[Path]:
    """Full preprocessing pipeline: validate, transcode if needed, split if needed.
    Returns list of files ready for upload."""
    info = probe_video(input_path)
    validate_video(info, input_path.name)
    current = input_path

    if needs_transcode(info["width"], info["height"]):
        if progress_callback:
            progress_callback("Transcoding to 720p...")
        current = transcode_720p(input_path, progress_callback)

    if needs_split(current):
        if progress_callback:
            progress_callback("Splitting large file...")
        return split_video(current, progress_callback)

    return [current]


def cleanup_prep():
    """Remove all files in the prep directory."""
    if PREP_DIR.exists():
        import shutil
        shutil.rmtree(PREP_DIR, ignore_errors=True)
