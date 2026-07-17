from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageOps


API_ROOT = "https://api.meshy.ai/openapi/v1/image-to-3d"
MESHY_KEY_URL = "https://www.meshy.ai/settings/api"


class MeshyAPIError(RuntimeError):
    pass


def image_data_uri(path: Path) -> str:
    """Normalise toute image prise en charge par l'interface en PNG Meshy."""
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
        stream = io.BytesIO()
        image.save(stream, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


class MeshyClient:
    def __init__(self, api_key: str, *, timeout: float = 60.0) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("La clé API Meshy est vide.")
        self.api_key = key
        self.timeout = timeout

    def _request(self, method: str, url: str, payload: dict | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Piece2STL/0.3",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except HTTPError as exc:
            detail = ""
            try:
                body = json.loads(exc.read().decode("utf-8", errors="replace"))
                detail = body.get("message") or body.get("detail") or ""
            except Exception:
                pass
            messages = {
                401: "Clé API Meshy invalide ou révoquée.",
                402: "Crédits Meshy insuffisants pour lancer cette génération.",
                429: "Limite de requêtes Meshy atteinte. Réessayez dans quelques instants.",
            }
            raise MeshyAPIError(messages.get(exc.code, detail or f"Erreur Meshy HTTP {exc.code}.")) from exc
        except URLError as exc:
            raise MeshyAPIError(f"Connexion à Meshy impossible : {exc.reason}") from exc

    def create(self, image_path: Path) -> str:
        result = self._request(
            "POST",
            API_ROOT,
            {
                "image_url": image_data_uri(image_path),
                "model_type": "standard",
                "ai_model": "latest",
                "should_texture": True,
                "enable_pbr": True,
                "remove_lighting": True,
                "should_remesh": True,
                "target_polycount": 100000,
                "moderation": True,
                "target_formats": ["glb", "stl"],
            },
        )
        task_id = result.get("result")
        if not task_id:
            raise MeshyAPIError("Meshy n’a pas renvoyé d’identifiant de tâche.")
        return str(task_id)

    def retrieve(self, task_id: str) -> dict:
        return self._request("GET", f"{API_ROOT}/{task_id}")

    def cancel_and_delete(self, task_id: str) -> None:
        try:
            self._request("DELETE", f"{API_ROOT}/{task_id}")
        except MeshyAPIError:
            pass

    def wait(
        self,
        task_id: str,
        *,
        progress: Callable[[int, str], None],
        cancelled: Callable[[], bool],
        interval: float = 4.0,
    ) -> dict:
        while True:
            if cancelled():
                self.cancel_and_delete(task_id)
                raise InterruptedError("Génération Meshy annulée.")
            task = self.retrieve(task_id)
            status = str(task.get("status", "PENDING")).upper()
            remote_progress = max(0, min(100, int(task.get("progress") or 0)))
            progress(15 + round(remote_progress * 0.68), f"Meshy crée le modèle — {remote_progress} %")
            if status == "SUCCEEDED":
                return task
            if status in {"FAILED", "CANCELED", "CANCELLED", "EXPIRED"}:
                error = task.get("task_error") or {}
                raise MeshyAPIError(error.get("message") or f"La tâche Meshy s’est arrêtée ({status}).")
            time.sleep(interval)

    def download(self, url: str, destination: Path) -> Path:
        request = Request(url, headers={"User-Agent": "Piece2STL/0.3"})
        try:
            with urlopen(request, timeout=max(120.0, self.timeout)) as response:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
            return destination
        except (HTTPError, URLError) as exc:
            raise MeshyAPIError(f"Téléchargement du modèle Meshy impossible : {exc}") from exc
