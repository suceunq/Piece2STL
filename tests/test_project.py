import json
import tempfile
import unittest
from pathlib import Path

from piece2stl.project import load_project, new_project, save_project, update_project


class ProjectTests(unittest.TestCase):
    def test_project_round_trip_and_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "photos"
            source.mkdir()
            state = new_project("photos", source, root)
            state = update_project(
                state,
                status="reconstructed",
                active_mesh_path=str(root / "mesh.ply"),
            )
            path = save_project(state, root / "piece2stl_project.json")

            loaded = load_project(path)
            self.assertEqual(loaded.status, "reconstructed")
            self.assertEqual(loaded.active_mesh_path, str(root / "mesh.ply"))

    def test_unknown_project_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = new_project("photos", root, root)
            path = save_project(state, root / "project.json")
            data = json.loads(path.read_text(encoding="utf-8"))
            data["version"] = 99
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_project(path)


if __name__ == "__main__":
    unittest.main()
