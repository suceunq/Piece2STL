import tempfile
import unittest
from pathlib import Path

import numpy as np
import trimesh

from piece2stl.pipeline.ai_postprocess import optimize_ai_mesh
from piece2stl.pipeline.export import load_mesh
from piece2stl.pipeline.mesh_report import inspect_mesh


class AIPostProcessTests(unittest.TestCase):
    def test_removes_tiny_artifact_and_preserves_vertex_colors(self):
        main = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
        artifact = trimesh.creation.icosphere(subdivisions=0, radius=0.03)
        artifact.apply_translation((3.0, 0.0, 0.0))
        mesh = trimesh.util.concatenate([main, artifact])
        colors = np.tile(np.array([[220, 40, 30, 255]], dtype=np.uint8), (len(mesh.vertices), 1))
        mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh, vertex_colors=colors)

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "raw.ply"
            output = Path(directory) / "clean.ply"
            mesh.export(source)
            report = optimize_ai_mesh(source, output)
            cleaned = load_mesh(output)
            topology = inspect_mesh(cleaned)

        self.assertGreater(report.removed_faces, 0)
        self.assertTrue(topology.printable)
        self.assertEqual(cleaned.visual.vertex_colors.shape[0], len(cleaned.vertices))
        self.assertGreater(cleaned.visual.vertex_colors[:, 0].mean(), 150)


if __name__ == "__main__":
    unittest.main()
