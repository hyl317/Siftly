from __future__ import annotations

from app.services.embedding_cache import (
    get_cached_segments,
    get_cache_size,
    save_segments,
)


class TestEmbeddingCacheRoundTrip:
    def test_save_then_load(self, tmp_cache_dir):
        segments = [(0.0, 5.0, [0.1, 0.2, 0.3]), (5.0, 10.0, [0.4, 0.5, 0.6])]
        save_segments("idx1", "vid1", segments)
        result = get_cached_segments("idx1", "vid1")
        assert result is not None
        assert len(result) == 2
        assert result[0] == (0.0, 5.0, [0.1, 0.2, 0.3])
        assert result[1] == (5.0, 10.0, [0.4, 0.5, 0.6])

    def test_missing_file_returns_none(self, tmp_cache_dir):
        assert get_cached_segments("idx1", "nonexistent") is None

    def test_corrupt_json_returns_none_and_removes_file(self, tmp_cache_dir):
        cache_dir = tmp_cache_dir / "idx1"
        cache_dir.mkdir(parents=True)
        bad_file = cache_dir / "vid1.json"
        bad_file.write_text("{invalid json")
        assert get_cached_segments("idx1", "vid1") is None
        assert not bad_file.exists()

    def test_cache_size_empty(self, tmp_cache_dir):
        assert get_cache_size("idx1") == 0

    def test_cache_size_after_save(self, tmp_cache_dir):
        save_segments("idx1", "vid1", [(0.0, 5.0, [0.1])])
        assert get_cache_size("idx1") > 0
