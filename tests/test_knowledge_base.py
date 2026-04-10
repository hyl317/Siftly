from __future__ import annotations

from PIL import Image

from app.services.knowledge_base import image_to_base64


class TestImageToBase64:
    def test_jpeg_passthrough(self, tmp_path):
        path = tmp_path / "test.jpg"
        Image.new("RGB", (4, 4), color="red").save(str(path), format="JPEG")
        result = image_to_base64(str(path))
        assert result is not None
        b64, media_type = result
        assert media_type == "image/jpeg"
        assert len(b64) > 0

    def test_png_passthrough(self, tmp_path):
        path = tmp_path / "test.png"
        Image.new("RGB", (4, 4), color="blue").save(str(path), format="PNG")
        result = image_to_base64(str(path))
        assert result is not None
        b64, media_type = result
        assert media_type == "image/png"
        assert len(b64) > 0

    def test_missing_file_returns_none(self):
        assert image_to_base64("/nonexistent/path.jpg") is None

    def test_non_standard_format_re_encoded_as_png(self, tmp_path):
        path = tmp_path / "test.bmp"
        Image.new("RGB", (4, 4), color="green").save(str(path), format="BMP")
        result = image_to_base64(str(path))
        assert result is not None
        _, media_type = result
        assert media_type == "image/png"
