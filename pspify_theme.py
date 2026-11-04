# PSPify - Retro Game to PSP Homebrew Converter
# Copyright (C) 2026 Mahmoud Etman (Ruzzar)
# Licensed under the GNU General Public License v3 (see LICENSE).

"""
Theme system.

A theme is just a small table of colours (see THEMES). Everything the user
sees is derived from it:

    colours --> Theme (adds hover / soft / contrast colours)
            --> QSS stylesheet   (one template, filled in from the Theme)
            --> QPalette         (so parts QSS cannot reach still match)
            --> tinted SVG icons (one template file per icon, recoloured)

To add a built-in theme, add one entry to THEMES. Users can also drop a
``*.json`` file into the ``Themes`` folder next to the app:

    {"name": "My Theme", "base": "Dark", "colors": {"accent": "#FF8800"}}

Only the keys you list are overridden; the rest come from ``base``.
This module imports no Qt at load time, so the colour and stylesheet logic can
be tested without a display.
"""

import json
import re
import tempfile
from pathlib import Path
from string import Template
from typing import Dict, List, Optional

from pspify_core import resource_path

# ---- colour tables ------------------------------------------------------------

REQUIRED_KEYS = ("bg", "sidebar", "card", "input", "border", "text", "text_dim",
                 "accent", "success", "warning", "error")

THEMES: Dict[str, Dict[str, object]] = {
    "Dark": {
        "dark": True, "bg": "#0F1115", "sidebar": "#14171C", "card": "#1A1E25", "input": "#232831",
        "border": "#2C323C", "text": "#E6E8EC", "text_dim": "#98A0AD", "accent": "#4C8DFF",
        "success": "#34C77B", "warning": "#F5A524", "error": "#F0616D",
    },
    "Light": {
        "dark": False, "bg": "#F3F5F9", "sidebar": "#FFFFFF", "card": "#FFFFFF", "input": "#F1F3F7",
        "border": "#DDE1E8", "text": "#1B1F27", "text_dim": "#5E6675", "accent": "#2F6BFF",
        "success": "#18884A", "warning": "#A35F00", "error": "#D93A47",
    },
    "Midnight": {
        "dark": True, "bg": "#000000", "sidebar": "#07080A", "card": "#0E1013", "input": "#171A1F",
        "border": "#22262D", "text": "#ECEEF2", "text_dim": "#8E96A3", "accent": "#8B7CFF",
        "success": "#3ED598", "warning": "#FFB84D", "error": "#FF6B7A",
    },
    "Nord": {
        "dark": True, "bg": "#2E3440", "sidebar": "#272C36", "card": "#3B4252", "input": "#434C5E",
        "border": "#4C566A", "text": "#ECEFF4", "text_dim": "#B0BACB", "accent": "#88C0D0",
        "success": "#A3BE8C", "warning": "#EBCB8B", "error": "#E8909A",
    },
}

DEFAULT_THEME = "Dark"

# Accent colours the user can pick in Settings ("Default" keeps the theme's own).
ACCENTS: Dict[str, str] = {
    "Blue": "#3D7EFF", "Violet": "#8B6CFF", "Teal": "#1FB6A6",
    "Green": "#2EBD6B", "Orange": "#F08A24", "Pink": "#E8508F",
}

FONT_STACK = '"Segoe UI", "Inter", "Noto Sans", "Ubuntu", "Cantarell", "Helvetica Neue", Arial, sans-serif'

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


# ---- colour maths ---------------------------------------------------------------

def _rgb(value: str):
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def mix(a: str, b: str, amount: float) -> str:
    """Blend colour ``a`` towards ``b`` by ``amount`` (0..1); both are '#RRGGBB'."""
    ra, rb = _rgb(a), _rgb(b)
    return "#%02X%02X%02X" % tuple(round(x * (1 - amount) + y * amount) for x, y in zip(ra, rb))


def luminance(value: str) -> float:
    """Relative luminance (WCAG) of '#RRGGBB'."""
    def channel(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def readable_on(background: str) -> str:
    """White if it has at least 3:1 contrast on ``background`` (bold UI text), else near-black."""
    return "#FFFFFF" if 1.05 / (luminance(background) + 0.05) >= 3.0 else "#10131A"


def ensure_contrast(color: str, background: str, target: float, toward: str) -> str:
    """Nudge ``color`` towards ``toward`` until it has ``target``:1 contrast on ``background``."""
    def ratio(a: str, b: str) -> float:
        hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)
    for step in range(21):
        candidate = mix(color, toward, step * 0.05)
        if ratio(candidate, background) >= target:
            return candidate
    return toward


# ---- Theme ----------------------------------------------------------------------

