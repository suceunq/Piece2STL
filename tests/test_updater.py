from piece2stl.updater import _version_tuple


def test_versions_compare_numerically():
    assert _version_tuple("v0.10.0") > _version_tuple("0.3.9")
    assert _version_tuple("1.2.3-beta") == (1, 2, 3)
