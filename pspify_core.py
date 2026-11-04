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
PSPify backend (no Qt dependency).

Turns folders of classic ROMs into ready-to-play PSP homebrew packages:
asset resizing, audio conversion, emulator config patching and PBP (EBOOT)
rebuilding.  The GUI (pspify_gui.py) and the command line entry point at the
bottom of this file both drive the same ``PSPEmulatorPacker.convert()``.

Module map
    1. Paths and external tools (ffmpeg / atracdenc are installed by the user)
    2. Configuration (load / normalise / save)
    3. System presets
    4. PBP container helpers, PARAM.SFO and XMB titles
    5. Game ID registry
    6. Asset processing (images + audio)
    7. The packer engine
    8. Command line interface
"""

from __future__ import annotations

import io
import itertools
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageFilter

APP_NAME = "PSPify"
APP_VERSION = "1.0"

# Number of games converted in parallel. Each worker may run ffmpeg, so a
# small pool keeps CPU and memory use modest even on low-end machines.
MAX_WORKERS = max(1, min(4, os.cpu_count() or 2))

# Pillow >= 9.1 moved the resampling filters into Image.Resampling.
_RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS


# =============================================================================
# 1. Paths and external tools (ffmpeg / atracdenc are installed by the user)
# =============================================================================

def app_dir() -> Path:
    """Folder that holds config.json, Games/, Emulators/ ... (next to the EXE)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def external_path(name: str = "") -> Path:
    """Path of a file or folder that lives OUTSIDE the bundle, next to the app."""
    return app_dir() / name if name else app_dir()


def resource_path(relative: str) -> Path:
    """Path of a read-only file bundled INSIDE the app (Resources/...).

    Uses the module location, not the working directory, so the app also runs
    when launched from another folder.
    """
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent
    return root / relative


# The audio tools are NOT shipped with PSPify: the user installs them (see README.txt).
TOOL_INFO: Dict[str, Tuple[str, str, str]] = {
    # key: (display name, what it is used for, where to get it)
    "ffmpeg": ("FFmpeg", "decodes your music files", "https://ffmpeg.org/download.html"),
    "atracdenc": ("atracdenc", "encodes Sony ATRAC3 audio", "https://github.com/dcherednik/atracdenc/releases"),
}

# Executables the user picked in Settings (name -> path). Filled from config.json.
_tool_overrides: Dict[str, str] = {}


def _exe_name(name: str) -> str:
    return name + (".exe" if os.name == "nt" else "")


@lru_cache(maxsize=None)
def _auto_find(name: str) -> Tuple[Optional[str], str]:
    """Look in the app folder, a Tools/ folder next to it, then on PATH."""
    exe = _exe_name(name)
    base = app_dir()
    for folder, label in ((base, "app folder"), (base / "Tools", "Tools folder"),
                          (base / "Tools" / name, "Tools folder")):
        candidate = folder / exe
        if candidate.is_file():
            return str(candidate), label
    found = shutil.which(name)
    return (found, "PATH") if found else (None, "")


def locate_tool(name: str) -> Tuple[Optional[str], str]:
    """(path, where it was found) of an audio tool, or (None, "") when it is not installed.

    Search order: the path chosen in Settings, the app folder, Tools/, then PATH.
    """
    custom = _tool_overrides.get(name)
    if custom and Path(custom).is_file():
        return custom, "custom path"
    return _auto_find(name)


def find_tool(name: str) -> Optional[str]:
    """Path of ffmpeg / atracdenc, or None when the user has not installed it."""
    return locate_tool(name)[0]


find_tool.cache_clear = _auto_find.cache_clear      # tests and Settings reset the PATH lookup


def set_tool_override(name: str, path: Optional[str]) -> None:
    """Remember (or forget, with None) an executable chosen by the user."""
    if path:
        _tool_overrides[name] = path
    else:
        _tool_overrides.pop(name, None)


def missing_tools() -> List[str]:
    """Human readable list of the optional audio tools that are not installed."""
    return [f"{display} ({purpose})" for key, (display, purpose, _url) in TOOL_INFO.items()
            if not find_tool(key)]


def missing_ffmpeg_libraries() -> List[str]:
    """Linux only: shared libraries the ffmpeg binary needs but cannot find.

    Returns an empty list when everything is fine or when it cannot be checked
    (statically linked binary, no ``ldd``, not on Linux).
    """
    ffmpeg = find_tool("ffmpeg")
    if not ffmpeg or not sys.platform.startswith("linux") or not shutil.which("ldd"):
        return []
    try:
        result = subprocess.run(["ldd", ffmpeg], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    # A line looks like: "libavcodec.so.61 => not found"
    return [line.split()[0] for line in result.stdout.splitlines() if "not found" in line]


def ensure_config_templates() -> None:
    """Restore the external Config/ folder from the bundled Config.zip if it is missing."""
    target = external_path("Config")
    if target.exists():
        return
    archive = resource_path("Resources/Config.zip")
    if not archive.is_file():
        print("[!] Config.zip not found inside the app; templates were not restored.")
        return
    root = app_dir().resolve()
    try:
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                destination = (root / member.filename).resolve()
                # Skip anything that would land outside the app folder (zip-slip guard).
                if destination != root and root not in destination.parents:
                    continue
                zf.extract(member, root)
        print("[+] Config templates restored.")
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"[!] Failed to restore config templates: {exc}")


def ensure_docs() -> None:
    """Frozen builds only: place README, licence and notices next to the EXE if missing."""
    if not getattr(sys, "frozen", False):
        return
    for source, target in (("README.txt", "README.txt"), ("LICENSE", "LICENSE.txt"),
                           ("THIRD_PARTY_NOTICES.txt", "THIRD_PARTY_NOTICES.txt")):
        destination = external_path(target)
        bundled = resource_path(f"Resources/Docs/{source}")
        if not destination.exists() and bundled.is_file():
            try:
                shutil.copyfile(bundled, destination)
            except OSError:
                pass


# =============================================================================
# 2. Configuration
# =============================================================================

class PSPConstants:
    """Technical limits and sizes required by the PSP XMB (Cross Media Bar)."""
    ICON_SIZES = {
        "landscape": (144, 80),   # NES / SNES style
        "square": (80, 80),       # GB / GBC / GBA style
        "portrait": (60, 80),     # Sega style
    }
    PIC0_SIZE = (310, 180)        # Title overlay shown on the right of the XMB
    PIC1_SIZE = (480, 272)        # Full-screen background
    MAX_AUDIO_DURATION = 59       # seconds of SND0 the XMB will play
    MAX_AUDIO_SIZE = 500000       # bytes of ATRAC3 payload the XMB accepts
    AT3_BLOCK_ALIGN = 384         # ATRAC3 132 kbps stereo frame size in bytes


DEFAULT_CONFIG: Dict[str, Any] = {
    "systems": {},
    "paths": {"emulators_dir": "Emulators", "games_dir": "Games", "output_dir": "Output"},
    "psp_path": {"storage_root": "ms0:/"},
    "images": {"pic0_add_shadow": True},
    "xmb": {"title_from_folder": True, "patch_eboot": False},
    "settings": {"theme": "Dark", "accent": "Default", "tools": {}},
}

