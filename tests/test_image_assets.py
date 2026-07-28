import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import image_assets


class ImageAssetResolutionTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.image_dir = self.tmpdir / "images"
        self.thumb_dir = self.image_dir / "thumbs"
        self.thumb_dir.mkdir(parents=True)
        image_assets.local_image_exists.cache_clear()

    def tearDown(self):
        image_assets.local_image_exists.cache_clear()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_prefer_thumb_uses_existing_thumbnail_when_original_is_missing(self):
        (self.thumb_dir / "45567_0.webp").write_bytes(b"thumb")

        with mock.patch.object(image_assets, "DATA_IMAGES_DIR", self.image_dir), \
             mock.patch.object(image_assets, "THUMB_DIR", self.thumb_dir):
            resolved = image_assets.resolve_image_url(
                "data/images/45567_0.jpg",
                "https://example.invalid/original.jpg",
                prefer_thumb=True,
            )

        self.assertEqual(resolved, "/data/images/thumbs/45567_0.webp")

    def test_s3_mode_prefers_predictable_thumbnail_url_without_local_check(self):
        with mock.patch.dict(
            os.environ,
            {
                "RADAR_IMAGE_STORAGE": "s3",
                "RADAR_IMAGE_PUBLIC_BASE_URL": "https://s3.vn-hcm-1.vietnix.cloud/radarbds/",
            },
            clear=False,
        ), mock.patch.object(image_assets, "DATA_IMAGES_DIR", self.image_dir), \
             mock.patch.object(image_assets, "THUMB_DIR", self.thumb_dir):
            resolved = image_assets.resolve_image_url(
                "data/images/45567_0.jpg",
                "https://example.invalid/original.jpg",
                prefer_thumb=True,
            )

        self.assertEqual(
            resolved,
            "https://s3.vn-hcm-1.vietnix.cloud/radarbds/data/images/thumbs/45567_0.webp",
        )

    def test_s3_mode_returns_original_public_url_for_detail_images(self):
        with mock.patch.dict(
            os.environ,
            {
                "RADAR_IMAGE_STORAGE": "s3",
                "RADAR_IMAGE_PUBLIC_BASE_URL": "https://s3.vn-hcm-1.vietnix.cloud/radarbds",
            },
            clear=False,
        ):
            resolved = image_assets.resolve_image_url(
                "data/images/45567_0.jpg",
                "https://example.invalid/original.jpg",
                prefer_thumb=False,
            )

        self.assertEqual(
            resolved,
            "https://s3.vn-hcm-1.vietnix.cloud/radarbds/data/images/45567_0.jpg",
        )


if __name__ == "__main__":
    unittest.main()
