"""Tests for storyline_worker pure-logic functions."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.storyline_worker import (
    _build_ordering_prompt,
    _extract_frames_1fps,
    _parse_ordering_response,
)


# ── _build_ordering_prompt ──────────────────────────────────────


class TestBuildOrderingPrompt:
    def test_basic_prompt(self):
        clips = [
            {"title": "Sunset", "category": "scenery", "start": 0, "end": 10},
            {"title": "Dance", "category": "action", "start": 5, "end": 15},
        ]
        descriptions = {0: "A sunset over mountains", 1: "People dancing"}
        prompt = _build_ordering_prompt(clips, descriptions)

        assert "Clip 0" in prompt
        assert "Clip 1" in prompt
        assert "Sunset" in prompt
        assert "Dance" in prompt
        assert "scenery" in prompt
        assert "A sunset over mountains" in prompt
        assert "People dancing" in prompt
        assert "JSON" in prompt

    def test_missing_title_uses_fallback(self):
        clips = [{"start": 0, "end": 5}]
        descriptions = {0: "desc"}
        prompt = _build_ordering_prompt(clips, descriptions)
        assert "Clip 0" in prompt

    def test_clip_name_used_for_timeline_clips(self):
        clips = [{"clip_name": "MyClip.mov", "start": 0, "end": 10}]
        descriptions = {0: "desc"}
        prompt = _build_ordering_prompt(clips, descriptions)
        assert "MyClip.mov" in prompt

    def test_duration_from_frames(self):
        clips = [{"start": 0, "end": 0, "duration_frames": 250, "fps": 25}]
        descriptions = {0: "desc"}
        prompt = _build_ordering_prompt(clips, descriptions)
        assert "10.0s" in prompt

    def test_missing_description(self):
        clips = [{"title": "X", "start": 0, "end": 5}]
        descriptions = {}
        prompt = _build_ordering_prompt(clips, descriptions)
        assert "(no description)" in prompt

    def test_shot_time_included(self):
        clips = [{"title": "X", "start": 0, "end": 5,
                  "shot_time": "2024-06-15 14:32:01"}]
        descriptions = {0: "desc"}
        prompt = _build_ordering_prompt(clips, descriptions)
        assert "2024-06-15 14:32:01" in prompt
        assert "Shot time:" in prompt

    def test_shot_time_omitted_when_empty(self):
        clips = [{"title": "X", "start": 0, "end": 5, "shot_time": ""}]
        descriptions = {0: "desc"}
        prompt = _build_ordering_prompt(clips, descriptions)
        assert "Shot time:" not in prompt


# ── _parse_ordering_response ────────────────────────────────────


def _make_response(text: str):
    """Create a mock Claude response."""
    block = SimpleNamespace(text=text)
    return SimpleNamespace(content=[block])


class TestParseOrderingResponse:
    def test_valid_response(self):
        resp = _make_response('{"order": [2, 0, 1], "rationale": "test"}')
        result = _parse_ordering_response(resp, 3)
        assert result == [2, 0, 1]

    def test_valid_with_code_block(self):
        resp = _make_response(
            '```json\n{"order": [1, 0], "rationale": "test"}\n```'
        )
        result = _parse_ordering_response(resp, 2)
        assert result == [1, 0]

    def test_invalid_json_falls_back(self):
        resp = _make_response("not json at all")
        result = _parse_ordering_response(resp, 3)
        assert result == [0, 1, 2]

    def test_missing_indices_falls_back(self):
        resp = _make_response('{"order": [0, 1]}')  # missing index 2
        result = _parse_ordering_response(resp, 3)
        assert result == [0, 1, 2]

    def test_duplicate_indices_falls_back(self):
        resp = _make_response('{"order": [0, 0, 1]}')
        result = _parse_ordering_response(resp, 3)
        assert result == [0, 1, 2]

    def test_empty_content_falls_back(self):
        resp = SimpleNamespace(content=[])
        result = _parse_ordering_response(resp, 2)
        assert result == [0, 1]

    def test_missing_order_key_falls_back(self):
        resp = _make_response('{"rationale": "no order key"}')
        result = _parse_ordering_response(resp, 2)
        assert result == [0, 1]

    def test_single_clip(self):
        resp = _make_response('{"order": [0], "rationale": "only one"}')
        result = _parse_ordering_response(resp, 1)
        assert result == [0]


# ── _extract_frames_1fps ────────────────────────────────────────


class TestExtractFrames:
    def test_nonexistent_file_returns_empty(self, tmp_path):
        result = _extract_frames_1fps(
            str(tmp_path / "nonexistent.mp4"), 0, 5
        )
        assert result == []
