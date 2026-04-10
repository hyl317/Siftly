from __future__ import annotations

import pytest
from app.utils.video_prep import VideoValidationError, validate_video, needs_transcode


class TestValidateVideo:
    def test_valid_video(self):
        validate_video({"duration": 30, "width": 1920, "height": 1080})

    def test_too_short(self):
        with pytest.raises(VideoValidationError, match="Too short"):
            validate_video({"duration": 2.0, "width": 1920, "height": 1080})

    def test_too_long(self):
        with pytest.raises(VideoValidationError, match="Too long"):
            validate_video({"duration": 3700, "width": 1920, "height": 1080})

    def test_resolution_too_low(self):
        with pytest.raises(VideoValidationError, match="too low"):
            validate_video({"duration": 30, "width": 320, "height": 200})

    def test_resolution_too_high(self):
        with pytest.raises(VideoValidationError, match="too high"):
            validate_video({"duration": 30, "width": 7680, "height": 4320})

    def test_extreme_aspect_ratio(self):
        with pytest.raises(VideoValidationError, match="Aspect ratio"):
            validate_video({"duration": 30, "width": 5000, "height": 100})

    def test_filename_in_error_prefix(self):
        with pytest.raises(VideoValidationError, match="^clip.mp4:"):
            validate_video({"duration": 1, "width": 100, "height": 100}, filename="clip.mp4")

    def test_multiple_errors_joined(self):
        with pytest.raises(VideoValidationError) as exc_info:
            validate_video({"duration": 1, "width": 320, "height": 200})
        assert "Too short" in str(exc_info.value)
        assert "too low" in str(exc_info.value)


class TestNeedsTranscode:
    def test_above_threshold(self):
        assert needs_transcode(1920, 1080) is True

    def test_at_threshold(self):
        assert needs_transcode(1280, 720) is False

    def test_below_threshold(self):
        assert needs_transcode(640, 480) is False

    def test_zero_height(self):
        assert needs_transcode(0, 0) is False
