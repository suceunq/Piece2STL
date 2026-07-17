import tempfile
import unittest
from pathlib import Path

import trimesh

from piece2stl.pipeline.mesh_repair import RepairParams, repair_mesh


class MeshRepairTests(unittest.TestCase):
    def test_repairs_a_small_hole_without_overwriting_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "open_box.ply"
            output = root / "repaired.ply"
            mesh = trimesh.creation.box()
            mesh.update_faces([False] + [True] * (len(mesh.faces) - 1))
            mesh.export(source)

            result = repair_mesh(source, output, RepairParams(close_holes_max_edges=20))

            self.assertTrue(source.exists())
            self.assertTrue(output.exists())
            self.assertFalse(result.before.printable)
            self.assertTrue(result.after.printable)
            self.assertTrue(result.improved)

    def test_invalid_parameters_are_rejected(self):
        with self.assertRaises(ValueError):
            repair_mesh(Path("input.ply"), Path("output.ply"), RepairParams(close_holes_max_edges=0))


if __name__ == "__main__":
    unittest.main()
