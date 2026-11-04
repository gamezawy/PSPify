#!/usr/bin/env python3
# PSPify - Retro Game to PSP Homebrew Converter
# Copyright (C) 2026 Mahmoud Etman (Ruzzar)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
PSPify GUI: the application window and its three pages.

    MainWindow       sidebar + page stack, starts / cancels conversions
    ProcessPage      live progress of a conversion and its summary
    SystemsPage      add / edit / enable the systems (cards live in pspify_widgets)
    SettingsPage     theme, storage root, folders, credits

All conversion work happens in pspify_core.PSPEmulatorPacker.convert(), run on
a QThread so the window never freezes.
"""

import os
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pspify_core import (
    APP_NAME, APP_VERSION, TOOL_INFO, PSPEmulatorPacker, external_path, format_elapsed, locate_tool,
    missing_ffmpeg_libraries, missing_tools, resource_path,
)
from pspify_qt import (
    QT_API, AlignCenter, AlignTop, AlignVCenter, KeepAspectRatio, PointingHandCursor, RichText,
    ScrollBarAlwaysOff, SmoothTransformation, TabFocus, TextBrowserInteraction, NoFrame,
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDesktopServices, QFileDialog, QFrame, QHBoxLayout, QIcon,
    QLabel, QLineEdit, QMainWindow, QPixmap, QProgressBar, QPushButton, QRadioButton, QScrollArea,
    QSize, QStackedWidget, QThread, QTimer, QUrl, QVBoxLayout, QWidget, exec_app, prepare_high_dpi,
    pyqtSignal,
)
from pspify_theme import ACCENTS, resolve_theme, theme_manager
from pspify_widgets import (
    Chip, IconButton, ProcessCard, SystemCard, elide_friendly, make_button, make_label, repolish, show_alert,
)

SIDEBAR_WIDTH = 220
NAV_ITEMS = (("Process", "nav_process"), ("Systems", "nav_sys"), ("Settings", "nav_set"))


# =============================================================================
# Background worker
# =============================================================================

class ConversionWorker(QThread):
    """Runs PSPEmulatorPacker.convert() off the GUI thread."""

    progress = pyqtSignal(str, int, int, str)       # system id, games done, games total, last game
    completed = pyqtSignal(object)                  # summary dict

    def __init__(self, packer: PSPEmulatorPacker, targets: List[Any]):
        super().__init__()
        self.packer = packer
        self.targets = targets
        self._cancel = threading.Event()

    def request_cancel(self) -> None:
        """Ask the engine to stop; games already running finish, no new ones start."""
        self._cancel.set()

    def run(self) -> None:
        try:
            summary = self.packer.convert(self.targets, progress=self.progress.emit,
                                          cancelled=self._cancel.is_set)
        except Exception as exc:        # never let an unexpected error kill the thread silently
            summary = {"success": 0, "grouped_skips": {}, "cancelled": False, "total": 0,
                       "last_sys": None, "last_folder": None,
                       "error": f"{type(exc).__name__}: {exc}"}
        self.completed.emit(summary)


# =============================================================================
# Process page
# =============================================================================

class ProcessPage(QWidget):
    """Shows what is happening during a conversion, then a summary of the result."""

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.win = window
        self.cards: Dict[str, ProcessCard] = {}
        self._done: Dict[str, int] = {}
        self._totals: Dict[str, int] = {}
        self._expected = 0
        self._has_run = False

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 0)
        root.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(make_label("Process", "PageTitle"))
        self.subtitle = make_label("", "PageSub")
        titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)
        self.clear_button = IconButton("clear", "Clear results")
        self.clear_button.clicked.connect(self.clear)
        header.addWidget(self.clear_button, 0, AlignTop)
        root.addLayout(header)

        # ---- overview card (shown from the first run on) ----
        self.overview = QFrame()
        self.overview.setObjectName("Card")
        self.overview.setVisible(False)
        overview = QVBoxLayout(self.overview)
        overview.setContentsMargins(20, 16, 20, 16)
        overview.setSpacing(12)
        stats = QHBoxLayout()
        stats.setSpacing(36)
        self.stat_values: List[QLabel] = []
        self.stat_captions: List[QLabel] = []
        for _ in range(3):
            column = QVBoxLayout()
            column.setSpacing(0)
            value = make_label("-", "Stat")
            caption = make_label("", "Dim")
            column.addWidget(value)
            column.addWidget(caption)
            stats.addLayout(column)
            self.stat_values.append(value)
            self.stat_captions.append(caption)
        stats.addStretch()
        overview.addLayout(stats)
        self.overall_bar = QProgressBar()
        self.overall_bar.setTextVisible(False)
        overview.addWidget(self.overall_bar)
        self.detail_label = make_label("", "Hint", wrap=True)
        self.detail_label.setVisible(False)
        overview.addWidget(self.detail_label)
        self.actions = QWidget()
        actions = QHBoxLayout(self.actions)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        open_output = make_button("Open output folder", height=34)
        open_output.clicked.connect(lambda: self.win.open_path(self.win.packer.path("output_dir")))
        open_log = make_button("Open log", height=34)
        open_log.clicked.connect(lambda: self.win.open_path(external_path("PSPify.log")))
        actions.addWidget(open_output)
        actions.addWidget(open_log)
        actions.addStretch()
        self.actions.setVisible(False)
        overview.addWidget(self.actions)
        root.addWidget(self.overview)

        # ---- per-system cards ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(NoFrame)
        scroll.setHorizontalScrollBarPolicy(ScrollBarAlwaysOff)
        content = QWidget()
        self.cards_layout = QVBoxLayout(content)
        self.cards_layout.setContentsMargins(0, 0, 10, 16)
        self.cards_layout.setSpacing(12)
        self.empty_label = make_label("", "Empty", wrap=True)
        self.empty_label.setAlignment(AlignCenter)
        self.cards_layout.addWidget(self.empty_label)
        self.cards_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.refresh_idle()

    # ---- idle / empty state ---------------------------------------------------

    def refresh_idle(self) -> None:
        """Describe what Start will do when nothing has run yet."""
        if self.cards or self._has_run:
            return
        packer = self.win.packer
        ready = incomplete = 0
        for sid, cfg in packer.config["systems"].items():
            if cfg.get("skipped"):
                continue
            if packer.system_issue(cfg):
                incomplete += 1
            else:
                ready += 1
        if ready:
            self.subtitle.setText("Ready to convert")
            text = f"{ready} system{'s' if ready != 1 else ''} ready to convert."
            if incomplete:
                text += f"\n{incomplete} need{'s' if incomplete == 1 else ''} attention on the Systems page."
            text += "\n\nPress Start to build the PSP packages from your Games folder."
        else:
            self.subtitle.setText("Nothing to convert yet")
            text = ("Set up a system first.\n\nPut game folders in Games/<System ID>, then open the Systems "
                    "page and choose an emulator and ROM folder for each system.")
        self.empty_label.setText(text)
        self.empty_label.setVisible(True)

    # ---- a run -----------------------------------------------------------------

    def begin(self, targets: List[Any], total_games: int) -> None:
        self._remove_cards()
        self._has_run = True
        self._expected = max(total_games, 1)
        self.empty_label.setVisible(False)
        self.overview.setVisible(True)
        self.detail_label.setVisible(False)
        self.actions.setVisible(False)
        self.overall_bar.setRange(0, self._expected)
        self.overall_bar.setValue(0)
        self.overall_bar.setProperty("state", "")
        repolish(self.overall_bar)
        self._set_stats(("0", "Processed"), (f"0 / {len(targets)}", "Systems"), ("00:00:00", "Elapsed"))
        self.subtitle.setText("Converting...")
        for sid, _folder, cfg in targets:
            card = ProcessCard(f"{cfg.get('name') or sid}  ({sid})")
            self.cards[sid] = card
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
        self.clear_button.setEnabled(False)

    def on_progress(self, sid: str, done: int, total: int, text: str) -> None:
        card = self.cards.get(sid)
        if card is None:
            return
        card.update_progress(done, total, text)
        self._done[sid], self._totals[sid] = done, total
        processed = sum(self._done.values())
        self.overall_bar.setValue(min(processed, self._expected))
        finished = sum(1 for k, t in self._totals.items() if self._done.get(k, 0) >= t)
        self._set_stats((str(processed), None), (f"{finished} / {len(self.cards)}", None), (None, None))

    def set_elapsed(self, text: str) -> None:
        self.stat_values[2].setText(text)

    def finish(self, summary: Dict[str, Any], elapsed: str) -> None:
        packer = self.win.packer
        skips: Dict[str, List[Any]] = {}
        for (sid, _kind), items in summary.get("grouped_skips", {}).items():
            skips.setdefault(sid, []).extend(items)
        cancelled = bool(summary.get("cancelled"))
        for sid, card in self.cards.items():
            converted = len(packer.mappings.get(sid, []))
            incomplete = self._done.get(sid, 0) < self._totals.get(sid, 0) or sid not in self._totals
            card.finish(converted, len(skips.get(sid, [])), cancelled and incomplete)

        total_skips = sum(len(v) for v in skips.values())
        self._set_stats((str(summary.get("success", 0)), "Converted"), (str(total_skips), "Skipped"),
                        (elapsed, "Elapsed"))
        state = "warn" if (cancelled or total_skips) else "done"
        if summary.get("error"):
            state = "bad"
        self.overall_bar.setProperty("state", state)
        repolish(self.overall_bar)
        if not cancelled:
            self.overall_bar.setValue(self._expected)

        lines = [f"\u2022 {name} ({sid}): {reason}"
                 for sid, items in sorted(skips.items()) for name, reason in sorted(items)]
        lines += [f"\u2022 {name} ({sid}): {text}" for sid, name, text in sorted(summary.get("warnings", []))]
        if summary.get("error"):
            lines.insert(0, f"Stopped by an unexpected error: {summary['error']}")
        if lines:
            shown = lines[:6]
            if len(lines) > 6:
                shown.append(f"... and {len(lines) - 6} more (see PSPify.log)")
            self.detail_label.setText("\n".join(shown))
            self.detail_label.setVisible(True)
        self.actions.setVisible(True)
        self.subtitle.setText("Cancelled" if cancelled else f"Finished in {elapsed}")
        self.clear_button.setEnabled(True)

    def _set_stats(self, *items) -> None:
        """Each item is (value or None, caption or None); None leaves that part unchanged."""
        for index, (value, caption) in enumerate(items):
            if value is not None:
                self.stat_values[index].setText(value)
            if caption is not None:
                self.stat_captions[index].setText(caption)

    # ---- clearing --------------------------------------------------------------

    def _remove_cards(self) -> None:
        for card in self.cards.values():
            self.cards_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self.cards.clear()
        self._done.clear()
        self._totals.clear()

    def clear(self) -> None:
        if self.win.is_running():
            return
        self._remove_cards()
        self._has_run = False
        self.overview.setVisible(False)
        self.refresh_idle()


# =============================================================================
# Systems page
# =============================================================================

class SystemsPage(QWidget):
    """List of configured systems with search, add, edit, enable and remove."""

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.win = window
        self.cards: List[SystemCard] = []
        self.stale = True

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 0)
        root.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(make_label("Systems", "PageTitle"))
        self.subtitle = make_label("", "PageSub")
        titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search systems")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(210)
        self.search.textChanged.connect(self.apply_filter)
        header.addWidget(self.search, 0, AlignVCenter)
        add_button = make_button("Add system", "Primary", "Add a new system", height=36)
        add_button.clicked.connect(self.add_new)
        header.addWidget(add_button, 0, AlignVCenter)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(NoFrame)
        scroll.setHorizontalScrollBarPolicy(ScrollBarAlwaysOff)
        content = QWidget()
        self.list_layout = QVBoxLayout(content)
        self.list_layout.setContentsMargins(0, 2, 10, 16)
        self.list_layout.setSpacing(12)
        self.empty_label = make_label("", "Empty", wrap=True)
        self.empty_label.setAlignment(AlignCenter)
        self.list_layout.addWidget(self.empty_label)
        self.list_layout.addStretch(1)
        self.scroll = scroll
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def on_show(self) -> None:
        if self.stale:
            self.rebuild()

    def rebuild(self) -> None:
        """Recreate every card from the config (after systems were added or removed)."""
        for card in self.cards:
            self.list_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self.cards = []
        systems = self.win.packer.config["systems"]
        for sid in sorted(systems, key=lambda k: str(systems[k].get("name", "")).lower()):
            self._add_card(SystemCard(sid, systems[sid], self.win.packer))
        self.stale = False
        self.apply_filter()
        self.update_subtitle()

    def _add_card(self, card: SystemCard, at_top: bool = False) -> None:
        card.saveRequested.connect(self._on_save)
        card.removeRequested.connect(self._on_remove)
        card.enabledChanged.connect(self._on_enabled)
        index = 1 if at_top else self.list_layout.count() - 1      # index 0 is the empty label
        self.list_layout.insertWidget(index, card)
        self.cards.append(card)

    def add_new(self) -> None:
        """Open a blank card at the top (only one draft at a time)."""
        if any(c.is_new for c in self.cards):
            return
        self.search.clear()
        for card in self.cards:
            card.collapse()
        blank = {"name": "", "emulator": "", "rom_extensions": [], "rom_filename": "game",
                 "roms_subdir": "", "cover_art": "landscape", "rom_compression": False,
                 "config_file": None, "skipped": False}
        self._add_card(SystemCard("", blank, self.win.packer, is_new=True), at_top=True)
        self.apply_filter()
        self.scroll.verticalScrollBar().setValue(0)

    def apply_filter(self, *_args) -> None:
        query = self.search.text().strip().lower()
        visible = 0
        for card in self.cards:
            show = card.is_new or query in card.search_text()
            card.setVisible(show)
            visible += show
        if visible:
            self.empty_label.setVisible(False)
        else:
            self.empty_label.setText("No systems match your search." if self.cards else
                                     "No systems yet.\n\nPress \"Add system\", or create a folder named after a "
                                     "system (for example SNES) inside Games and restart PSPify.")
            self.empty_label.setVisible(True)

    def update_subtitle(self) -> None:
        packer = self.win.packer
        systems = packer.config["systems"]
        ready = sum(1 for c in systems.values() if not c.get("skipped") and not packer.system_issue(c))
        self.subtitle.setText(f"{len(systems)} configured  \u00b7  {ready} ready")

    # ---- card signals -----------------------------------------------------------

    def _on_save(self, card: SystemCard, new_id: str, data: Dict[str, Any]) -> None:
        systems = self.win.packer.config["systems"]
        if not card.is_new and card.sid != new_id:
            systems.pop(card.sid, None)
        systems[new_id] = data
        if not self.win.save_config():
            return
        if card.is_new:
            self.rebuild()                    # re-sort so the new system lands in its place
        else:
            card.apply_saved(new_id, data)
            self.update_subtitle()

    def _on_remove(self, card: SystemCard) -> None:
        if card.is_new:
            self.cards.remove(card)
            self.list_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
            self.apply_filter()
            return
        self.win.packer.config["systems"].pop(card.sid, None)
        if self.win.save_config():
            self.rebuild()

    def _on_enabled(self, card: SystemCard, enabled: bool) -> None:
        system = self.win.packer.config["systems"].get(card.sid)
        if system is not None:
            system["skipped"] = not enabled
            self.win.save_config()
            self.update_subtitle()


# =============================================================================
# Settings page
# =============================================================================

class SettingsPage(QWidget):
    """Theme, storage root, visual assets, folder shortcuts and credits."""

    CREDITS = (
        '<p><b>GBA2PSP</b> \u2013 <a href="http://github.com/sahlberg/gba2psp">github.com/sahlberg/gba2psp</a><br>'
        "PBOOT.PBP processing and audio processing code are based on this project.</p>"
        '<p><b>FFmpeg</b> \u2013 <a href="https://ffmpeg.org">ffmpeg.org</a><br>'
        "Not included with PSPify; you install it separately. Used to decode your music files.</p>"
        '<p><b>atracdenc</b> \u2013 <a href="https://github.com/dcherednik/atracdenc">github.com/dcherednik/atracdenc</a><br>'
        "Not included with PSPify; you install it separately. Used for Sony ATRAC3 audio encoding.</p>"
        '<p><b>TempGBA4PSP-Single-game</b> \u2013 '
        '<a href="https://github.com/GrabowskiDev/TempGBA4PSP-Single-game">github.com/GrabowskiDev/TempGBA4PSP-Single-game</a><br>'
        "PBOOT.PBP structure initially sourced from this project.</p>"
        '<p><b>PyQt / Qt</b> \u2013 <a href="https://www.riverbankcomputing.com/software/pyqt/">riverbankcomputing.com</a><br>'
        "Used for the user interface.</p>"
        "<p>See <i>THIRD_PARTY_NOTICES.txt</i> next to PSPify for all notices.</p>"
    )

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.win = window
        config = window.packer.config

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 26, 28, 0)
        outer.setSpacing(14)
        outer.addWidget(make_label("Settings", "PageTitle"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(NoFrame)
        scroll.setHorizontalScrollBarPolicy(ScrollBarAlwaysOff)
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 10, 16)
        column.setSpacing(14)

        # ---- Appearance ----
        card, box = self._card("APPEARANCE")
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(make_label("Theme", "Dim"))
        self.theme_combo = QComboBox()
        self.theme_combo.setMinimumWidth(180)
        self.theme_combo.addItems(theme_manager.theme_names())
        self.theme_combo.setCurrentText(config["settings"].get("theme", "Dark"))
        self.theme_combo.currentTextChanged.connect(self.win.set_theme)
        row.addWidget(self.theme_combo)
        row.addStretch()
        box.addLayout(row)

        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(8)
        swatch_row.addWidget(make_label("Accent", "Dim"))
        swatch_row.addSpacing(8)
        self.swatches: Dict[str, QPushButton] = {}
        for name in ("Default",) + tuple(ACCENTS):
            button = QPushButton()
            button.setObjectName("Swatch")
            button.setCursor(PointingHandCursor)
            button.setFocusPolicy(TabFocus)
            button.setToolTip("Theme default" if name == "Default" else name)
            button.clicked.connect(lambda _checked=False, n=name: self.win.set_accent(n))
            swatch_row.addWidget(button)
            self.swatches[name] = button
        swatch_row.addStretch()
        box.addLayout(swatch_row)
        column.addWidget(card)

        # ---- Storage ----
        card, box = self._card("PSP STORAGE")
        self.storage_group = QButtonGroup(card)
        memory_stick = QRadioButton("Memory Stick  (ms0:/)")
        internal = QRadioButton("Internal storage  (ef0:/)  \u2013 PSP Go only")
        for button in (memory_stick, internal):
            self.storage_group.addButton(button)
            box.addWidget(button)
        (internal if config["psp_path"].get("storage_root") == "ef0:/" else memory_stick).setChecked(True)
        memory_stick.toggled.connect(lambda on: on and self._set_storage("ms0:/"))
        internal.toggled.connect(lambda on: on and self._set_storage("ef0:/"))
        box.addWidget(make_label("Where the packages will live on the PSP. Written into each emulator config.",
                                 "Hint", wrap=True))
        column.addWidget(card)

        # ---- XMB display ----
        card, box = self._card("XMB DISPLAY")
        self.shadow_check = QCheckBox("Add a soft drop shadow to PIC0 (the logo shown in the XMB)")
        self.shadow_check.setChecked(bool(config["images"].get("pic0_add_shadow", True)))
        self.shadow_check.toggled.connect(self._set_shadow)
        box.addWidget(self.shadow_check)

        self.title_check = QCheckBox("Use the game's folder name as its title")
        self.title_check.setChecked(bool(config["xmb"].get("title_from_folder", True)))
        self.title_check.toggled.connect(lambda on: self._set_xmb("title_from_folder", on))
        box.addWidget(self.title_check)
        box.addWidget(make_label("Tags such as (USA), [!] and (Rev 1) are removed, and \"Zelda, The\" becomes "
                                 "\"The Zelda\". Without this, every game shows the template title \"PSPify\".",
                                 "Hint", wrap=True))

        self.eboot_check = QCheckBox("Also patch EBOOT.PBP with the game's icon, backgrounds, music and title")
        self.eboot_check.setChecked(bool(config["xmb"].get("patch_eboot", False)))
        self.eboot_check.toggled.connect(lambda on: self._set_xmb("patch_eboot", on))
        box.addWidget(self.eboot_check)
        box.addWidget(make_label("For launchers other than the XMB, which show EBOOT.PBP instead of PBOOT.PBP. "
                                 "Only the copy in the Output folder is changed, never your emulator. "
                                 "Off by default.", "Hint", wrap=True))
        column.addWidget(card)

        # ---- Audio tools (installed by the user) ----
        card, box = self._card("AUDIO TOOLS  (OPTIONAL)")
        box.addWidget(make_label(
            "Only needed for background music (SND0). PSPify does not include these programs: install them "
            "so they are on your PATH, put them next to PSPify or in a Tools folder, or choose the "
            "executable here.", "Hint", wrap=True))
        self.tool_chips: Dict[str, Chip] = {}
        self.tool_paths: Dict[str, QLabel] = {}
        self.tool_auto_buttons: Dict[str, QPushButton] = {}
        for key, (display, purpose, _url) in TOOL_INFO.items():
            head = QHBoxLayout()
            head.setSpacing(10)
            title = make_label(display, "CardTitle")
            title.setToolTip(purpose.capitalize())
            chip = Chip()
            browse = make_button("Browse", tooltip=f"Choose the {display} executable", height=32)
            browse.clicked.connect(lambda _checked=False, k=key: self._browse_tool(k))
            auto = make_button("Auto", tooltip="Forget the chosen file and detect it automatically", height=32)
            auto.clicked.connect(lambda _checked=False, k=key: self._reset_tool(k))
            head.addWidget(title)
            head.addWidget(chip)
            head.addStretch()
            head.addWidget(browse)
            head.addWidget(auto)
            box.addLayout(head)
            path_label = elide_friendly(make_label("", "Hint"))
            box.addWidget(path_label)
            self.tool_chips[key], self.tool_paths[key], self.tool_auto_buttons[key] = chip, path_label, auto
        links = QLabel("Get them: " + "  \u00b7  ".join(
            f'<a href="{url}">{display}</a>' for display, _purpose, url in TOOL_INFO.values()))
        links.setTextFormat(RichText)
        links.setOpenExternalLinks(True)
        links.setTextInteractionFlags(TextBrowserInteraction)
        box.addWidget(links)
        column.addWidget(card)

        # ---- Folders ----
        card, box = self._card("FOLDERS")
        folders = QHBoxLayout()
        folders.setSpacing(10)
        for text, key in (("Games", "games_dir"), ("Emulators", "emulators_dir"), ("Output", "output_dir")):
            button = make_button(f"Open {text}", height=34)
            button.clicked.connect(lambda _checked=False, k=key: self.win.open_path(self.win.packer.path(k)))
            folders.addWidget(button)
        folders.addStretch()
        box.addLayout(folders)
        column.addWidget(card)

        # ---- About ----
        card, box = self._card("ABOUT")
        box.addWidget(make_label(f"{APP_NAME} {APP_VERSION}", "CardTitle"))
        box.addWidget(make_label("Free software released under the GNU General Public License v3.", "Hint", wrap=True))
        box.addWidget(make_label("THIRD-PARTY CREDITS", "Section"))
        credits = QLabel(self.CREDITS)
        credits.setTextFormat(RichText)
        credits.setOpenExternalLinks(True)
        credits.setTextInteractionFlags(TextBrowserInteraction)
        credits.setWordWrap(True)
        box.addWidget(credits)
        column.addWidget(card)
        column.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.refresh_swatches()
        self.refresh_tools()

    @staticmethod
    def _card(title: str):
        card = QFrame()
        card.setObjectName("Card")
        box = QVBoxLayout(card)
        box.setContentsMargins(20, 16, 20, 18)
        box.setSpacing(12)
        box.addWidget(make_label(title, "Section"))
        return card, box

    def refresh_swatches(self) -> None:
        """Paint each swatch and mark the selected one (called after theme / accent changes)."""
        settings = self.win.packer.config["settings"]
        current = settings.get("accent", "Default")
        default_accent = resolve_theme(settings.get("theme", "Dark"), "Default", theme_manager.custom).accent
        for name, button in self.swatches.items():
            color = default_accent if name == "Default" else ACCENTS[name]
            button.setStyleSheet(f"background-color: {color};")
            button.setProperty("selected", name == current)
            repolish(button)

    def refresh_tools(self) -> None:
        """Show whether each audio tool was found, and where."""
        chosen = self.win.packer.config["settings"].get("tools", {})
        for key, (display, _purpose, _url) in TOOL_INFO.items():
            path, where = locate_tool(key)
            if path:
                self.tool_chips[key].set_state("Found", "ok")
                self.tool_paths[key].setText(f"{where}: {path}")
            else:
                self.tool_chips[key].set_state("Not installed", "warn")
                note = "The file you chose no longer exists. " if chosen.get(key) else ""
                self.tool_paths[key].setText(f"{note}Not found. Install {display} or press Browse.")
            self.tool_auto_buttons[key].setEnabled(bool(chosen.get(key)))

    def _browse_tool(self, key: str) -> None:
        display = TOOL_INFO[key][0]
        current, _where = locate_tool(key)
        start = str(Path(current).parent) if current else str(external_path())
        chosen, _ = QFileDialog.getOpenFileName(self.win, f"Select the {display} executable", start)
        if not chosen:
            return
        if not Path(chosen).is_file():
            show_alert(self.win, "File not found", f"{chosen} does not exist.", kind="error")
            return
        self.win.packer.set_tool_path(key, chosen)
        self.win.save_config()
        self.refresh_tools()

    def _reset_tool(self, key: str) -> None:
        self.win.packer.set_tool_path(key, None)
        self.win.save_config()
        self.refresh_tools()

    def _set_storage(self, root: str) -> None:
        self.win.packer.config["psp_path"]["storage_root"] = root
        self.win.save_config()

    def _set_xmb(self, key: str, enabled: bool) -> None:
        self.win.packer.config["xmb"][key] = bool(enabled)
        self.win.save_config()

    def _set_shadow(self, enabled: bool) -> None:
        self.win.packer.config["images"]["pic0_add_shadow"] = bool(enabled)
        self.win.save_config()


# =============================================================================
# Main window
# =============================================================================

class MainWindow(QMainWindow):
    """Sidebar navigation, page stack and the Start / Cancel controls."""

    def __init__(self, packer: PSPEmulatorPacker, app: QApplication):
        super().__init__()
        self.packer = packer
        self.app = app
        self.worker: Optional[ConversionWorker] = None
        self._started_at = 0.0
        self._nav_index = 0

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(900, 600)
        width, height = self._saved_size()
        self.resize(width, height)
        icon_file = resource_path("Resources/Icon/app_icon.png")
        if icon_file.is_file():
            self.setWindowIcon(QIcon(str(icon_file)))

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.process_page = ProcessPage(self)
        self.systems_page = SystemsPage(self)
        self.settings_page = SettingsPage(self)
        for page in (self.process_page, self.systems_page, self.settings_page):
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)

        self.timer = QTimer(self)                  # drives the "Elapsed" counter while converting
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

        self._retheme_icons()
        self.set_active_page(0)
        self._update_titlebar()
        QTimer.singleShot(0, self._startup_checks)   # show the window first, then any alerts

    # ---- construction -----------------------------------------------------------

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 26, 18, 20)
        layout.setSpacing(6)

        logo = QLabel()
        logo.setAlignment(AlignCenter)
        logo_file = resource_path("Resources/Icon/app_logo.png")
        if logo_file.is_file():
            ratio = max(1.0, self.devicePixelRatioF())
            pixmap = QPixmap(str(logo_file)).scaled(int(150 * ratio), int(96 * ratio),
                                                    KeepAspectRatio, SmoothTransformation)
            pixmap.setDevicePixelRatio(ratio)
            logo.setPixmap(pixmap)
        else:
            logo.setText(APP_NAME)
            logo.setObjectName("Brand")
        layout.addWidget(logo)
        layout.addSpacing(22)

        self.nav_buttons: List[QPushButton] = []
        for index, (text, _icon) in enumerate(NAV_ITEMS):
            button = QPushButton(text)
            button.setObjectName("Nav")
            button.setFixedHeight(42)
            button.setIconSize(QSize(18, 18))
            button.setCursor(PointingHandCursor)
            button.setFocusPolicy(TabFocus)
            button.setProperty("active", False)
            button.clicked.connect(lambda _checked=False, i=index: self.set_active_page(i))
            layout.addWidget(button)
            self.nav_buttons.append(button)

        layout.addStretch(1)
        self.start_button = make_button("Start", "Primary", height=46)
        self.start_button.clicked.connect(self.start_conversion)
        self.cancel_button = make_button("Cancel", "Danger", height=46)
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_conversion)
        layout.addWidget(self.start_button)
        layout.addWidget(self.cancel_button)
        layout.addSpacing(6)
        layout.addWidget(make_label(f"v{APP_VERSION}", "BrandSub"), 0, AlignCenter)
        return sidebar

    def _saved_size(self):
        saved = self.packer.config["settings"].get("window")
        if isinstance(saved, list) and len(saved) == 2 and all(isinstance(v, int) for v in saved):
            return max(900, min(saved[0], 4000)), max(600, min(saved[1], 3000))
        return 1080, 700

    # ---- navigation -------------------------------------------------------------

    def set_active_page(self, index: int) -> None:
        self._nav_index = index
        for i, button in enumerate(self.nav_buttons):
            button.setProperty("active", i == index)
            repolish(button)
        self._refresh_nav_icons()
        self.stack.setCurrentIndex(index)
        if index == 0:
            self.process_page.refresh_idle()
        elif index == 1:
            self.systems_page.on_show()

    def _refresh_nav_icons(self) -> None:
        for i, (button, (_text, icon)) in enumerate(zip(self.nav_buttons, NAV_ITEMS)):
            button.setIcon(theme_manager.icon(icon, "on_accent" if i == self._nav_index else "text_dim"))

    # ---- theme ------------------------------------------------------------------

    def set_theme(self, name: str) -> None:
        if not name or name == self.packer.config["settings"].get("theme"):
            return
        self.packer.config["settings"]["theme"] = name
        self._apply_theme()
        self.save_config()

    def set_accent(self, name: str) -> None:
        if name == self.packer.config["settings"].get("accent"):
            return
        self.packer.config["settings"]["accent"] = name
        self._apply_theme()
        self.save_config()

    def _apply_theme(self) -> None:
        settings = self.packer.config["settings"]
        theme_manager.apply(self.app, settings.get("theme", "Dark"), settings.get("accent", "Default"))
        self._retheme_icons()
        self.settings_page.refresh_swatches()
        self._update_titlebar()

    def _retheme_icons(self) -> None:
        """Icons are tinted files, so they must be re-tinted after the colours change."""
        for button in self.findChildren(IconButton):
            button.retheme()
        self._refresh_nav_icons()

    def _update_titlebar(self) -> None:
        """Windows 10/11: match the native title bar to a dark / light theme."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            value = ctypes.c_int(1 if theme_manager.theme.dark else 0)
            hwnd = int(self.winId())
            for attribute in (20, 19):        # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old numbering)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value),
                                                           ctypes.sizeof(value))
        except Exception:
            pass

    # ---- helpers ----------------------------------------------------------------

    def save_config(self) -> bool:
        """Write config.json; tell the user if that fails."""
        try:
            self.packer.save_config()
            return True
        except OSError as exc:
            show_alert(self, "Could not save settings", f"config.json could not be written:\n{exc}", kind="error")
            return False

    def open_path(self, path: Path) -> None:
        """Open a folder or file with the system's default app (creates folders that are missing)."""
        try:
            if path.suffix == "":
                path.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                show_alert(self, "Nothing to open", f"{path.name} does not exist yet.", kind="info")
                return
        except OSError:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def is_running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    # ---- startup ----------------------------------------------------------------

    def _startup_checks(self) -> None:
        packer = self.packer
        if packer.config_notice:
            show_alert(self, "Settings were reset", packer.config_notice, kind="warning")
        problem = packer.template_problem()
        if problem:
            show_alert(self, "PSPify is incomplete",
                       f"{problem}\n\nReinstall PSPify; conversion cannot work without this file.", kind="error")

        added, unknown = packer.detect_systems()
        if added:
            self.save_config()
            self.systems_page.stale = True
        if unknown:
            show_alert(self, "Unrecognised folders",
                       "These folders in Games do not match any known system id and will be ignored:\n\n"
                       + "\n".join(f"\u2022 {name}" for name in unknown)
                       + "\n\nName them after a system id (for example SNES).",
                       kind="warning")

        libraries = missing_ffmpeg_libraries()
        tools = missing_tools()
        if libraries:
            show_alert(self, "FFmpeg is missing libraries",
                       "FFmpeg needs libraries that are not installed:\n\n"
                       + "\n".join(f"\u2022 {name}" for name in libraries)
                       + "\n\nInstall FFmpeg with your package manager (for example: sudo apt install ffmpeg). "
                         "Until then, background music (SND0) is skipped.", kind="warning")
        elif tools:
            show_alert(self, "Audio tools not found",
                       "Not installed:\n" + "\n".join(f"\u2022 {name}" for name in tools)
                       + "\n\nGames still convert, but background music (SND0) is skipped. PSPify does not "
                         "include these programs: install them so they are on your PATH, or choose their "
                         "location under Settings \u2192 Audio tools (download links are there too).", kind="warning")
        self.process_page.refresh_idle()

    # ---- conversion ---------------------------------------------------------------

    def start_conversion(self) -> None:
        if self.is_running():
            return
        packer = self.packer
        if not self.save_config():
            return
        problem = packer.template_problem()
        if problem:
            show_alert(self, "Cannot convert", problem, kind="error")
            return

        targets, incomplete, no_config = [], [], []
        for sid, cfg in packer.config["systems"].items():
            if cfg.get("skipped"):
                continue
            folder = packer.find_system_folder(sid)
            if folder is None or not any(d.is_dir() for d in folder.iterdir()):
                continue
            issue = packer.system_issue(cfg)
            if issue:
                incomplete.append(f"{cfg.get('name') or sid}: {issue}")
                continue
            run_cfg = dict(cfg)
            if packer.config_file_missing(cfg):
                no_config.append(cfg.get("name") or sid)
                run_cfg["config_file"] = None              # convert anyway, just without patching
            targets.append((sid, folder, run_cfg))

        if not targets:
            if incomplete:
                show_alert(self, "Nothing ready to convert",
                           "These systems need attention first:\n\n" + "\n".join(f"\u2022 {t}" for t in incomplete),
                           kind="warning")
                self.set_active_page(1)
            else:
                show_alert(self, "Nothing to convert",
                           "No game folders were found for any enabled system.\n\n"
                           "Put each game in its own folder inside Games/<System ID>/.", kind="info")
            return
        if no_config and not show_alert(
                self, "Config template not found",
                "The config template of these systems could not be found:\n\n"
                + "\n".join(f"\u2022 {n}" for n in no_config)
                + "\n\nGames will be converted, but the emulator config will not be patched.",
                kind="warning", confirm=True, yes_text="Convert anyway"):
            return
        if incomplete and not show_alert(
                self, "Some systems will be skipped",
                "These systems are incomplete and will be skipped:\n\n" + "\n".join(f"\u2022 {t}" for t in incomplete),
                kind="warning", confirm=True, yes_text="Continue"):
            return

        total = sum(sum(1 for d in folder.iterdir() if d.is_dir()) for _s, folder, _c in targets)
        self._set_running(True)
        self.process_page.begin(targets, total)
        self.set_active_page(0)
        self._started_at = time.perf_counter()
        self.timer.start()
        self.worker = ConversionWorker(packer, targets)
        self.worker.progress.connect(self.process_page.on_progress)
        self.worker.completed.connect(self._on_completed)
        self.worker.start()

    def cancel_conversion(self) -> None:
        if self.is_running():
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("Cancelling...")
            self.process_page.subtitle.setText("Cancelling... finishing the games already running")
            self.worker.request_cancel()

    def _tick(self) -> None:
        self.process_page.set_elapsed(format_elapsed(time.perf_counter() - self._started_at))

    def _on_completed(self, summary: Dict[str, Any]) -> None:
        self.timer.stop()
        elapsed = format_elapsed(time.perf_counter() - self._started_at)
        try:
            self.packer.write_mapping_log(elapsed, summary)
        except Exception:
            pass
        self.process_page.finish(summary, elapsed)
        self._set_running(False)
        if summary.get("error"):
            show_alert(self, "Conversion stopped", summary["error"], kind="error")
        self.worker = None

    def _set_running(self, running: bool) -> None:
        self.start_button.setVisible(not running)
        self.cancel_button.setVisible(running)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Cancel")
        for index, button in enumerate(self.nav_buttons):
            button.setEnabled(not running or index == 0)

    # ---- closing ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self.is_running():
            if not show_alert(self, "Conversion in progress", "Stop the conversion and quit?",
                              kind="warning", confirm=True, yes_text="Stop and quit"):
                event.ignore()
                return
            self.worker.request_cancel()
            self.worker.wait(15000)
        if not self.isMaximized():
            self.packer.config["settings"]["window"] = [self.width(), self.height()]
            try:
                self.packer.save_config()
            except OSError:
                pass
        event.accept()


