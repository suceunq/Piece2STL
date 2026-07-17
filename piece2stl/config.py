import shutil
import sys
import os
from pathlib import Path

if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = PROJECT_ROOT / "vendor"
AI_DIR = PROJECT_ROOT / "ai"

COLMAP_EXE = VENDOR_DIR / "colmap" / "bin" / "colmap.exe"
OPENMVS_DIR = VENDOR_DIR / "openmvs"

OPENMVS_INTERFACE_COLMAP = OPENMVS_DIR / "InterfaceCOLMAP.exe"
OPENMVS_DENSIFY = OPENMVS_DIR / "DensifyPointCloud.exe"
OPENMVS_RECONSTRUCT_MESH = OPENMVS_DIR / "ReconstructMesh.exe"


def find_ffmpeg() -> str:
    bundled = VENDOR_DIR / "ffmpeg" / "bin" / "ffmpeg.exe"
    ffmpeg = str(bundled) if bundled.exists() else shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError(
            "ffmpeg introuvable sur le PATH. Installe-le (ex: winget install Gyan.FFmpeg)."
        )
    return ffmpeg


def check_vendor_binaries() -> None:
    missing = [
        str(p)
        for p in [
            COLMAP_EXE,
            OPENMVS_INTERFACE_COLMAP,
            OPENMVS_DENSIFY,
            OPENMVS_RECONSTRUCT_MESH,
        ]
        if not p.exists()
    ]
    if missing:
        raise FileNotFoundError(
            "Binaires manquants dans vendor/: " + ", ".join(missing)
        )


def find_ai_runtime() -> tuple[Path, Path]:
    configured = os.environ.get("PIECE2STL_AI_PYTHON")
    runtime_root = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else PROJECT_ROOT
    )
    candidates = [
        Path(configured) if configured else None,
        runtime_root / ".ai-venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / ".ai-venv" / "Scripts" / "python.exe",
    ]
    ai_python = next((path for path in candidates if path and path.is_file()), None)
    worker = AI_DIR / "triposr_worker.py"
    ready_marker = ai_python.parent.parent / "piece2stl_ai_ready.json" if ai_python else None
    if not ai_python or not worker.is_file() or not ready_marker or not ready_marker.is_file():
        raise FileNotFoundError(
            "Le mode IA n’est pas installé. Lancez « Installer IA Piece2STL.bat », "
            "puis redémarrez l’application."
        )
    return ai_python, worker
