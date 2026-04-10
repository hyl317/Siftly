"""AI-powered clip ordering for cohesive storyline assembly.

Two-stage pipeline:
  Stage 1 — Describe each clip (Twelve Labs analyze or Claude vision)
  Stage 2 — Claude determines narrative order from descriptions
"""
from __future__ import annotations

import base64
import json
import logging
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)

# Maximum frames to extract per clip for vision-based description
MAX_FRAMES_PER_CLIP = 20


def _extract_frames_1fps(file_path: str, start_sec: float,
                         duration_sec: float) -> list[bytes]:
    """Extract one JPEG frame per second from a video clip.

    Returns a list of JPEG byte strings (up to MAX_FRAMES_PER_CLIP).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        pattern = str(Path(tmpdir) / "frame_%04d.jpg")
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(max(start_sec, 0)),
            "-t", str(min(duration_sec, MAX_FRAMES_PER_CLIP)),
            "-i", file_path,
            "-vf", "fps=1,scale=512:-2",
            "-q:v", "5",
            pattern,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60, check=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError):
            return []

        frames = []
        for p in sorted(Path(tmpdir).glob("frame_*.jpg")):
            frames.append(p.read_bytes())
            if len(frames) >= MAX_FRAMES_PER_CLIP:
                break
        return frames


def _build_ordering_prompt(clips: list[dict],
                           descriptions: dict[int, str]) -> str:
    """Build the prompt that asks Claude to arrange clips into a storyline."""
    clip_lines = []
    for i, clip in enumerate(clips):
        title = clip.get("title", "") or clip.get("clip_name", "") or f"Clip {i}"
        category = clip.get("category", "")
        desc = descriptions.get(i, "(no description)")
        duration = clip.get("end", 0) - clip.get("start", 0)
        if duration <= 0:
            duration = clip.get("duration_frames", 0) / clip.get("fps", 25)

        parts = [f"Clip {i}: \"{title}\""]
        if category:
            parts.append(f"  Category: {category}")
        parts.append(f"  Duration: {duration:.1f}s")
        parts.append(f"  Content: {desc}")
        clip_lines.append("\n".join(parts))

    clips_text = "\n\n".join(clip_lines)

    return f"""You are an experienced video editor. Given the following clips, arrange them into a cohesive storyline with good narrative flow and pacing.

Consider:
- Start with an establishing shot or scene-setter if available
- Group related content together
- Build tension or interest progressively
- End with a strong closing moment or resolution
- Maintain visual and thematic continuity between adjacent clips

{clips_text}

Return your answer as JSON with this exact format:
{{"order": [list of clip numbers in the order they should appear], "rationale": "brief explanation of your ordering logic"}}

