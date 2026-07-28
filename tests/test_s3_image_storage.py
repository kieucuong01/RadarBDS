import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import s3_image_storage


class S3ImageStorageTest(unittest.TestCase):
    def tearDown(self):
        s3_image_storage.s3_client.cache_clear()

    def test_upload_file_sets_public_acl_cache_and_content_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.webp"
            path.write_bytes(b"image")

            calls = []

            class FakeClient:
                def put_object(self, **kwargs):
                    calls.append(kwargs)

            with mock.patch.dict(
                os.environ,
                {
                    "RADAR_S3_BUCKET": "radarbds",
                    "RADAR_S3_OBJECT_ACL": "public-read",
                },
                clear=False,
            ), mock.patch.object(s3_image_storage, "s3_client", return_value=FakeClient()):
                result = s3_image_storage.upload_file(path, "/data/images/thumbs/sample.webp")

        self.assertEqual(result, "data/images/thumbs/sample.webp")
        kwargs = calls[0]
        self.assertEqual(kwargs["Bucket"], "radarbds")
        self.assertEqual(kwargs["Key"], "data/images/thumbs/sample.webp")
        self.assertIs(kwargs["Body"].closed, True)
        self.assertEqual(
            {key: kwargs[key] for key in ("ACL", "CacheControl", "ContentType")},
            {
                "ACL": "public-read",
                "CacheControl": "public, max-age=2592000, immutable",
                "ContentType": "image/webp",
            },
        )


if __name__ == "__main__":
    unittest.main()
