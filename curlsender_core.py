from __future__ import annotations

import json
import re
import shlex
from collections.abc import Collection, Mapping
from pathlib import Path
from urllib.parse import urlparse


CONTINUATION_RE = re.compile(r"[\\^`]\r?\n")
GEOMETRY_RE = re.compile(r"\d+x\d+\+-?\d+\+-?\d+")

CACHE_FILE = Path.home() / ".curlsender_last.txt"
PREFS_FILE = Path.home() / ".curlsender_prefs.json"
APP_ID = "cURLsender.ConsoleSignal"
DEFAULT_GEOMETRY = "1220x820"
DEFAULT_THEME = "dark"

HEADER_FLAGS = {"-H", "--header"}
DATA_FLAGS = {
    "-d",
    "--data",
    "--data-ascii",
    "--data-binary",
    "--data-raw",
    "--data-urlencode",
    "--json",
    "-F",
    "--form",
}
SENSITIVE_HEADER_PREFIXES = ("authorization:", "cookie:", "x-api-key:", "proxy-authorization:")


def normalize_command(text: str) -> str:
    """Collapse bash `\\`, cmd `^`, and PowerShell backtick line continuations.

    Bare newlines inside quoted strings are left alone so JSON bodies survive.
    """
    return CONTINUATION_RE.sub(" ", text).strip()


def find_unclosed_quote_line(text: str) -> int | None:
    """Return the 1-based line where an unclosed quote started, if any."""
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
        return token[len(prefix) :]
    return None


def analyze_command(raw: str) -> dict[str, object]:
    normalized = normalize_command(raw)
    analysis: dict[str, object] = {
        "raw": raw,
        "normalized": normalized,
        "has_command": bool(normalized),
        "valid": False,
        "error": None,
        "error_line": None,
        "tokens": [],
        "args": [],
        "method": "GET",
        "host": "Awaiting URL",
        "header_count": 0,
        "has_body": False,
        "has_output": False,
        "output_target": None,
        "has_verbose": False,
        "has_auth": False,
        "is_curl": False,
        "chip_texts": [],
        "detail_text": "Paste a curl command to populate the preflight.",
        "warning_count": 0,
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
                header_value = next_token.lower()
                if header_value.startswith(SENSITIVE_HEADER_PREFIXES):
                    has_auth = True
                    sensitive_count += 1
                i += 2
                continue
        elif inline_header:
            header_count += 1
            header_value = inline_header.lower()
            if header_value.startswith(SENSITIVE_HEADER_PREFIXES):
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
        elif token in ("--url",):
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
        detail_parts.append(f"{sensitive_count} sensitive header{'s' if sensitive_count != 1 else ''} will be cached locally")

    analysis.update(
        {
            "valid": True,
            "args": args,
            "method": method,
            "host": host,
            "header_count": header_count,
            "has_body": has_body,
            "has_output": has_output,
            "output_target": output_target,
            "has_verbose": has_verbose,
            "has_auth": has_auth,
            "warning_count": sensitive_count,
            "chip_texts": chips[:5],
            "detail_text": " | ".join(detail_parts),
        }
    )
    return analysis


def load_preferences_data(prefs_file: Path = PREFS_FILE) -> dict[str, object]:
    try:
        data = json.loads(prefs_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_geometry_preference(
    prefs: Mapping[str, object],
    default_geometry: str = DEFAULT_GEOMETRY,
) -> str:
    geometry = prefs.get("geometry", default_geometry)
    if not isinstance(geometry, str):
        return default_geometry
    return geometry if GEOMETRY_RE.fullmatch(geometry) else default_geometry


def resolve_theme_preference(
    prefs: Mapping[str, object],
    available_themes: Collection[str],
    default_theme: str = DEFAULT_THEME,
) -> str:
    theme_name = prefs.get("theme", default_theme)
    return theme_name if theme_name in available_themes else default_theme


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


__all__ = [
    "APP_ID",
    "CACHE_FILE",
    "CONTINUATION_RE",
    "DATA_FLAGS",
    "DEFAULT_GEOMETRY",
    "DEFAULT_THEME",
    "GEOMETRY_RE",
    "HEADER_FLAGS",
    "PREFS_FILE",
    "SENSITIVE_HEADER_PREFIXES",
    "analyze_command",
    "find_unclosed_quote_line",
    "load_preferences_data",
    "load_session_data",
    "normalize_command",
    "read_cached_command",
    "resolve_geometry_preference",
    "resolve_theme_preference",
    "save_preferences_data",
    "save_session_data",
    "write_cached_command",
]