class Theme:
    """A resolved theme: the base colours plus every derived colour the stylesheet needs."""

    def __init__(self, name: str, colors: Dict[str, object], accent: Optional[str] = None):
        c = {k: v for k, v in colors.items() if k != "dark"}
        if accent:
            c["accent"] = accent
        self.name = name
        self.dark = bool(colors.get("dark", True))
        c["on_accent"] = readable_on(c["accent"])
        c["accent_hover"] = mix(c["accent"], "#FFFFFF" if self.dark else "#000000", 0.14)
        c["hover"] = mix(c["card"], c["text"], 0.07)
        c["pressed"] = mix(c["card"], c["text"], 0.13)
        c["handle"] = mix(c["border"], c["text_dim"], 0.5)
        c["disabled"] = mix(c["text_dim"], c["card"], 0.55)
        c["accent_soft"] = mix(c["card"], c["accent"], 0.22)
        for key in ("success", "warning", "error"):
            c[key + "_soft"] = mix(c["card"], c[key], 0.20)
        c["on_error"] = readable_on(c["error"])
        # The accent used as TEXT (brand, busy chip) must stay readable on light surfaces too.
        c["accent_text"] = ensure_contrast(c["accent"], c["accent_soft"], 4.0, c["text"])
        self.c: Dict[str, str] = c

    def __getattr__(self, key: str) -> str:
        try:
            return self.__dict__["c"][key]
        except KeyError:
            raise AttributeError(key) from None


def load_custom_themes(folder: Path) -> Dict[str, Dict[str, object]]:
    """Read user themes from ``folder/*.json``. Invalid files are ignored, never fatal."""
    found: Dict[str, Dict[str, object]] = {}
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            name = str(data["name"]).strip()
            base = THEMES.get(str(data.get("base", DEFAULT_THEME)), THEMES[DEFAULT_THEME])
            colors = dict(base)
            for key, value in dict(data.get("colors", {})).items():
                if key in REQUIRED_KEYS and isinstance(value, str) and _HEX.match(value):
                    colors[key] = value.upper()
            if "dark" in data:
                colors["dark"] = bool(data["dark"])
            if name and name not in THEMES:
                found[name] = colors
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return found


def resolve_theme(name: str, accent_name: str = "Default",
                  custom: Optional[Dict[str, Dict[str, object]]] = None) -> Theme:
    """Theme by name (falls back to Dark) with an optional accent override."""
    table = dict(THEMES)
    table.update(custom or {})
    if name not in table:
        name = DEFAULT_THEME
    accent = ACCENTS.get(accent_name)
    if accent_name and _HEX.match(accent_name):
        accent = accent_name.upper()
    return Theme(name, table[name], accent)


# ---- icons ----------------------------------------------------------------------

# Every file in Resources/SVG is drawn in this colour; it is swapped for the
# requested tint, so one file serves every theme and state.
ICON_TEMPLATE_COLOR = "#E8EAED"


class IconCache:
    """Writes tinted copies of the SVG templates into a temp folder and returns their paths.

    Qt stylesheets can only reference icons by file path, so tinted files are
    kept on disk (a few hundred bytes each) and reused between runs.
    """

    def __init__(self, source_dir: Optional[Path] = None, cache_dir: Optional[Path] = None):
        self.source_dir = source_dir or resource_path("Resources/SVG")
        self.cache_dir = cache_dir or Path(tempfile.gettempdir()) / "pspify-icons"
        self._templates: Dict[str, str] = {}

    def path(self, name: str, color: str) -> str:
        """Path (forward slashes, as Qt stylesheets require) of icon ``name`` tinted ``color``."""
        template = self._templates.get(name)
        if template is None:
            template = (self.source_dir / f"{name}.svg").read_text(encoding="utf-8")
            self._templates[name] = template
        target = self.cache_dir / f"{name}_{color.lstrip('#').lower()}.svg"
        if not target.exists():
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                temp = target.with_suffix(".tmp")
                temp.write_text(re.sub(ICON_TEMPLATE_COLOR, color, template, flags=re.IGNORECASE), encoding="utf-8")
                temp.replace(target)
            except OSError:
                return (self.source_dir / f"{name}.svg").as_posix()   # untinted but still shows
        return target.as_posix()


# ---- stylesheet -----------------------------------------------------------------

