from __future__ import annotations

import ctypes
import importlib
import os
import runpy
import sys
import tempfile
import traceback
from pathlib import Path

APP_TITLE = "cURLsender Qt V2"
ENTRY_ENV_VAR = "CURLSENDER_QT_ENTRY"
ENTRY_CANDIDATES = (
    "curlsender_qt.py",
    "curlsender_qt_main.py",
    "curlsender_v2.py",
)
MIN_PYTHON = (3, 10)
MB_OK = 0x0
MB_ICONERROR = 0x10


def show_message(title: str, body: str, flags: int = MB_ICONERROR) -> None:
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(None, body, title, MB_OK | flags)
            return
        except Exception:
            pass
    sys.stderr.write(f"{title}\n{body}\n")


def resolve_entry(script_dir: Path) -> Path:
    override = os.environ.get(ENTRY_ENV_VAR, "").strip()
    if override:
        entry = Path(override)
        if not entry.is_absolute():
            entry = script_dir / entry
        return entry.resolve()

    for candidate in ENTRY_CANDIDATES:
        entry = (script_dir / candidate).resolve()
        if entry.is_file():
            return entry

    return (script_dir / ENTRY_CANDIDATES[0]).resolve()


def ensure_supported_python() -> None:
    if sys.version_info >= MIN_PYTHON:
        return

    required = ".".join(str(part) for part in MIN_PYTHON)
    current = ".".join(str(part) for part in sys.version_info[:3])
    show_message(
        APP_TITLE,
        "A V2 em Qt precisa de uma versao mais nova do Python.\n\n"
        f"Versao atual: {current}\n"
        f"Versao minima: {required}\n\n"
        "Instale um Python mais recente ou ajuste a virtualenv usada pelo launcher.",
    )
    raise SystemExit(1)


def ensure_pyside6_available(script_dir: Path) -> None:
    try:
        importlib.import_module("PySide6")
        importlib.import_module("PySide6.QtWidgets")
    except Exception:
        requirements_path = script_dir / "requirements-qt.txt"
        python_cmd = sys.executable or "py -3"
        if " " in python_cmd:
            python_cmd = f'"{python_cmd}"'
        show_message(
            APP_TITLE,
            "PySide6 nao esta disponivel nesta instalacao do Python.\n\n"
            "Instale as dependencias da V2 com:\n"
            f"  {python_cmd} -m pip install -r \"{requirements_path}\"\n\n"
            "Se voce estiver usando uma virtualenv local, ative-a antes da instalacao.",
        )
        raise SystemExit(1)


def write_crash_log() -> Path:
    log_path = Path(tempfile.gettempdir()) / "curlsender-qt-bootstrap-error.txt"
    log_path.write_text(traceback.format_exc(), encoding="utf-8")
    return log_path


def main() -> None:
    ensure_supported_python()

    script_dir = Path(__file__).resolve().parent
    os.chdir(script_dir)

    entry_path = resolve_entry(script_dir)
    if entry_path == Path(__file__).resolve():
        show_message(
            APP_TITLE,
            "O bootstrap Qt nao pode apontar para ele mesmo.\n\n"
            f"Revise a variavel de ambiente {ENTRY_ENV_VAR} ou adicione o entrypoint real da V2.",
        )
        raise SystemExit(1)

    if not entry_path.is_file():
        candidates = "\n".join(f"  - {name}" for name in ENTRY_CANDIDATES)
        show_message(
            APP_TITLE,
            "A infraestrutura de inicializacao da V2 esta pronta, mas o entrypoint Qt ainda nao foi encontrado.\n\n"
            f"Procurei por:\n{candidates}\n\n"
            f"Voce tambem pode definir {ENTRY_ENV_VAR} com um caminho relativo ou absoluto para o arquivo da V2.",
        )
        raise SystemExit(1)

    ensure_pyside6_available(script_dir)

    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    sys.argv = [str(entry_path), *sys.argv[1:]]

    try:
        runpy.run_path(str(entry_path), run_name="__main__")
    except SystemExit:
        raise
    except Exception:
        log_path = write_crash_log()
        show_message(
            APP_TITLE,
            "A V2 em Qt encontrou um erro ao iniciar.\n\n"
            f"Detalhes tecnicos foram gravados em:\n{log_path}",
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
