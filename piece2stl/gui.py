from __future__ import annotations

import sys
import os
import shutil
import subprocess
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtCore import QSettings, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .credentials import delete_meshy_key, load_meshy_key, save_meshy_key
from .hardware import HardwareReport, analyze_hardware, detect_gpus, sample_performance
from .meshy_api import MESHY_KEY_URL, MeshyClient
from .updater import UpdateInfo, check_for_update, download_update
from .inputs import list_images, validate_source
from .config import PROJECT_ROOT, check_vendor_binaries, find_ai_runtime, find_ffmpeg
from .project import (
    ProjectState,
    load_project,
    new_project,
    save_project,
    update_project,
)
from .quality import save_quality_report, select_images
from .pipeline.export import export_mesh, load_mesh
from .pipeline.ai_postprocess import optimize_ai_mesh, save_ai_postprocess_report
from .pipeline.frames import extract_frames, score_images
from .pipeline.mesh_report import inspect_mesh, save_report
from .pipeline.mesh_repair import RepairParams, repair_mesh, save_repair_report
from .pipeline.process import CancellationError, hidden_process_kwargs
from .pipeline.run_pipeline import reconstruct
from .pipeline.scale import apply_scale, scale_factor_from_two_points


class ReconstructionWorker(QThread):
    log_line = Signal(str)
    progress_changed = Signal(int, str)
    completed = Signal(object, object, object)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(
        self,
        *,
        image_dir: Path | None,
        video_path: Path | None,
        run_dir: Path,
        target_frames: int,
        exclude_blurry: bool,
    ) -> None:
        super().__init__()
        self.image_dir = image_dir
        self.video_path = video_path
        self.run_dir = run_dir
        self.target_frames = target_frames
        self.exclude_blurry = exclude_blurry

    def run(self) -> None:
        try:
            image_dir = self.image_dir
            if self.video_path:
                image_dir = self.run_dir / "frames"
                self.log_line.emit("Extraction des images de la vidéo…")
                images = extract_frames(
                    self.video_path,
                    image_dir,
                    target_count=self.target_frames,
                    log=self.log_line.emit,
                    cancel=self.isInterruptionRequested,
                )
            else:
                assert image_dir is not None
                images = list_images(image_dir)

            if len(images) < 20:
                self.log_line.emit(
                    f"Attention : seulement {len(images)} images. "
                    "Au moins 20 à 30 sont recommandées."
                )

            infos = score_images(images)
            selected_images, quality = select_images(infos, self.exclude_blurry)
            save_quality_report(quality, self.run_dir / "input_quality_report.json")
            self.log_line.emit(
                f"Contrôle qualité : {quality.total_images} images, "
                f"{quality.blurry_images} potentiellement floues, "
                f"{quality.selected_images} utilisées."
            )

            if self.exclude_blurry and len(selected_images) != len(images):
                self.progress_changed.emit(9, "Préparation des images sélectionnées")
                selected_dir = self.run_dir / "selected_images"
                selected_dir.mkdir(exist_ok=True)
                for selected in selected_images:
                    shutil.copy2(selected, selected_dir / selected.name)
                image_dir = selected_dir

            assert image_dir is not None
            mesh_path = reconstruct(
                image_dir=image_dir,
                workspace_dir=self.run_dir,
                sequential=self.video_path is not None,
                log=self.log_line.emit,
                cancel=self.isInterruptionRequested,
                progress=self.progress_changed.emit,
            )
            mesh = load_mesh(mesh_path)
            stl_path = export_mesh(mesh, self.run_dir / "export_unscaled.stl")
            report = inspect_mesh(mesh)
            save_report(report, self.run_dir / "mesh_report.json")
            self.completed.emit(stl_path, report, mesh_path)
        except CancellationError:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class RepairWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, input_path: Path, output_path: Path, params: RepairParams) -> None:
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.params = params

    def run(self) -> None:
        try:
            result = repair_mesh(self.input_path, self.output_path, self.params)
            save_repair_report(result, self.output_path.with_name("repair_report.json"))
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class AIWorker(QThread):
    log_line = Signal(str)
    progress_changed = Signal(int, str)
    completed = Signal(object, object, object)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, image_path: Path, run_dir: Path, resolution: int = 0) -> None:
        super().__init__()
        self.image_path = image_path
        self.run_dir = run_dir
        self.resolution = resolution

    def _log(self, line: str) -> None:
        self.log_line.emit(line)
        lowered = line.lower()
        if "préparation haute qualité" in lowered:
            self.progress_changed.emit(12, "Amélioration de l’image source")
        elif "arrière-plan" in lowered:
            self.progress_changed.emit(22, "Détourage précis de l’objet")
        elif "chargement du modèle" in lowered:
            self.progress_changed.emit(32, "Chargement du modèle IA")
        elif "géométrie 3d" in lowered:
            self.progress_changed.emit(45, "Génération haute définition de la géométrie 3D")

    def run(self) -> None:
        try:
            from .pipeline.process import run_command

            ai_python, worker = find_ai_runtime()
            raw_output_path = self.run_dir / "mesh_ai_raw.ply"
            output_path = self.run_dir / "mesh_ai.ply"
            self.progress_changed.emit(5, "Initialisation du mode IA")
            run_command(
                [
                    ai_python,
                    worker,
                    self.image_path,
                    "--output",
                    raw_output_path,
                    "--resolution",
                    str(self.resolution),
                    "--processed-output",
                    self.run_dir / "input_preprocessed.png",
                ],
                log=self._log,
                cancel=self.isInterruptionRequested,
            )
            self.progress_changed.emit(84, "Nettoyage et lissage du maillage")
            self.log_line.emit(
                "Nettoyage des artefacts, lissage préservant le volume et recalcul des normales…"
            )
            post_report = optimize_ai_mesh(raw_output_path, output_path)
            save_ai_postprocess_report(
                post_report, self.run_dir / "ai_postprocess_report.json"
            )
            self.log_line.emit(
                f"Post-traitement : {post_report.removed_faces} faces parasites retirées, "
                f"{post_report.smoothing_steps} passes de lissage."
            )
            self.progress_changed.emit(92, "Contrôle du maillage généré")
            mesh = load_mesh(output_path)
            report = inspect_mesh(mesh)
            save_report(report, self.run_dir / "mesh_report.json")
            stl_path = export_mesh(mesh, self.run_dir / "export_unscaled.stl")
            try:
                textured_path = export_mesh(mesh, self.run_dir / "export_textured.glb")
                self.log_line.emit(f"Modèle coloré GLB : {textured_path}")
            except Exception as exc:
                self.log_line.emit(f"Export GLB coloré non disponible : {exc}")
            self.progress_changed.emit(100, "Génération IA terminée")
            self.completed.emit(stl_path, report, output_path)
        except CancellationError:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MeshyWorker(QThread):
    """Génération Meshy explicitement choisie par l'utilisateur."""

    log_line = Signal(str)
    progress_changed = Signal(int, str)
    completed = Signal(object, object, object)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, image_path: Path, run_dir: Path, api_key: str) -> None:
        super().__init__()
        self.image_path = image_path
        self.run_dir = run_dir
        self.api_key = api_key

    def run(self) -> None:
        client = MeshyClient(self.api_key)
        task_id = ""
        try:
            self.progress_changed.emit(5, "Préparation sécurisée de l’image")
            self.log_line.emit("Envoi HTTPS vers Meshy Cloud (mode choisi explicitement)…")
            task_id = client.create(self.image_path)
            (self.run_dir / "meshy_task.json").write_text(
                '{"task_id": "' + task_id + '"}', encoding="utf-8"
            )
            self.progress_changed.emit(15, "Tâche Meshy démarrée")
            task = client.wait(
                task_id,
                progress=self.progress_changed.emit,
                cancelled=self.isInterruptionRequested,
            )
            urls = task.get("model_urls") or {}
            glb_url = urls.get("glb")
            if not glb_url:
                raise RuntimeError("Meshy n’a fourni aucun modèle GLB texturé.")
            self.progress_changed.emit(85, "Téléchargement du modèle texturé")
            glb_path = client.download(glb_url, self.run_dir / "export_textured.glb")
            if urls.get("stl"):
                client.download(urls["stl"], self.run_dir / "meshy_original.stl")

            self.progress_changed.emit(90, "Préparation du maillage pour l’impression")
            raw_path = self.run_dir / "mesh_meshy_raw.ply"
            mesh = load_mesh(glb_path)
            try:
                mesh.visual = mesh.visual.to_color()
            except Exception:
                pass
            export_mesh(mesh, raw_path)
            output_path = self.run_dir / "mesh_meshy.ply"
            post_report = optimize_ai_mesh(raw_path, output_path)
            save_ai_postprocess_report(post_report, self.run_dir / "ai_postprocess_report.json")
            cleaned = load_mesh(output_path)
            report = inspect_mesh(cleaned)
            save_report(report, self.run_dir / "mesh_report.json")
            stl_path = export_mesh(cleaned, self.run_dir / "export_unscaled.stl")
            self.progress_changed.emit(100, "Génération Meshy terminée")
            self.completed.emit(stl_path, report, output_path)
        except InterruptedError:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.api_key = ""


class HardwareScanWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.completed.emit(analyze_hardware())
        except Exception as exc:
            self.failed.emit(str(exc))


class HardwareScanDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Détection de votre matériel")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        layout = QVBoxLayout(self)
        title = QLabel("Détection de votre matériel")
        title.setObjectName("dialogTitle")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        layout.addWidget(title)
        self.summary = QLabel(
            "Piece2STL vérifie le GPU, la VRAM, la RAM, le processeur et les pilotes disponibles."
        )
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)
        self.details = QLabel("Analyse en cours…")
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        self.buttons.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        layout.addWidget(self.buttons)
        self.worker = HardwareScanWorker(self)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _completed(self, report: HardwareReport) -> None:
        colors = {"compatible": "#47c77b", "limited": "#e3a83b", "incompatible": "#ec6a6a"}
        self.summary.setText(f"<b style='color:{colors[report.level]}'>{report.title}</b>")
        self.details.setText("<br>".join(report.details))
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.buttons.setEnabled(True)

    def _failed(self, message: str) -> None:
        self.summary.setText("Analyse partielle")
        self.details.setText(
            "La détection détaillée n’a pas abouti. Le mode CPU universel et Meshy Cloud restent disponibles.<br>"
            + message
        )
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.buttons.setEnabled(True)


class PerformanceWorker(QThread):
    updated = Signal(object)

    def __init__(self, gpu=None) -> None:
        super().__init__()
        self.gpu = gpu

    def run(self) -> None:
        while not self.isInterruptionRequested():
            self.updated.emit(sample_performance(self.gpu))
            for _ in range(20):
                if self.isInterruptionRequested():
                    return
                time.sleep(0.1)


class UpdateWorker(QThread):
    checked = Signal(object)
    downloaded = Signal(object)
    progress_changed = Signal(int)
    failed = Signal(str)

    def __init__(self, info: UpdateInfo | None = None) -> None:
        super().__init__()
        self.info = info

    def run(self) -> None:
        try:
            if self.info is None:
                self.checked.emit(check_for_update(__version__))
            else:
                self.downloaded.emit(
                    download_update(self.info, self.progress_changed.emit)
                )
        except Exception as exc:
            self.failed.emit(str(exc))