# Every system entry in config.json is completed with these defaults.
SYSTEM_DEFAULTS: Dict[str, Any] = {
    "name": "",
    "rom_extensions": [],
    "cover_art": "landscape",
    "emulator": "",
    "rom_filename": "game",
    "roms_subdir": "",
    "rom_compression": False,
    "config_file": None,
    "skipped": False,
}

_STORAGE_ROOTS = ("ms0:/", "ef0:/")


def normalise_extensions(value: Any) -> List[str]:
    """Accept a list or a space/comma separated string; return ['.nes', '.fds']."""
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    result = []
    for item in value or []:
        cleaned = re.sub(r"[^A-Za-z0-9]", "", str(item)).lower()
        if cleaned and f".{cleaned}" not in result:
            result.append(f".{cleaned}")
    return result


def normalize_config(raw: Any) -> Dict[str, Any]:
    """Return a complete, well-typed config, tolerating hand-edited or older files."""
    cfg: Dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))      # deep copy
    if not isinstance(raw, dict):
        return cfg
    for section in ("paths", "psp_path", "images", "xmb", "settings"):
        if isinstance(raw.get(section), dict):
            cfg[section].update(raw[section])
    cfg["settings"].pop("use_fusion", None)         # the style toggle no longer exists
    cfg["xmb"] = {"title_from_folder": bool(cfg["xmb"].get("title_from_folder", True)),
                  "patch_eboot": bool(cfg["xmb"].get("patch_eboot", False))}
    tools = cfg["settings"].get("tools")
    cfg["settings"]["tools"] = ({str(k): str(v) for k, v in tools.items() if k in TOOL_INFO and v}
                                if isinstance(tools, dict) else {})
    if cfg["psp_path"].get("storage_root") not in _STORAGE_ROOTS:
        cfg["psp_path"]["storage_root"] = _STORAGE_ROOTS[0]

    systems = raw.get("systems")
    if isinstance(systems, dict):
        for sid, entry in systems.items():
            if not isinstance(entry, dict):
                continue
            merged = dict(SYSTEM_DEFAULTS)
            merged.update(entry)
            merged["rom_extensions"] = normalise_extensions(merged["rom_extensions"])
            if merged["cover_art"] not in PSPConstants.ICON_SIZES:
                merged["cover_art"] = "landscape"
            merged["config_file"] = (str(merged["config_file"]).strip() or None) if merged["config_file"] else None
            merged["skipped"] = bool(merged["skipped"])
            merged["rom_compression"] = bool(merged["rom_compression"])
            cfg["systems"][str(sid)] = merged
    return cfg


def load_config_file(path: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    """Read config.json. Returns (config, notice).

    A missing file is created. An unreadable one is renamed to config.json.bak
    and replaced with defaults; ``notice`` then explains what happened.
    """
    notice = None
    raw: Any = None
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError):
            backup = path.with_name(path.name + ".bak")
            try:
                shutil.copyfile(path, backup)
                notice = f"config.json could not be read and was reset. A copy was saved as {backup.name}."
            except OSError:
                notice = "config.json could not be read and was reset."
    cfg = normalize_config(raw)
    if raw is None:
        save_config_file(path, cfg)
    return cfg, notice


def save_config_file(path: Path, cfg: Dict[str, Any]) -> None:
    """Write config.json atomically (a crash can never leave a half-written file)."""
    cfg["systems"] = dict(sorted(cfg.get("systems", {}).items(),
                                 key=lambda item: str(item[1].get("name", "")).lower()))
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(cfg, handle, indent=4)
    os.replace(temp, path)


# =============================================================================
# 3. System presets
# =============================================================================

# name -> id (used as Games/<id> folder and CAT_<id> on the PSP), cover art
# orientation, default ROM extensions.
SYSTEM_PRESETS: Dict[str, Dict[str, str]] = {
    "Amiga 500": {"id": "AMI", "icon": "landscape", "ext": ".adf .uae"},
    "Amstrad CPC": {"id": "CPC", "icon": "landscape", "ext": ".dsk .cdt"},
    "Apple II": {"id": "APL2", "icon": "landscape", "ext": ".do .dsk .nib"},
    "Atari 2600": {"id": "A26", "icon": "landscape", "ext": ".a26 .bin"},
    "Atari 5200": {"id": "A52", "icon": "landscape", "ext": ".a52 .bin .rom"},
    "Atari 7800": {"id": "A78", "icon": "landscape", "ext": ".a78 .bin"},
    "Atari 800": {"id": "A800", "icon": "landscape", "ext": ".atr .xfd .rom"},
    "Atari Lynx": {"id": "LYNX", "icon": "square", "ext": ".lnx"},
    "Atari ST": {"id": "AST", "icon": "landscape", "ext": ".st .msa"},
    "CP System I": {"id": "CPS1", "icon": "portrait", "ext": ".zip"},
    "CP System II": {"id": "CPS2", "icon": "portrait", "ext": ".zip"},
    "ColecoVision": {"id": "COLE", "icon": "landscape", "ext": ".col .bin"},
    "Commodore 64": {"id": "C64", "icon": "landscape", "ext": ".d64 .t64 .prg .crt"},
    "MS-DOS": {"id": "DOS", "icon": "landscape", "ext": ".exe .com .bat"},
    "Game & Watch": {"id": "GW", "icon": "square", "ext": ".mgw"},
    "Game Boy Advance": {"id": "GBA", "icon": "square", "ext": ".gba"},
    "Game Boy / Color": {"id": "GBC", "icon": "square", "ext": ".gbc .gb"},
    "Intellivision": {"id": "INTV", "icon": "landscape", "ext": ".int .bin"},
    "Magnavox Odyssey 2": {"id": "O2", "icon": "landscape", "ext": ".bin"},
    "MSX": {"id": "MSX", "icon": "landscape", "ext": ".rom .mx1 .mx2 .dsk .cas"},
    "Neo Geo AES/MVS": {"id": "NEO", "icon": "portrait", "ext": ".zip"},
    "Neo Geo CD": {"id": "NGCD", "icon": "portrait", "ext": ".iso .bin"},
    "Neo Geo Pocket / Color": {"id": "NGPC", "icon": "square", "ext": ".ngp .ngc"},
    "Nintendo 64": {"id": "N64", "icon": "landscape", "ext": ".z64 .v64 .n64"},
    "Nintendo Entertainment System": {"id": "NES", "icon": "landscape", "ext": ".nes .fds"},
    "PC Engine / TurboGrafx-16": {"id": "PCE", "icon": "landscape", "ext": ".pce .hucard .iso"},
    "Pokemon Mini": {"id": "PKMN", "icon": "square", "ext": ".min"},
    "SCUMMVM": {"id": "SCUMM", "icon": "landscape", "ext": ".scummvm"},
    "SEGA 32x": {"id": "32x", "icon": "portrait", "ext": ".32x .bin"},
    "SEGA CD": {"id": "SCD", "icon": "portrait", "ext": ".iso .bin"},
    "SEGA Game Gear": {"id": "GG", "icon": "portrait", "ext": ".gg .bin"},
    "SEGA Master System": {"id": "SMS", "icon": "portrait", "ext": ".sms .bin"},
    "SEGA Mega Drive": {"id": "MD", "icon": "portrait", "ext": ".md .bin .gen .smd"},
    "SEGA SG-1000": {"id": "SG1K", "icon": "portrait", "ext": ".sg .bin"},
    "Super Nintendo": {"id": "SNES", "icon": "landscape", "ext": ".smc .sfc .fig"},
    "Vectrex": {"id": "VEC", "icon": "portrait", "ext": ".vec .bin"},
    "Virtual Boy": {"id": "VB", "icon": "landscape", "ext": ".vb"},
    "WonderSwan / Color": {"id": "WSC", "icon": "square", "ext": ".ws .wsc"},
    "ZX Spectrum": {"id": "ZXS", "icon": "landscape", "ext": ".tap .tzx .z80 .szx"},
}


