import subprocess
import queue
import threading
import os
from pathlib import Path
from typing import Callable, Optional, Sequence, Union

LogCallback = Callable[[str], None]
CancelCallback = Callable[[], bool]
ProgressCallback = Callable[[int, str], None]


class CancellationError(RuntimeError):
    pass


class CommandError(RuntimeError):
    def __init__(self, args: Sequence[str], returncode: int, tail: str):
        super().__init__(
            f"Commande échouée (code {returncode}): {' '.join(args)}\n--- fin de sortie ---\n{tail}"
        )
        self.args_ran = list(args)
        self.returncode = returncode


def hidden_process_kwargs() -> dict:
    """Options Windows empêchant toute console enfant de devenir visible."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def run_command(
    args: Sequence[Union[str, Path]],
    cwd: Optional[Path] = None,
    log: Optional[LogCallback] = None,
    cancel: Optional[CancelCallback] = None,
) -> None:
    str_args = [str(a) for a in args]
    log_fn = log or (lambda line: print(line))
    log_fn(f"$ {' '.join(str_args)}")

    process = subprocess.Popen(
        str_args,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        **hidden_process_kwargs(),
    )

    output_queue: queue.Queue[str | None] = queue.Queue()
    assert process.stdout is not None

    def read_output() -> None:
        try:
            for output_line in process.stdout:
                output_queue.put(output_line)
        finally:
            output_queue.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()

    tail_lines: list[str] = []
    output_closed = False
    while process.poll() is None or not output_closed:
        if cancel and cancel():
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    **hidden_process_kwargs(),
                )
            else:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            process.wait()
            reader.join(timeout=1)
            process.stdout.close()
            raise CancellationError("Traitement annulé par l’utilisateur.")
        try:
            queued_line = output_queue.get(timeout=0.1)
        except queue.Empty:
            continue
        if queued_line is None:
            output_closed = True
            continue
        line = queued_line.rstrip("\r\n")
        log_fn(line)
        tail_lines.append(line)
        if len(tail_lines) > 40:
            tail_lines.pop(0)

    returncode = process.wait()
    reader.join(timeout=1)
    process.stdout.close()
    if returncode != 0:
        raise CommandError(str_args, returncode, "\n".join(tail_lines))