# $tokens are filled from Theme.c (plus the icon paths). Selector cheat sheet:
#   #Nav #Primary #Danger #IconBtn #Swatch   push buttons
#   #Card                                     rounded surface
#   #Chip[kind="ok|warn|off|bad"]             status pill
STYLESHEET = Template("""
QWidget { font-family: $font; font-size: 13px; }
QMainWindow, QDialog { background-color: $bg; }
QToolTip { background-color: $card; color: $text; border: 1px solid $border; padding: 5px 8px; }

/* ---- sidebar ---- */
QFrame#Sidebar { background-color: $sidebar; border: none; border-right: 1px solid $border; }
QLabel#Brand { color: $accent_text; font-size: 24px; font-weight: 800; }
QLabel#BrandSub { color: $text_dim; font-size: 11px; }
QPushButton#Nav { background: transparent; border: none; border-radius: 10px; color: $text_dim;
    text-align: left; padding: 0 14px; font-size: 14px; font-weight: 600; }
QPushButton#Nav:hover { background-color: $hover; color: $text; }
QPushButton#Nav[active="true"] { background-color: $accent; color: $on_accent; }
QPushButton#Nav:disabled { color: $disabled; background: transparent; }
QPushButton#Nav[active="true"]:disabled { background-color: $accent_soft; color: $text_dim; }

/* ---- text ---- */
QLabel#PageTitle { font-size: 26px; font-weight: 700; }
QLabel#PageSub { color: $text_dim; font-size: 13px; }
QLabel#CardTitle { font-size: 15px; font-weight: 600; }
QLabel#Section { color: $text_dim; font-size: 11px; font-weight: 700; }
QLabel#Dim { color: $text_dim; }
QLabel#Hint { color: $text_dim; font-size: 12px; }
QLabel#Stat { font-size: 22px; font-weight: 700; }
QLabel#Empty { color: $text_dim; font-size: 14px; }

QLabel#Chip { border-radius: 10px; padding: 2px 10px; font-size: 11px; font-weight: 700;
    background-color: $border; color: $text_dim; }
QLabel#Chip[kind="ok"] { background-color: $success_soft; color: $success; }
QLabel#Chip[kind="warn"] { background-color: $warning_soft; color: $warning; }
QLabel#Chip[kind="bad"] { background-color: $error_soft; color: $error; }
QLabel#Chip[kind="busy"] { background-color: $accent_soft; color: $accent_text; }

/* ---- surfaces ---- */
QFrame#Card { background-color: $card; border: 1px solid $border; border-radius: 12px; }
QFrame#Divider { background-color: $border; border: none; max-height: 1px; min-height: 1px; }
QDialog#Alert { background-color: $card; }
QFrame#AlertBody { background-color: $card; border: 1px solid $border; }
QLabel#AlertTitle { font-size: 17px; font-weight: 700; }
QDialog#Alert[kind="error"] QLabel#AlertTitle { color: $error; }
QDialog#Alert[kind="warning"] QLabel#AlertTitle { color: $warning; }

/* ---- buttons ---- */
QPushButton { background-color: $input; border: 1px solid $border; border-radius: 8px; color: $text;
    padding: 7px 16px; font-weight: 600; }
QPushButton:hover { background-color: $hover; border-color: $handle; }
QPushButton:pressed { background-color: $pressed; }
QPushButton:focus { border-color: $accent; }
QPushButton:disabled { background-color: $input; border-color: $border; color: $disabled; }

QPushButton#Primary { background-color: $accent; border: 1px solid $accent; color: $on_accent; font-size: 14px; }
QPushButton#Primary:hover { background-color: $accent_hover; border-color: $accent_hover; }
QPushButton#Primary:pressed { background-color: $accent; }
QPushButton#Primary:disabled { background-color: $accent_soft; border-color: $accent_soft; color: $text_dim; }

QPushButton#Danger { background-color: $error; border: 1px solid $error; color: $on_error; font-size: 14px; }
QPushButton#Danger:hover { background-color: $error_soft; border-color: $error; color: $error; }

QPushButton#IconBtn { background: transparent; border: none; border-radius: 8px; padding: 0; }
QPushButton#IconBtn:hover { background-color: $hover; }
QPushButton#IconBtn[variant="danger"]:hover { background-color: $error_soft; }
QPushButton#IconBtn[variant="accent"]:hover { background-color: $accent_soft; }
QPushButton#IconBtn:disabled { background: transparent; }

QPushButton#Swatch { border: 2px solid transparent; border-radius: 14px; padding: 0;
    min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; }
QPushButton#Swatch:hover { border: 2px solid $handle; }
QPushButton#Swatch[selected="true"] { border: 2px solid $text; }

/* ---- inputs ---- */
QLineEdit, QComboBox { background-color: $input; border: 1px solid $border; border-radius: 8px;
    color: $text; padding: 6px 10px; min-height: 20px; selection-background-color: $accent;
    selection-color: $on_accent; }
QLineEdit:hover, QComboBox:hover { border-color: $handle; }
QLineEdit:focus, QComboBox:focus, QComboBox:on { border-color: $accent; }
QLineEdit:disabled, QComboBox:disabled { color: $disabled; background-color: $card; }
QLineEdit:read-only { color: $text_dim; }

QComboBox { combobox-popup: 0; padding-right: 26px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 26px;
    border: none; }
QComboBox::down-arrow { image: url($icon_arrow); width: 10px; height: 6px; }
QComboBox QAbstractItemView { background-color: $card; color: $text; border: 1px solid $border;
    outline: 0; padding: 4px; selection-background-color: $accent; selection-color: $on_accent; }
QComboBox QAbstractItemView::item { min-height: 26px; padding: 2px 8px; border-radius: 4px; }

QCheckBox, QRadioButton { spacing: 8px; background: transparent; }
QCheckBox:disabled, QRadioButton:disabled { color: $disabled; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $handle; border-radius: 5px;
    background-color: $input; }
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background-color: $accent; border-color: $accent; image: url($icon_check); }
QCheckBox::indicator:disabled { background-color: $border; border-color: $border; }
QRadioButton::indicator { width: 16px; height: 16px; border: 1px solid $handle; border-radius: 9px;
    background-color: $input; }
QRadioButton::indicator:hover { border-color: $accent; }
QRadioButton::indicator:checked { border-color: $accent; image: url($icon_dot); }
QRadioButton::indicator:disabled { background-color: $border; border-color: $border; }

/* ---- progress ---- */
QProgressBar { background-color: $border; border: none; border-radius: 3px; min-height: 6px;
    max-height: 6px; text-align: center; color: transparent; }
QProgressBar::chunk { background-color: $accent; border-radius: 3px; }
QProgressBar[state="done"]::chunk { background-color: $success; }
QProgressBar[state="warn"]::chunk { background-color: $warning; }
QProgressBar[state="bad"]::chunk { background-color: $error; }

/* ---- scrolling ---- */
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:vertical { background-color: $handle; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:horizontal { background-color: $handle; border-radius: 3px; min-width: 30px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background-color: $text_dim; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; background: none; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
""")


