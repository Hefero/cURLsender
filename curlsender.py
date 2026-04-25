from __future__ import annotations

import sys

# Startup guards — run before any PySide6 import so errors are user-friendly
if sys.version_info < (3, 10):
    import ctypes as _ctypes, os as _os
    _ver = ".".join(str(x) for x in sys.version_info[:3])
    _msg = f"cURLsender requires Python 3.10 or newer.\n\nFound: {_ver}\n\nDownload a newer Python from python.org."
    if _os.name == "nt":
        try:
            _ctypes.windll.user32.MessageBoxW(None, _msg, "cURLsender", 0x10)
        except Exception:
            pass
    else:
        print(_msg, file=sys.stderr)
    sys.exit(1)

try:
    import PySide6  # noqa: F401
except ImportError:
    import ctypes as _ctypes, os as _os
    _py = sys.executable or "py -3"
    _msg = f"PySide6 is not installed.\n\nRun:\n  {_py} -m pip install PySide6"
    if _os.name == "nt":
        try:
            _ctypes.windll.user32.MessageBoxW(None, _msg, "cURLsender", 0x10)
        except Exception:
            pass
    else:
        print(_msg, file=sys.stderr)
    sys.exit(1)

import codecs
import ctypes
import json
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Collection, Iterable, Mapping
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSettings, QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QFont,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
    QShortcut,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOption,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

CONTINUATION_RE = re.compile(r"[\\^`]\r?\n")
GEOMETRY_RE = re.compile(r"\d+x\d+\+-?\d+\+-?\d+")

CACHE_FILE = Path.home() / ".curlsender_last.txt"
PREFS_FILE = Path.home() / ".curlsender_prefs.json"
DEFAULT_GEOMETRY = "1220x820"
DEFAULT_THEME = "dark"

HEADER_FLAGS = {"-H", "--header"}
DATA_FLAGS = {
    "-d", "--data", "--data-ascii", "--data-binary", "--data-raw",
    "--data-urlencode", "--json", "-F", "--form",
}
SENSITIVE_HEADER_PREFIXES = ("authorization:", "cookie:", "x-api-key:", "proxy-authorization:")


def normalize_command(text: str) -> str:
    return CONTINUATION_RE.sub(" ", text).strip()


def find_unclosed_quote_line(text: str) -> int | None:
    in_single = False
    in_double = False
    open_line: int | None = None
    line = 1
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if in_single:
            if ch == "'":
                in_single = False
                open_line = None
            i += 1
            continue
        if in_double:
            if ch == "\\" and i + 1 < n:
                if text[i + 1] == "\n":
                    line += 1
                i += 2
                continue
            if ch == '"':
                in_double = False
                open_line = None
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            if text[i + 1] == "\n":
                line += 1
            i += 2
            continue
        if ch == "'":
            in_single = True
            open_line = line
        elif ch == '"':
            in_double = True
            open_line = line
        i += 1
    return open_line if (in_single or in_double) else None


def _option_value(token: str, flag: str) -> str | None:
    prefix = f"{flag}="
    if token.startswith(prefix):
        return token[len(prefix):]
    return None


def analyze_command(raw: str) -> dict[str, object]:
    normalized = normalize_command(raw)
    analysis: dict[str, object] = {
        "raw": raw, "normalized": normalized, "has_command": bool(normalized),
        "valid": False, "error": None, "error_line": None, "tokens": [], "args": [],
        "method": "GET", "host": "Awaiting URL", "header_count": 0, "has_body": False,
        "has_output": False, "output_target": None, "has_verbose": False, "has_auth": False,
        "is_curl": False, "chip_texts": [],
        "detail_text": "Paste a curl command to populate the preflight.", "warning_count": 0,
    }

    if not normalized:
        return analysis

    try:
        tokens = shlex.split(normalized, posix=True)
    except ValueError as exc:
        line_hint = find_unclosed_quote_line(raw)
        detail = f"Preflight blocked: {exc}"
        if line_hint is not None:
            detail = f"{detail} (quote opens on line {line_hint})"
        analysis["error"] = str(exc)
        analysis["error_line"] = line_hint
        analysis["detail_text"] = detail
        return analysis

    analysis["tokens"] = tokens
    args = tokens[1:] if tokens and tokens[0].lower() == "curl" else tokens[:]
    analysis["is_curl"] = bool(tokens and tokens[0].lower() == "curl")
    analysis["args"] = args

    if not args:
        analysis["detail_text"] = "No arguments were found after 'curl'."
        return analysis

    method = None
    header_count = 0
    has_body = False
    has_output = False
    output_target = None
    has_verbose = False
    has_auth = False
    sensitive_count = 0
    url = None
    i = 0

    while i < len(args):
        token = args[i]
        next_token = args[i + 1] if i + 1 < len(args) else None

        inline_method = _option_value(token, "--request")
        inline_header = _option_value(token, "--header")
        inline_output = _option_value(token, "--output")
        inline_url = _option_value(token, "--url")

        if token in ("-X", "--request"):
            if next_token:
                method = next_token.upper()
                i += 2
                continue
        elif inline_method:
            method = inline_method.upper()
        elif token in ("-I", "--head"):
            method = "HEAD"
        elif token in HEADER_FLAGS:
            if next_token:
                header_count += 1
                if next_token.lower().startswith(SENSITIVE_HEADER_PREFIXES):
                    has_auth = True
                    sensitive_count += 1
                i += 2
                continue
        elif inline_header:
            header_count += 1
            if inline_header.lower().startswith(SENSITIVE_HEADER_PREFIXES):
                has_auth = True
                sensitive_count += 1
        elif token in DATA_FLAGS:
            has_body = True
            i += 2 if next_token else 1
            continue
        elif any(token.startswith(f"{flag}=") for flag in DATA_FLAGS if flag.startswith("--")):
            has_body = True
        elif token in ("-o", "--output"):
            has_output = True
            output_target = next_token
            i += 2 if next_token else 1
            continue
        elif inline_output:
            has_output = True
            output_target = inline_output
        elif token == "-O":
            has_output = True
            output_target = "remote name"
        elif token in ("-v", "--verbose"):
            has_verbose = True
        elif token == "--url":
            if next_token:
                url = next_token
                i += 2
                continue
        elif inline_url:
            url = inline_url
        elif token.startswith(("http://", "https://")) and url is None:
            url = token
        elif not token.startswith("-") and url is None:
            if "." in token or "/" in token:
                url = token
        i += 1

    if method is None:
        method = "POST" if has_body else "GET"

    host = "Awaiting URL"
    if url:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = parsed.netloc or parsed.path.split("/")[0] or "Awaiting URL"

    chips = [method]
    if host != "Awaiting URL":
        chips.append(host)
    if header_count:
        chips.append(f"{header_count} header{'s' if header_count != 1 else ''}")
    if has_body:
        chips.append("Body detected")
    if has_output:
        chips.append("Output file")
    if has_auth:
        chips.append("Sensitive header")
    if has_verbose:
        chips.append("Verbose")

    detail_parts = [f"{len(args)} arg{'s' if len(args) != 1 else ''} ready"]
    if has_output and output_target:
        detail_parts.append(f"writes to {output_target}")
    if sensitive_count:
        detail_parts.append(
            f"{sensitive_count} sensitive header{'s' if sensitive_count != 1 else ''} will be cached locally"
        )

    analysis.update({
        "valid": True, "args": args, "method": method, "host": host,
        "header_count": header_count, "has_body": has_body, "has_output": has_output,
        "output_target": output_target, "has_verbose": has_verbose, "has_auth": has_auth,
        "warning_count": sensitive_count, "chip_texts": chips[:5],
        "detail_text": " | ".join(detail_parts),
    })
    return analysis


