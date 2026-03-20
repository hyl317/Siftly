from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

from app.config import PREP_DIR, MAX_FILE_SIZE_BYTES, MAX_RESOLUTION_HEIGHT
from app.utils.thumbnails import probe_video


MIN_DURATION = 4.0       # seconds
MAX_DURATION = 3600.0    # 1 hour
MIN_HEIGHT = 360
MAX_HEIGHT = 2160        # 4K
MAX_ASPECT_RATIO = 2.4    # longer/shorter must be <= 2.4

LUT_DIR = Path(__file__).resolve().parent.parent / "luts"
CUSTOM_PROFILES_PATH = LUT_DIR / "custom_profiles.json"

# Built-in profile name -> .cube filename (in LUT_DIR)
BUILTIN_PROFILES = {
    "S-Log3":  "slog3_to_rec709.cube",
    "C-Log2":  "clog2_to_rec709.cube",
    "C-Log3":  "clog3_to_rec709.cube",
    "D-Log":   "dlog_to_rec709.cube",
    "D-Log M": "dlogm_to_rec709.cube",
    "N-Log":   "nlog_to_rec709.cube",
    "V-Log":   "vlog_to_rec709.cube",
    "F-Log":   "flog_to_rec709.cube",
    "F-Log2":  "flog2_to_rec709.cube",
    "LogC3":   "logc3_to_rec709.cube",
    "LogC4":   "logc4_to_rec709.cube",
}


def _load_custom_profiles() -> dict[str, str]:
    """Load user-defined custom profiles from JSON. Returns {name: filename}."""
    if not CUSTOM_PROFILES_PATH.is_file():
        return {}
    try:
        return json.loads(CUSTOM_PROFILES_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_custom_profiles(profiles: dict[str, str]):
    CUSTOM_PROFILES_PATH.write_text(json.dumps(profiles, indent=2))


def get_all_profiles() -> dict[str, str]:
    """Return merged dict of built-in + custom profiles. {name: filename}."""
    merged = dict(BUILTIN_PROFILES)
    merged.update(_load_custom_profiles())
    return merged


def install_lut(source_path: Path, profile_name: str) -> Path:
    """Copy a .cube file into LUT_DIR with the correct filename for a profile.

    For built-in profiles, uses the expected filename.
    For custom profiles, generates a filename and saves the association.

    Returns the installed path.
    """
    import shutil

    if profile_name in BUILTIN_PROFILES:
        dest = LUT_DIR / BUILTIN_PROFILES[profile_name]
    else:
        # Custom profile — sanitize name for filename
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in profile_name)
        safe_name = safe_name.strip().replace(" ", "_").lower()
        filename = f"custom_{safe_name}.cube"
        dest = LUT_DIR / filename

        # Persist the custom profile association
        custom = _load_custom_profiles()
        custom[profile_name] = filename
        _save_custom_profiles(custom)

    shutil.copy2(source_path, dest)
    return dest


# Keep LOG_PROFILES as the combined view for backward compat
LOG_PROFILES = get_all_profiles()

# Camera make (lowercased) -> default LOG profile when 10-bit is detected
CAMERA_LOG_MAP = {
    "sony":      "S-Log3",
    "canon":     "C-Log3",
    "dji":       "D-Log M",
    "nikon":     "N-Log",
    "panasonic": "V-Log",
    "fujifilm":  "F-Log2",
    "arri":      "LogC4",
}

# Container format brands that identify the manufacturer
# (major_brand / compatible_brands from ffprobe format tags)
BRAND_MAKE_MAP = {
    "xfvc": "canon",    # Canon XF-AVC (R5, R5 II, C70, C300, etc.)
    "caep": "canon",    # Canon EOS Movie
    "xavc": "sony",     # Sony XAVC
    "xavs": "sony",     # Sony XAVC-S
}


class VideoValidationError(ValueError):
    """Raised when a video doesn't meet Twelve Labs requirements."""
    pass


class VideoPrepCancelled(Exception):
    """Raised when preprocessing is cancelled by the user."""
    pass


def _run_ffmpeg(cmd: list[str], cancel_event: threading.Event | None = None) -> str:
    """Run an ffmpeg command, killing it if cancel_event is set.

    Returns stderr output. Raises VideoPrepCancelled or RuntimeError.
    """
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        if cancel_event is None:
            _, stderr = proc.communicate()
        else:
            # Poll so we can check the cancel event
            while proc.poll() is None:
                if cancel_event.is_set():
                    proc.kill()
                    proc.wait()
                    raise VideoPrepCancelled()
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass
            _, stderr = proc.communicate()
    except VideoPrepCancelled:
        raise
    except Exception:
        proc.kill()
        proc.wait()
        raise

    if proc.returncode != 0:
        stderr_text = (stderr.decode(errors="replace") if stderr else "").strip()
        lines = stderr_text.splitlines()
        detail = "\n".join(lines[-5:]) if lines else "Unknown ffmpeg error"
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}):\n{detail}")

    return stderr.decode(errors="replace") if stderr else ""


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


