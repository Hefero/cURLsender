import subprocess
import sys
import threading
import time
import tkinter as tk
import ctypes
from tkinter import ttk
from curlsender_core import (
    APP_ID,
    DEFAULT_GEOMETRY,
    DEFAULT_THEME,
    analyze_command,
    load_preferences_data,
    read_cached_command,
    resolve_geometry_preference,
    resolve_theme_preference,
    save_preferences_data,
    write_cached_command,
)


_MIN_WINDOW_SIZE = (1040, 720)
_WINDOW_CORNER_RADIUS = 30
_DIALOG_CORNER_RADIUS = 24
_RESIZE_BORDER = 8

_IS_WINDOWS = sys.platform.startswith("win")
if _IS_WINDOWS:
    _USER32 = ctypes.windll.user32
    _GDI32 = ctypes.windll.gdi32
    _SHELL32 = ctypes.windll.shell32
    _GWL_EXSTYLE = -20
    _WS_EX_APPWINDOW = 0x00040000
    _WS_EX_TOOLWINDOW = 0x00000080
    _SWP_NOSIZE = 0x0001
    _SWP_NOMOVE = 0x0002
    _SWP_NOZORDER = 0x0004
    _SWP_NOACTIVATE = 0x0010
    _SWP_FRAMECHANGED = 0x0020

_THEMES = {
    "dark": {
        "window_bg": "#11161a",
        "shell_bg": "#151c21",
        "shell_border": "#28333b",
        "card_bg": "#1b242b",
        "card_alt_bg": "#202a31",
        "card_border": "#2f3b44",
        "metric_bg": "#243039",
        "text": "#eff3f6",
        "muted": "#99a7b5",
        "accent": "#3db497",
        "accent_hover": "#4bc4a7",
        "accent_text": "#071512",
        "secondary_bg": "#24343c",
        "secondary_hover": "#2c4049",
        "secondary_text": "#d5edf1",
        "ghost_bg": "#202930",
        "ghost_hover": "#28333b",
        "ghost_text": "#eff3f6",
        "editor_bg": "#0d1115",
        "editor_fg": "#d9e2e8",
        "output_bg": "#0b0f13",
        "output_fg": "#dce4ea",
        "gutter_bg": "#11181d",
        "gutter_fg": "#5d7180",
        "select_bg": "#245c61",
        "select_fg": "#ffffff",
        "focus": "#5f9eff",
        "good_bg": "#17362d",
        "good_fg": "#7ee2a8",
        "warn_bg": "#3e3217",
        "warn_fg": "#ffd07d",
        "bad_bg": "#422022",
        "bad_fg": "#ff9898",
        "chip_bg": "#18343c",
        "chip_fg": "#9fe5f0",
        "badge_bg": "#18343c",
        "badge_fg": "#d5edf1",
        "input_insert": "#7edcc5",
        "shadow": "#0c1014",
        "titlebar_btn_bg": "#202930",
        "titlebar_btn_hover": "#2a353d",
        "titlebar_btn_fg": "#d5edf1",
        "titlebar_close_hover": "#6b2f36",
        "dialog_scrim": "#050709",
    },
    "light": {
        "window_bg": "#ece4d4",
        "shell_bg": "#f6efdf",
        "shell_border": "#d8cfc0",
        "card_bg": "#fff9f1",
        "card_alt_bg": "#fffdf8",
        "card_border": "#d9cfbe",
        "metric_bg": "#eff7f5",
        "text": "#1f2429",
        "muted": "#697482",
        "accent": "#135d66",
        "accent_hover": "#197481",
        "accent_text": "#ffffff",
        "secondary_bg": "#d8ecef",
        "secondary_hover": "#cce5e8",
        "secondary_text": "#135d66",
        "ghost_bg": "#ebe4d7",
        "ghost_hover": "#e0d7c9",
        "ghost_text": "#1f2429",
        "editor_bg": "#11161a",
        "editor_fg": "#d9e2e8",
        "output_bg": "#10161a",
        "output_fg": "#dce4ea",
        "gutter_bg": "#171d22",
        "gutter_fg": "#6a7b88",
        "select_bg": "#32757f",
        "select_fg": "#ffffff",
        "focus": "#32757f",
        "good_bg": "#d9f0e2",
        "good_fg": "#1d7348",
        "warn_bg": "#f6ead2",
        "warn_fg": "#9a620f",
        "bad_bg": "#f5dada",
        "bad_fg": "#9f3d3d",
        "chip_bg": "#e3f1f3",
        "chip_fg": "#135d66",
        "badge_bg": "#e3f1f3",
        "badge_fg": "#135d66",
        "input_insert": "#7edcc5",
        "shadow": "#d5cab8",
        "titlebar_btn_bg": "#ebe4d7",
        "titlebar_btn_hover": "#e0d7c9",
        "titlebar_btn_fg": "#1f2429",
        "titlebar_close_hover": "#e9c9c9",
        "dialog_scrim": "#7b7468",
    },
}