def build_stylesheet(theme: Theme, icons: IconCache) -> str:
    """Fill the stylesheet template with a theme's colours and tinted icon paths."""
    tokens = dict(theme.c)
    tokens["font"] = FONT_STACK
    tokens["icon_arrow"] = icons.path("arrow_down", theme.text_dim)
    tokens["icon_check"] = icons.path("check", theme.on_accent)
    tokens["icon_dot"] = icons.path("dot", theme.accent)
    return STYLESHEET.substitute(tokens)


def build_palette(theme: Theme):
    """QPalette matching the theme, so anything QSS does not cover still looks right."""
    from pspify_qt import QColor, QPalette, PaletteDisabled, palette_role

    palette = QPalette()

    def put(role: str, color: str, disabled: bool = False) -> None:
        if disabled:
            palette.setColor(PaletteDisabled, palette_role(role), QColor(color))
        else:
            palette.setColor(palette_role(role), QColor(color))

    for role, color in (
        ("Window", theme.bg), ("WindowText", theme.text), ("Base", theme.input),
        ("AlternateBase", theme.card), ("Text", theme.text), ("Button", theme.input),
        ("ButtonText", theme.text), ("BrightText", theme.text), ("ToolTipBase", theme.card),
        ("ToolTipText", theme.text), ("Highlight", theme.accent), ("HighlightedText", theme.on_accent),
        ("Link", theme.accent), ("LinkVisited", theme.accent), ("PlaceholderText", theme.text_dim),
        ("Light", theme.hover), ("Midlight", theme.card), ("Mid", theme.border),
        ("Dark", theme.border), ("Shadow", theme.bg),
    ):
        put(role, color)
    for role in ("WindowText", "Text", "ButtonText"):
        put(role, theme.disabled, disabled=True)
    return palette


# ---- manager --------------------------------------------------------------------

class ThemeManager:
    """Holds the active theme and applies it to the whole application."""

    def __init__(self) -> None:
        self.icons = IconCache()
        self.theme = resolve_theme(DEFAULT_THEME)
        self.custom: Dict[str, Dict[str, object]] = {}
        self._qicons: Dict[str, object] = {}

    def theme_names(self) -> List[str]:
        return list(THEMES) + list(self.custom)

    def load_custom(self, folder: Path) -> None:
        self.custom = load_custom_themes(folder)

    def apply(self, app, name: str, accent: str = "Default") -> Theme:
        """Switch theme: palette first, then the stylesheet, on the QApplication."""
        self.theme = resolve_theme(name, accent, self.custom)
        app.setPalette(build_palette(self.theme))
        app.setStyleSheet(build_stylesheet(self.theme, self.icons))
        return self.theme

    def icon(self, name: str, color_key: str = "text_dim"):
        """QIcon of icon ``name`` tinted with a theme colour (e.g. 'accent', 'error')."""
        from pspify_qt import QIcon
        path = self.icons.path(name, self.theme.c[color_key])
        icon = self._qicons.get(path)
        if icon is None:
            icon = self._qicons[path] = QIcon(path)
        return icon


theme_manager = ThemeManager()
