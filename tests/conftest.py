from __future__ import annotations

import pytest


@pytest.fixture
def tmp_map_path(tmp_path, monkeypatch):
    """Redirect video_map._MAP_PATH to a temp file."""
    path = tmp_path / ".video_paths.json"
    monkeypatch.setattr("app.video_map._MAP_PATH", path)
    monkeypatch.setattr("app.video_map.get_index_id", lambda: "test_index")
    return path


@pytest.fixture
def tmp_cache_dir(tmp_path, monkeypatch):
    """Redirect embedding cache to a temp directory."""
    cache_dir = tmp_path / ".embeddings_cache"
    monkeypatch.setattr("app.services.embedding_cache.EMBEDDINGS_CACHE_DIR", cache_dir)
    return cache_dir