def attach_context_menu(text: tk.Text) -> None:
    """Add a right-click menu to a Text widget."""
    menu = tk.Menu(text, tearoff=0)

    def fire(event_name: str):
        return lambda: text.event_generate(event_name)

    def select_all() -> None:
        text.tag_add("sel", "1.0", "end-1c")
        text.focus_set()

    menu.add_command(label="Undo", command=fire("<<Undo>>"))
    menu.add_command(label="Redo", command=fire("<<Redo>>"))
    menu.add_separator()
    menu.add_command(label="Cut", command=fire("<<Cut>>"))
    menu.add_command(label="Copy", command=fire("<<Copy>>"))
    menu.add_command(label="Paste", command=fire("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="Select All", command=select_all)

    def show(event: tk.Event) -> str:
        readonly = str(text.cget("state")) == "disabled"
        has_sel = bool(text.tag_ranges("sel"))
        undoable = bool(text.cget("undo")) and not readonly
        menu.entryconfigure("Undo", state="normal" if undoable else "disabled")
        menu.entryconfigure("Redo", state="normal" if undoable else "disabled")
        menu.entryconfigure("Cut", state="normal" if (has_sel and not readonly) else "disabled")
        menu.entryconfigure("Copy", state="normal" if has_sel else "disabled")
        menu.entryconfigure("Paste", state="disabled" if readonly else "normal")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    text.bind("<Button-3>", show)
class NumberedText(ttk.Frame):
    GUTTER_WIDTH = 44
    GUTTER_PAD = 8

    def __init__(self, parent: tk.Misc, *, readonly: bool = False, **text_kwargs) -> None:
        super().__init__(parent)
        self._font = text_kwargs.get("font", ("Consolas", 10))
        self._readonly = readonly
        self._gutter_fg = "#808080"
        self._scrollbar_visible = True

        self.text = tk.Text(self, borderwidth=0, relief="flat", **text_kwargs)
        self.gutter = tk.Canvas(
            self,
            width=self.GUTTER_WIDTH,
            highlightthickness=0,
            borderwidth=0,
        )
        self.scrollbar = ttk.Scrollbar(self, command=self._on_scrollbar, style="Signal.Vertical.TScrollbar")
        self.text.configure(yscrollcommand=self._on_textscroll)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.gutter.grid(row=0, column=0, sticky="ns")
        self.text.grid(row=0, column=1, sticky="nsew")
        self.scrollbar.grid(row=0, column=2, sticky="ns")

        self.text.bind("<<Modified>>", self._on_modified, add="+")
        self.text.bind("<Configure>", lambda _event: self._redraw(), add="+")
        self.text.bind("<KeyRelease>", lambda _event: self._redraw(), add="+")
        self.text.bind("<MouseWheel>", lambda _event: self.after_idle(self._redraw), add="+")
        self.text.bind("<Button-4>", lambda _event: self.after_idle(self._redraw), add="+")
        self.text.bind("<Button-5>", lambda _event: self.after_idle(self._redraw), add="+")

    def apply_theme(self, colors: dict[str, str]) -> None:
        self.configure(style="EditorShell.TFrame")
        self.gutter.configure(bg=colors["gutter_bg"])
        self.text.configure(
            background=colors["editor_bg"] if not self._readonly else colors["output_bg"],
            foreground=colors["editor_fg"] if not self._readonly else colors["output_fg"],
            insertbackground=colors["input_insert"],
            selectbackground=colors["select_bg"],
            selectforeground=colors["select_fg"],
            highlightthickness=0,
            padx=0,
            pady=12,
        )
        self._gutter_fg = colors["gutter_fg"]
        self.after_idle(self._redraw)

    def _on_textscroll(self, first: str, last: str) -> None:
        self.scrollbar.set(first, last)
        should_show = not (float(first) <= 0.0 and float(last) >= 1.0)
        if should_show != self._scrollbar_visible:
            self._scrollbar_visible = should_show
            if should_show:
                self.scrollbar.grid()
            else:
                self.scrollbar.grid_remove()
        self._redraw()

    def _on_scrollbar(self, *args) -> None:
        self.text.yview(*args)
        self._redraw()

    def _on_modified(self, _event: tk.Event) -> None:
        self._redraw()
        self.text.edit_modified(False)

    def _redraw(self) -> None:
        self.gutter.delete("all")
        x = self.GUTTER_WIDTH - self.GUTTER_PAD
        i = self.text.index("@0,0")
        while True:
            dline = self.text.dlineinfo(i)
            if dline is None:
                break
            lineno = i.split(".")[0]
            self.gutter.create_text(
                x,
                dline[1],
                anchor="ne",
                text=lineno,
                font=self._font,
                fill=self._gutter_fg,
            )
            i = self.text.index(f"{i}+1line")


class CurlSenderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("cURLsender")
        self.prefs = self._load_preferences_data()
        self.current_theme = self._load_theme_preference()
        self._last_normal_geometry = self._load_geometry_preference()
        self.root.geometry(self._last_normal_geometry)
        self.root.minsize(*_MIN_WINDOW_SIZE)
        self.proc: subprocess.Popen | None = None
        self.auto_scroll = True
        self.cancel_requested = False
        self.run_state = "idle"
        self.run_started_at: float | None = None
        self.last_elapsed: float | None = None
        self.last_exit_code: int | None = None
        self.command_restored = False
        self.command_analysis = analyze_command("")
        self._drag_origin: tuple[int, int] | None = None
        self._resize_origin: dict[str, int | str] | None = None
        self._resize_handles: list[tk.Frame] = []
        self._geometry_job: str | None = None
        self._restore_borderless_after_map = False
        self._borderless_enabled = False
        self._window_handle: int | None = None
        self._close_dialog: tk.Toplevel | None = None
        self._icon_images: list[tk.PhotoImage] = []
        self._find_bar_visible = False
        self._find_matches: list[tuple[str, str]] = []
        self._find_index = -1
        self._suspend_geometry_save = True

        self.status_var = tk.StringVar(value="Idle")
        self.elapsed_var = tk.StringVar(value="-")
        self.target_var = tk.StringVar(value="Awaiting URL")
        self.result_var = tk.StringVar(value="No run yet")
        self.summary_note_var = tk.StringVar(value="Paste a curl command to populate the preflight.")
        self.action_meta_var = tk.StringVar(value="Ctrl+Enter executes. Output remains raw.")
        self.stream_title_var = tk.StringVar(value="Signal Stream")
        self.find_query_var = tk.StringVar(value="")
        self.find_query_var.trace_add("write", self._on_find_query_change)

        self._build_ui()
        self._install_window_icon()
        self._configure_window_chrome()
        self._apply_theme(self.current_theme)
        self._load_last()
        self._refresh_command_analysis()
        self._sync_ui_state(force_defaults=True)
        self.root.after_idle(self._finalize_window_setup)

    def _build_ui(self) -> None:
        mono = ("Consolas", 10)

        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")

        self.root.option_add("*tearOff", False)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        self.shell = ttk.Frame(self.root, style="Shell.TFrame", padding=20)
        self.shell.grid(row=0, column=0, sticky="nsew")
        self.shell.grid_columnconfigure(0, weight=1)
        self.shell.grid_rowconfigure(0, weight=1)

        self.app_frame = ttk.Frame(self.shell, style="App.TFrame", padding=18)
        self.app_frame.grid(row=0, column=0, sticky="nsew")
        self.app_frame.grid_columnconfigure(0, weight=1)
        self.app_frame.grid_rowconfigure(1, weight=1)

        self.header = ttk.Frame(self.app_frame, style="Card.TFrame", padding=(14, 12))
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.grid_columnconfigure(0, weight=1)

        brand = ttk.Frame(self.header, style="Card.TFrame")
        brand.grid(row=0, column=0, sticky="w")

        self.logo = tk.Label(
            brand,
            text="c",
            width=2,
            font=("Segoe UI Semibold", 18),
            bd=0,
            padx=10,
            pady=4,
        )
        self.logo.pack(side="left", padx=(0, 12))

        title_block = ttk.Frame(brand, style="Card.TFrame")
        title_block.pack(side="left")
        ttk.Label(title_block, text="cURLsender / Console Signal", style="Brand.TLabel").pack(anchor="w")
        ttk.Label(
            title_block,
            text="Paste, run, and read exactly what curl emits.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        header_right = ttk.Frame(self.header, style="Card.TFrame")
        header_right.grid(row=0, column=1, sticky="e")

        self.theme_btn = ttk.Button(header_right, command=self.toggle_theme, style="Ghost.TButton")
        self.theme_btn.pack(side="left", padx=(0, 10))

        self.status_badge = tk.Label(header_right, padx=12, pady=7, bd=0, font=("Segoe UI Semibold", 10))
        self.status_badge.pack(side="left", padx=(0, 10))

        self.minimize_btn = tk.Label(
            header_right,
            text="_",
            width=3,
            padx=0,
            pady=5,
            bd=0,
            cursor="hand2",
            font=("Segoe UI Semibold", 11),
        )
        self.minimize_btn.pack(side="left", padx=(0, 8))

        self.close_btn = tk.Label(
            header_right,
            text="X",
            width=3,
            padx=0,
            pady=5,
            bd=0,
            cursor="hand2",
            font=("Segoe UI Semibold", 10),
        )
        self.close_btn.pack(side="left")

        content = ttk.Frame(self.app_frame, style="App.TFrame")
        content.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        content.grid_columnconfigure(0, weight=7)
        content.grid_columnconfigure(1, weight=6)
        content.grid_rowconfigure(0, weight=1)

        left_col = ttk.Frame(content, style="App.TFrame")
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left_col.grid_columnconfigure(0, weight=1)
        left_col.grid_rowconfigure(0, weight=1)

        right_col = ttk.Frame(content, style="App.TFrame")
        right_col.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right_col.grid_columnconfigure(0, weight=1)
        right_col.grid_rowconfigure(1, weight=1)

        self.command_panel = ttk.Frame(left_col, style="Card.TFrame", padding=14)
        self.command_panel.grid(row=0, column=0, sticky="nsew")
        self.command_panel.grid_columnconfigure(0, weight=1)
        self.command_panel.grid_rowconfigure(2, weight=1)

        ttk.Label(self.command_panel, text="Command Deck", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            self.command_panel,
            text="Multiline paste is preserved. Ctrl+Enter executes the current deck.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 12))

        self.input_wrap = NumberedText(
            self.command_panel,
            height=16,
            font=mono,
            wrap="word",
            undo=True,
        )
        self.input_wrap.grid(row=2, column=0, sticky="nsew")
        self.input_box = self.input_wrap.text
        self.input_box.bind("<Control-Return>", self._on_ctrl_enter)
        attach_context_menu(self.input_box)

        self.preflight_row = tk.Frame(self.command_panel, bd=0)
        self.preflight_row.grid(row=3, column=0, sticky="ew", pady=(12, 0))

        self.actionbar = ttk.Frame(left_col, style="CardAlt.TFrame", padding=(14, 12))
        self.actionbar.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        self.actionbar.grid_columnconfigure(1, weight=1)

        buttons = ttk.Frame(self.actionbar, style="CardAlt.TFrame")
        buttons.grid(row=0, column=0, sticky="w")

        self.execute_btn = ttk.Button(buttons, text="Execute", command=self.on_execute, style="Accent.TButton")
        self.execute_btn.pack(side="left")

        self.clear_output_btn = ttk.Button(
            buttons,
            text="Clear output",
            command=self.on_clear_output,
            style="Secondary.TButton",
        )
        self.clear_output_btn.pack(side="left", padx=(8, 0))

        self.clear_all_btn = ttk.Button(
            buttons,
            text="Clear all",
            command=self.on_clear_all,
            style="Ghost.TButton",
        )
        self.clear_all_btn.pack(side="left", padx=(8, 0))

        ttk.Label(self.actionbar, textvariable=self.action_meta_var, style="MutedAlt.TLabel").grid(
            row=0, column=1, sticky="e"
        )

        self.summary_panel = ttk.Frame(right_col, style="Card.TFrame", padding=14)
        self.summary_panel.grid(row=0, column=0, sticky="ew")
        self.summary_panel.grid_columnconfigure(0, weight=1)

        ttk.Label(self.summary_panel, text="Execution Summary", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        metrics = ttk.Frame(self.summary_panel, style="Card.TFrame")
        metrics.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for column in range(2):
            metrics.grid_columnconfigure(column, weight=1)

        self.metric_cards: list[tuple[ttk.Frame, tk.Label, tk.Label]] = []
        metric_specs = [
            ("Status", self.status_var),
            ("Target", self.target_var),
            ("Method", tk.StringVar(value="GET")),
            ("Last result", self.result_var),
        ]
        self.method_var = metric_specs[2][1]

        for index, (label_text, value_var) in enumerate(metric_specs):
            row = index // 2
            column = index % 2
            card = ttk.Frame(metrics, style="Metric.TFrame", padding=12)
            card.grid(row=row, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0 if column == 1 else 6), pady=(0 if row == 0 else 12, 0))
            title = tk.Label(card, text=label_text, anchor="w", font=("Segoe UI", 9), bd=0)
            title.pack(anchor="w")
            value = tk.Label(card, textvariable=value_var, anchor="w", justify="left", font=("Segoe UI Semibold", 14), bd=0)
            value.pack(anchor="w", pady=(6, 0))
            self.metric_cards.append((card, title, value))

        ttk.Label(self.summary_panel, textvariable=self.summary_note_var, style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", pady=(12, 0)
        )

        self.output_panel = ttk.Frame(right_col, style="Card.TFrame", padding=14)
        self.output_panel.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        self.output_panel.grid_columnconfigure(0, weight=1)
        self.output_panel.grid_rowconfigure(2, weight=1)

        toolbar = ttk.Frame(self.output_panel, style="CardAlt.TFrame", padding=(12, 10))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_columnconfigure(0, weight=1)

        ttk.Label(toolbar, textvariable=self.stream_title_var, style="SectionAlt.TLabel").grid(row=0, column=0, sticky="w")

        toolbar_buttons = ttk.Frame(toolbar, style="CardAlt.TFrame")
        toolbar_buttons.grid(row=0, column=1, sticky="e")

        self.find_btn = ttk.Button(toolbar_buttons, text="Find", command=self.toggle_find_bar, style="Ghost.TButton")
        self.find_btn.pack(side="left")

        self.jump_btn = ttk.Button(toolbar_buttons, text="Jump to end", command=self.jump_to_end, style="Ghost.TButton")
        self.jump_btn.pack(side="left", padx=(8, 0))

        self.auto_scroll_btn = ttk.Button(
            toolbar_buttons,
            text="Auto-scroll: on",
            command=self.toggle_auto_scroll,
            style="Ghost.TButton",
        )
        self.auto_scroll_btn.pack(side="left", padx=(8, 0))

        self.copy_btn = ttk.Button(toolbar_buttons, text="Copy output", command=self.copy_output, style="Ghost.TButton")
        self.copy_btn.pack(side="left", padx=(8, 0))

        self.find_bar = ttk.Frame(self.output_panel, style="CardAlt.TFrame", padding=(12, 10))
        self.find_bar.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.find_bar.grid_columnconfigure(1, weight=1)

        ttk.Label(self.find_bar, text="Find in output", style="MutedAlt.TLabel").grid(row=0, column=0, sticky="w")
        self.find_entry = tk.Entry(self.find_bar, textvariable=self.find_query_var, relief="flat", bd=0, font=("Segoe UI", 10))
        self.find_entry.grid(row=0, column=1, sticky="ew", padx=(12, 10))
        self.find_prev_btn = ttk.Button(self.find_bar, text="Prev", command=self.find_previous_match, style="Ghost.TButton")
        self.find_prev_btn.grid(row=0, column=2, padx=(0, 8))
        self.find_next_btn = ttk.Button(self.find_bar, text="Next", command=self.find_next_match, style="Ghost.TButton")
        self.find_next_btn.grid(row=0, column=3)
        self.find_close_btn = ttk.Button(self.find_bar, text="Close", command=self.hide_find_bar, style="Ghost.TButton")
        self.find_close_btn.grid(row=0, column=4, padx=(8, 0))
        self.find_bar.grid_remove()

        self.output_wrap = NumberedText(
            self.output_panel,
            readonly=True,
            font=mono,
            wrap="word",
            state="disabled",
        )
        self.output_wrap.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        self.output_box = self.output_wrap.text
        attach_context_menu(self.output_box)

        self._bind_drag_handle(self.header)
        self._bind_drag_handle(brand)
        self._bind_drag_handle(title_block)
        self._bind_drag_handle(self.logo)
        self._bind_drag_handle(self.status_badge)

        self.minimize_btn.bind("<Button-1>", lambda _event: self.minimize_window())
        self.close_btn.bind("<Button-1>", lambda _event: self.request_close())

        self.root.bind("<Escape>", self._on_escape, add="+")
        self.root.bind("<Alt-F4>", lambda _event: (self.request_close(), "break")[1], add="+")
        self.root.bind("<Map>", self._on_window_map, add="+")
        self.root.bind("<Configure>", self._on_root_configure, add="+")
        self.find_entry.bind("<Return>", lambda _event: self.find_next_match())
        self.find_entry.bind("<Escape>", lambda _event: self.hide_find_bar())
        self.output_box.tag_configure("find_match", background="#f5d77e", foreground="#10161a")
        self.output_box.tag_configure("find_current", background="#3db497", foreground="#071512")

        for sequence in ("<KeyRelease>", "<<Paste>>", "<<Cut>>", "<<Undo>>", "<<Redo>>"):
            self.input_box.bind(sequence, self._schedule_refresh, add="+")

    def _load_preferences_data(self) -> dict[str, object]:
        return load_preferences_data()

    def _load_geometry_preference(self) -> str:
        return resolve_geometry_preference(self.prefs, DEFAULT_GEOMETRY)

    def _save_preferences(self) -> None:
        save_preferences_data(
            {
                "theme": self.current_theme,
                "geometry": self._last_normal_geometry,
            }
        )

    def _install_window_icon(self) -> None:
        self._icon_images = [self._make_icon_image(size) for size in (16, 32, 64)]
        self.root.iconphoto(True, *self._icon_images)

    def _make_icon_image(self, size: int) -> tk.PhotoImage:
        image = tk.PhotoImage(width=size, height=size)
        dark = "#0f1418"
        accent = "#3db497"
        accent_alt = "#5f9eff"
        light = "#eff3f6"
        border = max(1, size // 16)
        inset = max(2, size // 6)
        stroke = max(2, size // 8)

        image.put(dark, to=(0, 0, size, size))
        image.put(accent_alt, to=(border, border, size - border, size - border))
        image.put(accent, to=(border * 2, border * 2, size - border * 2, size - border * 2))
        image.put(dark, to=(inset, inset, size - inset, size - inset))
        image.put(light, to=(inset, inset, size - inset, inset + stroke))
        image.put(light, to=(inset, size - inset - stroke, size - inset, size - inset))
        image.put(light, to=(inset, inset, inset + stroke, size - inset))
        return image

    def _configure_window_chrome(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self.request_close)
        self._create_resize_handles()

    def _finalize_window_setup(self) -> None:
        self._set_borderless(True)
        self._apply_rounded_corners(self.root, _WINDOW_CORNER_RADIUS)
        self._suspend_geometry_save = False
        self._save_preferences()

    def _load_theme_preference(self) -> str:
        return resolve_theme_preference(self.prefs, _THEMES, DEFAULT_THEME)

    def _save_theme_preference(self) -> None:
        self._save_preferences()

    def _bind_drag_handle(self, widget: tk.Widget) -> None:
        widget.bind("<ButtonPress-1>", self._start_move, add="+")
        widget.bind("<B1-Motion>", self._drag_window, add="+")
        widget.bind("<ButtonRelease-1>", self._end_move, add="+")

    def _start_move(self, event: tk.Event) -> None:
        self._drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag_window(self, event: tk.Event) -> None:
        if self._drag_origin is None:
            return
        offset_x, offset_y = self._drag_origin
        self.root.geometry(f"+{event.x_root - offset_x}+{event.y_root - offset_y}")

    def _end_move(self, _event: tk.Event) -> None:
        self._drag_origin = None

    def _create_resize_handles(self) -> None:
        specs = [
            ("n", "sb_v_double_arrow", {"relx": 0, "rely": 0, "relwidth": 1, "height": _RESIZE_BORDER, "x": 14, "width": -28}),
            ("s", "sb_v_double_arrow", {"relx": 0, "rely": 1, "anchor": "sw", "relwidth": 1, "height": _RESIZE_BORDER, "x": 14, "width": -28}),
            ("w", "sb_h_double_arrow", {"relx": 0, "rely": 0, "relheight": 1, "width": _RESIZE_BORDER, "y": 14, "height": -28}),
            ("e", "sb_h_double_arrow", {"relx": 1, "rely": 0, "anchor": "ne", "relheight": 1, "width": _RESIZE_BORDER, "y": 14, "height": -28}),
            ("nw", "size_nw_se", {"x": 0, "y": 0, "width": _RESIZE_BORDER + 4, "height": _RESIZE_BORDER + 4}),
            ("ne", "size_ne_sw", {"relx": 1, "x": -(_RESIZE_BORDER + 4), "y": 0, "width": _RESIZE_BORDER + 4, "height": _RESIZE_BORDER + 4}),
            ("sw", "size_ne_sw", {"x": 0, "rely": 1, "y": -(_RESIZE_BORDER + 4), "width": _RESIZE_BORDER + 4, "height": _RESIZE_BORDER + 4}),
            ("se", "size_nw_se", {"relx": 1, "rely": 1, "x": -(_RESIZE_BORDER + 4), "y": -(_RESIZE_BORDER + 4), "width": _RESIZE_BORDER + 4, "height": _RESIZE_BORDER + 4}),
        ]
        for direction, cursor, placement in specs:
            handle = tk.Frame(self.root, bd=0, highlightthickness=0, cursor=cursor)
            handle.place(in_=self.root, **placement)
            handle.bind("<ButtonPress-1>", lambda event, d=direction: self._start_resize(event, d), add="+")
            handle.bind("<B1-Motion>", self._perform_resize, add="+")
            handle.bind("<ButtonRelease-1>", self._end_resize, add="+")
            self._resize_handles.append(handle)

    def _start_resize(self, event: tk.Event, direction: str) -> None:
        self._resize_origin = {
            "direction": direction,
            "x_root": event.x_root,
            "y_root": event.y_root,
            "width": self.root.winfo_width(),
            "height": self.root.winfo_height(),
            "x": self.root.winfo_x(),
            "y": self.root.winfo_y(),
        }

    def _perform_resize(self, event: tk.Event) -> None:
        if self._resize_origin is None:
            return

        direction = str(self._resize_origin["direction"])
        dx = event.x_root - int(self._resize_origin["x_root"])
        dy = event.y_root - int(self._resize_origin["y_root"])
        width = int(self._resize_origin["width"])
        height = int(self._resize_origin["height"])
        pos_x = int(self._resize_origin["x"])
        pos_y = int(self._resize_origin["y"])
        min_width, min_height = _MIN_WINDOW_SIZE

        if "e" in direction:
            width = max(min_width, width + dx)
        if "s" in direction:
            height = max(min_height, height + dy)
        if "w" in direction:
            width = max(min_width, width - dx)
            pos_x = int(self._resize_origin["x"]) + (int(self._resize_origin["width"]) - width)
        if "n" in direction:
            height = max(min_height, height - dy)
            pos_y = int(self._resize_origin["y"]) + (int(self._resize_origin["height"]) - height)

        self.root.geometry(f"{width}x{height}+{pos_x}+{pos_y}")

    def _end_resize(self, _event: tk.Event) -> None:
        self._resize_origin = None

    def _set_borderless(self, enabled: bool) -> None:
        self._borderless_enabled = enabled
        self.root.overrideredirect(enabled)
        if _IS_WINDOWS:
            self.root.update_idletasks()
            self._refresh_taskbar_window_style()

    def _refresh_taskbar_window_style(self) -> None:
        if not _IS_WINDOWS:
            return
        self._window_handle = _USER32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        style = _USER32.GetWindowLongW(self._window_handle, _GWL_EXSTYLE)
        style = (style & ~_WS_EX_TOOLWINDOW) | _WS_EX_APPWINDOW
        _USER32.SetWindowLongW(self._window_handle, _GWL_EXSTYLE, style)
        _USER32.SetWindowPos(
            self._window_handle,
            0,
            0,
            0,
            0,
            0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_FRAMECHANGED,
        )

    def _on_window_map(self, _event: tk.Event) -> None:
        if self._restore_borderless_after_map and self.root.state() == "normal":
            self._restore_borderless_after_map = False
            self.root.after(20, lambda: self._set_borderless(True))

    def _on_root_configure(self, event: tk.Event) -> None:
        if event.widget is not self.root:
            return

        self._apply_rounded_corners(self.root, _WINDOW_CORNER_RADIUS)
        if self._close_dialog is not None and self._close_dialog.winfo_exists():
            self._center_dialog(self._close_dialog)
            self._apply_rounded_corners(self._close_dialog, _DIALOG_CORNER_RADIUS)

        if self._suspend_geometry_save or self.root.state() != "normal":
            return

        self._last_normal_geometry = (
            f"{self.root.winfo_width()}x{self.root.winfo_height()}+{self.root.winfo_x()}+{self.root.winfo_y()}"
        )
        if self._geometry_job is not None:
            self.root.after_cancel(self._geometry_job)
        self._geometry_job = self.root.after(180, self._save_preferences)

    def _apply_rounded_corners(self, window: tk.Toplevel, radius: int) -> None:
        if not _IS_WINDOWS or not window.winfo_exists():
            return
        width = window.winfo_width()
        height = window.winfo_height()
        if width <= 1 or height <= 1:
            return
        region = _GDI32.CreateRoundRectRgn(0, 0, width + 1, height + 1, radius, radius)
        hwnd = self._window_handle if window is self.root and self._window_handle is not None else window.winfo_id()
        _USER32.SetWindowRgn(hwnd, region, True)

    def _style_titlebar_buttons(self, colors: dict[str, str]) -> None:
        self.minimize_btn.configure(bg=colors["titlebar_btn_bg"], fg=colors["titlebar_btn_fg"])
        self.close_btn.configure(bg=colors["titlebar_btn_bg"], fg=colors["titlebar_btn_fg"])
        self.find_entry.configure(
            bg=colors["ghost_bg"],
            fg=colors["text"],
            insertbackground=colors["text"],
            highlightthickness=1,
            highlightbackground=colors["card_border"],
            highlightcolor=colors["focus"],
        )

        self.minimize_btn.bind(
            "<Enter>",
            lambda _event: self.minimize_btn.configure(bg=colors["titlebar_btn_hover"]),
        )
        self.minimize_btn.bind(
            "<Leave>",
            lambda _event: self.minimize_btn.configure(bg=colors["titlebar_btn_bg"]),
        )
        self.close_btn.bind(
            "<Enter>",
            lambda _event: self.close_btn.configure(bg=colors["titlebar_close_hover"]),
        )
        self.close_btn.bind(
            "<Leave>",
            lambda _event: self.close_btn.configure(bg=colors["titlebar_btn_bg"]),
        )

    def minimize_window(self) -> None:
        self._restore_borderless_after_map = True
        self._set_borderless(False)
        self.root.update_idletasks()
        self.root.iconify()

    def request_close(self) -> None:
        if self._close_dialog is not None and self._close_dialog.winfo_exists():
            self._close_dialog.lift()
            self._close_dialog.focus_force()
            return
        self._show_close_dialog()

    def _show_close_dialog(self) -> None:
        colors = _THEMES[self.current_theme]
        dialog = tk.Toplevel(self.root)
        dialog.overrideredirect(True)
        dialog.transient(self.root)
        dialog.configure(bg=colors["dialog_scrim"])
        dialog.attributes("-topmost", True)

        card = tk.Frame(dialog, bg=colors["card_bg"], highlightthickness=1, highlightbackground=colors["card_border"])
        card.pack(padx=1, pady=1)

        title = tk.Label(
            card,
            text="Exit cURLsender?",
            bg=colors["card_bg"],
            fg=colors["text"],
            font=("Segoe UI Semibold", 13),
            padx=18,
            pady=16,
        )
        title.pack(anchor="w")

        body = tk.Label(
            card,
            text="The current command and theme preference are already cached locally. Do you want to close the app now?",
            bg=colors["card_bg"],
            fg=colors["muted"],
            justify="left",
            wraplength=320,
            font=("Segoe UI", 10),
            padx=18,
            pady=0,
        )
        body.pack(anchor="w")

        button_row = tk.Frame(card, bg=colors["card_bg"], padx=18, pady=18)
        button_row.pack(fill="x")

        cancel_btn = ttk.Button(button_row, text="Stay here", command=self._dismiss_close_dialog, style="Ghost.TButton")
        cancel_btn.pack(side="right")
        exit_btn = ttk.Button(button_row, text="Exit now", command=self._confirm_close, style="Accent.TButton")
        exit_btn.pack(side="right", padx=(0, 8))

        dialog.bind("<Escape>", lambda _event: self._dismiss_close_dialog())
        dialog.bind("<Return>", lambda _event: self._confirm_close())

        self._close_dialog = dialog
        self._center_dialog(dialog)
        self._apply_rounded_corners(dialog, _DIALOG_CORNER_RADIUS)
        dialog.grab_set()
        dialog.focus_force()

    def _center_dialog(self, dialog: tk.Toplevel) -> None:
        dialog.update_idletasks()
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        pos_x = self.root.winfo_x() + (self.root.winfo_width() - width) // 2
        pos_y = self.root.winfo_y() + (self.root.winfo_height() - height) // 2
        dialog.geometry(f"{width}x{height}+{pos_x}+{pos_y}")

    def _dismiss_close_dialog(self) -> None:
        if self._close_dialog is None or not self._close_dialog.winfo_exists():
            self._close_dialog = None
            return
        dialog = self._close_dialog
        self._close_dialog = None
        dialog.grab_release()
        dialog.destroy()
        self.root.focus_force()

    def _confirm_close(self) -> None:
        self._save_preferences()
        self._dismiss_close_dialog()
        self.root.destroy()

    def _apply_theme(self, theme_name: str) -> None:
        colors = _THEMES[theme_name]
        self.current_theme = theme_name

        self.root.configure(bg=colors["window_bg"])

        self.style.configure("Shell.TFrame", background=colors["shell_bg"])
        self.style.configure(
            "App.TFrame",
            background=colors["card_bg"],
            borderwidth=1,
            relief="solid",
            bordercolor=colors["shell_border"],
        )
        self.style.configure(
            "Card.TFrame",
            background=colors["card_bg"],
            borderwidth=1,
            relief="solid",
            bordercolor=colors["card_border"],
        )
        self.style.configure(
            "CardAlt.TFrame",
            background=colors["card_alt_bg"],
            borderwidth=1,
            relief="solid",
            bordercolor=colors["card_border"],
        )
        self.style.configure(
            "Metric.TFrame",
            background=colors["metric_bg"],
            borderwidth=1,
            relief="solid",
            bordercolor=colors["card_border"],
        )
        self.style.configure("EditorShell.TFrame", background=colors["editor_bg"])

        self.style.configure("Brand.TLabel", background=colors["card_bg"], foreground=colors["text"], font=("Segoe UI Semibold", 13))
        self.style.configure("Section.TLabel", background=colors["card_bg"], foreground=colors["muted"], font=("Segoe UI Semibold", 10))
        self.style.configure("SectionAlt.TLabel", background=colors["card_alt_bg"], foreground=colors["muted"], font=("Segoe UI Semibold", 10))
        self.style.configure("Muted.TLabel", background=colors["card_bg"], foreground=colors["muted"], font=("Segoe UI", 9))
        self.style.configure("MutedAlt.TLabel", background=colors["card_alt_bg"], foreground=colors["muted"], font=("Segoe UI", 9))

        self.style.configure(
            "Accent.TButton",
            background=colors["accent"],
            foreground=colors["accent_text"],
            borderwidth=0,
            focusthickness=3,
            focuscolor=colors["focus"],
            padding=(14, 10),
            font=("Segoe UI Semibold", 10),
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", colors["accent_hover"]), ("pressed", colors["accent_hover"])],
            foreground=[("disabled", colors["muted"])],
        )
        self.style.configure(
            "Secondary.TButton",
            background=colors["secondary_bg"],
            foreground=colors["secondary_text"],
            borderwidth=0,
            focusthickness=3,
            focuscolor=colors["focus"],
            padding=(14, 10),
            font=("Segoe UI Semibold", 10),
        )
        self.style.map(
            "Secondary.TButton",
            background=[("active", colors["secondary_hover"]), ("pressed", colors["secondary_hover"])],
            foreground=[("disabled", colors["muted"])],
        )
        self.style.configure(
            "Ghost.TButton",
            background=colors["ghost_bg"],
            foreground=colors["ghost_text"],
            borderwidth=0,
            focusthickness=3,
            focuscolor=colors["focus"],
            padding=(12, 10),
            font=("Segoe UI Semibold", 10),
        )
        self.style.map(
            "Ghost.TButton",
            background=[("active", colors["ghost_hover"]), ("pressed", colors["ghost_hover"])],
            foreground=[("disabled", colors["muted"])],
        )
        self.style.configure(
            "Signal.Vertical.TScrollbar",
            background=colors["ghost_bg"],
            darkcolor=colors["ghost_bg"],
            lightcolor=colors["ghost_bg"],
            troughcolor=colors["card_bg"],
            bordercolor=colors["card_border"],
            arrowcolor=colors["muted"],
            gripcount=0,
        )

        for text_widget in (self.input_wrap, self.output_wrap):
            text_widget.apply_theme(colors)

        self.logo.configure(bg=colors["accent"], fg=colors["accent_text"])
        self.preflight_row.configure(bg=colors["card_bg"])
        self.status_badge.configure(bg=colors["badge_bg"], fg=colors["badge_fg"])
        for handle in self._resize_handles:
            handle.configure(bg=colors["window_bg"])

        for card, title, value in self.metric_cards:
            title.configure(bg=colors["metric_bg"], fg=colors["muted"])
            value.configure(bg=colors["metric_bg"], fg=colors["text"])

        self._style_titlebar_buttons(colors)
        self.output_box.tag_configure("find_match", background=colors["warn_fg"], foreground=colors["output_bg"])
        self.output_box.tag_configure("find_current", background=colors["accent"], foreground=colors["accent_text"])
        self.theme_btn.configure(text=f"Theme: {'Light' if theme_name == 'dark' else 'Dark'}")
        self._sync_badge_colors()
        self._render_preflight()
        self._apply_rounded_corners(self.root, _WINDOW_CORNER_RADIUS)

    def toggle_theme(self) -> None:
        next_theme = "light" if self.current_theme == "dark" else "dark"
        self._apply_theme(next_theme)
        self._save_theme_preference()

    def _load_last(self) -> None:
        cached = read_cached_command()
        if cached:
            self.command_restored = True
            self.input_box.insert("1.0", cached)
            self.input_box.edit_reset()
            self.action_meta_var.set("Last command restored from local cache.")

    def _save_last(self, raw: str) -> None:
        write_cached_command(raw)

    def _schedule_refresh(self, _event: tk.Event | None = None) -> None:
        self.root.after_idle(self._refresh_command_analysis)

    def _refresh_command_analysis(self) -> None:
        self.command_analysis = analyze_command(self.input_box.get("1.0", "end-1c"))
        self.method_var.set(str(self.command_analysis["method"]))
        self.target_var.set(str(self.command_analysis["host"]))
        self.summary_note_var.set(str(self.command_analysis["detail_text"]))
        self._render_preflight()
        self._sync_ui_state(force_defaults=True)

    def _render_preflight(self) -> None:
        colors = _THEMES[self.current_theme]
        for child in self.preflight_row.winfo_children():
            child.destroy()

        chip_texts = list(self.command_analysis["chip_texts"])  # type: ignore[arg-type]
        if not chip_texts:
            chip_texts = ["Awaiting input"]
            bg = colors["ghost_bg"]
            fg = colors["muted"]
        else:
            bg = colors["chip_bg"]
            fg = colors["chip_fg"]

        if not self.command_analysis["valid"] and self.command_analysis["has_command"]:
            line_hint = self.command_analysis["error_line"]
            chip_texts = ["Quote check needed"]
            if line_hint is not None:
                chip_texts.append(f"line {line_hint}")
            bg = colors["warn_bg"]
            fg = colors["warn_fg"]

        for index, text in enumerate(chip_texts[:5]):
            chip = tk.Label(
                self.preflight_row,
                text=text,
                bg=bg,
                fg=fg,
                padx=10,
                pady=6,
                bd=0,
                font=("Segoe UI Semibold", 9),
            )
            chip.grid(row=0, column=index, padx=(0, 8), sticky="w")

    def _sync_badge_colors(self) -> None:
        colors = _THEMES[self.current_theme]
        status_text = self.status_var.get().lower()
        badge_bg = colors["badge_bg"]
        badge_fg = colors["badge_fg"]
        value_fg = colors["text"]

        if "stream" in status_text or "running" in status_text:
            badge_bg = colors["good_bg"]
            badge_fg = colors["good_fg"]
            value_fg = colors["good_fg"]
        elif "cancel" in status_text:
            badge_bg = colors["warn_bg"]
            badge_fg = colors["warn_fg"]
            value_fg = colors["warn_fg"]
        elif "error" in status_text:
            badge_bg = colors["bad_bg"]
            badge_fg = colors["bad_fg"]
            value_fg = colors["bad_fg"]
        elif "done" in status_text:
            badge_bg = colors["good_bg"]
            badge_fg = colors["good_fg"]
            value_fg = colors["good_fg"]

        self.status_badge.configure(bg=badge_bg, fg=badge_fg, text=self._build_status_badge_text())
        self.metric_cards[0][2].configure(fg=value_fg, bg=colors["metric_bg"])

    def _build_status_badge_text(self) -> str:
        analysis = self.command_analysis
        if self.run_state == "running":
            return "Live stream | cancel available | curl active"
        if self.run_state == "cancelling":
            return "Termination requested | waiting for curl"
        if self.run_state == "cancelled":
            return "Stopped early | raw output preserved"
        if self.run_state == "parse error":
            return "Parse error | fix quoting before execute"
        if self.run_state == "error":
            return "Execution error | inspect the signal stream"
        if self.run_state == "done":
            return "Complete | raw output preserved"
        if analysis["has_command"] and not analysis["valid"]:
            return "Preflight warning | close the quote before run"
        if analysis["valid"]:
            return "Ready | Ctrl+Enter executes | curl detected"
        return "Idle | paste a curl command to begin"

    def _sync_ui_state(self, *, force_defaults: bool = False) -> None:
        analysis = self.command_analysis
        restored_note = " Last command restored." if self.command_restored else ""

        if self.run_state == "idle" and force_defaults:
            if analysis["has_command"] and analysis["valid"]:
                self.status_var.set("Ready")
                self.action_meta_var.set(f"Ctrl+Enter executes. Local cache stays enabled.{restored_note}")
            elif analysis["has_command"] and not analysis["valid"]:
                self.status_var.set("Needs attention")
                self.action_meta_var.set(
                    f"Preflight found a quoting issue. Fix it before execute.{restored_note}"
                )
            else:
                self.status_var.set("Idle")
                self.action_meta_var.set(f"Paste a curl command to begin.{restored_note}")

        if self.last_elapsed is None:
            self.elapsed_var.set("-")

        result = "No run yet"
        if self.last_exit_code is not None:
            elapsed = f" in {self.last_elapsed:.2f}s" if self.last_elapsed is not None else ""
            result = f"exit {self.last_exit_code}{elapsed}"
        elif self.run_state == "running":
            result = "pending"
        elif self.run_state == "cancelling":
            result = "awaiting stop"
        elif self.run_state == "cancelled":
            result = f"exit {self.last_exit_code}" if self.last_exit_code is not None else "cancelled"
        self.result_var.set(result)

        self.stream_title_var.set(f"Signal Stream | elapsed {self.elapsed_var.get()}")
        self.auto_scroll_btn.configure(text=f"Auto-scroll: {'on' if self.auto_scroll else 'off'}")
        self.execute_btn.configure(text="Cancel" if self.run_state in {"running", "cancelling"} else "Execute")
        self.clear_all_btn.configure(state="disabled" if self.run_state in {"running", "cancelling"} else "normal")
        self._sync_badge_colors()

    def _set_run_state(self, state: str, *, action_meta: str | None = None) -> None:
        self.run_state = state
        if state == "running":
            self.status_var.set("Streaming")
        elif state == "cancelling":
            self.status_var.set("Cancelling")
        elif state == "cancelled":
            self.status_var.set("Cancelled")
        elif state == "parse error":
            self.status_var.set("Parse error")
        elif state == "error":
            self.status_var.set("Execution error")
        elif state == "done":
            self.status_var.set("Done")
        elif state == "idle":
            self.status_var.set("Idle")

        if action_meta is not None:
            self.action_meta_var.set(action_meta)
        self._sync_ui_state()

    def _on_ctrl_enter(self, _event: tk.Event) -> str:
        self.on_execute()
        return "break"

    def _on_escape(self, _event: tk.Event) -> str | None:
        if self._close_dialog is not None and self._close_dialog.winfo_exists():
            self._dismiss_close_dialog()
            return "break"
        if self._find_bar_visible and self.root.focus_get() == self.find_entry:
            self.hide_find_bar()
            return "break"
        if self.proc is not None and self.proc.poll() is None:
            self.on_execute()
            return "break"
        return None

    def _append(self, text: str) -> None:
        self.output_box.configure(state="normal")
        self.output_box.insert("end", text)
        if self.auto_scroll:
            self.output_box.see("end")
        self.output_box.configure(state="disabled")
        if self._find_bar_visible and self.find_query_var.get().strip():
            self.root.after_idle(self._refresh_find_matches)

    def _clear_output(self) -> None:
        self.output_box.configure(state="normal")
        self.output_box.delete("1.0", "end")
        self.output_box.configure(state="disabled")
        self._clear_find_highlights()
        self._find_matches = []
        self._find_index = -1

    def on_clear_output(self) -> None:
        self._clear_output()
        self.action_meta_var.set("Signal stream cleared. Command deck preserved.")
        self._sync_ui_state()

    def on_clear_all(self) -> None:
        self.input_box.delete("1.0", "end")
        self._clear_output()
        self.run_started_at = None
        self.last_elapsed = None
        self.last_exit_code = None
        self.run_state = "idle"
        self.command_restored = False
        self._refresh_command_analysis()

    def jump_to_end(self) -> None:
        self.output_box.see("end")
        self.action_meta_var.set("Jumped to the latest signal output.")
        self._sync_ui_state()

    def toggle_auto_scroll(self) -> None:
        self.auto_scroll = not self.auto_scroll
        if self.auto_scroll:
            self.output_box.see("end")
            self.action_meta_var.set("Auto-scroll enabled for live output.")
        else:
            self.action_meta_var.set("Auto-scroll paused. Streaming continues.")
        self._sync_ui_state()

    def copy_output(self) -> None:
        output = self.output_box.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(output)
        self.action_meta_var.set("Signal stream copied to the clipboard.")
        self._sync_ui_state()

    def toggle_find_bar(self) -> None:
        if self._find_bar_visible:
            self.hide_find_bar()
        else:
            self.show_find_bar()

    def show_find_bar(self) -> None:
        self._find_bar_visible = True
        self.find_bar.grid()
        self.find_entry.focus_set()
        self.find_entry.selection_range(0, "end")
        self.action_meta_var.set("Find opened for the signal stream.")
        self._refresh_find_matches()

    def hide_find_bar(self) -> None:
        self._find_bar_visible = False
        self.find_bar.grid_remove()
        self.find_query_var.set("")
        self._clear_find_highlights()
        self._find_matches = []
        self._find_index = -1
        self.action_meta_var.set("Find closed. Streaming view restored.")
        self._sync_ui_state()

    def _on_find_query_change(self, *_args) -> None:
        if self._find_bar_visible:
            self.root.after_idle(self._refresh_find_matches)

    def _clear_find_highlights(self) -> None:
        self.output_box.tag_remove("find_match", "1.0", "end")
        self.output_box.tag_remove("find_current", "1.0", "end")

    def _refresh_find_matches(self) -> None:
        self._clear_find_highlights()
        self._find_matches = []
        self._find_index = -1
        query = self.find_query_var.get().strip()
        if not query:
            return

        cursor = "1.0"
        while True:
            match_start = self.output_box.search(query, cursor, nocase=True, stopindex="end-1c")
            if not match_start:
                break
            match_end = f"{match_start}+{len(query)}c"
            self._find_matches.append((match_start, match_end))
            self.output_box.tag_add("find_match", match_start, match_end)
            cursor = match_end

        if not self._find_matches:
            self.action_meta_var.set(f"No matches for '{query}' in the signal stream.")
            return

        self._find_index = 0
        self._focus_find_match()

    def _focus_find_match(self) -> None:
        if not self._find_matches:
            return
        self.output_box.tag_remove("find_current", "1.0", "end")
        start, end = self._find_matches[self._find_index]
        self.output_box.tag_add("find_current", start, end)
        self.output_box.see(start)
        self.action_meta_var.set(
            f"Find match {self._find_index + 1} of {len(self._find_matches)} in the signal stream."
        )

    def find_next_match(self) -> None:
        if not self._find_bar_visible:
            self.show_find_bar()
            return
        if not self._find_matches:
            self._refresh_find_matches()
            return
        self._find_index = (self._find_index + 1) % len(self._find_matches)
        self._focus_find_match()

    def find_previous_match(self) -> None:
        if not self._find_bar_visible:
            self.show_find_bar()
            return
        if not self._find_matches:
            self._refresh_find_matches()
            return
        self._find_index = (self._find_index - 1) % len(self._find_matches)
        self._focus_find_match()

    def on_execute(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.cancel_requested = True
            self._set_run_state("cancelling", action_meta="Termination signal sent to curl.")
            try:
                self.proc.terminate()
            except OSError:
                pass
            return

        raw = self.input_box.get("1.0", "end-1c")
        self.command_analysis = analyze_command(raw)
        if not self.command_analysis["normalized"]:
            self.action_meta_var.set("Paste a curl command before executing.")
            self._sync_ui_state()
            return

        if not self.command_analysis["valid"]:
            self._clear_output()
            error = self.command_analysis["error"]
            line_hint = self.command_analysis["error_line"]
            if line_hint is not None:
                self._append(f"Parse error: {error} - unclosed quote opens on line {line_hint}.\n")
            else:
                self._append(f"Parse error: {error}\n")
            self.last_exit_code = None
            self.last_elapsed = None
            self._set_run_state("parse error", action_meta="Execution blocked by a parse error.")
            return

        args = ["curl", *self.command_analysis["args"]]  # type: ignore[list-item]
        self._save_last(raw)
        self.cancel_requested = False
        self._clear_output()
        self.last_exit_code = None
        self.last_elapsed = None
        self.run_started_at = time.monotonic()
        self._set_run_state("running", action_meta="Streaming raw output. Use Execute again or Esc to cancel.")
        self._tick_elapsed()

        threading.Thread(target=self._run, args=(args,), daemon=True).start()

    def _tick_elapsed(self) -> None:
        if self.run_state not in {"running", "cancelling"} or self.run_started_at is None:
            return
        elapsed = time.monotonic() - self.run_started_at
        self.elapsed_var.set(f"{elapsed:.2f}s")
        self.stream_title_var.set(f"Signal Stream | elapsed {self.elapsed_var.get()}")
        self._sync_badge_colors()
        self.root.after(150, self._tick_elapsed)

    def _run(self, args: list[str]) -> None:
        start = time.monotonic()
        try:
            self.proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError:
            self.root.after(
                0,
                self._finish_error,
                "'curl' not found on PATH. Windows 10 (1803+) and Windows 11 ship curl.exe in System32.",
            )
            return
        except OSError as exc:
            self.root.after(0, self._finish_error, str(exc))
            return

        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.root.after(0, self._append, line)
        self.proc.wait()
        elapsed = time.monotonic() - start
        rc = self.proc.returncode
        self.root.after(0, self._finish_ok, rc, elapsed)

    def _finish_ok(self, rc: int, elapsed: float) -> None:
        self.last_exit_code = rc
        self.last_elapsed = elapsed
        self.elapsed_var.set(f"{elapsed:.2f}s")

        if self.cancel_requested and rc != 0:
            self._append(f"\n[cancelled with exit {rc} in {elapsed:.2f}s]\n")
            self._set_run_state("cancelled", action_meta="Execution stopped after a cancel request.")
        else:
            self._append(f"\n[exit {rc} in {elapsed:.2f}s]\n")
            self._set_run_state("done", action_meta="Execution finished. Raw output preserved in the stream.")

        self.execute_btn.configure(text="Execute")
        self.cancel_requested = False
        self.proc = None
        self.run_started_at = None
        self._sync_ui_state()

    def _finish_error(self, msg: str) -> None:
        self._append(f"Error: {msg}\n")
        self.last_exit_code = None
        self.last_elapsed = None
        self.run_started_at = None
        self.cancel_requested = False
        self.proc = None
        self._set_run_state("error", action_meta="curl could not be started. Inspect the signal stream.")


def main() -> None:
    if _IS_WINDOWS:
        try:
            _SHELL32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except OSError:
            pass
    root = tk.Tk()
    CurlSenderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
