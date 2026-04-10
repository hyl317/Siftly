from __future__ import annotations

import threading

from app import video_map


class TestVideoMapRoundTrip:
    def test_set_then_get(self, tmp_map_path):
        video_map.set_path("vid1", "/path/to/video.mp4")
        assert video_map.get_path("vid1") == "/path/to/video.mp4"

    def test_get_missing_returns_none(self, tmp_map_path):
        assert video_map.get_path("nonexistent") is None

    def test_get_all(self, tmp_map_path):
        video_map.set_path("vid1", "/a.mp4")
        video_map.set_path("vid2", "/b.mp4")
        result = video_map.get_all()
        assert result == {"vid1": "/a.mp4", "vid2": "/b.mp4"}

    def test_find_by_path_current_index(self, tmp_map_path):
        video_map.set_path("vid1", "/a.mp4")
        assert video_map.find_by_path("/a.mp4") == "vid1"

    def test_find_by_path_wrong_index(self, tmp_map_path, monkeypatch):
        video_map.set_path("vid1", "/a.mp4")
        monkeypatch.setattr("app.video_map.get_index_id", lambda: "other_index")
        assert video_map.find_by_path("/a.mp4") is None

    def test_find_by_path_not_found(self, tmp_map_path):
        assert video_map.find_by_path("/nonexistent.mp4") is None


class TestVideoMapConcurrency:
    def test_concurrent_writes_no_data_loss(self, tmp_map_path):
        """All concurrent set_path calls should persist (validates the lock)."""
        n = 20
        barrier = threading.Barrier(n)

        def write(i):
            barrier.wait()
            video_map.set_path(f"vid{i}", f"/path/{i}.mp4")

        threads = [threading.Thread(target=write, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        result = video_map.get_all()
        assert len(result) == n
        for i in range(n):
            assert result[f"vid{i}"] == f"/path/{i}.mp4"