def preset_for_folder(folder_name: str) -> Optional[Tuple[str, Dict[str, str]]]:
    """Match a Games/ sub-folder to a preset by full name or by system ID."""
    wanted = folder_name.upper()
    for name, data in SYSTEM_PRESETS.items():
        if wanted == name.upper() or wanted == data["id"].upper():
            return name, data
    return None


# =============================================================================
# 4. PBP container helpers
# =============================================================================
#
# A PBP file starts with a 40 byte header: the magic "\0PBP", a 4 byte version
# and eight little-endian offsets, one per section below. Sections follow each
# other in this exact order, so rebuilding a PBP means swapping the contents
# of the sections we customise and recomputing the offsets.

PBP_SECTIONS = ("param.sfo", "icon0.png", "icon1.png", "pic0.png",
                "pic1.png", "snd0.at3", "data.psp", "data.psar")
_PBP_HEADER_SIZE = 8 + 4 * len(PBP_SECTIONS)        # magic+version, then 8 offsets


def split_pbp(data: bytes) -> Tuple[bytes, Dict[str, bytes]]:
    """Split a PBP into (8 byte magic/version, {section name: bytes})."""
    if len(data) < _PBP_HEADER_SIZE or data[:4] != b"\x00PBP":
        raise ValueError("PBOOT.PBP template is not a valid PBP file")
    offsets = list(struct.unpack_from("<8I", data, 8))
    ends = offsets[1:] + [len(data)]
    if offsets[0] < _PBP_HEADER_SIZE or any(a > b for a, b in zip(offsets, ends)) or ends[-1] > len(data):
        raise ValueError("PBOOT.PBP template has a corrupt section table")
    return data[:8], {name: data[start:end] for name, start, end in zip(PBP_SECTIONS, offsets, ends)}


def build_pbp(header: bytes, parts: Dict[str, bytes]) -> bytes:
    """Reassemble a PBP from its sections, recomputing every offset."""
    offsets, cursor = [], _PBP_HEADER_SIZE
    for name in PBP_SECTIONS:
        offsets.append(cursor)
        cursor += len(parts[name])
    return header + struct.pack("<8I", *offsets) + b"".join(parts[n] for n in PBP_SECTIONS)


# ---- PARAM.SFO -----------------------------------------------------------------------------
#
# PARAM.SFO is the small key/value table that holds a game's XMB title and flags.
#   header  20 bytes: "\0PSF", version, key table offset, data table offset, entry count
#   index   16 bytes per entry: key offset (u16), format (u16), used length (u32),
#           max length (u32), data offset (u32)
#   keys    NUL-terminated names, padded to a multiple of 4
#   data    one slot of "max length" bytes per entry
# Emulators differ: 4 to 9 entries, and the TITLE slot is 128 bytes in most but only
# 32 in some (NesterJ). PBOOT.PBP has both TITLE and PBOOT_TITLE; EBOOT.PBP only TITLE.

_SFO_MAGIC = b"\x00PSF"
_SFO_TEXT_FORMATS = (0x0004, 0x0204)           # UTF-8 text (with / without special NUL handling)
SFO_TITLE_LIMIT = 128                          # the largest TITLE slot the XMB uses


class SfoEntry:
    """One PARAM.SFO entry; ``slot`` is the full data slot (``max_len`` bytes)."""
    __slots__ = ("index", "key", "fmt", "length", "max_len", "slot", "offset")

    def __init__(self, index: int, key: str, fmt: int, length: int, max_len: int, slot: bytes, offset: int):
        self.index, self.key, self.fmt = index, key, fmt
        self.length, self.max_len, self.slot, self.offset = length, max_len, slot, offset


def parse_sfo(data: bytes) -> Tuple[int, List[SfoEntry]]:
    """Read a PARAM.SFO; raises ValueError if it is not a well-formed one."""
    if len(data) < 20 or data[:4] != _SFO_MAGIC:
        raise ValueError("not a PARAM.SFO")
    version, key_off, data_off, count = struct.unpack_from("<IIII", data, 4)
    if count > 64 or not (20 + 16 * count <= key_off <= data_off <= len(data)):
        raise ValueError("corrupt PARAM.SFO header")
    entries: List[SfoEntry] = []
    for i in range(count):
        key_pos, fmt, length, max_len, rel = struct.unpack_from("<HHIII", data, 20 + 16 * i)
        start = key_off + key_pos
        end = data.find(b"\x00", start, data_off)
        if end < 0:
            raise ValueError("corrupt PARAM.SFO key table")
        offset = data_off + rel
        if length > max_len or offset + max_len > len(data):
            raise ValueError("corrupt PARAM.SFO data table")
        try:
            key = data[start:end].decode("ascii")
        except UnicodeDecodeError:
            raise ValueError("corrupt PARAM.SFO key") from None
        entries.append(SfoEntry(i, key, fmt, length, max_len, data[offset:offset + max_len], offset))
    return version, entries


def build_sfo(version: int, entries: List[SfoEntry]) -> bytes:
    """Lay a PARAM.SFO out again from its entries (same layout rules the real files follow)."""
    keys = bytearray()
    key_positions = []
    for entry in entries:
        key_positions.append(len(keys))
        keys += entry.key.encode("ascii") + b"\x00"
    keys += b"\x00" * (-len(keys) % 4)
    key_off = 20 + 16 * len(entries)
    index, data = bytearray(), bytearray()
    for entry, key_pos in zip(entries, key_positions):
        index += struct.pack("<HHIII", key_pos, entry.fmt, entry.length, entry.max_len, len(data))
        data += entry.slot
    header = struct.pack("<4sIIII", _SFO_MAGIC, version, key_off, key_off + len(keys), len(entries))
    return header + bytes(index) + bytes(keys) + bytes(data)


