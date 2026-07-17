import json

from piece2stl import updater
from piece2stl.updater import _version_tuple


def test_versions_compare_numerically():
    assert _version_tuple("v0.10.0") > _version_tuple("0.3.9")
    assert _version_tuple("1.2.3-beta") == (1, 2, 3)


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(
            {
                "tag_name": "v0.3.0",
                "body": "notes",
                "assets": [
                    {"name": "Piece2STL-Setup-0.3.0.exe", "browser_download_url": "https://example/setup"},
                    {"name": "Piece2STL-Setup-0.3.0.exe.sha256", "browser_download_url": "https://example/hash"},
                ],
            }
        ).encode()


def test_versioned_installer_name_is_accepted(monkeypatch):
    monkeypatch.setattr(updater, "urlopen", lambda request, timeout: Response())
    info = updater.check_for_update("0.2.9")
    assert info and info.version == "0.3.0"
