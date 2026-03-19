import subprocess
from pathlib import Path


def extract_thumbnail(video_path: Path, output_path: Path, time_sec: float = 1.0) -> bool:
    """Extract a single frame from video as a JPEG thumbnail."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-ss", str(time_sec),
                "-i", str(video_path),
                "-frames:v", "1",
                "-q:v", "3",
                str(output_path),
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
        return output_path.exists()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def probe_video(video_path: Path) -> dict:
    """Get video metadata via ffprobe. Returns dict with width, height, duration."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        import json
        data = json.loads(result.stdout)
        video_stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
            {},
        )
        return {
            "width": int(video_stream.get("width", 0)),
            "height": int(video_stream.get("height", 0)),
            "duration": float(data.get("format", {}).get("duration", 0)),
        }
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, ValueError, StopIteration):
        return {"width": 0, "height": 0, "duration": 0}
