from __future__ import annotations

from dataclasses import dataclass
import ctypes
from functools import lru_cache
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

from .pipeline.process import hidden_process_kwargs


@dataclass(frozen=True)
class GPUInfo:
    name: str
    vram_gb: float
    driver: str
    vendor: str


@dataclass(frozen=True)
class HardwareReport:
    cpu: str
    ram_gb: float
    gpus: tuple[GPUInfo, ...]
    level: str
    title: str
    details: tuple[str, ...]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def memory_status() -> tuple[float, float, float]:
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    total = status.ullTotalPhys / 1024**3
    available = status.ullAvailPhys / 1024**3
    return total, total - available, available


def _registry_vram() -> dict[str, float]:
    if sys.platform != "win32":
        return {}
    import winreg
    values: dict[str, float] = {}
    root_path = r"SYSTEM\CurrentControlSet\Control\Video"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root_path)
    except OSError:
        return values
    with root:
        index = 0
        while True:
            try:
                guid = winreg.EnumKey(root, index)
                index += 1
            except OSError:
                break
            try:
                with winreg.OpenKey(root, guid + r"\0000") as key:
                    raw_name = winreg.QueryValueEx(key, "HardwareInformation.AdapterString")[0]
                    if isinstance(raw_name, bytes):
                        name = raw_name.decode("utf-16-le", errors="ignore").rstrip("\x00")
                    else:
                        name = str(raw_name)
                    size = int(winreg.QueryValueEx(key, "HardwareInformation.qwMemorySize")[0])
                    values[name.lower()] = size / 1024**3
            except (OSError, TypeError, ValueError):
                continue
    return values


def detect_gpus() -> tuple[GPUInfo, ...]:
    if sys.platform != "win32":
        return ()
    command = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        **hidden_process_kwargs(),
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return ()
    data = json.loads(completed.stdout)
    rows = data if isinstance(data, list) else [data]
    registry = _registry_vram()
    result: list[GPUInfo] = []
    for row in rows:
        name = str(row.get("Name") or "Carte graphique inconnue")
        lowered = name.lower()
        vendor = "NVIDIA" if "nvidia" in lowered or "geforce" in lowered else (
            "AMD" if "amd" in lowered or "radeon" in lowered else (
                "Intel" if "intel" in lowered or "arc" in lowered else "Autre"
            )
        )
        vram = registry.get(lowered, 0.0)
        if not vram:
            vram = int(row.get("AdapterRAM") or 0) / 1024**3
        result.append(GPUInfo(name, round(vram, 1), str(row.get("DriverVersion") or "inconnu"), vendor))
    return tuple(result)


def analyze_hardware() -> HardwareReport:
    total_ram, _, _ = memory_status()
    cpu = platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "Processeur inconnu")
    gpus = detect_gpus()
    best = max(gpus, key=lambda gpu: gpu.vram_gb, default=None)
    limitations: list[str] = []
    compatible_gpu = False
    if best:
        name = best.name.lower()
        if best.vendor == "NVIDIA":
            compatible_gpu = "rtx" in name and best.vram_gb >= 6
            if "rtx" not in name: limitations.append("Une NVIDIA RTX est recommandée pour CUDA.")
        elif best.vendor == "AMD":
            match = re.search(r"rx\s*(\d{4})", name)
            compatible_gpu = bool(match and int(match.group(1)) >= 6000 and best.vram_gb >= 6)
            if not compatible_gpu: limitations.append("Une AMD Radeon RX 6000 ou plus récente avec 6 Go de VRAM est recommandée.")
        elif best.vendor == "Intel":
            compatible_gpu = "arc" in name and best.vram_gb >= 6
            if not compatible_gpu: limitations.append("Une Intel Arc avec 6 Go de VRAM est recommandée pour XPU.")
        else:
            limitations.append("Le GPU n’est pas reconnu pour l’accélération locale ; le mode CPU et Meshy Cloud restent disponibles.")
        if best.vram_gb < 6:
            limitations.append(f"VRAM détectée : {best.vram_gb:.1f} Go ; 6 Go minimum, 10 Go conseillés.")
    else:
        limitations.append("Aucune carte graphique détectée ; le calcul local utilisera le processeur.")
    if total_ram < 8:
        limitations.append(f"RAM détectée : {total_ram:.1f} Go ; 8 Go minimum.")
    elif total_ram < 16:
        limitations.append(f"RAM détectée : {total_ram:.1f} Go ; 16 Go sont conseillés.")
    if total_ram < 8:
        level, title = "incompatible", "Configuration insuffisante pour le mode local"
    elif compatible_gpu and total_ram >= 16:
        level, title = "compatible", "Configuration compatible"
    else:
        level, title = "limited", "Compatible avec limitations"
    details = [f"CPU : {cpu}", f"RAM : {total_ram:.1f} Go"]
    details.extend(f"GPU : {g.name} — {g.vram_gb:.1f} Go — pilote {g.driver}" for g in gpus)
    details.extend(limitations or ["Le mode IA local peut utiliser l’accélération GPU en haute qualité."])
    return HardwareReport(cpu, round(total_ram, 1), gpus, level, title, tuple(details))