def _truncate_utf8(encoded: bytes, limit: int) -> bytes:
    """Cut UTF-8 bytes to ``limit`` without leaving half a character at the end."""
    return encoded[:limit].decode("utf-8", "ignore").encode("utf-8")


def set_sfo_titles(sfo: bytes, title: str, keys: Tuple[str, ...] = ("TITLE",)) -> bytes:
    """Return ``sfo`` with the given title fields set to ``title``.

    A title that fits is written into its existing slot and nothing else changes. A
    TITLE slot that is too small for it (some emulators have 32 bytes) is enlarged to
    the standard 128 bytes, which needs the file laid out again. Other keys (PBOOT_TITLE) are
    cut to their own size. Raises ValueError if ``sfo`` is not a valid PARAM.SFO.
    """
    version, entries = parse_sfo(sfo)
    full = title.encode("utf-8")
    targets = [e for e in entries if e.key in keys and e.fmt in _SFO_TEXT_FORMATS]
    grown = False
    for entry in targets:
        if entry.key == "TITLE" and entry.max_len < SFO_TITLE_LIMIT and len(full) + 1 > entry.max_len:
            entry.max_len, grown = SFO_TITLE_LIMIT, True       # the standard size every other emulator uses
        text = _truncate_utf8(full, entry.max_len - 1)
        entry.length = len(text) + 1
        entry.slot = text + b"\x00" * (entry.max_len - len(text))
    if grown:
        return build_sfo(version, entries)
    out = bytearray(sfo)                         # nothing changed size: patch the slots in place
    for entry in targets:
        struct.pack_into("<I", out, 20 + 16 * entry.index + 4, entry.length)
        out[entry.offset:entry.offset + entry.max_len] = entry.slot
    return bytes(out)


# ---- XMB titles ----------------------------------------------------------------------------

_TAG_GROUPS = re.compile(r"\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}")
_TRAILING_ARTICLE = re.compile(r"(?P<base>.+?),\s+(?P<article>The|A|An)(?P<rest>\s*[-:].*)?", re.IGNORECASE)


def clean_title(folder_name: str) -> Optional[str]:
    """Turn a game folder name into the title shown on the XMB, without tags.

        Super Mario Bros (USA) [!]                  ->  Super Mario Bros
        Legend of Zelda, The - A Link to the Past   ->  The Legend of Zelda - A Link to the Past
        Sonic_the_Hedgehog                          ->  Sonic the Hedgehog

    Removes (...), [...] and {...} groups, joins "Name, The" back into "The Name",
    turns underscores into spaces when the name has no spaces, and drops control
    characters. Returns None if nothing usable is left (the existing title is kept).
    """
    name = "".join(ch for ch in folder_name if ch.isprintable())
    if " " not in name.strip():
        name = name.replace("_", " ")
    previous = None
    while previous != name:                       # remove nested groups from the inside out
        previous, name = name, _TAG_GROUPS.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" -_,;:")
    match = _TRAILING_ARTICLE.fullmatch(name)
    if match:
        article = match.group("article")
        article = article[0].upper() + article[1:].lower()
        name = f"{article} {match.group('base')}{match.group('rest') or ''}"
    return name or None


# ---- EBOOT.PBP -----------------------------------------------------------------------------

def find_eboot(folder: Path) -> Optional[Path]:
    """The EBOOT.PBP inside ``folder`` (any capitalisation), or None."""
    exact = folder / "EBOOT.PBP"
    if exact.is_file():
        return exact
    for candidate in folder.iterdir() if folder.is_dir() else ():
        if candidate.is_file() and candidate.name.lower() == "eboot.pbp":
            return candidate
    return None