class AIInstallWorker(QThread):
    """Installe le moteur IA sans ouvrir de console Windows."""

    log_line = Signal(str)
    progress_changed = Signal(int, str, str)
    completed = Signal()
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, script: Path) -> None:
        super().__init__()
        self.script = script
        self.process: subprocess.Popen[str] | None = None

    def _stop_process_tree(self) -> None:
        if not self.process or self.process.poll() is not None:
            return
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                **hidden_process_kwargs(),
            )
        else:
            self.process.terminate()

    def run(self) -> None:
        output_queue: queue.Queue[str | None] = queue.Queue()
        recent_lines: list[str] = []
        try:
            self.process = subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(self.script),
                    "-Backend",
                    "Auto",
                ],
                cwd=str(self.script.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **hidden_process_kwargs(),
            )
            assert self.process.stdout is not None

            def read_output() -> None:
                assert self.process and self.process.stdout
                for raw_line in self.process.stdout:
                    output_queue.put(raw_line)
                output_queue.put(None)

            threading.Thread(target=read_output, daemon=True).start()
            stream_finished = False
            while not stream_finished:
                if self.isInterruptionRequested():
                    self._stop_process_tree()
                    self.process.wait(timeout=10)
                    self.cancelled.emit()
                    return
                try:
                    raw_line = output_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if raw_line is None:
                    stream_finished = True
                    continue
                line = raw_line.rstrip()
                if not line:
                    continue
                if line.startswith("PIECE2STL_PROGRESS|"):
                    parts = line.split("|", 3)
                    if len(parts) == 4:
                        try:
                            percent = max(0, min(100, int(parts[1])))
                        except ValueError:
                            percent = 0
                        self.progress_changed.emit(percent, parts[2], parts[3])
                    continue
                recent_lines.append(line)
                del recent_lines[:-20]
                self.log_line.emit(line)

            return_code = self.process.wait()
            if return_code != 0:
                detail = "\n".join(recent_lines[-8:])
                raise RuntimeError(
                    f"L’installateur IA s’est arrêté avec le code {return_code}."
                    + (f"\n\n{detail}" if detail else "")
                )
            self.completed.emit()
        except subprocess.TimeoutExpired:
            self._stop_process_tree()
            self.failed.emit("L’arrêt de l’installateur IA a pris trop de temps.")
        except Exception as exc:
            self._stop_process_tree()
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Piece2STL — Photos vers impression 3D")
        self.resize(1240, 920)
        self.worker: ReconstructionWorker | AIWorker | MeshyWorker | AIInstallWorker | RepairWorker | None = None
        self.performance_worker: PerformanceWorker | None = None
        self.update_worker: UpdateWorker | None = None
        self.pending_update: UpdateInfo | None = None
        self.last_run_dir: Path | None = None
        self.last_mesh_path: Path | None = None
        self.picked_points: list[np.ndarray] = []
        self.project_state: ProjectState | None = None
        self.project_file: Path | None = None
        self.preview_mesh = None
        self.preview_color_array: str | None = None
        self.preview_textured = True

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = QLabel("Créer une pièce 3D à partir de photos")
        title.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        subtitle = QLabel(
            "Importez des photos ou une vidéo. Piece2STL contrôle les images, "
            "reconstruit la pièce et prépare un STL."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        self.mode_label = QLabel(
            "Modes locaux : photogrammétrie précise ou IA rapide • aucune photo envoyée dans le cloud"
        )
        self.mode_label.setStyleSheet("color: #55c67a; font-weight: 600;")
        layout.addWidget(self.mode_label)

        source_box = QGroupBox("1. Source")
        source_layout = QVBoxLayout(source_box)
        radio_row = QGridLayout()
        radio_row.setHorizontalSpacing(12)
        radio_row.setVerticalSpacing(10)
        self.photos_radio = QRadioButton("  📷  Dossier de photos\n       Précision maximale avec plusieurs vues")
        self.video_radio = QRadioButton("  🎬  Vidéo\n       Extraction automatique des meilleures vues")
        self.ai_radio = QRadioButton("  ◆  Photo unique — IA locale\n       Privé, hors ligne, AMD / NVIDIA / Intel")
        self.meshy_radio = QRadioButton("  ☁  Photo unique — Meshy Cloud\n       Qualité supérieure via votre clé API")
        self.photos_radio.setChecked(True)
        self.source_group = QButtonGroup(self)
        self.source_group.addButton(self.photos_radio)
        self.source_group.addButton(self.video_radio)
        self.source_group.addButton(self.ai_radio)
        self.source_group.addButton(self.meshy_radio)
        for button in (self.photos_radio, self.video_radio, self.ai_radio, self.meshy_radio):
            button.setObjectName("sourceChoice")
            button.setMinimumHeight(72)
        radio_row.addWidget(self.photos_radio, 0, 0)
        radio_row.addWidget(self.video_radio, 0, 1)
        radio_row.addWidget(self.ai_radio, 1, 0)
        radio_row.addWidget(self.meshy_radio, 1, 1)
        source_layout.addLayout(radio_row)

        source_row = QHBoxLayout()
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Sélectionnez un dossier contenant les photos")
        self.browse_source_button = QPushButton("Choisir la source…")
        self.browse_source_button.setMinimumHeight(38)
        self.browse_source_button.clicked.connect(self._browse_source)
        source_row.addWidget(self.source_edit)
        source_row.addWidget(self.browse_source_button)
        source_layout.addLayout(source_row)
        self.photos_radio.toggled.connect(self._update_source_hint)
        self.video_radio.toggled.connect(self._update_source_hint)
        self.ai_radio.toggled.connect(self._update_source_hint)
        self.meshy_radio.toggled.connect(self._update_source_hint)
        layout.addWidget(source_box)

        self.meshy_box = QGroupBox("Connexion Meshy Cloud — facultative")
        meshy_form = QFormLayout(self.meshy_box)
        key_row = QHBoxLayout()
        self.meshy_key_edit = QLineEdit(load_meshy_key())
        self.meshy_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.meshy_key_edit.setPlaceholderText("msy_…")
        self.show_key_button = QPushButton("Afficher")
        self.show_key_button.setCheckable(True)
        self.show_key_button.toggled.connect(self._toggle_api_key_visibility)
        self.meshy_link_button = QPushButton("Créer / gérer ma clé Meshy ↗")
        self.meshy_link_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(MESHY_KEY_URL))
        )
        key_row.addWidget(self.meshy_key_edit, 2)
        key_row.addWidget(self.show_key_button)
        key_row.addWidget(self.meshy_link_button)
        meshy_form.addRow("Clé API", key_row)
        self.remember_meshy_check = QCheckBox(
            "Mémoriser de façon sécurisée dans le Gestionnaire d’identifiants Windows"
        )
        self.remember_meshy_check.setChecked(bool(self.meshy_key_edit.text()))
        meshy_form.addRow("Sécurité", self.remember_meshy_check)
        cloud_note = QLabel(
            "Aucune image n’est envoyée tant que le mode Meshy Cloud n’est pas sélectionné et confirmé. "
            "La génération consomme les crédits de votre compte Meshy."
        )
        cloud_note.setWordWrap(True)
        cloud_note.setObjectName("mutedText")
        meshy_form.addRow("Confidentialité", cloud_note)
        layout.addWidget(self.meshy_box)

        project_box = QGroupBox("2. Destination")
        project_form = QFormLayout(project_box)
        project_row = QHBoxLayout()
        self.project_edit = QLineEdit(str(Path.home() / "Documents" / "Piece2STL"))
        browse_project = QPushButton("Parcourir…")
        browse_project.clicked.connect(self._browse_project)
        project_row.addWidget(self.project_edit)
        project_row.addWidget(browse_project)
        project_form.addRow("Dossier des projets", project_row)
        self.frames_spin = QSpinBox()
        self.frames_spin.setRange(20, 200)
        self.frames_spin.setValue(60)
        self.frames_spin.setEnabled(False)
        project_form.addRow("Images extraites de la vidéo", self.frames_spin)
        self.exclude_blurry_check = QCheckBox("Exclure automatiquement les images floues")
        self.exclude_blurry_check.setToolTip(
            "Peut améliorer la reconstruction, mais trop d’exclusions réduisent le recouvrement entre les vues."
        )
        project_form.addRow("Contrôle qualité", self.exclude_blurry_check)
        self.ai_quality_combo = QComboBox()
        self.ai_quality_combo.addItem("Optimale automatique — recommandée", 0)
        self.ai_quality_combo.addItem("Standard — 256", 256)
        self.ai_quality_combo.addItem("Haute — 320", 320)
        self.ai_quality_combo.addItem("Ultra — 384", 384)
        self.ai_quality_combo.setCurrentIndex(0)
        self.ai_quality_combo.setEnabled(False)
        self.ai_quality_combo.setToolTip(
            "Le mode automatique choisit la meilleure résolution sûre selon le GPU et sa mémoire."
        )
        project_form.addRow("Qualité IA", self.ai_quality_combo)
        layout.addWidget(project_box)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("Créer mon modèle 3D")
        self.start_button.setMinimumHeight(44)
        self.start_button.clicked.connect(self._start)
        self.open_button = QPushButton("Ouvrir le résultat")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_result)
        self.scale_button = QPushButton("Mettre à l’échelle")
        self.scale_button.setEnabled(False)
        self.scale_button.clicked.connect(self._start_scale_tool)
        self.cancel_button = QPushButton("Annuler")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_processing)
        self.repair_preset = QComboBox()
        self.repair_preset.addItem("Réparation prudente", "safe")
        self.repair_preset.addItem("Réparation intensive", "strong")
        self.repair_preset.setToolTip(
            "La réparation intensive ferme des ouvertures plus grandes et peut modifier davantage la forme."
        )
        self.repair_button = QPushButton("Réparer le maillage")
        self.repair_button.setEnabled(False)
        self.repair_button.clicked.connect(self._start_repair)
        action_row.addWidget(self.start_button, 2)
        action_row.addWidget(self.repair_preset)
        action_row.addWidget(self.repair_button)
        action_row.addWidget(self.open_button)
        action_row.addWidget(self.scale_button)
        action_row.addWidget(self.cancel_button)
        layout.addLayout(action_row)

        resume_row = QHBoxLayout()
        self.resume_button = QPushButton("Reprendre un projet…")
        self.resume_button.clicked.connect(self._resume_project)
        self.import_button = QPushButton("Ouvrir un maillage existant…")
        self.import_button.clicked.connect(self._import_mesh)
        self.ai_install_button = QPushButton("Installer/configurer l’IA…")
        self.ai_install_button.clicked.connect(self._launch_ai_installer)
        resume_row.addWidget(self.resume_button)
        resume_row.addWidget(self.import_button)
        resume_row.addWidget(self.ai_install_button)
        resume_row.addStretch()
        layout.addLayout(resume_row)

        activity_box = QGroupBox("Progression")
        activity_layout = QVBoxLayout(activity_box)
        activity_layout.setSpacing(8)

        self.status_label = QLabel("Prêt")
        self.status_label.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        self.status_label.setWordWrap(True)
        activity_layout.addWidget(self.status_label)

        self.status_explanation = QLabel(
            "Choisissez une source, puis Piece2STL vous expliquera chaque étape ici."
        )
        self.status_explanation.setWordWrap(True)
        self.status_explanation.setStyleSheet("color: #aeb8c2;")
        activity_layout.addWidget(self.status_explanation)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.progress.setMinimumHeight(24)
        self.progress.setStyleSheet(
            "QProgressBar { border: 1px solid #46515c; border-radius: 7px; "
            "background: #242a30; text-align: center; font-weight: 600; }"
            "QProgressBar::chunk { background: #3f9b62; border-radius: 6px; }"
        )
        activity_layout.addWidget(self.progress)

        background_hint = QLabel(
            "Vous pouvez réduire Piece2STL : le traitement continuera en arrière-plan."
        )
        background_hint.setStyleSheet("color: #7f8b96; font-size: 9pt;")
        background_hint.setWordWrap(True)
        activity_layout.addWidget(background_hint)

        self.details_button = QPushButton("Afficher le journal technique")
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self._toggle_logs)
        activity_layout.addWidget(self.details_button)

        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(2500)
        self.logs.setMinimumHeight(135)
        self.logs.setPlaceholderText("La progression détaillée apparaîtra ici.")
        self.logs.setVisible(False)
        activity_layout.addWidget(self.logs)
        layout.addWidget(activity_box)

        self.performance_box = QGroupBox("Performances locales")
        performance_layout = QGridLayout(self.performance_box)
        self.performance_toggle = QCheckBox("Afficher le suivi en temps réel")
        self.performance_toggle.setChecked(True)
        self.performance_toggle.toggled.connect(self._toggle_performance_panel)
        performance_layout.addWidget(self.performance_toggle, 0, 0, 1, 4)
        self.gpu_load_label = QLabel("GPU : —")
        self.vram_label = QLabel("VRAM : —")
        self.temperature_label = QLabel("Température : —")
        self.ram_label = QLabel("Mémoire : —")
        for index, widget in enumerate(
            (self.gpu_load_label, self.vram_label, self.temperature_label, self.ram_label)
        ):
            widget.setObjectName("metricPill")
            performance_layout.addWidget(widget, 1, index)
        layout.addWidget(self.performance_box)

        preview_box = QGroupBox("3. Aperçu et dimensions")
        preview_layout = QVBoxLayout(preview_box)
        preview_toolbar = QHBoxLayout()
        self.preview_mode_label = QLabel("Affichage : modèle texturé")
        self.preview_mode_button = QPushButton("Afficher le maillage brut")
        self.preview_mode_button.setEnabled(False)
        self.preview_mode_button.clicked.connect(self._toggle_preview_mode)
        preview_toolbar.addWidget(self.preview_mode_label)
        preview_toolbar.addStretch()
        preview_toolbar.addWidget(self.preview_mode_button)
        preview_layout.addLayout(preview_toolbar)
        self.preview = QtInteractor(preview_box)
        self.preview.setMinimumHeight(310)
        self.preview.set_background("#20252b")
        preview_layout.addWidget(self.preview.interactor)
        self.dimensions_label = QLabel("Dimensions : disponibles après reconstruction")
        preview_layout.addWidget(self.dimensions_label)
        layout.addWidget(preview_box, 2)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(central)
        self.setCentralWidget(scroll)

        file_menu = self.menuBar().addMenu("Fichier")
        open_folder_action = QAction("Ouvrir le dernier résultat", self)
        open_folder_action.triggered.connect(self._open_result)
        file_menu.addAction(open_folder_action)
        file_menu.addSeparator()
        quit_action = QAction("Quitter", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        tools_menu = self.menuBar().addMenu("Outils")
        hardware_action = QAction("Analyser mon matériel…", self)
        hardware_action.triggered.connect(self._show_hardware_scan)
        tools_menu.addAction(hardware_action)
        update_action = QAction("Rechercher les mises à jour…", self)
        update_action.triggered.connect(lambda: self._check_updates(manual=True))
        tools_menu.addAction(update_action)
        help_menu = self.menuBar().addMenu("Aide")
        about_action = QAction(f"À propos de Piece2STL {__version__}", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        self._update_source_hint()
        QTimer.singleShot(2500, lambda: self._check_updates(manual=False))

    def _toggle_api_key_visibility(self, visible: bool) -> None:
        self.meshy_key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self.show_key_button.setText("Masquer" if visible else "Afficher")

    def _toggle_performance_panel(self, visible: bool) -> None:
        for widget in (
            self.gpu_load_label, self.vram_label, self.temperature_label, self.ram_label
        ):
            widget.setVisible(visible)
        if not visible:
            self._stop_performance_monitor()

    def _start_performance_monitor(self) -> None:
        if not self.performance_toggle.isChecked() or (
            self.performance_worker and self.performance_worker.isRunning()
        ):
            return
        gpus = detect_gpus()
        gpu = max(gpus, key=lambda item: item.vram_gb, default=None)
        self.performance_worker = PerformanceWorker(gpu)
        self.performance_worker.updated.connect(self._update_performance)
        self.performance_worker.start()

    def _stop_performance_monitor(self) -> None:
        if self.performance_worker and self.performance_worker.isRunning():
            self.performance_worker.requestInterruption()
            self.performance_worker.wait(3000)
        self.performance_worker = None

    def _update_performance(self, values: dict) -> None:
        self.gpu_load_label.setText(f"GPU : {values['gpu']}")
        self.vram_label.setText(f"VRAM : {values['vram']}")
        self.temperature_label.setText(f"Température : {values['temperature']}")
        self.ram_label.setText(f"Mémoire : {values['ram']}")

    def _show_hardware_scan(self) -> None:
        HardwareScanDialog(self).exec()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "À propos de Piece2STL",
            f"<b>Piece2STL {__version__}</b><br><br>Photos et images vers des modèles 3D imprimables, "
            "avec calcul local AMD, NVIDIA et Intel ou génération Meshy Cloud facultative.",
        )

    def _check_updates(self, *, manual: bool) -> None:
        if self.update_worker and self.update_worker.isRunning():
            if manual:
                QMessageBox.information(self, "Mise à jour", "Une vérification est déjà en cours.")
            return
        self.update_worker = UpdateWorker()
        self.update_worker.checked.connect(
            lambda info: self._update_checked(info, manual=manual)
        )
        self.update_worker.failed.connect(
            lambda message: self._update_failed(message, manual=manual)
        )
        self.update_worker.start()

    def _update_checked(self, info: UpdateInfo | None, *, manual: bool) -> None:
        if not info:
            if manual:
                QMessageBox.information(
                    self, "Piece2STL est à jour", f"Vous utilisez la version {__version__}."
                )
            return
        self.pending_update = info
        answer = QMessageBox.question(
            self,
            "Mise à jour disponible",
            f"Piece2STL {info.version} est disponible.\n\nTélécharger et installer maintenant ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._download_update(info)

    def _download_update(self, info: UpdateInfo) -> None:
        self.status_label.setText(f"Téléchargement de Piece2STL {info.version}")
        self.status_explanation.setText(
            "La somme SHA-256 sera vérifiée avant toute installation."
        )
        self.update_worker = UpdateWorker(info)
        self.update_worker.progress_changed.connect(self.progress.setValue)
        self.update_worker.downloaded.connect(self._update_downloaded)
        self.update_worker.failed.connect(lambda message: self._update_failed(message, manual=True))
        self.update_worker.start()

    def _update_downloaded(self, installer: Path) -> None:
        answer = QMessageBox.question(
            self,
            "Mise à jour prête",
            "La mise à jour a été téléchargée et vérifiée. Installer et redémarrer maintenant ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        subprocess.Popen(
            [str(installer), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
            cwd=str(installer.parent),
            **hidden_process_kwargs(),
        )
        QApplication.quit()

    def _update_failed(self, message: str, *, manual: bool) -> None:
        if manual:
            QMessageBox.warning(self, "Mise à jour indisponible", message)

    def _toggle_logs(self, visible: bool) -> None:
        self.logs.setVisible(visible)
        self.details_button.setText(
            "Masquer le journal technique" if visible else "Afficher le journal technique"
        )

    def _update_source_hint(self) -> None:
        self.source_edit.clear()
        if self.photos_radio.isChecked():
            hint = "Sélectionnez un dossier contenant les photos"
        elif self.ai_radio.isChecked() or self.meshy_radio.isChecked():
            hint = "Sélectionnez une photo claire de l’objet"
        else:
            hint = "Sélectionnez une vidéo"
        self.source_edit.setPlaceholderText(hint)
        self.frames_spin.setEnabled(self.video_radio.isChecked())
        single_image = self.ai_radio.isChecked() or self.meshy_radio.isChecked()
        self.exclude_blurry_check.setEnabled(not single_image)
        self.ai_quality_combo.setEnabled(self.ai_radio.isChecked())
        self.meshy_box.setEnabled(self.meshy_radio.isChecked())
        self.mode_label.setText(
            "Mode Meshy Cloud : l’image est envoyée uniquement après votre confirmation."
            if self.meshy_radio.isChecked()
            else "Modes locaux : photogrammétrie précise ou IA rapide • aucune photo envoyée dans le cloud"
        )

    def _browse_source(self) -> None:
        if self.photos_radio.isChecked():
            path = QFileDialog.getExistingDirectory(self, "Choisir les photos")
        elif self.ai_radio.isChecked() or self.meshy_radio.isChecked():
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Choisir une photo",
                filter="Images (*.jpg *.jpeg *.png *.webp);;Tous (*.*)",
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Choisir une vidéo", filter="Vidéos (*.mp4 *.mov *.avi *.mkv);;Tous (*.*)"
            )
        if path:
            self.source_edit.setText(path)

    def _browse_project(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choisir le dossier des projets")
        if path:
            self.project_edit.setText(path)

    def _start(self) -> None:
        source = Path(self.source_edit.text().strip())
        ai_mode = self.ai_radio.isChecked()
        cloud_mode = self.meshy_radio.isChecked()
        image_dir = source if self.photos_radio.isChecked() else None
        video_path = source if self.video_radio.isChecked() else None
        if ai_mode or cloud_mode:
            errors = []
            if not source.is_file() or source.suffix.lower() not in {
                ".jpg", ".jpeg", ".png", ".webp"
            }:
                errors.append("Choisissez une image JPG, JPEG, PNG ou WebP valide.")
            if cloud_mode and not self.meshy_key_edit.text().strip():
                errors.append("Saisissez votre clé API Meshy ou utilisez le lien pour en créer une.")
        else:
            errors = validate_source(image_dir=image_dir, video_path=video_path)
        project_root_text = self.project_edit.text().strip()
        if not project_root_text:
            errors.append("Choisissez un dossier de destination.")
        if errors:
            QMessageBox.warning(self, "Entrée incomplète", "\n".join(errors))
            return

        if cloud_mode:
            answer = QMessageBox.question(
                self,
                "Confirmer l’envoi vers Meshy",
                "L’image sélectionnée sera envoyée à Meshy Cloud via HTTPS et cette génération "
                "consommera les crédits de votre compte.\n\nContinuer ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            if self.remember_meshy_check.isChecked():
                if not save_meshy_key(self.meshy_key_edit.text()):
                    QMessageBox.warning(
                        self,
                        "Stockage sécurisé indisponible",
                        "La clé sera utilisée uniquement pour cette session et ne sera pas enregistrée.",
                    )
            else:
                delete_meshy_key()

        try:
            if ai_mode:
                find_ai_runtime()
            elif not cloud_mode:
                check_vendor_binaries()
                if video_path:
                    find_ffmpeg()
        except FileNotFoundError as exc:
            QMessageBox.critical(self, "Composant manquant", str(exc))
            return

        project_root = Path(project_root_text)
        project_root.mkdir(parents=True, exist_ok=True)
        free_gb = shutil.disk_usage(project_root).free / (1024**3)
        if free_gb < 5:
            answer = QMessageBox.warning(
                self,
                "Espace disque faible",
                f"Il reste seulement {free_gb:.1f} Go. Une reconstruction peut nécessiter "
                "plus de 5 Go. Continuer malgré tout ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        run_name = datetime.now().strftime("scan_%Y%m%d_%H%M%S")
        run_dir = project_root / run_name
        run_dir.mkdir(parents=True, exist_ok=False)
        self.last_run_dir = run_dir
        self.last_mesh_path = None
        source_type = "meshy" if cloud_mode else ("ai" if ai_mode else ("photos" if image_dir else "video"))
        self.project_state = new_project(source_type, source, run_dir)
        self.project_file = run_dir / "piece2stl_project.json"
        save_project(self.project_state, self.project_file)
        self._clear_preview()
        self.logs.clear()
        self.logs.appendPlainText(f"Projet : {run_dir}")
        self.status_label.setText("Reconstruction en cours… Cette opération peut être longue.")
        self.status_explanation.setText(
            "Piece2STL prépare les fichiers de travail. Vous pouvez réduire la fenêtre pendant le calcul."
        )
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.start_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.scale_button.setEnabled(False)
        self.repair_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.import_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        if cloud_mode:
            self.worker = MeshyWorker(
                source, run_dir, self.meshy_key_edit.text().strip()
            )
        elif ai_mode:
            self.worker = AIWorker(
                source, run_dir, resolution=int(self.ai_quality_combo.currentData())
            )
        else:
            self.worker = ReconstructionWorker(
                image_dir=image_dir,
                video_path=video_path,
                run_dir=run_dir,
                target_frames=self.frames_spin.value(),
                exclude_blurry=self.exclude_blurry_check.isChecked(),
            )
        self.worker.log_line.connect(self.logs.appendPlainText)
        self.worker.progress_changed.connect(self._update_progress)
        self.worker.completed.connect(self._completed)
        self.worker.cancelled.connect(self._cancelled)
        self.worker.failed.connect(self._failed)
        self.worker.start()
        if not cloud_mode:
            self._start_performance_monitor()

    def _completed(self, stl_path: Path, report, mesh_path: Path) -> None:
        self._stop_performance_monitor()
        self.last_mesh_path = Path(mesh_path)
        self._save_project_state(
            status="reconstructed",
            active_mesh_path=str(self.last_mesh_path.resolve()) if self.last_mesh_path else "",
            last_error="",
        )
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        watertight = "oui" if report.watertight else "non — réparation conseillée"
        self.status_label.setText(
            f"Modèle créé : {report.vertices:,} sommets, {report.faces:,} faces. "
            f"Étanche : {watertight}."
        )
        self.status_explanation.setText(
            "La reconstruction est terminée. Inspectez le modèle, réparez-le si nécessaire, "
            "puis indiquez une dimension réelle avant l’impression."
        )
        self._show_mesh(self.last_mesh_path)
        self._show_dimensions(report.dimensions, scaled=False)
        if not report.printable:
            self.logs.appendPlainText(
                "Contrôle d’imprimabilité : le maillage n’est pas encore garanti imprimable "
                "(étanchéité, normales ou volume à corriger)."
            )
            self.logs.appendPlainText(
                f"Arêtes ouvertes : {report.boundary_edges}; "
                f"arêtes non-manifold : {report.non_manifold_edges}."
            )
        self.logs.appendPlainText(f"STL non mis à l’échelle : {stl_path}")
        self.start_button.setEnabled(True)
        self.resume_button.setEnabled(True)
        self.import_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.open_button.setEnabled(True)
        self.scale_button.setEnabled(self.last_mesh_path is not None)
        self.repair_button.setEnabled(self.last_mesh_path is not None and not report.printable)

    def _failed(self, message: str) -> None:
        self._stop_performance_monitor()
        self._save_project_state(status="failed", last_error=message)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status_label.setText("La reconstruction a échoué. Consultez le journal.")
        self.status_explanation.setText(
            "Aucun fichier existant n’a été supprimé. Le journal technique contient la cause de l’erreur."
        )
        self.details_button.setChecked(True)
        self.logs.appendPlainText(f"ERREUR : {message}")
        self.start_button.setEnabled(True)
        self.resume_button.setEnabled(True)
        self.import_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.open_button.setEnabled(self.last_run_dir is not None)
        QMessageBox.critical(self, "Échec de la reconstruction", message)

    def _update_progress(self, value: int, message: str) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(value)
        self.status_label.setText(message)
        self.status_explanation.setText(self._explain_progress(message))

    @staticmethod
    def _explain_progress(message: str) -> str:
        lowered = message.lower()
        explanations = (
            ("vérification", "Vérification des moteurs, de l’espace disponible et des fichiers nécessaires."),
            ("préparation des images", "Copie des meilleures vues dans un dossier de travail, sans modifier les originaux."),
            ("détection des détails", "Recherche de points visuels reconnaissables sur chaque photographie."),
            ("correspondance", "Comparaison des photos pour retrouver le même point sous plusieurs angles."),
            ("positions de caméra", "Calcul de la position de chaque prise de vue autour de l’objet."),
            ("reconstruction dense", "Création de millions de points décrivant la surface visible de l’objet."),
            ("nuage de points", "Transformation des correspondances entre photos en une surface 3D détaillée."),
            ("création du maillage", "Connexion des points en triangles pour former un véritable objet 3D."),
            ("nettoyage du maillage", "Suppression des défauts évidents et préparation du fichier pour l’export STL."),
            ("initialisation du mode ia", "Démarrage du moteur adapté à votre carte graphique, entièrement en local."),
            ("chargement du modèle ia", "Chargement du réseau neuronal en mémoire vidéo ou, si nécessaire, en mémoire système."),
            ("détourage", "Séparation automatique de l’objet et de l’arrière-plan de la photo."),
            ("géométrie 3d", "L’IA estime les parties visibles et cachées afin de produire un volume 3D."),
            ("contrôle du maillage", "Vérification de l’étanchéité, des faces et des arêtes avant la création du STL."),
            ("meshy", "Meshy 6 reconstruit la géométrie, crée les parties cachées et applique une texture PBR dans le cloud."),
            ("téléchargement du modèle", "Récupération sécurisée du GLB texturé et du modèle destiné à l’impression."),
        )
        for needle, explanation in explanations:
            if needle in lowered:
                return explanation
        return "Piece2STL poursuit le traitement en arrière-plan. Les fichiers source restent inchangés."

    def _cancel_processing(self) -> None:
        if self.worker and self.worker.isRunning():
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Annulation en cours…")
            self.status_explanation.setText(
                "Arrêt propre des calculs et conservation des fichiers déjà produits."
            )
            self.logs.appendPlainText("Annulation demandée par l’utilisateur.")
            self.worker.requestInterruption()

    def _cancelled(self) -> None:
        self._stop_performance_monitor()
        self._save_project_state(status="cancelled", last_error="")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText("Traitement annulé. Le projet partiel a été conservé.")
        self.status_explanation.setText(
            "Vous pouvez relancer une opération. Les sources originales n’ont pas été modifiées."
        )
        self.logs.appendPlainText("Traitement annulé proprement.")
        self.start_button.setEnabled(True)
        self.resume_button.setEnabled(True)
        self.import_button.setEnabled(True)
        self.open_button.setEnabled(self.last_run_dir is not None)
        self.cancel_button.setEnabled(False)

    def _start_repair(self) -> None:
        if not self.last_mesh_path or not self.last_run_dir:
            return
        intensive = self.repair_preset.currentData() == "strong"
        params = RepairParams(
            close_holes_max_edges=1000 if intensive else 200,
            # Ne jamais supprimer automatiquement un petit composant : il peut
            # s'agir de la pièce principale elle-même.
            remove_components_below_faces=0,
            prevent_self_intersections=not intensive,
        )
        output_path = self.last_run_dir / "mesh_repaired.ply"
        self.status_label.setText("Réparation du maillage en cours…")
        self.progress.setRange(0, 0)
        self.start_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.import_button.setEnabled(False)
        self.repair_button.setEnabled(False)
        self.scale_button.setEnabled(False)
        self.worker = RepairWorker(self.last_mesh_path, output_path, params)
        self.worker.completed.connect(self._repair_completed)
        self.worker.failed.connect(self._repair_failed)
        self.worker.start()

    def _repair_completed(self, result) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.start_button.setEnabled(True)
        self.resume_button.setEnabled(True)
        self.import_button.setEnabled(True)
        self.last_mesh_path = result.output_path
        self._save_project_state(
            status="repaired" if result.after.printable else "repair_incomplete",
            active_mesh_path=str(result.output_path.resolve()),
            scaled_output_path="",
            last_error="",
        )
        export_mesh(load_mesh(result.output_path), result.output_path.with_name("export_repaired_unscaled.stl"))
        self._show_mesh(result.output_path)
        self._show_dimensions(result.after.dimensions, scaled=False)
        self.scale_button.setEnabled(True)
        self.repair_button.setEnabled(not result.after.printable)
        if result.after.printable:
            message = "Réparation réussie : le maillage passe les contrôles d’imprimabilité."
        elif result.improved:
            message = "Le maillage a été amélioré, mais certains défauts subsistent."
        else:
            message = "La réparation automatique n’a pas résolu les défauts détectés."
        self.status_label.setText(message)
        self.logs.appendPlainText(message)
        self.logs.appendPlainText(
            f"Arêtes ouvertes avant/après : {result.before.boundary_edges} / "
            f"{result.after.boundary_edges}."
        )
        self.logs.appendPlainText(f"Maillage réparé conservé séparément : {result.output_path}")

    def _repair_failed(self, message: str) -> None:
        self._save_project_state(status="repair_failed", last_error=message)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.start_button.setEnabled(True)
        self.resume_button.setEnabled(True)
        self.import_button.setEnabled(True)
        self.repair_button.setEnabled(True)
        self.scale_button.setEnabled(self.last_mesh_path is not None)
        self.status_label.setText("La réparation automatique a échoué.")
        self.logs.appendPlainText(f"ERREUR DE RÉPARATION : {message}")
        QMessageBox.critical(self, "Échec de la réparation", message)

    def _open_result(self) -> None:
        if self.last_run_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_run_dir)))

    def _resume_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Reprendre un projet Piece2STL",
            filter="Projet Piece2STL (piece2stl_project.json *.piece2stl.json);;JSON (*.json)",
        )
        if not path:
            return
        try:
            state = load_project(Path(path))
            mesh_path = Path(state.active_mesh_path) if state.active_mesh_path else None
            if not mesh_path or not mesh_path.is_file():
                raise FileNotFoundError("Le maillage actif du projet est introuvable.")
            self.project_state = state
            self.project_file = Path(path)
            self.last_run_dir = Path(state.run_dir)
            self._load_existing_mesh(mesh_path, f"Projet repris : {Path(path).name}")
            if state.scaled_output_path and Path(state.scaled_output_path).is_file():
                self.logs.appendPlainText(f"Export calibré existant : {state.scaled_output_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Projet illisible", str(exc))

    def _import_mesh(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Ouvrir un maillage",
            filter="Maillages (*.ply *.stl *.obj *.3mf *.glb);;Tous (*.*)",
        )
        if not path:
            return
        try:
            mesh_path = Path(path).resolve()
            load_mesh(mesh_path)
            self.last_run_dir = mesh_path.parent
            self.project_state = new_project("mesh", mesh_path, mesh_path.parent)
            self.project_state = update_project(
                self.project_state,
                status="imported",
                active_mesh_path=str(mesh_path),
            )
            self.project_file = mesh_path.with_suffix(".piece2stl.json")
            save_project(self.project_state, self.project_file)
            self._load_existing_mesh(mesh_path, f"Maillage importé : {mesh_path.name}")
        except Exception as exc:
            QMessageBox.critical(self, "Maillage illisible", str(exc))

    def _launch_ai_installer(self) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(
                self,
                "Traitement déjà en cours",
                "Attendez la fin du traitement actuel ou annulez-le avant de configurer l’IA.",
            )
            return
        if getattr(sys, "frozen", False):
            script = Path(sys.executable).resolve().parent / "setup_ai.ps1"
        else:
            script = Path(__file__).resolve().parent.parent / "scripts" / "setup_ai.ps1"
        if not script.is_file():
            QMessageBox.critical(
                self, "Installateur absent", f"Fichier introuvable : {script}"
            )
            return
        self.logs.clear()
        self.logs.appendPlainText(f"Installateur : {script}")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText("Préparation de l’IA locale")
        self.status_explanation.setText(
            "Piece2STL va détecter votre carte graphique et installer le moteur approprié en arrière-plan."
        )
        self.start_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.import_button.setEnabled(False)
        self.ai_install_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        self.worker = AIInstallWorker(script)
        self.worker.log_line.connect(self.logs.appendPlainText)
        self.worker.progress_changed.connect(self._update_ai_install_progress)
        self.worker.completed.connect(self._ai_install_completed)
        self.worker.cancelled.connect(self._ai_install_cancelled)
        self.worker.failed.connect(self._ai_install_failed)
        self.worker.start()

    def _update_ai_install_progress(
        self, value: int, title: str, explanation: str
    ) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(value)
        self.status_label.setText(title)
        self.status_explanation.setText(explanation)

    def _restore_after_ai_install(self) -> None:
        self.start_button.setEnabled(True)
        self.resume_button.setEnabled(True)
        self.import_button.setEnabled(True)
        self.ai_install_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def _ai_install_completed(self) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.status_label.setText("IA locale prête")
        self.status_explanation.setText(
            "Installation vérifiée. Vous pouvez choisir « Photo unique — IA locale » et créer un modèle immédiatement."
        )
        self.logs.appendPlainText("Installation IA terminée et vérifiée.")
        self.ai_install_button.setText("Réinstaller/configurer l’IA…")
        self._restore_after_ai_install()
        QMessageBox.information(
            self,
            "IA prête",
            "Le moteur IA est installé et opérationnel. Aucun redémarrage de Piece2STL n’est nécessaire.",
        )

    def _ai_install_cancelled(self) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText("Installation IA annulée")
        self.status_explanation.setText(
            "Les téléchargements incomplets pourront être repris en relançant l’installation."
        )
        self.logs.appendPlainText("Installation IA annulée par l’utilisateur.")
        self._restore_after_ai_install()

    def _ai_install_failed(self, message: str) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText("L’installation de l’IA a échoué")
        self.status_explanation.setText(
            "Le journal technique est affiché pour aider à identifier le téléchargement ou le composant en cause."
        )
        self.logs.appendPlainText(f"ERREUR D’INSTALLATION IA : {message}")
        self.details_button.setChecked(True)
        self._restore_after_ai_install()
        QMessageBox.critical(self, "Échec de l’installation IA", message)

    def _load_existing_mesh(self, mesh_path: Path, message: str) -> None:
        mesh = load_mesh(mesh_path)
        report = inspect_mesh(mesh)
        self.last_mesh_path = mesh_path
        self.logs.clear()
        self.logs.appendPlainText(message)
        self.logs.appendPlainText(
            f"Contrôle : {report.vertices:,} sommets, {report.faces:,} faces, "
            f"{report.boundary_edges} arêtes ouvertes."
        )
        self._show_mesh(mesh_path)
        self._show_dimensions(report.dimensions, scaled=False)
        self.status_label.setText(
            "Maillage prêt à être inspecté." if report.printable
            else "Maillage chargé : une réparation est recommandée."
        )
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.open_button.setEnabled(True)
        self.scale_button.setEnabled(True)
        self.repair_button.setEnabled(not report.printable)

    def _save_project_state(self, **changes) -> None:
        if not self.project_state or not self.project_file:
            return
        self.project_state = update_project(self.project_state, **changes)
        save_project(self.project_state, self.project_file)

    def _start_scale_tool(self) -> None:
        if not self.last_mesh_path:
            return
        self.picked_points.clear()
        self.preview.disable_picking()
        self.preview.enable_point_picking(
            callback=self._point_picked,
            show_message=False,
            use_mesh=True,
            left_clicking=True,
            show_point=True,
            color="red",
            point_size=14,
        )
        self.status_label.setText(
            "Mise à l’échelle : cliquez deux points correspondant à une distance connue."
        )

    def _point_picked(self, point) -> None:
        if point is None or len(self.picked_points) >= 2:
            return
        picked = np.asarray(point, dtype=float)
        self.picked_points.append(picked)
        self.preview.add_point_labels(
            [picked],
            [f"P{len(self.picked_points)}"],
            point_color="red",
            point_size=14,
            font_size=16,
            name=f"scale_point_{len(self.picked_points)}",
        )
        if len(self.picked_points) == 2:
            self.preview.disable_picking()
            measured = float(np.linalg.norm(self.picked_points[0] - self.picked_points[1]))
            distance, accepted = QInputDialog.getDouble(
                self,
                "Distance réelle",
                f"Distance mesurée dans le modèle : {measured:.4f}\n"
                "Indiquez la distance réelle en millimètres :",
                value=10.0,
                minValue=0.001,
                maxValue=1_000_000.0,
                decimals=3,
            )
            if accepted:
                self._export_scaled(distance)
            else:
                self.status_label.setText("Mise à l’échelle annulée.")

    def _export_scaled(self, real_distance_mm: float) -> None:
        assert self.last_mesh_path is not None
        try:
            factor = scale_factor_from_two_points(
                self.picked_points[0], self.picked_points[1], real_distance_mm
            )
            mesh = load_mesh(self.last_mesh_path)
            scaled = apply_scale(mesh, factor)
            out_stl = self.last_mesh_path.with_name("export_scaled_mm.stl")
            export_mesh(scaled, out_stl)
            scaled_preview = self.last_mesh_path.with_name("mesh_scaled_mm.ply")
            export_mesh(scaled, scaled_preview)
            try:
                export_mesh(scaled, self.last_mesh_path.with_name("export_scaled_mm.3mf"))
            except Exception as exc:
                self.logs.appendPlainText(f"Export 3MF non disponible : {exc}")
            report = inspect_mesh(scaled)
            save_report(report, self.last_mesh_path.with_name("mesh_report_scaled.json"))
            self._show_mesh(scaled_preview)
            self._show_dimensions(report.dimensions, scaled=True)
            self.status_label.setText(
                f"Échelle appliquée (facteur {factor:.6f}). STL prêt : {out_stl.name}"
            )
            self.logs.appendPlainText(f"STL mis à l’échelle en millimètres : {out_stl}")
            self._save_project_state(
                status="scaled",
                scaled_output_path=str(out_stl.resolve()),
                last_error="",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Échec de la mise à l’échelle", str(exc))

    def _clear_preview(self) -> None:
        self.preview.clear()
        self.preview.set_background("#20252b")
        self.preview_mesh = None
        self.preview_color_array = None
        self.preview_textured = True
        self.preview_mode_label.setText("Affichage : aucun modèle")
        self.preview_mode_button.setText("Afficher le maillage brut")
        self.preview_mode_button.setEnabled(False)
        self.dimensions_label.setText("Dimensions : disponibles après reconstruction")

    def _show_mesh(self, path: Path | None) -> None:
        if not path or not path.exists():
            return
        try:
            self.preview_mesh = pv.read(str(path))
            self.preview_color_array = None
            for name in ("RGBA", "RGB", "rgba", "rgb"):
                if name in self.preview_mesh.point_data:
                    values = self.preview_mesh.point_data[name]
                    if values.ndim == 2 and values.shape[1] in (3, 4):
                        self.preview_color_array = name
                        break
            self.preview_textured = bool(self.preview_color_array)
            self.preview_mode_button.setEnabled(bool(self.preview_color_array))
            self._render_preview(reset_camera=True)
        except Exception as exc:
            self.logs.appendPlainText(f"Aperçu 3D indisponible : {exc}")

    def _toggle_preview_mode(self) -> None:
        if self.preview_mesh is None or not self.preview_color_array:
            return
        self.preview_textured = not self.preview_textured
        self._render_preview(reset_camera=False)

    def _render_preview(self, *, reset_camera: bool) -> None:
        if self.preview_mesh is None:
            return
        camera = None if reset_camera else self.preview.camera_position
        self.preview.clear()
        self.preview.set_background("#20252b")
        if self.preview_textured and self.preview_color_array:
            self.preview.add_mesh(
                self.preview_mesh,
                scalars=self.preview_color_array,
                rgb=True,
                smooth_shading=True,
                show_scalar_bar=False,
            )
            self.preview_mode_label.setText("Affichage : modèle texturé")
            self.preview_mode_button.setText("Afficher le maillage brut")
        else:
            self.preview.add_mesh(
                self.preview_mesh,
                color="#d7a86e",
                smooth_shading=True,
                show_edges=True,
                edge_color="#39424b",
                edge_opacity=0.55,
                line_width=1.0,
            )
            self.preview_mode_label.setText("Affichage : maillage brut avec arêtes")
            self.preview_mode_button.setText("Afficher l’aperçu texturé")
        self.preview.add_axes()
        if reset_camera:
            self.preview.reset_camera()
        elif camera is not None:
            self.preview.camera_position = camera

    def _show_dimensions(self, dimensions, *, scaled: bool) -> None:
        unit = " mm" if scaled else " (unités non calibrées)"
        self.dimensions_label.setText(
            f"Dimensions X × Y × Z : {dimensions[0]:.2f} × "
            f"{dimensions[1]:.2f} × {dimensions[2]:.2f}{unit}"
        )

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(
                self,
                "Traitement en cours",
                "Attendez la fin du traitement avant de fermer Piece2STL.",
            )
            event.ignore()
            return
        self._stop_performance_monitor()
        self.preview.close()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Piece2STL")
    app.setOrganizationName("Piece2STL")
    icon_path = PROJECT_ROOT / "assets" / "piece2stl.ico"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyle("Fusion")
    app.setStyleSheet(
        """
        QMainWindow, QDialog, QScrollArea, QWidget { background: #11161d; color: #edf3f8; font-family: 'Segoe UI'; font-size: 10pt; }
        QMenuBar { background: #0d1218; padding: 4px; }
        QMenuBar::item:selected, QMenu::item:selected { background: #235d56; }
        QMenu { background: #17202a; border: 1px solid #31404d; padding: 5px; }
        QGroupBox { border: 1px solid #2d3a45; border-radius: 10px; margin-top: 14px; padding: 14px 12px 10px; font-weight: 600; background: #171d24; }
        QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: #dce7ef; }
        QLineEdit, QComboBox, QSpinBox, QPlainTextEdit { background: #202832; border: 1px solid #3a4855; border-radius: 6px; padding: 7px; selection-background-color: #288b78; }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #42c5a3; }
        QPushButton { background: #293541; border: 1px solid #435361; border-radius: 7px; padding: 8px 13px; font-weight: 600; }
        QPushButton:hover { background: #344452; border-color: #59c9ad; }
        QPushButton:pressed { background: #1d7567; }
        QPushButton:disabled { color: #697680; background: #1c242c; border-color: #2b343d; }
        QPushButton#primaryButton { background: #19856f; border-color: #45c6a8; font-size: 11pt; }
        QRadioButton#sourceChoice { background: #202933; border: 1px solid #354554; border-radius: 10px; padding: 11px 14px; font-weight: 600; }
        QRadioButton#sourceChoice:hover { border-color: #4cbca2; background: #25323d; }
        QRadioButton#sourceChoice:checked { background: #173d39; border: 2px solid #48c9aa; }
        QRadioButton#sourceChoice::indicator { width: 16px; height: 16px; }
        QProgressBar { border: 1px solid #3b4b57; border-radius: 7px; background: #202832; text-align: center; min-height: 22px; }
        QProgressBar::chunk { background: #36ad7b; border-radius: 6px; }
        QLabel#mutedText { color: #97a7b5; font-size: 9pt; }
        QLabel#metricPill { background: #202a33; border: 1px solid #344553; border-radius: 7px; padding: 8px; color: #b8ddd4; }
        QToolTip { background: #202832; color: #edf3f8; border: 1px solid #4b5b68; }
        """
    )
    window = MainWindow()
    window.start_button.setObjectName("primaryButton")
    window.start_button.style().unpolish(window.start_button)
    window.start_button.style().polish(window.start_button)
    settings = QSettings()
    if (
        not settings.value("firstLaunch/hardwareScanComplete", False, type=bool)
        and not bool(os.environ.get("PIECE2STL_SKIP_FIRST_RUN"))
    ):
        HardwareScanDialog(window).exec()
        settings.setValue("firstLaunch/hardwareScanComplete", True)
    window.show()
    return app.exec()
