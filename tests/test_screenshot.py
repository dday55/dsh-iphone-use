"""Screenshots: only the image handed to the model is retained.

The native PNG is staged outside the retained folder, so a long session no longer
accumulates both a multi-megabyte PNG and its JPEG for every observation.
"""
import base64
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "iphone-use" / "server"))

from wda_controller import PhoneController


def tiny_png(width=2, height=2):
    """A real, complete PNG small enough that no downscaling is needed."""
    def chunk(kind, payload):
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


class FakeClient:
    def __init__(self, png):
        self.png = png

    def request(self, method, path, payload=None, timeout=None):
        if path == "/screenshot":
            return {"value": base64.b64encode(self.png).decode("ascii")}
        raise AssertionError(f"unexpected request {method} {path}")

    def session(self, method, path, payload=None, timeout=None):
        raise AssertionError(f"unexpected session {method} {path}")


class ScreenshotRetentionTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="iphone-use-shot-"))
        self.controller = PhoneController(FakeClient(tiny_png()), self.directory)

    def test_small_capture_keeps_exactly_one_artifact(self):
        image = self.controller.capture({"width": 375.0, "height": 667.0}, allow_cached_stream=False)
        artifacts = self.directory / "artifacts"
        files = sorted(p.name for p in artifacts.iterdir())
        self.assertEqual(len(files), 1, files)
        self.assertTrue(image["path"].endswith(files[0]))
        self.assertTrue(Path(image["path"]).is_file())

    def test_native_staging_area_does_not_keep_the_png(self):
        self.controller.capture({"width": 375.0, "height": 667.0}, allow_cached_stream=False)
        staging = self.directory / "tmp"
        leftovers = sorted(p.name for p in staging.iterdir()) if staging.exists() else []
        self.assertEqual(leftovers, [])

    def test_pixel_to_point_scale_is_reported(self):
        image = self.controller.capture({"width": 375.0, "height": 667.0}, allow_cached_stream=False)
        self.assertEqual(image["width"], 2)
        self.assertEqual(image["height"], 2)
        self.assertEqual(image["pixel_to_point"], [187.5, 333.5])


if __name__ == "__main__":
    unittest.main()