Return ONLY the JSON object, no other text."""


def _parse_ordering_response(response, num_clips: int) -> list[int]:
    """Parse Claude's response into an ordered list of clip indices.

    Falls back to original order if parsing fails or response is invalid.
    """
    try:
        text = response.content[0].text.strip()
        # Handle markdown code blocks
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(text)
        order = data["order"]

        # Validate: must be a permutation of [0, num_clips)
        if sorted(order) != list(range(num_clips)):
            logger.warning("AI returned invalid ordering %s, falling back", order)
            return list(range(num_clips))

        rationale = data.get("rationale", "")
        if rationale:
            logger.info("AI storyline rationale: %s", rationale)

        return order
    except (json.JSONDecodeError, KeyError, TypeError, IndexError) as e:
        logger.warning("Failed to parse AI ordering response: %s", e)
        return list(range(num_clips))


class StorylineWorker(QThread):
    """AI-powered clip ordering worker.

    Accepts either highlights (Entry Point A, uses Twelve Labs analyze)
    or timeline_clips (Entry Point B, uses Claude vision on thumbnails).
    """
    progress = Signal(str)
    finished = Signal(list)  # reordered clip list
    error = Signal(str)

    def __init__(self, highlights: list[dict] | None = None,
                 timeline_clips: list[dict] | None = None, parent=None):
        super().__init__(parent)
        self._highlights = highlights
        self._timeline_clips = timeline_clips

    def run(self):
        try:
            if self._highlights:
                self._run_highlights()
            elif self._timeline_clips:
                self._run_timeline()
            else:
                self.error.emit("No clips provided")
        except Exception as e:
            logger.exception("Storyline worker failed")
            self.error.emit(str(e))

    # ── Entry Point A: Highlights (Twelve Labs analyze) ──────────

    def _run_highlights(self):
        from app.services.api_client import get_client

        clips = self._highlights
        if len(clips) <= 1:
            self.finished.emit(clips)
            return

        client = get_client()
        descriptions: dict[int, str] = {}

        for i, clip in enumerate(clips):
            self.progress.emit(f"Analyzing clip {i + 1}/{len(clips)}...")
            try:
                start = clip.get("start", 0.0)
                end = clip.get("end", 0.0)
                response = client.analyze(
                    video_id=clip["video_id"],
                    prompt=(
                        f"Describe what happens between {start:.1f}s and "
                        f"{end:.1f}s in 1-2 sentences. Focus on the visual "
                        f"content, action, mood, and setting."
                    ),
                )
                descriptions[i] = response.data or ""
            except Exception as e:
                logger.warning("Failed to analyze clip %d: %s", i, e)
                title = clip.get("title", "")
                descriptions[i] = title or "(could not analyze)"

        self._order_with_claude(clips, descriptions)

    # ── Entry Point B: Timeline clips (Claude vision) ────────────

    def _run_timeline(self):
        clips = self._timeline_clips
        if len(clips) <= 1:
            self.finished.emit(clips)
            return

        from anthropic import Anthropic
        vision_client = Anthropic()
        descriptions: dict[int, str] = {}

        for i, clip in enumerate(clips):
            self.progress.emit(f"Analyzing clip {i + 1}/{len(clips)}...")
            try:
                desc = self._describe_clip_with_vision(vision_client, clip)
                descriptions[i] = desc
            except Exception as e:
                logger.warning("Failed to describe clip %d: %s", i, e)
                descriptions[i] = clip.get("clip_name", "(unknown)")

        self._order_with_claude(clips, descriptions)

    def _describe_clip_with_vision(self, client, clip: dict) -> str:
        """Extract 1fps thumbnails from a clip and ask Claude to describe it."""
        file_path = clip.get("file_path", "")
        fps = clip.get("fps", 25)
        left_offset = clip.get("left_offset", 0)
        duration_frames = clip.get("duration_frames", 0)

        start_sec = left_offset / fps
        duration_sec = duration_frames / fps

        frames = _extract_frames_1fps(file_path, start_sec, duration_sec)
        if not frames:
            return clip.get("clip_name", "(no frames extracted)")

        content = []
        for frame_data in frames:
            b64 = base64.b64encode(frame_data).decode("ascii")
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": b64,
                },
            })
        content.append({
            "type": "text",
            "text": (
                f"These are frames extracted at 1 frame per second from a "
                f"{duration_sec:.1f}s video clip. Describe what happens in "
                f"this clip in 1-2 sentences. Focus on the visual content, "
                f"action, mood, and setting."
            ),
        })

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text

    # ── Shared: Claude ordering ──────────────────────────────────

    def _order_with_claude(self, clips: list[dict],
                           descriptions: dict[int, str]):
        """Stage 2: Ask Claude to arrange clips into a storyline."""
        self.progress.emit("Planning storyline...")

        from anthropic import Anthropic
        client = Anthropic()

        prompt = _build_ordering_prompt(clips, descriptions)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        ordered_indices = _parse_ordering_response(response, len(clips))
        reordered = [clips[i] for i in ordered_indices]
        self.finished.emit(reordered)