# =============================================================================
# Entry point
# =============================================================================

def install_crash_logging() -> None:
    """Log unhandled exceptions to PSPify-crash.log instead of letting Qt abort the app."""
    def log(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            with open(external_path("PSPify-crash.log"), "a", encoding="utf-8") as handle:
                handle.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{text}")
        except OSError:
            pass
        sys.stderr.write(text)

    sys.excepthook = log
    threading.excepthook = lambda args: log(args.exc_type, args.exc_value, args.exc_traceback)


def warn_if_xcb_cursor_missing() -> None:
    """Qt 6.5+ on X11 needs libxcb-cursor0; without it the app cannot start at all."""
    if QT_API != 6 or not sys.platform.startswith("linux") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return
    import ctypes.util
    if not ctypes.util.find_library("xcb-cursor"):
        sys.stderr.write("[!] Qt 6 needs libxcb-cursor0 on X11. Install it with: sudo apt install libxcb-cursor0\n")


def main() -> int:
    install_crash_logging()
    prepare_high_dpi()
    warn_if_xcb_cursor_missing()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")                 # one consistent base on every OS; the theme does the rest

    packer = PSPEmulatorPacker()
    theme_manager.load_custom(external_path("Themes"))
    settings = packer.config["settings"]
    theme_manager.apply(app, settings.get("theme", "Dark"), settings.get("accent", "Default"))

    window = MainWindow(packer, app)
    window.show()
    return exec_app(app)


if __name__ == "__main__":
    sys.exit(main())
