import numpy as np
import trimesh

from piece2stl.pipeline.units import (
    convert_declared_units_to_mm,
    normalize_generated_mesh_to_mm,
)


def test_generated_mesh_longest_dimension_is_100_mm():
    mesh = trimesh.creation.box(extents=(1.0, 2.0, 4.0))
    result, report = normalize_generated_mesh_to_mm(mesh)
    assert np.allclose(result.extents, (25.0, 50.0, 100.0))
    assert result.units == "mm"
    assert report.scale_factor == 25.0
    assert not report.calibrated


def test_declared_inches_are_converted_exactly_to_mm():
    mesh = trimesh.creation.box(extents=(1.0, 2.0, 3.0))
    mesh.units = "inches"
    result, report = convert_declared_units_to_mm(mesh)
    assert np.allclose(result.extents, (25.4, 50.8, 76.2))
    assert report.scale_factor == 25.4


def test_unitless_import_is_assumed_to_be_mm_without_rescaling():
    mesh = trimesh.creation.box(extents=(10.0, 20.0, 30.0))
    result, report = convert_declared_units_to_mm(mesh)
    assert np.allclose(result.extents, mesh.extents)
    assert report.policy == "assume-millimeters"
