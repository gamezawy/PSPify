# PSPify - Retro Game to PSP Homebrew Converter
# Copyright (C) 2026 Mahmoud Etman (Ruzzar)
# Licensed under the GNU General Public License v3 (see LICENSE).

"""
Reusable widgets.

None of these widgets hard-code a colour: they only set object names and
dynamic properties (``kind``, ``variant``, ``state``) that the stylesheet in
pspify_theme.py reacts to. That is what makes every theme work everywhere.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from pspify_core import SYSTEM_PRESETS, external_path, normalise_extensions
from pspify_qt import (
    AlignLeft, AlignVCenter, FramelessWindowHint, DialogWindow, NoFrame, PlainText,
    PointingHandCursor, ScrollBarAlwaysOff, SizeIgnored, SizePreferred, TabFocus,
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QProgressBar, QPushButton, QRadioButton, QScrollArea, QSize,
    QVBoxLayout, QWidget, exec_dialog, pyqtSignal,
)
from pspify_theme import theme_manager


# ---- small helpers --------------------------------------------------------------

def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property (kind, state, active ...) changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def make_label(text: str = "", name: str = "", wrap: bool = False, parent: Optional[QWidget] = None) -> QLabel:
    """A plain-text label with an object name the stylesheet can target."""
    label = QLabel(text, parent)
    if name:
        label.setObjectName(name)
    label.setTextFormat(PlainText)
    label.setWordWrap(wrap)
    return label


def make_button(text: str, name: str = "", tooltip: str = "", height: int = 0) -> QPushButton:
    """A push button that only takes keyboard focus via Tab (no sticky focus ring after a click)."""
    button = QPushButton(text)
    if name:
        button.setObjectName(name)
    if tooltip:
        button.setToolTip(tooltip)
    if height:
        button.setFixedHeight(height)
    button.setCursor(PointingHandCursor)
    button.setFocusPolicy(TabFocus)
    return button


def make_divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFixedHeight(1)
    return line


def elide_friendly(label: QLabel) -> QLabel:
    """Let a label be clipped instead of forcing the window wider when its text is long."""
    label.setSizePolicy(SizeIgnored, SizePreferred)
    return label


# ---- dialogs --------------------------------------------------------------------

class Alert(QDialog):
    """Themed, frameless message box. ``kind`` is 'info', 'warning' or 'error'."""

    def __init__(self, parent: Optional[QWidget], title: str, message: str, kind: str = "info",
                 confirm: bool = False, yes_text: str = "", no_text: str = ""):
        super().__init__(parent)
        self.setObjectName("Alert")
        self.setProperty("kind", kind)
        self.setWindowFlags(FramelessWindowHint | DialogWindow)
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setMaximumWidth(640)

        # QDialog only honours "background" in stylesheets, so the card surface and its
        # border live on an inner QFrame that fills the whole dialog.
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        body_frame = QFrame()
        body_frame.setObjectName("AlertBody")
        shell.addWidget(body_frame)
        layout = QVBoxLayout(body_frame)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(make_label(title, "AlertTitle", wrap=True))

        body = make_label(message, wrap=True)
        if message.count("\n") > 9:                      # long lists scroll instead of growing the dialog
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(NoFrame)
            scroll.setHorizontalScrollBarPolicy(ScrollBarAlwaysOff)
            scroll.setFixedHeight(220)
            scroll.setWidget(body)
            layout.addWidget(scroll)
        else:
            layout.addWidget(body)

        layout.addSpacing(6)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch()
        if confirm:
            no_button = make_button(no_text or "No", height=36)
            no_button.setMinimumWidth(90)
            no_button.clicked.connect(self.reject)
            buttons.addWidget(no_button)
        yes_button = make_button(yes_text or ("Yes" if confirm else "OK"), "Primary", height=36)
        yes_button.setMinimumWidth(90)
        yes_button.setDefault(True)
        yes_button.clicked.connect(self.accept)
        buttons.addWidget(yes_button)
        layout.addLayout(buttons)


def show_alert(parent: Optional[QWidget], title: str, message: str, kind: str = "info",
               confirm: bool = False, yes_text: str = "", no_text: str = "") -> bool:
    """Show an Alert and return True if the user accepted (OK / Yes)."""
    return bool(exec_dialog(Alert(parent, title, message, kind, confirm, yes_text, no_text)))


# ---- small controls -------------------------------------------------------------

class IconButton(QPushButton):
    """A square, borderless button showing one tinted icon."""

    _COLORS = {"danger": "error", "success": "success", "accent": "accent"}

    def __init__(self, icon_name: str, tooltip: str = "", variant: str = "neutral", size: int = 34):
        super().__init__()
        self.setObjectName("IconBtn")
        self.setProperty("variant", variant)
        self.setFixedSize(size, size)
        self.setIconSize(QSize(18, 18))
        self.setToolTip(tooltip)
        self.setCursor(PointingHandCursor)
        self.setFocusPolicy(TabFocus)
        self._icon_name = icon_name
        self._color_key = self._COLORS.get(variant, "text_dim")
        self.retheme()

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self.retheme()

    def retheme(self) -> None:
        """Re-tint the icon; called by the main window after every theme change."""
        self.setIcon(theme_manager.icon(self._icon_name, self._color_key))


class Chip(QLabel):
    """A small status pill. ``kind``: ok, warn, bad, busy or off."""

    def __init__(self, text: str = "", kind: str = "off"):
        super().__init__(text)
        self.setObjectName("Chip")
        self.setProperty("kind", kind)

    def set_state(self, text: str, kind: str, tooltip: str = "") -> None:
        self.setText(text)
        self.setProperty("kind", kind)
        self.setToolTip(tooltip)
        repolish(self)


# ---- Process page card ----------------------------------------------------------

class ProcessCard(QFrame):
    """Progress of one system while converting."""

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(make_label(title, "CardTitle"))
        top.addStretch()
        self.count_label = make_label("0 / 0", "Dim")
        self.chip = Chip("Running", "busy")
        top.addWidget(self.count_label)
        top.addWidget(self.chip)
        layout.addLayout(top)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        layout.addWidget(self.bar)

        self.status_label = elide_friendly(make_label("Starting...", "Hint"))
        layout.addWidget(self.status_label)

    def update_progress(self, done: int, total: int, text: str) -> None:
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)
        self.count_label.setText(f"{done} / {total}")
        self.status_label.setText(text)

    def finish(self, converted: int, problems: int, cancelled: bool) -> None:
        """Final look: green when clean, amber when something was skipped or cancelled."""
        if cancelled:
            self.chip.set_state("Cancelled", "warn")
            state = "warn"
        elif problems:
            self.chip.set_state(f"{problems} skipped", "warn")
            state = "warn"
        else:
            self.chip.set_state("Done", "ok")
            state = "done"
        self.bar.setProperty("state", state)
        repolish(self.bar)
        self.status_label.setText(f"{converted} converted" + (f", {problems} skipped" if problems else ""))


# ---- Systems page card ----------------------------------------------------------

class SystemCard(QFrame):
    """
    One system (NES, SNES ...) in the Systems page.

    Collapsed it shows name, ID, emulator, a status chip and quick actions.
    The edit form is created the first time the card is expanded, so a long
    list of systems stays cheap to build.

    Signals (the page persists the config, the card never touches it):
        saveRequested(card, new_id, data)
        removeRequested(card)
        enabledChanged(card, enabled)
    """

    saveRequested = pyqtSignal(object, str, object)
    removeRequested = pyqtSignal(object)
    enabledChanged = pyqtSignal(object, bool)

    def __init__(self, sid: str, data: Dict[str, Any], packer, is_new: bool = False):
        super().__init__()
        self.setObjectName("Card")
        self.sid = sid
        self.data = dict(data)
        self.packer = packer
        self.is_new = is_new
        self._loading = False
        self._dirty = False
        self._details: Optional[QWidget] = None
        self._last_emulator = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 14, 14)
        outer.setSpacing(12)
        outer.addLayout(self._build_header())

        if is_new:
            self._toggle_details()           # a brand new card opens straight into the form
            self._set_dirty(True)
        self._refresh_header()

    # ---- header ---------------------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = elide_friendly(make_label("", "CardTitle"))
        self.meta_label = elide_friendly(make_label("", "Hint"))
        titles.addWidget(self.title_label)
        titles.addWidget(self.meta_label)
        row.addLayout(titles, 1)

        self.chip = Chip()
        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.setToolTip("Disabled systems are skipped when you press Start")
        self.enabled_check.setChecked(not self.data.get("skipped", False))
        self.enabled_check.toggled.connect(self._on_enabled_toggled)

        self.expand_button = IconButton("arrow_down", "Show / hide details")
        self.expand_button.clicked.connect(self._toggle_details)
        self.remove_button = IconButton("remove", "Remove this system", variant="danger")
        self.remove_button.clicked.connect(self._on_remove)

        row.addWidget(self.chip, 0, AlignVCenter)
        row.addWidget(self.enabled_check, 0, AlignVCenter)
        row.addWidget(self.expand_button, 0, AlignVCenter)
        row.addWidget(self.remove_button, 0, AlignVCenter)
        return row

    def _refresh_header(self) -> None:
        """Update title, subtitle and status chip from the last SAVED data."""
        if self.is_new:
            self.title_label.setText("New system")
            self.meta_label.setText("Pick a system, an emulator and a ROM folder, then save")
            self.chip.set_state("Draft", "busy")
            self.enabled_check.setVisible(False)
            return
        emulator = self.data.get("emulator") or "No emulator"
        self.title_label.setText(self.data.get("name") or self.sid)
        self.meta_label.setText(f"{self.sid}  \u00b7  {emulator}")
        issue = self.packer.system_issue(self.data)
        if self.data.get("skipped"):
            self.chip.set_state("Disabled", "off", "This system is skipped when converting")
        elif issue:
            self.chip.set_state("Incomplete", "warn", issue)
        else:
            self.chip.set_state("Ready", "ok", "")

    def search_text(self) -> str:
        """Lower-case text the Systems page search box matches against."""
        return f"{self.data.get('name', '')} {self.sid} {self.data.get('emulator', '')}".lower()

    # ---- header actions -------------------------------------------------------

    def _on_enabled_toggled(self, checked: bool) -> None:
        if self._loading or self.is_new:
            return
        self.data["skipped"] = not checked
        self._refresh_header()
        self.enabledChanged.emit(self, checked)

    def _on_remove(self) -> None:
        if self.is_new:
            self.removeRequested.emit(self)
            return
        from_name = self.data.get("name") or self.sid
        if show_alert(self.window(), "Remove system?",
                      f"Remove '{from_name}' from PSPify?\n\nYour games, emulators and templates are not deleted.",
                      kind="warning", confirm=True, yes_text="Remove"):
            self.removeRequested.emit(self)

    def _toggle_details(self) -> None:
        if self._details is None:
            self._details = self._build_details()
            self.layout().addWidget(self._details)
            self._set_dirty(self._dirty)          # sync Save / Revert buttons now that the form exists
            opening = True
        else:
            opening = self._details.isHidden()       # isHidden = explicitly collapsed (isVisible is False for off-screen widgets too)
        self._details.setVisible(opening)
        self.expand_button.set_icon_name("arrow_up" if opening else "arrow_down")

    def collapse(self) -> None:
        if self._details is not None and not self._details.isHidden():
            self._toggle_details()

    # ---- edit form ------------------------------------------------------------

    def _build_details(self) -> QWidget:
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 0, 4, 0)
        box.setSpacing(12)
        box.addWidget(make_divider())

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        row = 0

        def label(text: str) -> QLabel:
            lab = make_label(text, "Dim")
            lab.setMinimumWidth(96)
            return lab

        # System preset (new systems only; an existing system's name is fixed)
        self.preset_combo = QComboBox() if self.is_new else None
        if self.is_new:
            self.preset_combo.addItem("Select a system...", "")
            for name in sorted(SYSTEM_PRESETS, key=str.lower):
                self.preset_combo.addItem(name, name)
            self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
            grid.addWidget(label("System"), row, 0, AlignVCenter)
            grid.addWidget(self.preset_combo, row, 1, 1, 2)
            row += 1

        self.id_edit = QLineEdit(self.sid)
        self.id_edit.setReadOnly(True)
        self.id_edit.setFixedWidth(110)
        self.id_edit.setToolTip("Used for the Games/<ID> folder and the CAT_<ID> folder on the PSP")
        grid.addWidget(label("ID"), row, 0, AlignVCenter)
        grid.addWidget(self.id_edit, row, 1, 1, 2, AlignLeft)
        row += 1

        cover_row = QHBoxLayout()
        cover_row.setSpacing(18)
        self.cover_group = QButtonGroup(panel)
        self.cover_buttons: Dict[str, QRadioButton] = {}
        for option in ("landscape", "portrait", "square"):
            button = QRadioButton(option.capitalize())
            self.cover_group.addButton(button)
            self.cover_buttons[option] = button
            button.toggled.connect(self._mark_dirty)
            cover_row.addWidget(button)
        cover_row.addStretch()
        grid.addWidget(label("Cover art"), row, 0, AlignVCenter)
        grid.addLayout(cover_row, row, 1, 1, 2)
        row += 1

        self.emulator_combo = QComboBox()
        self.emulator_combo.setToolTip("An emulator folder inside the Emulators folder")
        self.emulator_combo.activated.connect(self._on_emulator_chosen)
        self.emulator_combo.currentIndexChanged.connect(self._mark_dirty)
        grid.addWidget(label("Emulator"), row, 0, AlignVCenter)
        grid.addWidget(self.emulator_combo, row, 1, 1, 2)
        row += 1

        self.rom_edit = QLineEdit()
        self.rom_edit.setPlaceholderText("Folder inside the emulator, e.g. Roms")
        self.rom_edit.setToolTip("Where the emulator looks for ROMs, relative to the emulator folder")
        self.rom_edit.textChanged.connect(self._mark_dirty)
        rom_browse = make_button("Browse", tooltip="Pick the ROM folder inside the emulator")
        rom_browse.clicked.connect(self._browse_rom)
        grid.addWidget(label("ROM folder"), row, 0, AlignVCenter)
        grid.addWidget(self.rom_edit, row, 1)
        grid.addWidget(rom_browse, row, 2)
        row += 1

        self.ext_edit = QLineEdit()
        self.ext_edit.setPlaceholderText("e.g. .nes .fds")
        self.ext_edit.setToolTip("File extensions that count as ROMs, separated by spaces")
        self.ext_edit.textChanged.connect(self._mark_dirty)
        grid.addWidget(label("Extensions"), row, 0, AlignVCenter)
        grid.addWidget(self.ext_edit, row, 1, 1, 2)
        row += 1

        self.config_check = QCheckBox("Config file")
        self.config_check.setToolTip("Copy and patch an emulator config template for every game")
        self.config_edit = QLineEdit()
        self.config_edit.setPlaceholderText("Config/EmulatorName/file.ini")
        self.config_edit.textChanged.connect(self._mark_dirty)
        self.config_browse = make_button("Browse", tooltip="Pick a config template")
        self.config_browse.clicked.connect(self._browse_config)
        self.config_check.toggled.connect(self._on_config_toggled)
        grid.addWidget(self.config_check, row, 0, AlignVCenter)
        grid.addWidget(self.config_edit, row, 1)
        grid.addWidget(self.config_browse, row, 2)
        row += 1

        self.compress_check = QCheckBox("Compress each ROM into a .zip")
        self.compress_check.toggled.connect(self._mark_dirty)
        grid.addWidget(self.compress_check, row, 1, 1, 2)
        box.addLayout(grid)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.dirty_label = make_label("Unsaved changes", "Hint")
        self.dirty_label.setVisible(False)
        self.revert_button = make_button("Discard" if self.is_new else "Revert", height=34)
        self.revert_button.clicked.connect(self._on_revert)
        self.save_button = make_button("Save", "Primary", height=34)
        self.save_button.setMinimumWidth(90)
        self.save_button.clicked.connect(self._on_save)
        footer.addWidget(self.dirty_label)
        footer.addStretch()
        footer.addWidget(self.revert_button)
        footer.addWidget(self.save_button)
        box.addLayout(footer)

        self._load_fields()
        return panel

    def _emulator_names(self) -> List[str]:
        """Folders inside Emulators/, plus the saved one even if its folder vanished."""
        folder = self.packer.path("emulators_dir")
        names = sorted((d.name for d in folder.iterdir() if d.is_dir()), key=str.lower) if folder.is_dir() else []
        saved = self.data.get("emulator")
        if saved and saved not in names:
            names.insert(0, saved)
        return names

    def _load_fields(self) -> None:
        """Fill the form from the saved data (also used by Revert)."""
        self._loading = True
        try:
            data = self.data
            self.id_edit.setText(self.sid)
            for option, button in self.cover_buttons.items():
                button.setChecked(option == data.get("cover_art", "landscape"))

            self.emulator_combo.clear()
            self.emulator_combo.addItem("Select an emulator...", "")
            for name in self._emulator_names():
                self.emulator_combo.addItem(name, name)
            index = self.emulator_combo.findData(data.get("emulator", ""))
            self.emulator_combo.setCurrentIndex(max(index, 0))
            self._last_emulator = data.get("emulator", "")

            self.rom_edit.setText(data.get("roms_subdir", ""))
            self.ext_edit.setText(" ".join(data.get("rom_extensions", [])))
            has_config = bool(data.get("config_file"))
            self.config_check.setChecked(has_config)
            self.config_edit.setText(data.get("config_file") or "")
            self.config_edit.setEnabled(has_config)
            self.config_browse.setEnabled(has_config)
            self.compress_check.setChecked(bool(data.get("rom_compression", False)))
            self.enabled_check.setChecked(not data.get("skipped", False))
            if self.is_new:
                self.preset_combo.setCurrentIndex(0)
        finally:
            self._loading = False

    # ---- form behaviour ---------------------------------------------------------

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        if self._details is not None:
            self.dirty_label.setVisible(dirty)
            self.save_button.setEnabled(dirty)
            self.revert_button.setEnabled(dirty)

    def _mark_dirty(self, *_args) -> None:
        if not self._loading:
            self._set_dirty(True)

    def _on_preset_changed(self, index: int) -> None:
        """Picking a standard system fills in its ID, extensions and cover art."""
        if self._loading or index <= 0:
            return
        preset = SYSTEM_PRESETS.get(self.preset_combo.itemData(index))
        if not preset:
            return
        self._loading = True
        try:
            self.id_edit.setText(preset["id"])
            self.ext_edit.setText(preset["ext"])
            button = self.cover_buttons.get(preset["icon"])
            if button:
                button.setChecked(True)
        finally:
            self._loading = False
        self._set_dirty(True)

    def _on_emulator_chosen(self, _index: int) -> None:
        """A different emulator has a different layout: clear the paths tied to the old one."""
        chosen = self.emulator_combo.currentData() or ""
        if chosen != self._last_emulator:
            self._last_emulator = chosen
            self._loading = True
            try:
                self.rom_edit.clear()
                self.config_edit.clear()
                self.config_check.setChecked(False)
                self.config_edit.setEnabled(False)
                self.config_browse.setEnabled(False)
            finally:
                self._loading = False
            self._set_dirty(True)

    def _on_config_toggled(self, checked: bool) -> None:
        self.config_edit.setEnabled(checked)
        self.config_browse.setEnabled(checked)
        self._mark_dirty()

    def _browse_config(self) -> None:
        emulator = self.emulator_combo.currentData() or ""
        root = external_path("Config")
        if emulator and (root / emulator).is_dir():
            start = root / emulator
        else:
            start = root if root.is_dir() else external_path()
        chosen, _ = QFileDialog.getOpenFileName(self.window(), "Select a config template", str(start))
        if not chosen:
            return
        path = Path(chosen).resolve()
        try:                                  # inside the app folder -> store relative (portable)
            text = path.relative_to(external_path().resolve()).as_posix()
        except ValueError:
            text = path.as_posix()
        self.config_edit.setText(text)
        self.config_check.setChecked(True)

    def _browse_rom(self) -> None:
        emulator = self.emulator_combo.currentData() or ""
        if not emulator:
            show_alert(self.window(), "Choose an emulator first",
                       "Select the emulator before picking its ROM folder.", kind="warning")
            return
        base = (self.packer.path("emulators_dir") / emulator).resolve()
        chosen = QFileDialog.getExistingDirectory(self.window(), "Select the ROM folder", str(base))
        if not chosen:
            return
        try:
            self.rom_edit.setText(Path(chosen).resolve().relative_to(base).as_posix())
        except ValueError:
            self.rom_edit.setText(Path(chosen).name)

    def _on_revert(self) -> None:
        if self.is_new:
            self.removeRequested.emit(self)
            return
        self._load_fields()
        self._set_dirty(False)

    def _on_save(self) -> None:
        """Validate the form; on success hand the data to the page to persist."""
        window = self.window()
        if self.is_new:
            name = self.preset_combo.currentData() or ""
            new_id = self.id_edit.text().strip().upper()
            if not name:
                show_alert(window, "Missing system", "Choose a system from the list.", kind="error")
                return
        else:
            name, new_id = self.data.get("name", ""), self.sid

        emulator = self.emulator_combo.currentData() or ""
        rom_folder = self.rom_edit.text().strip().replace("\\", "/").strip("/")
        problem = None
        if not new_id:
            problem = "The system needs an ID."
        elif not emulator:
            problem = "Choose an emulator."
        elif not rom_folder:
            problem = "Enter the ROM folder (inside the emulator)."
        elif self.config_check.isChecked() and not self.config_edit.text().strip():
            problem = "Enter a config file path or untick \"Config file\"."
        if self.is_new and not problem and new_id in self.packer.config["systems"]:
            problem = f"A system with ID {new_id} already exists."
        extensions = normalise_extensions(self.ext_edit.text())
        if not problem and not extensions:
            problem = "Enter at least one ROM extension."
        if problem:
            show_alert(window, "Cannot save", problem, kind="error")
            return

        preset = SYSTEM_PRESETS.get(name)
        if preset:
            unusual = [e for e in extensions if e not in preset["ext"].split()]
            if unusual and not show_alert(
                    window, "Unusual extensions",
                    f"{', '.join(unusual)} are not typical for {name}.\nSave anyway?",
                    kind="warning", confirm=True, yes_text="Save anyway"):
                return

        cover = next((o for o, b in self.cover_buttons.items() if b.isChecked()), "landscape")
        data = {
            "name": name,
            "rom_extensions": extensions,
            "cover_art": cover,
            "emulator": emulator,
            "rom_filename": self.data.get("rom_filename", "game"),
            "roms_subdir": rom_folder,
            "rom_compression": self.compress_check.isChecked(),
            "config_file": self.config_edit.text().strip() if self.config_check.isChecked() else None,
            "skipped": not self.enabled_check.isChecked() if not self.is_new else False,
        }
        self.saveRequested.emit(self, new_id, data)

    def apply_saved(self, sid: str, data: Dict[str, Any]) -> None:
        """Called by the page after the config was written: show the saved state."""
        self.sid, self.data, self.is_new = sid, dict(data), False
        self.enabled_check.setVisible(True)
        self._refresh_header()
        if self._details is not None:
            self._load_fields()
            self.revert_button.setText("Revert")
        self._set_dirty(False)
