from dataclasses import asdict, dataclass, replace
from datetime import datetime
import json
from pathlib import Path


@dataclass(frozen=True)
class ProjectState:
    version: int
    created_at: str
    updated_at: str
    source_type: str
    source_path: str
    run_dir: str
    status: str
    active_mesh_path: str = ""
    scaled_output_path: str = ""
    last_error: str = ""


def new_project(source_type: str, source_path: Path, run_dir: Path) -> ProjectState:
    now = datetime.now().isoformat(timespec="seconds")
    return ProjectState(
        version=1,
        created_at=now,
        updated_at=now,
        source_type=source_type,
        source_path=str(source_path.resolve()),
        run_dir=str(run_dir.resolve()),
        status="created",
    )


def update_project(state: ProjectState, **changes) -> ProjectState:
    return replace(
        state,
        updated_at=datetime.now().isoformat(timespec="seconds"),
        **changes,
    )


def save_project(state: ProjectState, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def load_project(path: Path) -> ProjectState:
    data = json.loads(path.read_text(encoding="utf-8"))
    state = ProjectState(**data)
    if state.version != 1:
        raise ValueError(f"Version de projet non prise en charge : {state.version}")
    if not Path(state.run_dir).is_dir():
        raise FileNotFoundError("Le dossier associé au projet est introuvable.")
    return state
