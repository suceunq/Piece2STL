import tempfile
import unittest
from pathlib import Path

from piece2stl.inputs import list_images, validate_source


class InputTests(unittest.TestCase):
    def test_list_images_accepts_supported_extensions_case_insensitively(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("a.JPG", "b.jpeg", "c.png", "notes.txt"):
                (root / name).touch()
            self.assertEqual([p.name for p in list_images(root)], ["a.JPG", "b.jpeg", "c.png"])

    def test_exactly_one_source_is_required(self):
        self.assertTrue(validate_source())
        self.assertTrue(validate_source(Path("photos"), Path("video.mp4")))

    def test_empty_photo_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            errors = validate_source(image_dir=Path(directory))
            self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
