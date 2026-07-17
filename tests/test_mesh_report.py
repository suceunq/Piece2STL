import json
import tempfile
import unittest
from pathlib import Path

import trimesh

from piece2stl.pipeline.mesh_report import inspect_mesh, save_report


class MeshReportTests(unittest.TestCase):
    def test_box_is_reported_as_printable(self):
        report = inspect_mesh(trimesh.creation.box(extents=(10, 20, 30)))
        self.assertTrue(report.printable)
        self.assertEqual(report.dimensions, (10.0, 20.0, 30.0))
        self.assertEqual(report.boundary_edges, 0)

    def test_open_mesh_is_not_reported_as_printable(self):
        mesh = trimesh.creation.box()
        mesh.update_faces([False] + [True] * (len(mesh.faces) - 1))
        report = inspect_mesh(mesh)
        self.assertFalse(report.printable)
        self.assertGreater(report.boundary_edges, 0)

    def test_report_is_saved_as_json(self):
        report = inspect_mesh(trimesh.creation.box())
        with tempfile.TemporaryDirectory() as directory:
            path = save_report(report, Path(directory) / "report.json")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(data["printable"])
            self.assertEqual(len(data["dimensions"]), 3)