def load_preferences_data(prefs_file: Path = PREFS_FILE) -> dict[str, object]:
    try:
        data = json.loads(prefs_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_preferences_data(data: Mapping[str, object], prefs_file: Path = PREFS_FILE) -> None:
    try:
        prefs_file.write_text(json.dumps(dict(data), indent=2), encoding="utf-8")
    except OSError:
        pass


def load_session_data(prefs_file: Path = PREFS_FILE) -> dict[str, object]:
    try:
        prefs = load_preferences_data(prefs_file)
        return prefs.get("session_data", {}) if isinstance(prefs.get("session_data"), dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_session_data(session: Mapping[str, object], prefs_file: Path = PREFS_FILE) -> None:
    try:
        prefs = load_preferences_data(prefs_file)
        prefs["session_data"] = dict(session)
        save_preferences_data(prefs, prefs_file)
    except OSError:
        pass


def read_cached_command(cache_file: Path = CACHE_FILE) -> str:
    try:
        return cache_file.read_text(encoding="utf-8")
    except OSError:
        return ""


def write_cached_command(raw: str, cache_file: Path = CACHE_FILE) -> None:
    try:
        cache_file.write_text(raw, encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, *, h_spacing: int = 8, v_spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def addItems(self, widgets: Iterable[QWidget]) -> None:
        for widget in widgets:
            self.addWidget(widget)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = effective.x(), effective.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if line_height > 0 and next_x - self._h_spacing > effective.right() + 1:
                x = effective.x()
                y += line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return max(y + line_height - rect.y() + margins.bottom(), 0)


class _LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        self._editor.paint_line_number_area(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._line_number_area = _LineNumberArea(self)
        self._colors: dict[str, str] = {
            "editor_bg": "#0d1115", "editor_fg": "#d9e2e8",
            "gutter_bg": "#11181d", "gutter_fg": "#5d7180",
            "focus": "#5f9eff", "select_bg": "#32757f", "select_fg": "#0a1416",
        }
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.verticalScrollBar().rangeChanged.connect(self._sync_scrollbar_visibility)
        self.update_line_number_area_width(0)
        self.highlight_current_line()
        self._sync_scrollbar_visibility(0, 0)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" " * 4))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def line_number_area_width(self) -> int:
        return 20 + self.fontMetrics().horizontalAdvance("9") * len(str(max(1, self.blockCount())))

    def update_line_number_area_width(self, _block_count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def _sync_scrollbar_visibility(self, minimum: int, maximum: int) -> None:
        self.verticalScrollBar().setVisible(maximum > minimum)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        contents = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(contents.left(), contents.top(), self.line_number_area_width(), contents.height())
        )

    def paint_line_number_area(self, event) -> None:
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor(self._colors["gutter_bg"]))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current_line = self.textCursor().blockNumber()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                color = QColor(self._colors["editor_fg"] if block_number == current_line else self._colors["gutter_fg"])
                painter.setPen(color)
                painter.drawText(
                    0, top, self._line_number_area.width() - 10,
                    self.fontMetrics().height(), Qt.AlignmentFlag.AlignRight, str(block_number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self) -> None:
        if self.isReadOnly():
            self.setExtraSelections([])
            return
        selection = QTextEdit.ExtraSelection()
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.format.setBackground(QColor(self._colors["focus"]).lighter(130))
        selection.format.setForeground(QColor(self._colors["editor_fg"]))
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    def apply_theme(self, colors: dict[str, str]) -> None:
        self._colors = {**self._colors, **colors}
        self._line_number_area.update()
        self.highlight_current_line()
        self.setStyleSheet(
            "QPlainTextEdit {"
            f"background: {self._colors['editor_bg']}; color: {self._colors['editor_fg']};"
            "border: none; padding: 14px 16px 14px 0;"
            f"selection-background-color: {self._colors['select_bg']};"
            f"selection-color: {self._colors['select_fg']};"
            "}"
        )
        self.viewport().update()


class PaintableWidget(QWidget):
    def paintEvent(self, event) -> None:  # type: ignore[override]
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, self)
        super().paintEvent(event)


# ---------------------------------------------------------------------------
# App constants
# ---------------------------------------------------------------------------

_WINDOW_MARGIN = 18
_WINDOW_RADIUS = 30
_CARD_RADIUS = 24
_RESIZE_MARGIN = 8
_MIN_WINDOW_SIZE = QSize(1040, 720)
_DEFAULT_WINDOW_SIZE = QSize(1220, 820)
_SETTINGS_ORGANIZATION = "cURLsender"
_SETTINGS_APPLICATION = "ConsoleSignal"
_APP_ID = "cURLsender.App"
_IS_WINDOWS = sys.platform.startswith("win")

_THEMES = {
    "dark": {
        "window_bg": "#11161a", "shell_bg": "#151c21", "shell_border": "#28333b",
        "card_bg": "#1b242b", "card_alt_bg": "#202a31", "card_border": "#2f3b44",
        "metric_bg": "#243039", "text": "#eff3f6", "muted": "#99a7b5",
        "accent": "#3db497", "accent_hover": "#4bc4a7", "accent_text": "#071512",
        "secondary_bg": "#24343c", "secondary_hover": "#2c4049", "secondary_text": "#d5edf1",
        "ghost_bg": "#202930", "ghost_hover": "#28333b", "ghost_text": "#eff3f6",
        "editor_bg": "#0d1115", "editor_fg": "#d9e2e8",
        "output_bg": "#0b0f13", "output_fg": "#dce4ea",
        "gutter_bg": "#11181d", "gutter_fg": "#5d7180",
        "select_bg": "#32757f", "select_fg": "#0a1416", "focus": "#5f9eff",
        "good_bg": "#17362d", "good_fg": "#7ee2a8",
        "warn_bg": "#3e3217", "warn_fg": "#ffd07d",
        "bad_bg": "#422022", "bad_fg": "#ff9898",
        "chip_bg": "#18343c", "chip_fg": "#9fe5f0",
        "badge_bg": "#18343c", "badge_fg": "#d5edf1",
        "shadow": "#0c1014",
        "titlebar_btn_bg": "#202930", "titlebar_btn_hover": "#2a353d",
        "titlebar_btn_fg": "#d5edf1", "titlebar_close_hover": "#6b2f36",
        "find_match_bg": "#245c61", "find_current_bg": "#3db497", "find_current_fg": "#071512",
        "logo_start": "#3db497", "logo_end": "#5f9eff",
    },
    "light": {
        "window_bg": "#ece4d4", "shell_bg": "#f6efdf", "shell_border": "#d8cfc0",
        "card_bg": "#fff9f1", "card_alt_bg": "#fffdf8", "card_border": "#d9cfbe",
        "metric_bg": "#eff7f5", "text": "#1f2429", "muted": "#697482",
        "accent": "#135d66", "accent_hover": "#197481", "accent_text": "#ffffff",
        "secondary_bg": "#d8ecef", "secondary_hover": "#cce5e8", "secondary_text": "#135d66",
        "ghost_bg": "#ebe4d7", "ghost_hover": "#e0d7c9", "ghost_text": "#1f2429",
        "editor_bg": "#11161a", "editor_fg": "#d9e2e8",
        "output_bg": "#10161a", "output_fg": "#dce4ea",
        "gutter_bg": "#171d22", "gutter_fg": "#6a7b88",
        "select_bg": "#32757f", "select_fg": "#0a1416", "focus": "#32757f",
        "good_bg": "#d9f0e2", "good_fg": "#1d7348",
        "warn_bg": "#f6ead2", "warn_fg": "#9a620f",
        "bad_bg": "#f5dada", "bad_fg": "#9f3d3d",
        "chip_bg": "#e3f1f3", "chip_fg": "#135d66",
        "badge_bg": "#e3f1f3", "badge_fg": "#135d66",
        "shadow": "#d5cab8",
        "titlebar_btn_bg": "#ebe4d7", "titlebar_btn_hover": "#e0d7c9",
        "titlebar_btn_fg": "#1f2429", "titlebar_close_hover": "#e9c9c9",
        "find_match_bg": "#d8ecef", "find_current_bg": "#135d66", "find_current_fg": "#ffffff",
        "logo_start": "#135d66", "logo_end": "#3f90a0",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_app_user_model_id(app_id: str) -> None:
    if not _IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except OSError:
        pass


def _build_app_icon(theme_name: str = DEFAULT_THEME) -> QIcon:
    colors = _THEMES[theme_name]
    pixmap = QPixmap(128, 128)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(8, 8, 112, 112)
    path = QPainterPath()
    path.addRoundedRect(rect, 32, 32)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0.0, QColor(colors["logo_start"]))
    gradient.setColorAt(1.0, QColor(colors["logo_end"]))
    painter.fillPath(path, gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    inset = QRectF(28, 28, 72, 72)
    inner = QPainterPath()
    inner.addRoundedRect(inset, 24, 24)
    painter.fillPath(inner, QColor(255, 255, 255, 32))
    painter.setFont(QFont("Segoe UI", 58, QFont.Weight.Black))
    painter.setPen(QColor("#ffffff"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "c")
    painter.end()
    return QIcon(pixmap)


def _format_rate(byte_count: int, seconds: float | None) -> str:
    if not seconds or seconds <= 0 or byte_count <= 0:
        return "-"
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    rate = byte_count / seconds
    i = 0
    while rate >= 1024 and i < len(units) - 1:
        rate /= 1024
        i += 1
    return f"{rate:.{1 if rate < 10 and i > 0 else 0}f} {units[i]}"


def _font_stack(size: int, *, monospace: bool = False, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont("Cascadia Code" if monospace else "Segoe UI", size)
    font.setWeight(weight)
    return font


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class CurlRunWorker(QObject):
    chunk = Signal(str, int)
    failed = Signal(str)
    finished = Signal(int, float, bool, int)

    def __init__(self, args: list[str]) -> None:
        super().__init__()
        self._args = args
        self._proc: subprocess.Popen[bytes] | None = None
        self._cancel_requested = False

    @Slot()
    def run(self) -> None:
        started_at = time.monotonic()
        try:
            self._proc = subprocess.Popen(
                ["curl", *self._args],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=False, bufsize=0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError:
            self.failed.emit("'curl' not found on PATH. Windows 10 (1803+) and Windows 11 ship curl.exe in System32.")
            return
        except OSError as exc:
            self.failed.emit(str(exc))
            return

        assert self._proc.stdout is not None
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        total_bytes = 0

        while True:
            if self._cancel_requested and self._proc.poll() is None:
                try:
                    self._proc.terminate()
                except OSError:
                    pass
            try:
                chunk = self._proc.stdout.read1(4096)  # type: ignore[attr-defined]
            except AttributeError:
                chunk = self._proc.stdout.read(4096)
            if chunk:
                total_bytes += len(chunk)
                decoded = decoder.decode(chunk)
                if decoded:
                    self.chunk.emit(decoded, len(chunk))
                continue
            return_code = self._proc.poll()
            if return_code is not None:
                tail = decoder.decode(b"", final=True)
                if tail:
                    total_bytes += len(tail.encode("utf-8", errors="replace"))
                    self.chunk.emit(tail, len(tail.encode("utf-8", errors="replace")))
                self.finished.emit(return_code, time.monotonic() - started_at,
                                   self._cancel_requested and return_code != 0, total_bytes)
                return
            time.sleep(0.02)

    def request_cancel(self) -> None:
        self._cancel_requested = True
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# UI components
# ---------------------------------------------------------------------------

class LogoBadge(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(52, 52)
        self._colors = _THEMES[DEFAULT_THEME]

    def apply_theme(self, colors: dict[str, str]) -> None:
        self._colors = colors
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(self._colors["logo_start"]))
        gradient.setColorAt(1.0, QColor(self._colors["logo_end"]))
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        painter.fillPath(path, gradient)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 30, QFont.Weight.Black))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "c")
        painter.end()


class TitleBar(PaintableWidget):
    def __init__(self, host: "ConsoleSignalWindow") -> None:
        super().__init__(host)
        self._host = host
        self.setObjectName("TitleBar")

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            if not isinstance(self.childAt(event.position().toPoint()), QPushButton):
                self._host.begin_title_drag(event.globalPosition().toPoint())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._host.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "-") -> None:
        super().__init__()
        self.setProperty("cardRole", "metric")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("MetricTitle")
        self.title_label.setFont(_font_stack(10, weight=QFont.Weight.Medium))
        self.value_label = QLabel(value)
        self.value_label.setObjectName("MetricValue")
        self.value_label.setFont(_font_stack(14, weight=QFont.Weight.Bold))
        self.value_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addStretch(1)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)

    def set_variant(self, variant: str) -> None:
        self.setProperty("variant", variant)
        self.style().unpolish(self)
        self.style().polish(self)


class OutputEditor(CodeEditor):
    def __init__(self, parent: QWidget | None = None) -> None:
        self._highlight_selections: list[QTextEdit.ExtraSelection] = []
        super().__init__(parent)
        self.setReadOnly(True)

    def highlight_current_line(self) -> None:
        self.setExtraSelections(self._highlight_selections)

    def set_highlight_selections(self, selections) -> None:
        self._highlight_selections = list(selections)
        self.setExtraSelections(self._highlight_selections)

    def apply_theme(self, colors: dict[str, str]) -> None:
        self._colors = {**self._colors, **colors}
        self._line_number_area.update()
        self.setStyleSheet(
            "QPlainTextEdit {"
            f"background: {self._colors['output_bg']}; color: {self._colors['output_fg']};"
            "border: none; padding: 14px 16px 14px 0;"
            f"selection-background-color: {self._colors['select_bg']};"
            f"selection-color: {self._colors['select_fg']};"
            "}"
        )
        self.viewport().update()
        self.highlight_current_line()


class ExitDialog(QDialog):
    def __init__(self, parent: QWidget, colors: dict[str, str], *, running: bool) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._colors = colors

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        self.surface = QFrame()
        self.surface.setObjectName("ExitDialogSurface")
        outer.addWidget(self.surface)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(colors["shadow"]))
        self.surface.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(18)

        title = QLabel("Close cURLsender?")
        title.setFont(_font_stack(15, weight=QFont.Weight.Bold))
        layout.addWidget(title)

        body = QLabel(
            "Closing now will cancel the current execution and preserve whatever output has already arrived."
            if running else "You can reopen cURLsender anytime."
        )
        body.setWordWrap(True)
        body.setObjectName("DialogBody")
        body.setFont(_font_stack(11))
        layout.addWidget(body)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        stay_btn = QPushButton("Stay here")
        stay_btn.setProperty("variant", "ghost")
        stay_btn.clicked.connect(self.reject)
        exit_btn = QPushButton("Exit app")
        exit_btn.setProperty("variant", "primary")
        exit_btn.clicked.connect(self.accept)
        buttons.addWidget(stay_btn)
        buttons.addWidget(exit_btn)
        layout.addLayout(buttons)

        self.setStyleSheet(f"""
            QFrame#ExitDialogSurface {{
                background: {colors['card_bg']}; border: 1px solid {colors['card_border']};
                border-radius: {_CARD_RADIUS}px;
            }}
            QLabel {{ color: {colors['text']}; }}
            QLabel#DialogBody {{ color: {colors['muted']}; }}
            QPushButton {{
                border: 1px solid transparent; border-radius: 14px;
                padding: 10px 14px; font: 600 11pt "Segoe UI";
            }}
            QPushButton[variant="primary"] {{ background: {colors['accent']}; color: {colors['accent_text']}; }}
            QPushButton[variant="primary"]:hover {{ background: {colors['accent_hover']}; }}
            QPushButton[variant="ghost"] {{ background: {colors['ghost_bg']}; color: {colors['ghost_text']}; }}
            QPushButton[variant="ghost"]:hover {{ background: {colors['ghost_hover']}; }}
        """)
        self.resize(420, 220)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ring_inset = 10 - 12
        rect = self.rect().adjusted(ring_inset, ring_inset, -ring_inset, -ring_inset)
        painter.setBrush(QColor(self._colors["shell_border"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 34, 34)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class ConsoleSignalWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings(_SETTINGS_ORGANIZATION, _SETTINGS_APPLICATION)
        self.current_theme = self._load_theme_preference()
        self.colors = _THEMES[self.current_theme]
        self.command_analysis = analyze_command("")
        self.command_restored = False
        self.run_state = "idle"
        self.run_started_at: float | None = None
        self.last_elapsed: float | None = None
        self.last_exit_code: int | None = None
        self.cancel_requested = False
        self.auto_scroll = self._load_bool("output/autoScroll", True)
        self._find_positions: list[int] = []
        self._find_index = -1
        self._close_after_finish = False
        self._allow_close = False
        self._worker: CurlRunWorker | None = None
        self._worker_thread: QThread | None = None
        self._bytes_received = 0
        self._drag_origin: QPoint | None = None
        self._drag_start_frame: QPoint | None = None
        self._manual_resize_edges = Qt.Edges()
        self._manual_resize_origin: QPoint | None = None
        self._manual_resize_geometry = self.geometry()

        self.setWindowTitle("cURLsender")
        self.setMinimumSize(_MIN_WINDOW_SIZE)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.installEventFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(150)
        self.elapsed_timer.timeout.connect(self._tick_elapsed)

        self._build_ui()
        self._restore_window()
        self._load_last_command()
        self._restore_session()
        self._apply_theme(self.current_theme, persist=False)
        self._refresh_command_analysis()

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.on_execute)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.on_execute)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.toggle_find_bar)
        QShortcut(QKeySequence("Esc"), self, activated=self.handle_escape)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        if self.isMaximized():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ring_inset = _WINDOW_MARGIN - 16
        rect = self.rect().adjusted(ring_inset, ring_inset, -ring_inset, -ring_inset)
        painter.setBrush(QColor(self.colors["shell_border"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, _WINDOW_RADIUS + 14, _WINDOW_RADIUS + 14)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(_WINDOW_MARGIN, _WINDOW_MARGIN, _WINDOW_MARGIN, _WINDOW_MARGIN)

        self.surface = PaintableWidget()
        self.surface.setObjectName("Surface")
        self.surface.setMouseTracking(True)
        root.addWidget(self.surface)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 14)
        shadow.setColor(QColor(self.colors["shadow"]))
        self.surface.setGraphicsEffect(shadow)
        self._shadow_effect = shadow

        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(26, 26, 26, 26)
        surface_layout.setSpacing(18)

        self.title_bar = TitleBar(self)
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(20, 18, 20, 18)
        title_layout.setSpacing(18)

        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(14)
        self.logo = LogoBadge()
        brand_layout.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignTop)

        brand_text_layout = QVBoxLayout()
        brand_text_layout.setSpacing(4)
        self.brand_title = QLabel("cURLsender / Console Signal")
        self.brand_title.setObjectName("BrandTitle")
        self.brand_title.setFont(_font_stack(18, weight=QFont.Weight.Bold))
        self.brand_subtitle = QLabel("Desktop shell for faithful curl execution with rounded desktop polish.")
        self.brand_subtitle.setObjectName("BrandSubtitle")
        self.brand_subtitle.setFont(_font_stack(11))
        brand_text_layout.addWidget(self.brand_title)
        brand_text_layout.addWidget(self.brand_subtitle)
        brand_layout.addLayout(brand_text_layout, 1)
        title_layout.addLayout(brand_layout, 1)

        header_actions = QHBoxLayout()
        header_actions.setSpacing(10)
        self.theme_btn = QPushButton()
        self.theme_btn.setProperty("variant", "ghost")
        self.theme_btn.clicked.connect(self.toggle_theme)
        self.status_badge = QLabel()
        self.status_badge.setObjectName("StatusBadge")
        self.status_badge.setFixedHeight(34)
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.minimize_btn = QPushButton("_")
        self.minimize_btn.setProperty("titleRole", "minimize")
        self.minimize_btn.clicked.connect(self.showMinimized)
        self.close_btn = QPushButton("X")
        self.close_btn.setProperty("titleRole", "close")
        self.close_btn.clicked.connect(self.request_close)
        for btn in (self.theme_btn, self.minimize_btn, self.close_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        header_actions.addWidget(self.theme_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        header_actions.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        header_actions.addWidget(self.minimize_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        header_actions.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        title_layout.addLayout(header_actions)
        surface_layout.addWidget(self.title_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(18)
        surface_layout.addWidget(body, 1)

        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(18)
        right_column = QWidget()
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(18)
        body_layout.addWidget(left_column, 10)
        body_layout.addWidget(right_column, 11)

        # Command card
        self.command_card = self._create_card("default")
        command_layout = QVBoxLayout(self.command_card)
        command_layout.setContentsMargins(20, 18, 20, 18)
        command_layout.setSpacing(16)
        left_layout.addWidget(self.command_card, 1)
        command_title = QLabel("COMMAND DECK")
        command_title.setObjectName("SectionTitle")
        command_title.setFont(_font_stack(11, weight=QFont.Weight.Bold))
        command_layout.addWidget(command_title)
        self.command_editor = CodeEditor()
        self.command_editor.setFont(_font_stack(11, monospace=True, weight=QFont.Weight.Medium))
        self.command_editor.setLineWrapMode(CodeEditor.LineWrapMode.WidgetWidth)
        self.command_editor.textChanged.connect(self._refresh_command_analysis)
        command_layout.addWidget(self.command_editor, 1)
        self.preflight_wrap = QWidget()
        self.preflight_layout = FlowLayout(self.preflight_wrap, h_spacing=8, v_spacing=8)
        self.preflight_layout.setContentsMargins(0, 0, 0, 0)
        command_layout.addWidget(self.preflight_wrap)
        self.preflight_note = QLabel("Paste a curl command to populate the preflight.")
        self.preflight_note.setObjectName("PreflightNote")
        self.preflight_note.setWordWrap(True)
        self.preflight_note.setFont(_font_stack(10))
        command_layout.addWidget(self.preflight_note)

        # Action card
        self.action_card = self._create_card("alt")
        action_layout = QVBoxLayout(self.action_card)
        action_layout.setContentsMargins(20, 16, 20, 16)
        action_layout.setSpacing(12)
        left_layout.addWidget(self.action_card)
        btn_row_top = QHBoxLayout()
        btn_row_top.setSpacing(10)
        self.execute_btn = QPushButton("Execute")
        self.execute_btn.setProperty("variant", "primary")
        self.execute_btn.clicked.connect(self.on_execute)
        self.validate_btn = QPushButton("Validate only")
        self.validate_btn.setProperty("variant", "secondary")
        self.validate_btn.clicked.connect(self.on_validate)
        btn_row_top.addWidget(self.execute_btn)
        btn_row_top.addWidget(self.validate_btn)
        btn_row_top.addStretch(1)
        action_layout.addLayout(btn_row_top)
        btn_row_bottom = QHBoxLayout()
        btn_row_bottom.setSpacing(10)
        self.clear_output_btn = QPushButton("Clear output")
        self.clear_output_btn.setProperty("variant", "ghost")
        self.clear_output_btn.clicked.connect(self.on_clear_output)
        self.clear_all_btn = QPushButton("Clear all")
        self.clear_all_btn.setProperty("variant", "ghost")
        self.clear_all_btn.clicked.connect(self.on_clear_all)
        btn_row_bottom.addWidget(self.clear_output_btn)
        btn_row_bottom.addWidget(self.clear_all_btn)
        btn_row_bottom.addStretch(1)
        action_layout.addLayout(btn_row_bottom)
        for btn in (self.execute_btn, self.validate_btn, self.clear_output_btn, self.clear_all_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_meta = QLabel("Use Esc to cancel current execution.")
        self.action_meta.setObjectName("ActionMeta")
        self.action_meta.setWordWrap(True)
        self.action_meta.setFont(_font_stack(11))
        action_layout.addWidget(self.action_meta)

        # Summary card
        self.summary_card = self._create_card("default")
        summary_layout = QVBoxLayout(self.summary_card)
        summary_layout.setContentsMargins(20, 18, 20, 18)
        summary_layout.setSpacing(16)
        right_layout.addWidget(self.summary_card)
        summary_title = QLabel("EXECUTION SUMMARY")
        summary_title.setObjectName("SectionTitle")
        summary_title.setFont(_font_stack(11, weight=QFont.Weight.Bold))
        summary_layout.addWidget(summary_title)
        metric_grid = QGridLayout()
        metric_grid.setHorizontalSpacing(14)
        metric_grid.setVerticalSpacing(14)
        summary_layout.addLayout(metric_grid)
        self.metric_status = MetricCard("Status", "Idle")
        self.metric_elapsed = MetricCard("Elapsed", "-")
        self.metric_rate = MetricCard("Rate", "-")
        self.metric_exit = MetricCard("Exit", "No run yet")
        self.metric_cards = [self.metric_status, self.metric_elapsed, self.metric_rate, self.metric_exit]
        for idx, card in enumerate(self.metric_cards):
            metric_grid.addWidget(card, 0, idx)

        # Output card
        self.output_card = self._create_card("default")
        output_layout = QVBoxLayout(self.output_card)
        output_layout.setContentsMargins(20, 18, 20, 18)
        output_layout.setSpacing(14)
        right_layout.addWidget(self.output_card, 1)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self.output_title = QLabel("SIGNAL STREAM")
        self.output_title.setObjectName("SectionTitle")
        self.output_title.setFont(_font_stack(11, weight=QFont.Weight.Bold))
        toolbar.addWidget(self.output_title)
        toolbar.addStretch(1)
        self.find_btn = QPushButton("Find")
        self.find_btn.setProperty("variant", "ghost")
        self.find_btn.setProperty("toolbarRole", True)
        self.find_btn.clicked.connect(self.toggle_find_bar)
        self.jump_btn = QPushButton("Jump to end")
        self.jump_btn.setProperty("variant", "ghost")
        self.jump_btn.setProperty("toolbarRole", True)
        self.jump_btn.clicked.connect(self.jump_to_end)
        self.auto_scroll_btn = QPushButton("Auto-scroll on")
        self.auto_scroll_btn.setProperty("variant", "ghost")
        self.auto_scroll_btn.setProperty("toolbarRole", True)
        self.auto_scroll_btn.clicked.connect(self.toggle_auto_scroll)
        self.copy_btn = QPushButton("Copy output")
        self.copy_btn.setProperty("variant", "ghost")
        self.copy_btn.setProperty("toolbarRole", True)
        self.copy_btn.clicked.connect(self.copy_output)
        for btn in (self.find_btn, self.jump_btn, self.auto_scroll_btn, self.copy_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            toolbar.addWidget(btn)
        output_layout.addLayout(toolbar)

        self.find_bar = QFrame()
        self.find_bar.setObjectName("FindBar")
        self.find_bar.hide()
        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(14, 10, 14, 10)
        find_layout.setSpacing(10)
        self.find_entry = QLineEdit()
        self.find_entry.setPlaceholderText("Find in output")
        self.find_entry.textChanged.connect(self._refresh_find_matches)
        self.find_entry.returnPressed.connect(self.find_next_match)
        self.find_status = QLabel("Type to search")
        self.find_status.setObjectName("FindStatus")
        self.find_prev_btn = QPushButton("Prev")
        self.find_prev_btn.setProperty("variant", "ghost")
        self.find_prev_btn.clicked.connect(self.find_previous_match)
        self.find_next_btn = QPushButton("Next")
        self.find_next_btn.setProperty("variant", "ghost")
        self.find_next_btn.clicked.connect(self.find_next_match)
        self.find_close_btn = QPushButton("Close")
        self.find_close_btn.setProperty("variant", "ghost")
        self.find_close_btn.clicked.connect(self.hide_find_bar)
        for btn in (self.find_prev_btn, self.find_next_btn, self.find_close_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        find_layout.addWidget(self.find_entry, 1)
        find_layout.addWidget(self.find_status)
        find_layout.addWidget(self.find_prev_btn)
        find_layout.addWidget(self.find_next_btn)
        find_layout.addWidget(self.find_close_btn)
        output_layout.addWidget(self.find_bar)

        self.output_editor = OutputEditor()
        self.output_editor.setFont(_font_stack(11, monospace=True, weight=QFont.Weight.Medium))
        self.output_editor.setLineWrapMode(OutputEditor.LineWrapMode.WidgetWidth)
        output_layout.addWidget(self.output_editor, 1)

    def _create_card(self, role: str) -> QFrame:
        card = QFrame()
        card.setProperty("cardRole", role)
        return card

    def _load_theme_preference(self) -> str:
        stored = self.settings.value("ui/theme", DEFAULT_THEME)
        return stored if stored in _THEMES else DEFAULT_THEME

    def _load_bool(self, key: str, default: bool) -> bool:
        value = self.settings.value(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _restore_window(self) -> None:
        geometry = self.settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(_DEFAULT_WINDOW_SIZE)
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                available = screen.availableGeometry()
                self.move(
                    available.x() + (available.width() - self.width()) // 2,
                    available.y() + (available.height() - self.height()) // 2,
                )

    def _save_window_state(self) -> None:
        if not self.isMinimized():
            self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("ui/theme", self.current_theme)
        self.settings.setValue("output/autoScroll", self.auto_scroll)
        self.settings.sync()
        self._save_session()

    def _load_last_command(self) -> None:
        cached = read_cached_command()
        if cached:
            self.command_restored = True
            self.command_editor.blockSignals(True)
            self.command_editor.setPlainText(cached)
            self.command_editor.blockSignals(False)
            self.action_meta.setText("Last command restored from local cache.")
        else:
            default_cmd = (
                'curl -X GET "https://jsonplaceholder.typicode.com/posts/1" \\\n'
                '  -H "User-Agent: cURLsender/2.0" \\\n'
                '  -H "Accept: application/json" \\\n'
                '  -H "X-Custom-Header: Demo-Request" \\\n'
                '  --verbose \\\n'
                '  --connect-timeout 10 \\\n'
                '  --max-time 30 \\\n'
                '  --location \\\n'
                '  --compressed'
            )
            self.command_editor.blockSignals(True)
            self.command_editor.setPlainText(default_cmd)
            self.command_editor.blockSignals(False)
            self.action_meta.setText("Default demo command loaded. Edit and execute or paste your own.")
        self._clear_editor_selections()

    def _save_session(self) -> None:
        save_session_data({
            "command": self.command_editor.toPlainText(),
            "output": self.output_editor.toPlainText() if self.run_state != "idle" else "",
            "auto_scroll": self.auto_scroll,
            "last_exit_code": self.last_exit_code,
        })

    def _clear_editor_selections(self) -> None:
        self.command_editor.setExtraSelections([])
        cursor = self.command_editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.command_editor.setTextCursor(cursor)

    def _restore_session(self) -> None:
        session = load_session_data()
        output = session.get("output", "") if session else ""
        if output and isinstance(output, str):
            self.output_editor.blockSignals(True)
            self.output_editor.setPlainText(output)
            self.output_editor.blockSignals(False)

    def _build_stylesheet(self) -> str:
        c = self.colors
        r = 0 if self.isMaximized() else _WINDOW_RADIUS
        return f"""
        QWidget {{ color: {c['text']}; font: 10pt "Segoe UI"; }}
        QWidget#Surface {{ background: {c['shell_bg']}; border: 1px solid {c['shell_border']}; border-radius: {r}px; }}
        QFrame[cardRole="default"] {{ background: {c['card_bg']}; border: 1px solid {c['card_border']}; border-radius: {_CARD_RADIUS}px; }}
        QFrame[cardRole="alt"] {{ background: {c['card_alt_bg']}; border: 1px solid {c['card_border']}; border-radius: {_CARD_RADIUS}px; }}
        QFrame[cardRole="metric"] {{ background: {c['metric_bg']}; border: 1px solid transparent; border-radius: 20px; }}
        QFrame[cardRole="metric"][variant="good"] {{ border-color: {c['good_fg']}; }}
        QFrame[cardRole="metric"][variant="warn"] {{ border-color: {c['warn_fg']}; }}
        QFrame[cardRole="metric"][variant="bad"] {{ border-color: {c['bad_fg']}; }}
        QWidget#TitleBar {{ background: {c['card_bg']}; border: 1px solid {c['card_border']}; border-radius: {_CARD_RADIUS}px; }}
        QLabel#BrandTitle {{ color: {c['text']}; font: 700 18pt "Segoe UI"; }}
        QLabel#BrandSubtitle, QLabel#PreflightNote, QLabel#ActionMeta, QLabel#FindStatus, QLabel#MetricTitle {{ color: {c['muted']}; }}
        QLabel#SectionTitle {{ color: {c['text']}; letter-spacing: 0.08em; }}
        QLabel#MetricValue {{ color: {c['text']}; }}
        QLabel#StatusBadge {{ background: {c['badge_bg']}; color: {c['badge_fg']}; border: 1px solid transparent; border-radius: 12px; padding: 5px 14px; font: 600 10pt "Segoe UI"; }}
        QLabel#PreflightChip {{ border-radius: 14px; padding: 7px 11px; font: 600 9pt "Segoe UI"; }}
        QLabel#PreflightChip[tone="accent"] {{ background: {c['chip_bg']}; color: {c['chip_fg']}; }}
        QLabel#PreflightChip[tone="warn"] {{ background: {c['warn_bg']}; color: {c['warn_fg']}; }}
        QLabel#PreflightChip[tone="ghost"] {{ background: {c['ghost_bg']}; color: {c['muted']}; }}
        QPushButton {{ border: 1px solid transparent; border-radius: 16px; padding: 9px 16px; font: 600 10pt "Segoe UI"; }}
        QPushButton[variant="primary"] {{ background: {c['accent']}; color: {c['accent_text']}; }}
        QPushButton[variant="primary"]:hover {{ background: {c['accent_hover']}; }}
        QPushButton[variant="secondary"] {{ background: {c['secondary_bg']}; color: {c['secondary_text']}; }}
        QPushButton[variant="secondary"]:hover {{ background: {c['secondary_hover']}; }}
        QPushButton[variant="ghost"] {{ background: {c['ghost_bg']}; color: {c['ghost_text']}; }}
        QPushButton[variant="ghost"]:hover {{ background: {c['ghost_hover']}; }}
        QPushButton[toolbarRole="true"] {{ padding: 6px 12px; font: 600 9pt "Segoe UI"; border-radius: 12px; }}
        QPushButton[titleRole] {{ min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; border-radius: 12px; background: {c['titlebar_btn_bg']}; color: {c['titlebar_btn_fg']}; font: 700 13pt "Segoe UI"; padding: 0; }}
        QPushButton[titleRole]:hover {{ background: {c['titlebar_btn_hover']}; }}
        QPushButton[titleRole="close"]:hover {{ background: {c['titlebar_close_hover']}; }}
        QLineEdit {{ background: {c['editor_bg']}; color: {c['editor_fg']}; border: 1px solid {c['card_border']}; border-radius: 12px; padding: 10px 12px; selection-background-color: {c['select_bg']}; selection-color: {c['select_fg']}; }}
        QFrame#FindBar {{ background: {c['card_alt_bg']}; border: 1px solid {c['card_border']}; border-radius: 16px; }}
        QScrollBar:vertical {{ background: transparent; width: 12px; margin: 8px 0 8px 0; }}
        QScrollBar::handle:vertical {{ background: {c['ghost_bg']}; min-height: 34px; border-radius: 6px; }}
        QScrollBar::handle:vertical:hover {{ background: {c['secondary_bg']}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; height: 0px; }}
        """

    def _apply_theme(self, theme_name: str, *, persist: bool = True) -> None:
        self.current_theme = theme_name if theme_name in _THEMES else DEFAULT_THEME
        self.colors = _THEMES[self.current_theme]
        self.setStyleSheet(self._build_stylesheet())
        self.logo.apply_theme(self.colors)
        self.command_editor.apply_theme(self.colors)
        self.output_editor.apply_theme(self.colors)
        self.theme_btn.setText(f"Theme: {'Light' if self.current_theme == 'dark' else 'Dark'}")
        self._update_status_badge()
        self._render_preflight()
        self._sync_ui_state(force_defaults=True)
        self._refresh_find_matches()
        if self._shadow_effect is not None:
            self._shadow_effect.setColor(QColor(self.colors["shadow"]))
        if persist:
            self.settings.setValue("ui/theme", self.current_theme)

    def toggle_theme(self) -> None:
        self._apply_theme("light" if self.current_theme == "dark" else "dark")

    def _refresh_command_analysis(self) -> None:
        self.command_analysis = analyze_command(self.command_editor.toPlainText())
        self.preflight_note.setText(str(self.command_analysis["detail_text"]))
        self._render_preflight()
        self._sync_ui_state(force_defaults=True)

    def _render_preflight(self) -> None:
        while self.preflight_layout.count():
            item = self.preflight_layout.takeAt(0)
            if item and (w := item.widget()):
                w.deleteLater()

        chip_texts = list(self.command_analysis["chip_texts"])
        if self.command_analysis["has_output"] and "Large transfer risk" not in chip_texts:
            chip_texts.append("Large transfer risk")

        tone = "accent"
        if not chip_texts:
            chip_texts = ["Awaiting input"]
            tone = "ghost"
        if self.command_analysis["has_command"] and not self.command_analysis["valid"]:
            chip_texts = ["Quote check needed"]
            if (line_hint := self.command_analysis["error_line"]) is not None:
                chip_texts.append(f"line {line_hint}")
            tone = "warn"

        for text in chip_texts[:6]:
            label = QLabel(text)
            label.setObjectName("PreflightChip")
            label.setProperty("tone", tone)
            self.preflight_layout.addWidget(label)

    def _status_badge_text(self) -> str:
        mapping = {
            "running": "Streaming", "cancelling": "Cancelling", "cancelled": "Cancelled",
            "parse error": "Parse error", "error": "Error", "done": "Complete",
        }
        if self.run_state in mapping:
            return mapping[self.run_state]
        if self.command_analysis["has_command"] and not self.command_analysis["valid"]:
            return "Warning"
        return "Ready" if self.command_analysis["valid"] else "Idle"

    def _update_status_badge(self) -> None:
        self.status_badge.setText(self._status_badge_text())
        if self.run_state in {"running", "done"}:
            bg, fg = self.colors["good_bg"], self.colors["good_fg"]
        elif self.run_state in {"cancelling", "cancelled", "parse error"}:
            bg, fg = self.colors["warn_bg"], self.colors["warn_fg"]
        elif self.run_state == "error":
            bg, fg = self.colors["bad_bg"], self.colors["bad_fg"]
        else:
            bg, fg = self.colors["badge_bg"], self.colors["badge_fg"]
        self.status_badge.setStyleSheet(
            f"background:{bg};color:{fg};border-radius:12px;padding:5px 14px;font:600 10pt 'Segoe UI';"
        )

    def _sync_ui_state(self, *, force_defaults: bool = False) -> None:
        if self.run_state == "idle" and force_defaults:
            restored = " Last command restored." if self.command_restored else ""
            if self.command_analysis["has_command"] and self.command_analysis["valid"]:
                self.action_meta.setText(f"Ctrl+Enter executes. Local cache stays enabled.{restored}")
            elif self.command_analysis["has_command"]:
                self.action_meta.setText(f"Preflight found a quoting issue. Fix it before execute.{restored}")
            else:
                self.action_meta.setText(f"Paste a curl command to begin.{restored}")

        state_map = {
            "running": "Streaming", "cancelling": "Cancelling", "cancelled": "Cancelled",
            "parse error": "Parse error", "error": "Execution error", "done": "Done",
        }
        status_value = state_map.get(self.run_state, "Ready" if (
            self.command_analysis["valid"] and self.command_analysis["has_command"]
        ) else "Idle")

        elapsed_text = f"{self.last_elapsed:.2f}s" if self.last_elapsed is not None else "-"
        if self.run_started_at is not None and self.run_state in {"running", "cancelling"}:
            elapsed_text = f"{time.monotonic() - self.run_started_at:.2f}s"

        if self.last_exit_code is not None:
            exit_text = str(self.last_exit_code)
        elif self.run_state == "running":
            exit_text = "Pending"
        elif self.run_state == "cancelling":
            exit_text = "Stopping"
        elif self.run_state == "parse error":
            exit_text = "Blocked"
        else:
            exit_text = "No run yet"

        self.metric_status.set_value(status_value)
        self.metric_elapsed.set_value(elapsed_text)
        rate_seconds = self.last_elapsed
        if self.run_started_at is not None and self.run_state in {"running", "cancelling"}:
            rate_seconds = max(time.monotonic() - self.run_started_at, 0.01)
        self.metric_rate.set_value(_format_rate(self._bytes_received, rate_seconds))
        self.metric_exit.set_value(exit_text)
        self.output_title.setText("SIGNAL STREAM")

        variant_map = {"running": "good", "done": "good", "cancelling": "warn", "cancelled": "warn",
                       "parse error": "warn", "error": "bad"}
        self.metric_status.set_variant(variant_map.get(self.run_state, "neutral"))

        self.execute_btn.setText("Cancel request" if self.run_state in {"running", "cancelling"} else "Execute")
        busy = self.run_state in {"running", "cancelling"}
        self.validate_btn.setDisabled(busy)
        self.clear_all_btn.setDisabled(busy)
        self.auto_scroll_btn.setText(f"Auto-scroll {'on' if self.auto_scroll else 'off'}")
        self._update_status_badge()

    def _set_run_state(self, state: str, *, action_meta: str | None = None) -> None:
        self.run_state = state
        if action_meta is not None:
            self.action_meta.setText(action_meta)
        self._sync_ui_state()

    def _append_output(self, text: str) -> None:
        cursor = self.output_editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.output_editor.setTextCursor(cursor)
        if self.auto_scroll:
            self.output_editor.moveCursor(QTextCursor.MoveOperation.End)
            self.output_editor.ensureCursorVisible()
        if self.find_bar.isVisible() and self.find_entry.text().strip():
            self._refresh_find_matches()

    def _clear_output(self) -> None:
        self.output_editor.clear()
        self._find_positions = []
        self._find_index = -1
        self.output_editor.set_highlight_selections([])
        self.find_status.setText("Type to search")

    def on_clear_output(self) -> None:
        self._clear_output()
        self.action_meta.setText("Signal stream cleared. Command deck preserved.")
        self._sync_ui_state()

    def on_clear_all(self) -> None:
        self.command_editor.clear()
        self._clear_output()
        self.run_started_at = None
        self.last_elapsed = None
        self.last_exit_code = None
        self._bytes_received = 0
        self.command_restored = False
        self.run_state = "idle"
        self._refresh_command_analysis()

    def copy_output(self) -> None:
        QGuiApplication.clipboard().setText(self.output_editor.toPlainText())
        self.action_meta.setText("Signal stream copied to the clipboard.")
        self._sync_ui_state()

    def jump_to_end(self) -> None:
        self.output_editor.moveCursor(QTextCursor.MoveOperation.End)
        self.output_editor.ensureCursorVisible()
        self.action_meta.setText("Jumped to the latest signal output.")
        self._sync_ui_state()

    def toggle_auto_scroll(self) -> None:
        self.auto_scroll = not self.auto_scroll
        if self.auto_scroll:
            self.jump_to_end()
        else:
            self.action_meta.setText("Auto-scroll paused. Streaming continues.")
            self._sync_ui_state()

    def toggle_find_bar(self) -> None:
        self.hide_find_bar() if self.find_bar.isVisible() else self.show_find_bar()

    def show_find_bar(self) -> None:
        self.find_bar.show()
        self.find_entry.setFocus()
        self.find_entry.selectAll()
        self.action_meta.setText("Find opened for the signal stream.")
        self._refresh_find_matches()

    def hide_find_bar(self) -> None:
        self.find_bar.hide()
        self.find_entry.clear()
        self._find_positions = []
        self._find_index = -1
        self.output_editor.set_highlight_selections([])
        self.find_status.setText("Type to search")
        self.action_meta.setText("Find closed. Streaming view restored.")
        self._sync_ui_state()

    def _refresh_find_matches(self, *_args) -> None:
        query = self.find_entry.text()
        if not self.find_bar.isVisible():
            return
        if not query:
            self._find_positions = []
            self._find_index = -1
            self.output_editor.set_highlight_selections([])
            self.find_status.setText("Type to search")
            return

        content = self.output_editor.toPlainText()
        needle = query.casefold()
        positions: list[int] = []
        start = 0
        while (index := content.casefold().find(needle, start)) >= 0:
            positions.append(index)
            start = index + len(query)

        self._find_positions = positions
        if not positions:
            self._find_index = -1
            self.output_editor.set_highlight_selections([])
            self.find_status.setText("No matches")
            self.action_meta.setText(f"No matches for '{query}' in the signal stream.")
            return

        if self._find_index < 0 or self._find_index >= len(positions):
            self._find_index = 0

        selections = []
        for idx, position in enumerate(positions):
            cursor = self.output_editor.textCursor()
            cursor.setPosition(position)
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, len(query))
            sel = QTextEdit.ExtraSelection()
            if idx == self._find_index:
                sel.format.setBackground(QColor(self.colors["find_current_bg"]))
                sel.format.setForeground(QColor(self.colors["find_current_fg"]))
            else:
                sel.format.setBackground(QColor(self.colors["find_match_bg"]))
            sel.cursor = cursor
            selections.append(sel)

        self.output_editor.set_highlight_selections(selections)
        cursor = self.output_editor.textCursor()
        cursor.setPosition(positions[self._find_index])
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, len(query))
        self.output_editor.setTextCursor(cursor)
        self.output_editor.ensureCursorVisible()
        self.find_status.setText(f"{self._find_index + 1}/{len(positions)}")

    def find_next_match(self) -> None:
        if not self.find_bar.isVisible():
            self.show_find_bar()
            return
        if not self._find_positions:
            self._refresh_find_matches()
            return
        self._find_index = (self._find_index + 1) % len(self._find_positions)
        self._refresh_find_matches()

    def find_previous_match(self) -> None:
        if not self.find_bar.isVisible():
            self.show_find_bar()
            return
        if not self._find_positions:
            self._refresh_find_matches()
            return
        self._find_index = (self._find_index - 1) % len(self._find_positions)
        self._refresh_find_matches()

    def on_validate(self) -> None:
        self.command_analysis = analyze_command(self.command_editor.toPlainText())
        if not self.command_analysis["normalized"]:
            self.run_state = "idle"
            self.action_meta.setText("Paste a curl command before validating.")
        elif not self.command_analysis["valid"]:
            self.run_state = "parse error"
            self.action_meta.setText(self.command_analysis["detail_text"])
        else:
            self.run_state = "idle"
            self.action_meta.setText("Preflight passed. Execution not started.")
        self.preflight_note.setText(str(self.command_analysis["detail_text"]))
        self._render_preflight()
        self._sync_ui_state(force_defaults=False)

    def on_execute(self) -> None:
        if self._worker is not None and self.run_state in {"running", "cancelling"}:
            self.cancel_requested = True
            self._set_run_state("cancelling", action_meta="Termination signal sent to curl.")
            self._worker.request_cancel()
            return

        raw = self.command_editor.toPlainText()
        self.command_analysis = analyze_command(raw)

        if not self.command_analysis["normalized"]:
            self.action_meta.setText("Paste a curl command before executing.")
            self._sync_ui_state()
            return

        if not self.command_analysis["valid"]:
            self._clear_output()
            error = self.command_analysis["error"]
            line_hint = self.command_analysis["error_line"]
            msg = f"Parse error: {error}" + (f" - unclosed quote opens on line {line_hint}.\n" if line_hint else "\n")
            self._append_output(msg)
            self.last_exit_code = None
            self.last_elapsed = None
            self._set_run_state("parse error", action_meta="Execution blocked by a parse error.")
            return

        write_cached_command(raw)
        self.command_restored = False
        self._clear_output()
        self.cancel_requested = False
        self.last_exit_code = None
        self.last_elapsed = None
        self._bytes_received = 0
        self.run_started_at = time.monotonic()
        self._set_run_state("running", action_meta="Streaming raw output. Use Execute again or Esc to cancel.")
        self.elapsed_timer.start()

        self._worker_thread = QThread(self)
        self._worker = CurlRunWorker(list(self.command_analysis["args"]))
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.chunk.connect(self._on_worker_chunk)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.failed.connect(self._worker_thread.quit)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._cleanup_worker)
        self._worker_thread.start()

    @Slot(str, int)
    def _on_worker_chunk(self, text: str, byte_count: int) -> None:
        self._bytes_received += byte_count
        self._append_output(text)
        self._sync_ui_state()

    @Slot(str)
    def _on_worker_failed(self, message: str) -> None:
        self.elapsed_timer.stop()
        self._append_output(f"Error: {message}\n")
        self.last_exit_code = None
        self.last_elapsed = None
        self.run_started_at = None
        self.cancel_requested = False
        self._set_run_state("error", action_meta="curl could not be started. Inspect the signal stream.")
        if self._close_after_finish:
            self._allow_close = True
            self.close()

    @Slot(int, float, bool, int)
    def _on_worker_finished(self, return_code: int, elapsed: float, cancelled: bool, total_bytes: int) -> None:
        self.elapsed_timer.stop()
        self.last_exit_code = return_code
        self.last_elapsed = elapsed
        self.run_started_at = None
        self._bytes_received = max(self._bytes_received, total_bytes)
        if cancelled:
            self._append_output(f"\n[cancelled with exit {return_code} in {elapsed:.2f}s]\n")
            self._set_run_state("cancelled", action_meta="Execution stopped after a cancel request.")
        else:
            self._append_output(f"\n[exit {return_code} in {elapsed:.2f}s]\n")
            self._set_run_state("done", action_meta="Execution finished. Raw output preserved in the stream.")
        self.cancel_requested = False
        if self._close_after_finish:
            self._allow_close = True
            self.close()

    def _cleanup_worker(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        if self._worker_thread is not None:
            self._worker_thread.deleteLater()
        self._worker = None
        self._worker_thread = None

    def _tick_elapsed(self) -> None:
        if self.run_state not in {"running", "cancelling"} or self.run_started_at is None:
            self.elapsed_timer.stop()
            return
        self._sync_ui_state()

    def handle_escape(self) -> None:
        if self.find_bar.isVisible():
            self.hide_find_bar()
            return
        if self.run_state in {"running", "cancelling"} and self._worker is not None:
            self.on_execute()

    def begin_title_drag(self, global_pos: QPoint) -> None:
        if self.isMaximized():
            return
        handle = self.windowHandle()
        if handle is not None and handle.startSystemMove():
            return
        self._drag_origin = global_pos
        self._drag_start_frame = self.frameGeometry().topLeft()

    def toggle_maximized(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()
        QTimer.singleShot(0, self._apply_window_chrome)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched)):
            if event.type() in {QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove,
                                 QEvent.Type.MouseButtonRelease, QEvent.Type.Leave}:
                return self._handle_window_mouse_event(event)
        return super().eventFilter(watched, event)

    def _handle_window_mouse_event(self, event) -> bool:
        if self.isMaximized():
            if event.type() == QEvent.Type.MouseMove and not self._drag_origin:
                self.unsetCursor()
            return False

        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_for_global_pos(event.globalPosition().toPoint())
            if edges != Qt.Edges():
                handle = self.windowHandle()
                if handle is not None and handle.startSystemResize(edges):
                    return True
                self._manual_resize_edges = edges
                self._manual_resize_origin = event.globalPosition().toPoint()
                self._manual_resize_geometry = self.geometry()
                return True

        if event.type() == QEvent.Type.MouseMove:
            global_pos = event.globalPosition().toPoint()
            if self._drag_origin is not None and self._drag_start_frame is not None and event.buttons() & Qt.MouseButton.LeftButton:
                self.move(self._drag_start_frame + global_pos - self._drag_origin)
                return True
            if self._manual_resize_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
                self._apply_manual_resize(global_pos)
                return True
            self._update_resize_cursor(global_pos)

        if event.type() == QEvent.Type.MouseButtonRelease:
            self._drag_origin = None
            self._drag_start_frame = None
            self._manual_resize_origin = None
            self._manual_resize_edges = Qt.Edges()
            return False

        if event.type() == QEvent.Type.Leave and self._manual_resize_origin is None:
            self.unsetCursor()
        return False

    def _edges_for_global_pos(self, global_pos: QPoint) -> Qt.Edges:
        local = self.mapFromGlobal(global_pos)
        s = self.surface.geometry()
        left = s.left() <= local.x() <= s.left() + _RESIZE_MARGIN
        right = s.right() - _RESIZE_MARGIN <= local.x() <= s.right()
        top = s.top() <= local.y() <= s.top() + _RESIZE_MARGIN
        bottom = s.bottom() - _RESIZE_MARGIN <= local.y() <= s.bottom()
        edges = Qt.Edges()
        if left: edges |= Qt.Edge.LeftEdge
        if right: edges |= Qt.Edge.RightEdge
        if top: edges |= Qt.Edge.TopEdge
        if bottom: edges |= Qt.Edge.BottomEdge
        return edges

    def _update_resize_cursor(self, global_pos: QPoint) -> None:
        edges = self._edges_for_global_pos(global_pos)
        if edges in {Qt.Edge.LeftEdge, Qt.Edge.RightEdge}:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edges in {Qt.Edge.TopEdge, Qt.Edge.BottomEdge}:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif edges in {Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.Edge.BottomEdge | Qt.Edge.RightEdge}:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges in {Qt.Edge.TopEdge | Qt.Edge.RightEdge, Qt.Edge.BottomEdge | Qt.Edge.LeftEdge}:
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        else:
            self.unsetCursor()

    def _apply_manual_resize(self, global_pos: QPoint) -> None:
        if self._manual_resize_origin is None:
            return
        g = self._manual_resize_geometry
        d = global_pos - self._manual_resize_origin
        left, top, right, bottom = g.left(), g.top(), g.right(), g.bottom()
        if self._manual_resize_edges & Qt.Edge.LeftEdge: left += d.x()
        if self._manual_resize_edges & Qt.Edge.RightEdge: right += d.x()
        if self._manual_resize_edges & Qt.Edge.TopEdge: top += d.y()
        if self._manual_resize_edges & Qt.Edge.BottomEdge: bottom += d.y()
        new_w = max(right - left + 1, self.minimumWidth())
        new_h = max(bottom - top + 1, self.minimumHeight())
        if self._manual_resize_edges & Qt.Edge.LeftEdge: left = right - new_w + 1
        if self._manual_resize_edges & Qt.Edge.TopEdge: top = bottom - new_h + 1
        self.setGeometry(left, top, new_w, new_h)

    def request_close(self) -> None:
        dialog = ExitDialog(self, self.colors, running=self.run_state in {"running", "cancelling"})
        dialog.move(self.frameGeometry().center() - dialog.rect().center())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if self.run_state in {"running", "cancelling"} and self._worker is not None:
            self._close_after_finish = True
            if self.run_state != "cancelling":
                self.on_execute()
            return
        self._allow_close = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._allow_close:
            event.ignore()
            self.request_close()
            return
        self._save_window_state()
        super().closeEvent(event)

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            QTimer.singleShot(0, self._apply_window_chrome)

    def _apply_window_chrome(self) -> None:
        if (outer := self.layout()) is None:
            return
        margin = 0 if self.isMaximized() else _WINDOW_MARGIN
        outer.setContentsMargins(margin, margin, margin, margin)
        self._shadow_effect.setEnabled(not self.isMaximized())
        self.setStyleSheet(self._build_stylesheet())


def main() -> int:
    _set_app_user_model_id(_APP_ID)
    app = QApplication(sys.argv)
    app.setApplicationName("cURLsender")
    app.setOrganizationName(_SETTINGS_ORGANIZATION)
    icon = _build_app_icon()
    app.setWindowIcon(icon)
    window = ConsoleSignalWindow()
    window.setWindowIcon(icon)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