def patch_eboot(path: Path, replacements: Dict[str, bytes], title: Optional[str]) -> str:
    """Put the game's artwork, music and title into an emulator's EBOOT.PBP (in place).

    ``path`` must be the COPY inside Output/, never the original emulator. Only the
    listed PBP sections and the TITLE are replaced; the emulator program inside
    (data.psp) is copied through byte for byte. A file that is not a PBP (for example
    a bare ELF) is left unchanged. Returns a short status; never raises.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        return f"Not patched ({type(exc).__name__})"
    if data[:4] == b"\x7fELF":
        return "Not patched: it is a plain ELF program, not a PBP (it has no icon or title to replace)"
    try:
        header, parts = split_pbp(data)
    except ValueError:
        return "Not patched: not a valid PBP file"

    done = [name for name in PBP_SECTIONS if name in replacements and replacements[name]]
    parts.update({name: replacements[name] for name in done})
    labels = [name.split(".")[0].upper() for name in done]
    problem = ""
    if title:
        try:
            parts["param.sfo"] = set_sfo_titles(parts["param.sfo"], title, ("TITLE",))
            labels.append("title")
        except ValueError:
            problem = "its PARAM.SFO could not be read, so the title was not changed"
    if not labels:
        return f"Not patched: {problem}" if problem else "Nothing to patch"
    if not _write_pbp(path, header, parts):
        return "Not patched (could not write the file)"
    summary = ", ".join(labels)
    return f"Partly patched ({summary}): {problem}" if problem else f"OK ({summary})"


def _write_pbp(path: Path, header: bytes, parts: Dict[str, bytes]) -> bool:
    """Atomically replace ``path`` with a rebuilt PBP."""
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_bytes(build_pbp(header, parts))
        os.replace(temp, path)
        return True
    except OSError:
        try:
            temp.unlink()
        except OSError:
            pass
        return False


# =============================================================================
# 5. Game ID registry
# =============================================================================

_ID_ALPHABET = "1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Folder-name tags that select a one letter ID prefix. Whole words only, so
# "Modern Combat" is not mistaken for a "MOD" and "Brewster" for "BREW".
_TAG_PATTERNS = (
    ("T", re.compile(r"[\[(]T[-+]|\bTRANSLAT(?:ION|ED)\b")),     # Translation
    ("H", re.compile(r"\[H\d?\]|\bHACK(?:ED)?\b|\bMOD(?:DED)?\b")),  # Hack / mod
    ("P", re.compile(r"\bPROTO(?:TYPE)?\b|\bBETA\b")),            # Prototype
    ("B", re.compile(r"\bHOME ?BREW\b|\bBREW\b")),                # Homebrew
)


class IDRegistry:
    """
    Hands out unique 4 character IDs per system.

    Four characters are mandatory because emulator config files are often
    binary: changing the string length would shift every internal offset.

    ``known`` maps system -> {folder name: ID} from earlier runs, so a game
    keeps the same ID forever, even when other games are added later.
    """

    def __init__(self, known: Optional[Dict[str, Dict[str, str]]] = None):
        self._lock = threading.Lock()
        self._assigned: Dict[str, Dict[str, str]] = {}
        self._used: Dict[str, set] = {}
        for system, names in (known or {}).items():
            self._assigned[system] = dict(names)
            self._used[system] = set(names.values())

    def generate(self, system: str, name: str) -> str:
        """Return the ID of ``name`` in ``system``, allocating one if it is new."""
        with self._lock:
            names = self._assigned.setdefault(system, {})
            if name in names:
                return names[name]
            used = self._used.setdefault(system, set())
            game_id = self._allocate(used, self._base_for(name))
            used.add(game_id)
            names[name] = game_id
            return game_id

    @staticmethod
    def _base_for(name: str) -> str:
        """Derive the first three characters from the folder name."""
        upper = name.upper()
        prefix = next((letter for letter, pattern in _TAG_PATTERNS if pattern.search(upper)), "")

        # Drop (region) and [tag] groups, then keep only letters/digits.
        clean = re.sub(r"\(.*?\)|\[.*?\]", "", name)
        clean = re.sub(r"[^A-Z0-9\s]", "", clean.upper()).strip()
        words = clean.split()

        if prefix:                          # tagged: prefix + first letter of two words
            base = prefix + words[0][0] + words[1][0] if len(words) >= 2 else (prefix + clean)[:3]
        elif len(words) >= 3:               # acronym of the first three words
            base = "".join(w[0] for w in words[:3])
        elif len(words) == 2:
            base = words[0][0] + words[1][:2]
        else:
            base = clean[:3]
        return base.ljust(3, "0")[:3]

    @staticmethod
    def _allocate(used: set, base: str) -> str:
        """First free ID: base+1 char (36 options), then base[:2]+2 chars, then base[:1]+3."""
        for keep in (3, 2, 1):
            prefix = base[:keep]
            for tail in itertools.product(_ID_ALPHABET, repeat=4 - keep):
                candidate = prefix + "".join(tail)
                if candidate not in used:
                    return candidate
        raise RuntimeError("No free game IDs left for this system")


# =============================================================================
# 6. Asset processing (non destructive: source folders are only ever read)
# =============================================================================

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".avif"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".wma", ".opus", ".mka", ".webm"}

# RIFF/WAVE header of a 132 kbps stereo 44.1 kHz ATRAC3 file as the PSP expects
# it (format tag 0x0270, block align 0x180 = 384 bytes). The 14 trailing codec
# bytes are copied unchanged from known-good AT3 files (see GBA2PSP credits).
_AT3_FMT_CHUNK = (b"fmt \x20\x00\x00\x00\x70\x02\x02\x00\x44\xAC\x00\x00\x99\x40\x00\x00"
                  b"\x80\x01\x00\x00\x0E\x00\x01\x00\x00\x10\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00")
_EA3_HEADER_SIZE = 96          # atracdenc writes a 96 byte EA3 tag before the audio frames
_TOOL_TIMEOUT = 180            # seconds; a stuck encoder must never hang the whole batch


def _run_tool(command: List[str]) -> bool:
    """Run an external tool quietly. True when it exited with status 0."""
    options: Dict[str, Any] = {"capture_output": True, "stdin": subprocess.DEVNULL, "timeout": _TOOL_TIMEOUT}
    if os.name == "nt":      # do not flash a console window in the windowed build
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        return subprocess.run(command, **options).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class AssetProcessor:
    """Image resizing and audio conversion, done in memory / temp folders."""

    @staticmethod
    def get_img(files: List[Path], name: str, target_size: Tuple[int, int],
                shadow_requested: bool = False) -> Tuple[Optional[bytes], str]:
        """Find ICON0 / PIC0 / PIC1 among ``files`` and return (PNG bytes, label)."""
        source = next((f for f in files if f.stem.upper() == name and f.suffix.lower() in IMAGE_EXTENSIONS), None)
        if source is None:
            return None, "Not found"
        try:
            with Image.open(source) as img:
                is_png = source.suffix.lower() == ".png"
                needs_conversion = not (is_png and img.size == target_size)

                if name == "PIC0":
                    if shadow_requested:
                        label = "Shadow + Converted" if needs_conversion else "Shadow"
                    else:
                        label = "Resized/Converted" if needs_conversion else "No conversion"
                else:
                    label = "Resized/Converted" if needs_conversion else "No conversion"

                final = img.convert("RGBA")
                if needs_conversion or shadow_requested:
                    if name == "PIC0":
                        final = AssetProcessor._pic0_canvas(final, target_size, shadow_requested)
                    else:
                        final = final.resize(target_size, _RESAMPLE)

                buffer = io.BytesIO()
                final.save(buffer, format="PNG")
                return buffer.getvalue(), label
        except Exception:                       # corrupt / unsupported image: skip it, keep going
            return None, "Unreadable image"

    @staticmethod
    def _pic0_canvas(img: "Image.Image", size: Tuple[int, int], shadow: bool) -> "Image.Image":
        """Centre the logo on a transparent canvas and optionally add a soft shadow."""
        # Shrink to 92% so the 0,0-offset blurred shadow stays visible at the edges.
        img.thumbnail((int(size[0] * 0.92), int(size[1] * 0.92)), _RESAMPLE)
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        canvas.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
        if not shadow:
            return canvas
        shade = Image.new("RGBA", canvas.size, (0, 0, 0, 180))                    # shadow opacity
        shade.putalpha(canvas.split()[3].filter(ImageFilter.GaussianBlur(8)))     # soft edge
        result = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        result.paste(shade, (0, 0))
        result.paste(canvas, (0, 0), canvas)
        return result

    @staticmethod
    def get_audio(files: List[Path]) -> Tuple[Optional[bytes], str]:
        """Return (AT3 bytes, label) from a native .at3 or by converting any common format."""
        native = next((f for f in files if f.suffix.lower() == ".at3"), None)
        if native:
            return native.read_bytes(), "Native"

        source = next((f for f in files if f.suffix.lower() in AUDIO_EXTENSIONS), None)
        if source is None:
            return None, "Not found"

        ffmpeg, atracdenc = find_tool("ffmpeg"), find_tool("atracdenc")
        if not ffmpeg or not atracdenc:
            return None, "Tools missing"

        with tempfile.TemporaryDirectory() as tmp:
            wav, ea3 = Path(tmp) / "a.wav", Path(tmp) / "a.ea3"
            if not _run_tool([ffmpeg, "-y", "-i", str(source), "-ar", "44100", "-ac", "2",
                              "-t", str(PSPConstants.MAX_AUDIO_DURATION), str(wav)]):
                return None, "Conversion failed"
            if not _run_tool([atracdenc, "--encode=atrac3", "-i", str(wav), "-o", str(ea3)]):
                return None, "Conversion failed"
            try:
                payload = ea3.read_bytes()[_EA3_HEADER_SIZE:]
            except OSError:
                return None, "Conversion failed"

        # Never exceed the size limit, and only cut on a whole ATRAC3 frame.
        block = PSPConstants.AT3_BLOCK_ALIGN
        limit = (PSPConstants.MAX_AUDIO_SIZE // block) * block
        payload = payload[:limit]
        body = _AT3_FMT_CHUNK + b"data" + struct.pack("<I", len(payload)) + payload
        riff = b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE"
        return riff + body, "Converted"


# =============================================================================
# 7. The packer engine
# =============================================================================

ProgressCallback = Callable[[str, int, int, str], None]


def _safe_system_id(system: str) -> bool:
    """System IDs become folder names (CAT_<id>), so only plain characters are allowed."""
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]{1,16}", system))


class PSPEmulatorPacker:
    """Reads the config, converts game folders and writes the conversion log."""

    def __init__(self) -> None:
        self.mappings: Dict[str, List[Tuple[str, str]]] = {}      # system -> [(folder, id)]
        self.registry = IDRegistry()
        self._template_lock = threading.Lock()
        self._template: Optional[Tuple[bytes, Dict[str, bytes]]] = None
        self.config_path = external_path("config.json")
        self.id_map_path = external_path("id_map.json")
        self.config, self.config_notice = load_config_file(self.config_path)
        self.id_map = self._load_id_map()
        self._prepare_workspace()
        for name, path in self.config["settings"]["tools"].items():
            set_tool_override(name, path)

    # ---- workspace -----------------------------------------------------------

    def _prepare_workspace(self) -> None:
        """Create the working folders and restore bundled templates / docs."""
        for key in ("emulators_dir", "games_dir", "output_dir"):
            self.path(key).mkdir(parents=True, exist_ok=True)
        ensure_config_templates()
        ensure_docs()

    def path(self, key: str) -> Path:
        """Absolute path of a configured folder: 'emulators_dir', 'games_dir' or 'output_dir'."""
        return external_path(self.config["paths"][key])

    def save_config(self) -> None:
        save_config_file(self.config_path, self.config)

    def set_tool_path(self, name: str, path: Optional[str]) -> None:
        """Use ``path`` for an audio tool (None = go back to automatic detection) and remember it."""
        tools = self.config["settings"].setdefault("tools", {})
        if path:
            tools[name] = path
        else:
            tools.pop(name, None)
        set_tool_override(name, path)

    def template_problem(self) -> Optional[str]:
        """None if the bundled PBOOT.PBP template is usable, else a readable reason."""
        try:
            self._pbp_template()
            return None
        except (OSError, ValueError) as exc:
            return f"PBOOT.PBP template problem: {exc}"

    # ---- ID persistence ------------------------------------------------------

    def _load_id_map(self) -> Dict[str, Dict[str, str]]:
        try:
            with open(self.id_map_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(s): {str(k): str(v) for k, v in m.items()}
                for s, m in data.items() if isinstance(m, dict)}

    def _save_id_map(self) -> None:
        try:
            temp = self.id_map_path.with_name(self.id_map_path.name + ".tmp")
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(self.id_map, handle, indent=2, sort_keys=True)
            os.replace(temp, self.id_map_path)
        except OSError:
            pass          # IDs are still deterministic without the file; not worth failing a run

    # ---- helpers -------------------------------------------------------------

    def _pbp_template(self) -> Tuple[bytes, Dict[str, bytes]]:
        """Parse PBOOT.PBP once and reuse it for every game."""
        with self._template_lock:
            if self._template is None:
                self._template = split_pbp(resource_path("Resources/PBOOT.PBP").read_bytes())
            return self._template

    def detect_systems(self) -> Tuple[List[str], List[str]]:
        """Scan Games/ and register every folder named after a known system.

        Returns (IDs of newly registered systems, names of unrecognised folders).
        The caller is responsible for saving the config when anything was added.
        """
        added: List[str] = []
        unknown: List[str] = []
        games = self.path("games_dir")
        if not games.is_dir():
            return added, unknown
        systems = self.config["systems"]
        known = {sid.upper() for sid in systems} | {str(c.get("name", "")).upper() for c in systems.values()}
        for folder in sorted((d for d in games.iterdir() if d.is_dir()), key=lambda d: d.name.lower()):
            match = preset_for_folder(folder.name)
            if match:
                name, preset = match
                if preset["id"] not in systems:
                    systems[preset["id"]] = dict(SYSTEM_DEFAULTS, name=name,
                                                 rom_extensions=preset["ext"].split(), cover_art=preset["icon"])
                    added.append(preset["id"])
            elif folder.name.upper() not in known:
                unknown.append(folder.name)
        return added, unknown

    def find_system_folder(self, sys_id: str) -> Optional[Path]:
        """Locate Games/<ID> for a configured system using strict case-insensitive ID matching.

        Matches folder.name.upper() == sys_id.upper() only. Full-name folders are not accepted.
        Returns None when no matching folder exists.
        """
        games = self.path("games_dir")
        if not games.is_dir():
            return None
        wanted = sys_id.upper()
        for child in games.iterdir():
            if child.is_dir() and child.name.upper() == wanted:
                return child
        return None

    def system_issue(self, cfg: Dict[str, Any]) -> Optional[str]:
        """Why a system cannot be converted yet (None when it is ready)."""
        if not cfg.get("emulator"):
            return "No emulator selected"
        if not cfg.get("roms_subdir"):
            return "ROM path not set"
        if not cfg.get("rom_extensions"):
            return "No ROM extensions"
        emulator = self.path("emulators_dir") / cfg["emulator"]
        if not emulator.is_dir():
            return "Emulator folder not found"
        if not any(emulator.iterdir()):
            return "Emulator folder is empty"
        return None

    def config_file_missing(self, cfg: Dict[str, Any]) -> bool:
        """True if the system names a config template that does not exist on disk."""
        template = cfg.get("config_file")
        return bool(template) and not external_path(str(template)).exists()

    # ---- config patching -----------------------------------------------------

    def binary_patch(self, system: str, game_id: str, package: Path, rom_name: str,
                     config_name: Optional[str], sys_info: Dict[str, Any]) -> str:
        """Point the copied emulator config at this game's folder and ROM.

        Works on raw bytes so binary configs are never corrupted. Returns a
        short status: OK, No changes, Not supported, Template missing,
        Non-ASCII path or Patching Failed.
        """
        if not sys_info.get("config_file"):
            return "Not supported"
        if not config_name:
            return "Template missing"
        target = package / config_name
        if not target.exists():
            return "Template missing"

        try:
            storage = self.config["psp_path"]["storage_root"].lower().encode("ascii")
            subdir = sys_info.get("roms_subdir", "").strip("/\\").encode("ascii")
            game_dir = storage + b"PSP/GAME/CAT_" + system.encode("ascii") + b"/" + game_id.encode("ascii") + b"/"
            rom_bytes = rom_name.encode("ascii")
        except UnicodeEncodeError:
            return "Non-ASCII path"

        try:
            data = target.read_bytes()
            changes = 0

            # 1. Replace the template's placeholder game folder, e.g.
            #    ms0:/PSP/GAME/CAT_ANY/GAME/  ->  <root>PSP/GAME/CAT_<system>/<id>/
            patched = re.sub(rb"(ms0:/|ef0:/)PSP/GAME/CAT_[^/]+/GAME/", lambda _m: game_dir, data)
            if patched != data:
                data, changes = patched, changes + 1

            # 2. Text configs: swap the ROM file name after the ROM sub-folder.
            if config_name.lower().endswith((".ini", ".cfg", ".txt")):
                rom_folder = game_dir + (subdir + b"/" if subdir else b"")
                pattern = b"(" + re.escape(rom_folder) + rb")[^\s\n\r\x00\"']+"
                data, count = re.subn(pattern, lambda m: m.group(1) + rom_bytes, data)
                changes += count

            target.write_bytes(data)
            return "OK" if changes else "No changes"
        except (OSError, re.error):
            return "Patching Failed"

    # ---- one game ------------------------------------------------------------

    def process_game(self, folder: Path, system: str, temp_cfg: Optional[Dict[str, Any]] = None,
                     game_id: Optional[str] = None) -> Tuple[str, Any]:
        """Convert one game folder.

        Returns ("SUCCESS", (name, status dict, id)), ("SKIP", reason) when
        something is missing, or ("ERROR", reason) on an unexpected failure.
        This method never raises: one bad game must not stop a whole batch.
        """
        sys_info = temp_cfg if temp_cfg is not None else self.config["systems"][system]
        try:
            return self._process_game(folder, system, sys_info, game_id)
        except Exception as exc:
            return "ERROR", f"{type(exc).__name__}: {exc}"

    def _process_game(self, folder: Path, system: str, sys_info: Dict[str, Any],
                      game_id: Optional[str]) -> Tuple[str, Any]:
        if not _safe_system_id(system):
            return "SKIP", f"System ID '{system}' contains unsupported characters."

        emulator = self.path("emulators_dir") / sys_info["emulator"]
        if not emulator.is_dir():
            return "SKIP", f"Emulator folder '{sys_info['emulator']}' not found."
        if find_eboot(emulator) is None:
            return "SKIP", "Emulator files are missing."

        files = sorted((f for f in folder.iterdir() if f.is_file()), key=lambda f: f.name.lower())
        roms = [f for f in files if f.suffix.lower() in sys_info["rom_extensions"]]
        if not roms:
            return "SKIP", "No ROM file found."
        rom_src = roms[0]

        try:
            header, template_parts = self._pbp_template()
        except (OSError, ValueError) as exc:
            return "SKIP", f"PBOOT.PBP template problem: {exc}"

        game_id = game_id or self.registry.generate(system, folder.name)

        out_root = self.path("output_dir").resolve()
        package = out_root / f"CAT_{system}" / game_id
        if out_root not in package.resolve().parents:           # defensive: never delete outside Output/
            return "SKIP", "Output path is outside the Output folder."
        if package.exists():
            shutil.rmtree(package)

        try:
            shutil.copytree(emulator, package, dirs_exist_ok=True)
            status = self._build_package(files, rom_src, package, sys_info, system, game_id,
                                         header, template_parts, folder.name)
        except Exception:
            shutil.rmtree(package, ignore_errors=True)           # do not leave half-built packages
            raise
        if len(roms) > 1:
            status["ROM"] += f" - used {rom_src.name}, ignored {len(roms) - 1} other ROM file(s)"
        return "SUCCESS", (folder.name, status, game_id)

    def _build_package(self, files: List[Path], rom_src: Path, package: Path, sys_info: Dict[str, Any],
                       system: str, game_id: str, header: bytes,
                       template_parts: Dict[str, bytes], game_name: str) -> Dict[str, str]:
        """Copy ROM + config into ``package``, patch the config, write PBOOT.PBP and
        (when enabled in Settings) patch the emulator's EBOOT.PBP the same way."""
        status: Dict[str, str] = {}

        # --- ROM ---------------------------------------------------------------
        rom_dir = package / sys_info["roms_subdir"]
        if package.resolve() not in rom_dir.resolve().parents and rom_dir.resolve() != package.resolve():
            raise ValueError("ROM path points outside the package folder")
        rom_dir.mkdir(parents=True, exist_ok=True)

        base_name = Path(sys_info.get("rom_filename") or "game").name
        rom_name = base_name if "." in base_name else base_name + rom_src.suffix
        if sys_info.get("rom_compression"):
            rom_name = f"{base_name}.zip"
            with zipfile.ZipFile(rom_dir / rom_name, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(rom_src, arcname=rom_src.name)
            status["ROM"] = "OK (Compressed)"
        else:
            shutil.copy2(rom_src, rom_dir / rom_name)
            status["ROM"] = "OK (No compression)"

        # --- Config template -------------------------------------------------------
        config_name = None
        if sys_info.get("config_file"):
            template = external_path(str(sys_info["config_file"]))
            if template.is_file():
                config_name = template.name
                shutil.copy2(template, package / config_name)
        patch_status = self.binary_patch(system, game_id, package, rom_name, config_name, sys_info)

        # --- Visual / audio assets -----------------------------------------------
        parts = dict(template_parts)
        shadow = bool(self.config["images"].get("pic0_add_shadow", True))
        icon_size = PSPConstants.ICON_SIZES.get(sys_info.get("cover_art"), PSPConstants.ICON_SIZES["landscape"])
        assets = (
            ("ICON0", "icon0.png", AssetProcessor.get_img(files, "ICON0", icon_size)),
            ("PIC0", "pic0.png", AssetProcessor.get_img(files, "PIC0", PSPConstants.PIC0_SIZE, shadow)),
            ("PIC1", "pic1.png", AssetProcessor.get_img(files, "PIC1", PSPConstants.PIC1_SIZE)),
            ("SND0", "snd0.at3", AssetProcessor.get_audio(files)),
        )
        replacements: Dict[str, bytes] = {}            # sections the game provides itself
        for label, section, (payload, note) in assets:
            if payload:
                parts[section] = payload
                replacements[section] = payload
                status[label] = f"OK ({note})"
            else:
                status[label] = note
        status["CONFIG"] = patch_status

        # --- XMB title (PBOOT has TITLE and PBOOT_TITLE) --------------------------------
        xmb = self.config.get("xmb", {})
        title = clean_title(game_name) if xmb.get("title_from_folder", True) else None
        if title:
            try:
                parts["param.sfo"] = set_sfo_titles(parts["param.sfo"], title, ("TITLE", "PBOOT_TITLE"))
                status["TITLE"] = title
            except ValueError:
                status["TITLE"] = "Unchanged (PARAM.SFO of the template is unreadable)"
                title = None

        (package / "PBOOT.PBP").write_bytes(build_pbp(header, parts))

        # --- Optional: the same artwork / music / title inside the emulator's EBOOT.PBP ---
        if xmb.get("patch_eboot", False):
            eboot = find_eboot(package)
            status["EBOOT"] = (patch_eboot(eboot, replacements, title) if eboot
                               else "Not patched: EBOOT.PBP is missing")
        return status

    # ---- a whole batch ---------------------------------------------------------

    def convert(self, targets: List[Tuple[str, Path, Dict[str, Any]]],
                progress: Optional[ProgressCallback] = None,
                cancelled: Optional[Callable[[], bool]] = None,
                workers: int = MAX_WORKERS) -> Dict[str, Any]:
        """Convert every game of every target system.

        targets    list of (system id, Games/<system> folder, system config)
        progress   called as progress(system, games_done, games_total, last_game)
                   from the calling thread only
        cancelled  polled between games; once it returns True no new game starts

        Returns a summary dict: success count, grouped_skips, cancelled flag,
        last_sys / last_folder (where a cancel happened) and total games.
        """
        progress = progress or (lambda *_: None)
        cancelled = cancelled or (lambda: False)
        self.registry = IDRegistry(self.id_map)
        self.mappings = {}
        summary: Dict[str, Any] = {"success": 0, "grouped_skips": {}, "cancelled": False,
                                   "last_sys": None, "last_folder": None, "total": 0, "warnings": []}

        for system, system_folder, cfg in targets:
            if cancelled():
                summary["cancelled"] = True
                break
            folders = sorted((d for d in system_folder.iterdir() if d.is_dir()), key=lambda d: d.name.lower())
            total = len(folders)
            summary["total"] += total
            progress(system, 0, total, "Starting...")

            # Allocate IDs up front, in sorted order, so they never depend on thread timing.
            ids = {f: self.registry.generate(system, f.name) for f in folders}

            def job(folder: Path, system=system, cfg=cfg, ids=ids):
                if cancelled():
                    return "CANCELLED", ""
                return self.process_game(folder, system, temp_cfg=cfg, game_id=ids[folder])

            done = 0
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                futures = {pool.submit(job, f): f for f in folders}
                for future in as_completed(futures):
                    folder = futures[future]
                    try:
                        kind, data = future.result()
                    except Exception as exc:          # job() already guards; this is belt and braces
                        kind, data = "ERROR", f"{type(exc).__name__}: {exc}"
                    if kind == "CANCELLED":
                        summary["cancelled"] = True
                        summary["last_sys"] = summary["last_sys"] or system
                        summary["last_folder"] = summary["last_folder"] or folder.name
                        continue
                    done += 1
                    if kind == "SUCCESS":
                        name, status, game_id = data
                        summary["success"] += 1
                        for key in ("EBOOT", "TITLE"):             # problems the user should hear about
                            note = status.get(key, "")
                            if note.startswith(("Not patched", "Partly patched", "Unchanged")):
                                summary["warnings"].append((system, name, f"{key}: {note}"))
                        self.mappings.setdefault(system, []).append((name, game_id))
                        self.id_map.setdefault(system, {})[name] = game_id    # remember for next run
                    else:
                        summary["grouped_skips"].setdefault((system, kind), []).append((folder.name, data))
                    progress(system, done, total, folder.name)
            if not summary["cancelled"]:
                progress(system, total, total, "Done")

        self._save_id_map()
        return summary

    # ---- reporting -------------------------------------------------------------

    def write_mapping_log(self, total_time: str, summary: Dict[str, Any]) -> None:
        """Write PSPify.log: converted games with their IDs, then skipped games and why."""
        width = 120
        rule, thin = "=" * width, "-" * width
        skips: Dict[str, List[Tuple[str, str]]] = {}
        for (system, _kind), items in summary.get("grouped_skips", {}).items():
            skips.setdefault(system, []).extend(items)
        total_skips = sum(len(v) for v in skips.values())

        def system_title(system: str) -> str:
            return f"SYSTEM: {self.config['systems'].get(system, {}).get('name', system)} ({system})"

        lines = [rule, "PSPIFY CONVERSION PROCESS REPORT".center(width), rule,
                 f"Generated on:     {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}",
                 f"Total Time:       {total_time}",
                 f"Processed:        {summary.get('success', 0)}",
                 f"Skipped:          {total_skips}", rule, ""]

        if summary.get("success", 0) > 0:
            lines += [" [ SUCCESSFUL CONVERSIONS ] ".center(width), thin]
            for system, games in sorted(self.mappings.items()):
                lines += [system_title(system), "-" * 40]
                lines += [f"{original:<108} => ID: {gid}" for original, gid in sorted(games)]
                lines.append(thin)
            lines += ["", ""]

        warnings = summary.get("warnings", [])
        if warnings:
            lines += [" [ WARNINGS (the game was converted, but part of it was not) ] ".center(width), thin]
            for system, name, text in sorted(warnings):
                lines += [f"{name} ({system})", f"    {text}"]
            lines += [thin, ""]

        if total_skips:
            lines += [" [ SKIPPED GAMES / ERRORS ] ".center(width), thin]
            for system, items in sorted(skips.items()):
                lines += [system_title(system), "-" * 40]
                for folder_name, reason in sorted(items):
                    lines += [folder_name, f"    REASON: {reason}"]
                lines.append(thin)
            lines.append("")

        lines += [rule, "END OF REPORT".center(width), rule, ""]
        try:
            external_path("PSPify.log").write_text("\n".join(lines), encoding="utf-8")
        except OSError:
            pass


# =============================================================================
# 8. Command line interface (python pspify_core.py)
# =============================================================================

def format_elapsed(seconds: float) -> str:
    """Seconds -> HH:MM:SS."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02}:{minutes:02}:{secs:02}"


def run_cli() -> int:
    """Convert everything without a GUI. Returns a process exit code."""
    start = time.perf_counter()
    packer = PSPEmulatorPacker()
    if packer.config_notice:
        print(f"[!] {packer.config_notice}")
    problem = packer.template_problem()
    if problem:
        print(f"[!] {problem}")
        return 1
    for tool in missing_tools():
        print(f"[!] Missing tool: {tool} - background music (SND0) will be skipped.")

    targets = []
    for sid, cfg in packer.config["systems"].items():
        folder = packer.find_system_folder(sid)
        if cfg.get("skipped") or not folder or not any(d.is_dir() for d in folder.iterdir()):
            continue
        issue = packer.system_issue(cfg)
        if issue:
            print(f"[!] {cfg['name']} skipped: {issue}")
            continue
        if packer.config_file_missing(cfg):
            print(f"[!] {cfg['name']}: config file not found, converting without it.")
            cfg = dict(cfg, config_file=None)
        targets.append((sid, folder, cfg))
    if not targets:
        print("[!] Nothing to convert. Put game folders in Games/<System ID>/ and configure the system in the GUI.")
        return 1

    def report(system: str, done: int, total: int, text: str) -> None:
        print(f"  [{system}] {done}/{total}  {text}")

    summary = packer.convert(targets, progress=report)
    elapsed = format_elapsed(time.perf_counter() - start)
    skipped = sum(len(v) for v in summary["grouped_skips"].values())
    print(f"\nProcessed: {summary['success']}   Skipped: {skipped}   Time: {elapsed}")
    for (system, _kind), items in summary["grouped_skips"].items():
        for name, reason in items:
            print(f"  - {name} ({system}): {reason}")
    packer.write_mapping_log(elapsed, summary)
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    try:
        sys.exit(run_cli())
    except KeyboardInterrupt:
        print("\n[!] Interrupted.")
        sys.exit(130)
