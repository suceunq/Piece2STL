import tempfile
import unittest
from pathlib import Path

from piece2stl.pipeline.frames import FrameInfo
from piece2stl.quality import select_images


class QualityTests(unittest.TestCase):
    def test_blurry_images_can_be_excluded(self):
        infos = [
            FrameInfo(Path(f"image_{index}.jpg"), 100.0, index < 2)
            for index in range(12)
        ]
        selected, report = select_images(infos, True, minimum_images=10)
        self.assertEqual(len(selected), 10)
        self.assertEqual(report.blurry_images, 2)
        self.assertAlmostEqual(report.blurry_ratio, 2 / 12)

    def test_filter_refuses_too_few_images(self):
        infos = [FrameInfo(Path(f"{index}.jpg"), 1.0, True) for index in range(12)]
        with self.assertRaises(ValueError):
            select_images(infos, True, minimum_images=10)


if __name__ == "__main__":
    unittest.main()
