from __future__ import annotations

import pytest
from app.services.search_worker import (
    _cosine_similarity,
    _merge_adjacent_clips,
    _score_to_level,
)


# ── _cosine_similarity ───────────────────────────────────────────────

class TestCosineSimilarity:
    def test_identical_vectors(self):
        assert _cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert _cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert _cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self):
        assert _cosine_similarity([0, 0], [1, 1]) == 0.0
        assert _cosine_similarity([1, 1], [0, 0]) == 0.0

    def test_scaled_vectors_are_similar(self):
        assert _cosine_similarity([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)

    def test_high_dimensional(self):
        a = [1.0] * 100
        b = [1.0] * 100
        assert _cosine_similarity(a, b) == pytest.approx(1.0)


# ── _score_to_level ──────────────────────────────────────────────────

class TestScoreToLevel:
    @pytest.mark.parametrize("score,expected", [
        (100, "high"),
        (70, "high"),
        (69.9, "medium"),
        (40, "medium"),
        (39.9, "low"),
        (0, "low"),
    ])
    def test_boundaries(self, score, expected):
        assert _score_to_level(score) == expected


# ── _merge_adjacent_clips ────────────────────────────────────────────

def _clip(video_id, start, end, score):
    return {"video_id": video_id, "start": start, "end": end, "score": score}


class TestMergeAdjacentClips:
    def test_empty_list(self):
        assert _merge_adjacent_clips([]) == []

    def test_single_clip_unchanged(self):
        clips = [_clip("v1", 0, 5, 80)]
        result = _merge_adjacent_clips(clips)
        assert len(result) == 1
        assert result[0]["start"] == 0
        assert result[0]["end"] == 5

    def test_adjacent_same_level_merged(self):
        clips = [
            _clip("v1", 0, 5, 80),
            _clip("v1", 5.5, 10, 90),  # gap=0.5 < tolerance=1.0, both "high"
        ]
        result = _merge_adjacent_clips(clips)
        assert len(result) == 1
        assert result[0]["start"] == 0
        assert result[0]["end"] == 10

    def test_gap_exceeds_tolerance_not_merged(self):
        clips = [
            _clip("v1", 0, 5, 80),
            _clip("v1", 7, 10, 90),  # gap=2 > tolerance=1.0
        ]
        result = _merge_adjacent_clips(clips)
        assert len(result) == 2

    def test_different_level_not_merged(self):
        clips = [
            _clip("v1", 0, 5, 80),   # high
            _clip("v1", 5.5, 10, 30),  # low — different level
        ]
        result = _merge_adjacent_clips(clips)
        assert len(result) == 2

    def test_different_video_not_merged(self):
        clips = [
            _clip("v1", 0, 5, 80),
            _clip("v2", 5.5, 10, 85),
        ]
        result = _merge_adjacent_clips(clips)
        assert len(result) == 2

    def test_merged_score_is_weighted_average(self):
        # 5s at 80, 5s at 90 → weighted avg = (80*5 + 90*5) / 10 = 85
        clips = [
            _clip("v1", 0, 5, 80),
            _clip("v1", 5, 10, 90),
        ]
        result = _merge_adjacent_clips(clips)
        assert len(result) == 1
        assert result[0]["score"] == pytest.approx(85.0, abs=0.1)

    def test_result_sorted_by_score_descending(self):
        clips = [
            _clip("v1", 0, 5, 30),   # low
            _clip("v2", 0, 5, 90),   # high
            _clip("v3", 0, 5, 50),   # medium
        ]
        result = _merge_adjacent_clips(clips)
        scores = [c["score"] for c in result]
        assert scores == sorted(scores, reverse=True)
