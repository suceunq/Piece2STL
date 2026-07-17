import base64
import io
import json
from pathlib import Path

from PIL import Image

from piece2stl import meshy_api
from piece2stl.meshy_api import MeshyClient, image_data_uri


class Response:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _size=-1):
        value, self.payload = self.payload, b""
        return value


def test_webp_is_normalized_to_png_data_uri(tmp_path: Path):
    path = tmp_path / "source.webp"
    Image.new("RGB", (8, 6), "red").save(path)
    uri = image_data_uri(path)
    assert uri.startswith("data:image/png;base64,")
    decoded = base64.b64decode(uri.split(",", 1)[1])
    assert decoded.startswith(b"\x89PNG")


def test_create_uses_meshi_6_quality_options(monkeypatch, tmp_path: Path):
    path = tmp_path / "source.png"
    Image.new("RGBA", (8, 8), "blue").save(path)
    captured = {}

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.data)
        return Response({"result": "task-123"})

    monkeypatch.setattr(meshy_api, "urlopen", fake_urlopen)
    task = MeshyClient("msy_test").create(path)
    assert task == "task-123"
    assert captured["authorization"] == "Bearer msy_test"
    assert captured["payload"]["ai_model"] == "latest"
    assert captured["payload"]["enable_pbr"] is True
    assert captured["payload"]["should_remesh"] is True
    assert captured["payload"]["target_polycount"] == 100000
    assert captured["payload"]["target_formats"] == ["glb", "stl"]
