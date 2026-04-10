from __future__ import annotations

import pytest
from app.services.otio_export import _tc_to_seconds


class TestTcToSeconds:
    def test_zero_timecode(self):
        assert _tc_to_seconds("00:00:00:00", 24.0) == 0.0

    def test_one_hour(self):
        assert _tc_to_seconds("01:00:00:00", 24.0) == 3600.0

    def test_one_minute(self):
        assert _tc_to_seconds("00:01:00:00", 30.0) == 60.0

    def test_frames_converted(self):
        # 12 frames at 24fps = 0.5s
        assert _tc_to_seconds("00:00:01:12", 24.0) == pytest.approx(1.5)

    def test_semicolon_separator(self):
        assert _tc_to_seconds("00:01:00;00", 30.0) == 60.0

    def test_wrong_format_returns_zero(self):
        assert _tc_to_seconds("01:00:00", 24.0) == 0.0
        assert _tc_to_seconds("", 24.0) == 0.0

    def test_combined(self):
        # 1h 2m 3s 12f at 24fps = 3723.5
        assert _tc_to_seconds("01:02:03:12", 24.0) == pytest.approx(3723.5)