def _valid_temperature(value: float) -> float | None:
    return value if 0.0 < value < 150.0 else None


def _parse_temperature_text(text: str) -> float | None:
    patterns = (
        r'"(?:temperature|edge|junction|hotspot)[^"]*"\s*:\s*"?(-?\d+(?:\.\d+)?)',
        r"(?:temperature|edge|junction|hotspot)[^\d-]{0,40}(-?\d+(?:\.\d+)?)\s*°?c?",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = _valid_temperature(float(match.group(1)))
            if value is not None:
                return value
    return None


@lru_cache(maxsize=1)
def _find_amd_smi() -> str | None:
    executable = shutil_which("amd-smi") or shutil_which("amd-smi.exe")
    if executable:
        return executable
    roots = [Path(r"C:\Program Files\AMD\ROCm"), Path(r"C:\Program Files\AMD")]
    for root in roots:
        if root.is_dir():
            try:
                return str(next(root.glob("**/amd-smi.exe")))
            except StopIteration:
                pass
    return None


def _query_amd_temperature() -> float | None:
    executable = _find_amd_smi()
    if not executable:
        return None
    commands = (
        [executable, "monitor", "--temperature", "--json"],
        [executable, "--rocm-smi"],
    )
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=6,
                **hidden_process_kwargs(),
            )
            value = _parse_temperature_text(completed.stdout)
            if completed.returncode == 0 and value is not None:
                return value
        except Exception:
            continue
    return None


def _query_monitor_provider_temperature() -> float | None:
    """Utilise Libre/OpenHardwareMonitor lorsqu'un fournisseur WMI est actif."""
    if sys.platform != "win32":
        return None
    script = (
        "$namespaces=@('root/LibreHardwareMonitor','root/OpenHardwareMonitor');"
        "foreach($ns in $namespaces){try{$s=Get-CimInstance -Namespace $ns -ClassName Sensor -ErrorAction Stop | "
        "Where-Object {$_.SensorType -eq 'Temperature' -and ($_.Name -match 'GPU|Core|Hot Spot|Junction')} | "
        "Select-Object -First 1;if($s){Write-Output $s.Value;exit 0}}catch{}};exit 1"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=6,
            **hidden_process_kwargs(),
        )
        if completed.returncode == 0:
            return _valid_temperature(float(completed.stdout.strip().replace(",", ".")))
    except Exception:
        pass
    return None


def sample_performance(gpu: GPUInfo | None = None) -> dict[str, str | None]:
    total, used, _ = memory_status()
    result: dict[str, str | None] = {
        "ram": f"{used:.1f} / {total:.1f} Go",
        "gpu": "—",
        "vram": "—",
        "temperature": None,
    }
    if gpu:
        result["vram"] = f"— / {gpu.vram_gb:.1f} Go" if gpu.vram_gb else "—"
    executable = shutil_which("nvidia-smi")
    if gpu and gpu.vendor == "NVIDIA" and executable:
        try:
            completed = subprocess.run(
                [executable, "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, **hidden_process_kwargs(),
            )
            load, mem_used, mem_total, temp = [value.strip() for value in completed.stdout.splitlines()[0].split(",")]
            temperature = _valid_temperature(float(temp))
            result.update(
                gpu=f"{load} %",
                vram=f"{int(mem_used)/1024:.1f} / {int(mem_total)/1024:.1f} Go",
                temperature=f"{temperature:g} °C" if temperature is not None else None,
            )
        except Exception:
            pass
    elif gpu and sys.platform == "win32":
        # Compteurs Windows communs à AMD, Intel et NVIDIA. La somme est
        # plafonnée à 100 %, car plusieurs moteurs (3D/copie/compute) peuvent
        # travailler simultanément.
        script = (
            "$u=(Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples | "
            "Measure-Object CookedValue -Sum; "
            "$m=(Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage' -ErrorAction SilentlyContinue).CounterSamples | "
            "Measure-Object CookedValue -Sum; "
            "Write-Output ([math]::Min(100,[math]::Round($u.Sum,0)).ToString()+'|'+[math]::Round($m.Sum/1GB,1).ToString([Globalization.CultureInfo]::InvariantCulture))"
        )
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=8, **hidden_process_kwargs(),
            )
            load, memory = completed.stdout.strip().split("|", 1)
            result["gpu"] = f"{load} %"
            result["vram"] = f"{float(memory):.1f} / {gpu.vram_gb:.1f} Go"
        except Exception:
            pass
        temperature = _query_amd_temperature() if gpu.vendor == "AMD" else None
        temperature = temperature or _query_monitor_provider_temperature()
        if temperature is not None:
            result["temperature"] = f"{temperature:g} °C"
    return result


def shutil_which(name: str) -> str | None:
    from shutil import which
    return which(name)
