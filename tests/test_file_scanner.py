from __future__ import annotations

from pathlib import Path

from app.utils.file_scanner import scan_folder


class TestScanFolder:
    def test_empty_dir(self, tmp_path):
        assert scan_folder(tmp_path) == []

    def test_non_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.touch()
        assert scan_folder(f) == []

    def test_finds_video_files(self, tmp_path):
        (tmp_path / "clip.mp4").touch()
        (tmp_path / "readme.txt").touch()
        (tmp_path / "movie.mov").touch()
        result = scan_folder(tmp_path)
        names = [p.name for p in result]
        assert "clip.mp4" in names
        assert "movie.mov" in names
        assert "readme.txt" not in names

    def test_excludes_macos_resource_forks(self, tmp_path):
        (tmp_path / "._hidden.mp4").touch()
        (tmp_path / "visible.mp4").touch()
        result = scan_folder(tmp_path)
        names = [p.name for p in result]
        assert "visible.mp4" in names
        assert "._hidden.mp4" not in names

    def test_non_recursive(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "nested.mp4").touch()
        (tmp_path / "top.mp4").touch()
        result = scan_folder(tmp_path)
        names = [p.name for p in result]
        assert "top.mp4" in names
        assert "nested.mp4" not in names

    def test_results_sorted(self, tmp_path):
        (tmp_path / "b.mp4").touch()
        (tmp_path / "a.mp4").touch()
        (tmp_path / "c.mp4").touch()
        result = scan_folder(tmp_path)
        assert result == sorted(result)
