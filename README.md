# cURLsender

![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![License](https://img.shields.io/badge/license-MIT-green) ![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

A desktop GUI for running pasted `curl` commands and reading the response exactly as `curl` emits it.

## Screenshots

| Dark theme | Light theme |
|:---:|:---:|
| ![cURLsender dark theme](assets/screenshot_dark.png) | ![cURLsender light theme](assets/screenshot_light.png) |

## Features

- Borderless window with rounded card panels
- Dark and light themes, switchable at runtime
- Preflight analysis: method, host, header count, body/auth detection — before you execute
- Session persistence: restores last command and output on next launch
- Output search (`Ctrl+F`) with match highlighting
- Runs the real `curl` binary — flags behave exactly as documented
- Accepts commands with or without a leading `curl`
- Handles `\`, `^`, and `` ` `` line continuations from any shell
- Parses bash-style quoted arguments on Windows via `shlex.split(posix=True)`
- Streams stdout + stderr as raw output
- `Ctrl+Enter` to execute, `Esc` to cancel
- Windows one-click launcher (`.vbs`)

## Dependencies

| Dependency | Version | How to get it |
|---|---|---|
| Python | 3.10+ | [python.org/downloads](https://www.python.org/downloads/) |
| PySide6 | 6.6+ | `pip install -r requirements.txt` |
| curl | any recent | Bundled on Windows 10 (1803+) and Windows 11; preinstalled on macOS/Linux |

## Installation

```bash
git clone https://github.com/Hefero/cURLsender.git
cd cURLsender
pip install -r requirements.txt
```

Or download the ZIP and extract it anywhere, then install PySide6.

## Running

**Windows** — double-click `curlsender.vbs`

Or from a terminal:

```bash
python curlsender.py
```

**macOS / Linux:**

```bash
chmod +x curlsender.sh
./curlsender.sh
# or directly:
python3 curlsender.py
```

## Usage

1. Paste a cURL command into the command editor.
2. Press `Ctrl+Enter` or click **Execute**.
3. Read the raw output in the stream panel.
4. Click **Execute** again while running to cancel, or press `Esc`.
5. Use **Clear output** to wipe only the stream, or **Clear all** to reset the session.

### Example

```bash
curl -X POST https://httpbin.org/post \
  -H 'Content-Type: application/json' \
  -d '{"hello": "world"}'
```

## Troubleshooting

**`python` is not recognized**
Python was not added to PATH. Re-run the installer and check "Add python.exe to PATH".

**`PySide6` is missing**
```bash
pip install -r requirements.txt
```

**`'curl' not found on PATH`**
Install `curl` or make sure it is on PATH.

**Parse error: No closing quotation**
The pasted command has unbalanced quotes. Check headers and body blocks.

**Variables like `$TOKEN` are not expanded**
By design. Substitute literal values before pasting.

## Repository layout

| File | Purpose |
|---|---|
| `curlsender.py` | Application — single file, all logic |
| `curlsender.vbs` | Windows double-click launcher |
| `curlsender.sh` | macOS / Linux launcher |
| `requirements.txt` | Python dependencies |

## Limitations

- Windows command-line length cap (~32 KB) — use `-d @body.json` for large payloads.
- No environment variable expansion — substitute literal values before pasting.
- No response pretty-printing, headers pane, or request history.

## License

MIT — see [LICENSE](LICENSE).