def detect_log_profile(video_path: Path) -> str | None:
    """Detect LOG color profile from video metadata.

    Uses camera make + 10-bit pixel format as heuristic.
    Returns a profile name (key in LOG_PROFILES) or None.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                str(video_path),
            ],
            capture_output=True, text=True, timeout=30, check=True,
        )
        data = json.loads(result.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, ValueError):
        return None

    # Check if video is 10-bit (strong LOG indicator)
    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        {},
    )
    pix_fmt = video_stream.get("pix_fmt", "")
    is_10bit = "10" in pix_fmt  # yuv420p10le, yuv422p10le, etc.

    if not is_10bit:
        return None

    # Gather all available clues for identifying the camera manufacturer
    fmt = data.get("format", {})
    tags = fmt.get("tags", {})
    stream_tags = video_stream.get("tags", {})
    all_tags = {k.lower(): v for k, v in {**tags, **stream_tags}.items()}

    # 1. Check explicit make/manufacturer tags
    make = all_tags.get("make", "") or all_tags.get("manufacturer", "")
    make_lower = make.lower()

    if make_lower:
        for camera_make, profile in CAMERA_LOG_MAP.items():
            if camera_make in make_lower:
                return profile

    # 2. Check container format brand (major_brand / compatible_brands)
    #    Many cameras (Canon R5 II, Sony FX series) leave make empty but
    #    use manufacturer-specific container formats
    brands = (
        tags.get("major_brand", "") + " " +
        tags.get("compatible_brands", "")
    ).lower()
    for brand_prefix, brand_make in BRAND_MAKE_MAP.items():
        if brand_prefix in brands:
            return CAMERA_LOG_MAP[brand_make]

    # 3. Filename heuristic (last resort — many cameras embed make in filename)
    filename_lower = video_path.name.lower()
    for camera_make, profile in CAMERA_LOG_MAP.items():
        if camera_make in filename_lower:
            return profile

    return None


def resolve_lut_path(profile: str, video_path: Path | None = None) -> Path | None:
    """Resolve a color profile selection to a .cube LUT file path.

    Args:
        profile: One of "Auto-detect", "None (Rec.709)", a profile name, or
                 a full path to a custom .cube file.
        video_path: Required when profile is "Auto-detect".

    Returns:
        Path to a .cube file, or None if no LUT should be applied.
    """
    if profile == "None (Rec.709)" or not profile:
        return None

    all_profiles = get_all_profiles()

    if profile == "Auto-detect":
        if video_path is None:
            return None
        detected = detect_log_profile(video_path)
        if detected is None or detected not in all_profiles:
            return None
        lut = LUT_DIR / all_profiles[detected]
        return lut if lut.is_file() else None

    # Named profile
    if profile in all_profiles:
        lut = LUT_DIR / all_profiles[profile]
        return lut if lut.is_file() else None

    # Custom LUT path
    custom = Path(profile)
    if custom.is_file() and custom.suffix.lower() == ".cube":
        return custom

    return None


def transcode_720p(input_path: Path, lut_path: Path | None = None,
                   cancel_event: threading.Event | None = None,
                   progress_callback=None) -> Path:
    """Transcode video to 720p, optionally applying a LUT. Returns path to transcoded file."""
    PREP_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PREP_DIR / f"{input_path.stem}_720p.mp4"

    if output_path.exists():
        output_path.unlink()

    # Build video filter chain
    vf_parts = []
    if lut_path:
        # Escape backslashes and colons in path for ffmpeg filter syntax
        lut_str = str(lut_path).replace("\\", "/").replace(":", "\\:")
        vf_parts.append(f"lut3d='{lut_str}'")
    vf_parts.append("scale=-2:720")
    vf_string = ",".join(vf_parts)

    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-vf", vf_string,
        "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path),
    ]
    _run_ffmpeg(cmd, cancel_event)

    if not output_path.exists():
        raise FileNotFoundError(
            f"Transcode produced no output. ffmpeg may not support this file format.\n"
            f"Input: {input_path.name}"
        )

    return output_path


def split_video(input_path: Path, cancel_event: threading.Event | None = None,
                progress_callback=None) -> list[Path]:
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
    _run_ffmpeg(cmd, cancel_event)

    chunks = sorted(PREP_DIR.glob(f"{input_path.stem}_part*.mp4"))
    if not chunks:
        raise FileNotFoundError(f"Split produced no output chunks for: {input_path.name}")

    return chunks


def prepare_video(input_path: Path, lut_path: Path | None = None,
                  cancel_event: threading.Event | None = None,
                  progress_callback=None) -> list[Path]:
    """Full preprocessing pipeline: validate, transcode if needed, split if needed.
    Returns list of files ready for upload. Raises VideoPrepCancelled if cancelled."""
    info = probe_video(input_path)
    validate_video(info, input_path.name)
    current = input_path

    force_transcode = lut_path is not None

    if force_transcode or needs_transcode(info["width"], info["height"]):
        status = "Applying LUT + transcoding..." if lut_path else "Transcoding to 720p..."
        if progress_callback:
            progress_callback(status)
        current = transcode_720p(input_path, lut_path=lut_path,
                                 cancel_event=cancel_event,
                                 progress_callback=progress_callback)

    if needs_split(current):
        if progress_callback:
            progress_callback("Splitting large file...")
        return split_video(current, cancel_event=cancel_event,
                           progress_callback=progress_callback)

    return [current]


def cleanup_prep():
    """Remove all files in the prep directory."""
    if PREP_DIR.exists():
        import shutil
        shutil.rmtree(PREP_DIR, ignore_errors=True)
