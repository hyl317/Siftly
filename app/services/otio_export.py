from __future__ import annotations

import subprocess
from pathlib import Path

import opentimelineio as otio

from app import video_map


def _probe_video(file_path: str) -> dict:
    """Get video fps, duration, and start timecode via ffprobe."""
    info = {"fps": 24.0, "duration": 0.0, "start_tc_sec": 0.0}
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate,duration",
             "-show_entries", "format_tags=timecode",
             "-print_format", "json", file_path],
            capture_output=True, text=True, timeout=10,
        )
        import json
        data = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0]
        # FPS
        r_frame_rate = stream.get("r_frame_rate", "24/1")
        num, den = r_frame_rate.split("/")
        info["fps"] = round(int(num) / int(den), 3)
        # Duration
        info["duration"] = float(stream.get("duration", 0))
        # Start timecode (e.g. "23:25:41:16")
        tc = (data.get("format", {}).get("tags", {}).get("timecode", "")
              or stream.get("tags", {}).get("timecode", ""))
        if tc:
            info["start_tc_sec"] = _tc_to_seconds(tc, info["fps"])
    except Exception:
        pass
    return info


def _tc_to_seconds(tc: str, fps: float) -> float:
    """Convert timecode string 'HH:MM:SS:FF' to seconds."""
    parts = tc.replace(";", ":").split(":")
    if len(parts) != 4:
        return 0.0
    h, m, s, f = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    return h * 3600 + m * 60 + s + f / fps


def export_otio(highlights: list[dict], output_path: str) -> tuple[int, int]:
    """Export highlights as an OTIO timeline file for DaVinci Resolve.

    Returns (exported_count, skipped_count).
    """
    timeline = otio.schema.Timeline(name="Highlights")
    video_track = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    audio_track = otio.schema.Track(name="A1", kind=otio.schema.TrackKind.Audio)
    timeline.tracks.append(video_track)
    timeline.tracks.append(audio_track)

    # Cache probe info per video file to avoid repeated ffprobe calls
    probe_cache: dict[str, dict] = {}
    skipped = 0

    for h in sorted(highlights, key=lambda x: x.get("score", 0), reverse=True):
        video_id = h.get("video_id", "")
        local_path = video_map.get_path(video_id)
        if not local_path:
            skipped += 1
            continue

        start_sec = h.get("start", 0.0)
        end_sec = h.get("end", 0.0)
        duration_sec = end_sec - start_sec
        if duration_sec <= 0:
            skipped += 1
            continue

        if local_path not in probe_cache:
            probe_cache[local_path] = _probe_video(local_path)
        info = probe_cache[local_path]
        fps = info["fps"]
        file_duration = info["duration"]
        start_tc_sec = info["start_tc_sec"]

        filename = Path(local_path).name
        available_range = None
        if file_duration > 0:
            available_range = otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(start_tc_sec * fps, fps),
                duration=otio.opentime.RationalTime(file_duration * fps, fps),
            )

        media_ref = otio.schema.ExternalReference(
            target_url=local_path,
            available_range=available_range,
        )
        media_ref.name = filename
        # source_range uses timecode-based start (file's start TC + clip offset)
        source_range = otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime((start_tc_sec + start_sec) * fps, fps),
            duration=otio.opentime.RationalTime(duration_sec * fps, fps),
        )
        video_clip = otio.schema.Clip(
            name=filename,
            media_reference=media_ref,
            source_range=source_range,
        )
        video_track.append(video_clip)

        # Add matching audio clip referencing the same source
        audio_ref = otio.schema.ExternalReference(
            target_url=local_path,
            available_range=available_range,
        )
        audio_ref.name = filename
        audio_clip = otio.schema.Clip(
            name=filename,
            media_reference=audio_ref,
            source_range=source_range,
        )
        audio_track.append(audio_clip)

    exported = len(video_track)
    otio.adapters.write_to_file(timeline, output_path)
    return exported, skipped
