# PSPify

**Retro Game to PSP Package Converter** · v1.0

PSPify is an open-source desktop application that converts folders of retro game ROMs into organized, ready-to-copy PSP homebrew packages (`PBOOT.PBP`). Packages are structured for use with the **Game Categories Lite** PSP plugin.

---

## Key Features

- **Automated package creation**
    - Processes game folders in batches.
    - Copies the configured emulator into each game package.
    - Places the ROM in the emulator's expected directory.
    - Updates the emulator configuration to launch the correct game.
    - Builds a `PBOOT.PBP` entry containing the game's title and assets.
- **PSP-ready artwork and audio**
    - Converts `ICON0`, `PIC0`, and `PIC1` artwork to PSP-compatible formats.
    - Converts optional background music for the `SND0` asset.
- **Organized output**
    - Groups packages by system under `Output/CAT_<SYSTEM>/`.
    - Assigns each game a persistent four-character ID.
    - Preserves existing package IDs when new games are added, helping keep PSP save paths stable.
- **Configurable experience**
    - Includes Dark, Light, Midnight, and Nord themes.
    - Supports custom JSON themes.
    - Provides configurable XMB titles, PIC0 shadows, ROM compression, and PSP storage roots.
- **Batch processing feedback**
    - Displays per-system progress.
    - Supports cancellation after currently running games finish.
    - Reports skipped games and warnings in the application log.

> PSPify does **not** include or distribute ROMs, commercial emulators, or official PSP firmware. You must provide your own legally obtained files. FFmpeg and `atracdenc` are also not bundled; install them separately if you want to generate `SND0` background music.

---

## Supported Systems

The complete list of available systems is displayed in the application's **Systems** tab. Below are the supported systems, their IDs, and recognized extensions:

- **Nintendo Entertainment System**
    - System ID / Folder: `NES`
    - ROM Extensions: `.nes`, `.fds`
- **Super Nintendo Entertainment System**
    - System ID / Folder: `SNES`
    - ROM Extensions: `.smc`, `.sfc`, `.fig`
- **Game Boy / Game Boy Color**
    - System ID / Folder: `GBC`
    - ROM Extensions: `.gb`, `.gbc`
- **Game Boy Advance**
    - System ID / Folder: `GBA`
    - ROM Extensions: `.gba`
- **Nintendo 64**
    - System ID / Folder: `N64`
    - ROM Extensions: `.z64`, `.v64`, `.n64`
- **SEGA Mega Drive / Genesis**
    - System ID / Folder: `MD`
    - ROM Extensions: `.md`, `.bin`, `.gen`, `.smd`
- **SEGA Master System**
    - System ID / Folder: `SMS`
    - ROM Extensions: `.sms`, `.bin`
- **SEGA Game Gear**
    - System ID / Folder: `GG`
    - ROM Extensions: `.gg`, `.bin`

---

## Requirements

### Required Dependencies

- **Python**: 3.8 or later.
- **GUI Toolkit**: PyQt6 or PyQt5.
- **Image Processing**: Pillow.
- **Emulators**: A compatible emulator for each system you want to process (other emulators may work as well, though compatibility isn't guaranteed).
- **Game Files**: Your own legally obtained ROM files and optional artwork/audio assets.

### Optional: Background Music Tools

Required only if you want PSPify to create the `SND0` background music asset:

- **FFmpeg**: Decodes supported audio files to WAV format. ([ffmpeg.org](https://ffmpeg.org))
- **atracdenc**: Encodes WAV audio to Sony ATRAC3 format. ([github.com/dcherednik/atracdenc](https://github.com/dcherednik/atracdenc))

**FFmpeg Installation Examples:**

- **Ubuntu / Debian**: `sudo apt update && sudo apt install ffmpeg`
- **Fedora / RHEL**: `sudo dnf install ffmpeg`
- **Arch Linux**: `sudo pacman -S ffmpeg`
- **Windows**: `winget install ffmpeg` or download directly from [ffmpeg.org](https://ffmpeg.org).
- **macOS**: `brew install ffmpeg`

PSPify searches for audio tools in the following order:

1. Executable path set under **Settings → Audio tools → Browse**.
2. Application root directory or a `Tools/` subdirectory beside it.
3. System `PATH` environment variable.

If either tool is missing, package creation continues without background music conversion.

### PSP Requirements

- A PSP running custom firmware with the **Game Categories Lite** plugin installed.
- Set the plugin's **Category Mode** to **Contextual** or **Multiple MS** so that `CAT_` folders render correctly.

---

## Installation and Launch

1. Clone or download the repository:\
   git clone https://github.com/gamezawy/PSPify.git\
   cd PSPify
2. Create and activate a virtual environment:\
   python -m venv .venv\
   \
   \# Linux / macOS\
   source .venv/bin/activate\
   \
   \# Windows\
   .venv\\Scripts\\activate
3. Install dependencies:\
   \# PyQt6 (Recommended)\
   pip install -r requirements-pyqt6.txt\
   \
   \# PyQt5 (Legacy)\
   pip install -r requirements-pyqt5.txt
4. Launch the application:\
   python pspify\_gui.py

**Qt Compatibility Notes:**

- PSPify uses PyQt6 by default if available.
- Force PyQt5 mode by setting the environment variable: `PSPIFY_QT=5`.
- On some Linux systems running PyQt6 under X11, install `libxcb-cursor0`:\
  sudo apt install libxcb-cursor0

---

## Folder Structure

Arrange your PSPify directory structure as follows:

```
PSPify/
├── pspify_gui.py              # GUI entry point
├── pspify_core.py             # Core processing / CLI entry point
├── config.json                # Generated on first run
├── id_map.json                # Persistent game ID registry
├── Config/                    # Emulator configuration templates
├── Themes/                    # Optional custom themes
├── Emulators/
│   └── <Emulator Name>/       # User-supplied emulator files
├── Games/
│   └── <SYSTEM ID>/
│       └── <Game Name>/
│           ├── <game ROM>
│           ├── ICON0.<extension>
│           ├── PIC0.<extension>
│           ├── PIC1.<extension>
│           └── SND0.<extension>
└── Output/                    # Generated PSP packages
```

The `config.json` and `id_map.json` files are created automatically during operation.

---

## Preparing Game Folders

### Directory Setup

- Create one folder per system inside `Games/` using the system ID (e.g., `NES`, `SNES`, `GBA`).
- Create a dedicated folder for each game inside its system directory.
- Place the game's ROM file and optional media assets inside the game folder.
- Maintain **one ROM file per game folder**. If multiple ROMs are detected, PSPify selects the first alphabetically and logs a warning.

### Asset File Naming

Name your media assets using the standard PSP asset prefixes:

- **`ICON0`**: Game icon displayed while browsing in the XMB.
- **`PIC0`**: Foreground overlay image / logo.
- **`PIC1`**: Full-screen background image.
- **`SND0`**: Background audio track.

**Supported Image Formats:** `.png`, `.jpg`, `.jpeg`, `.bmp`, `.webp`, `.avif`\
**Supported Audio Formats:** `.mp3`, `.wav`, `.ogg`, `.m4a`, `.aac`, `.flac`, `.opus`, `.wma`, `.mka`, `.webm`, `.at3`

---

## Usage Guide

### 1. Configure Systems

- Navigate to the **Systems** tab. System folders under `Games/` are detected automatically.
- Click **Add system** to define a system manually.
- Expand a system card to edit its settings:
    - Link the corresponding emulator directory under `Emulators/`.
    - Specify the relative **ROM folder** expected by the emulator (e.g., `Roms`).
    - Enter supported extensions (e.g., `.smc .sfc`).
- Verify system status:
    - **Ready**: Fully configured and active.
    - **Incomplete**: Required paths or configuration missing.
    - **Disabled**: Excluded from processing.

### 2. Process Games

- Open the **Process** tab.
- Click **Start** to begin batch conversion.
- Monitor per-system progress indicators.
- Click **Cancel** to safely stop execution after current tasks complete.
- Check `Output/` and review `PSPify.log` for execution details.

### 3. Application Settings

Customize settings via the **Settings** tab:

- **Appearance**: Select built-in themes and accent colors.
- **Audio tools**: Check FFmpeg/atracdenc status and set executable paths.
- **XMB display**: Configure PIC0 shadow effects, title parsing rules, and EBOOT patching.
- **Storage**: Choose storage root (`ms0:/` for Memory Stick, `ef0:/` for PSP Go internal storage).
- **Shortcuts**: Quickly access `Games/`, `Emulators/`, and `Output/` folders.

---

## XMB Titles and EBOOT Patching

### Title Generation Rules

By default, PSPify formats the game's folder name into an XMB title (**Settings → XMB display → Use the game's folder name as its title**).

*Example:* `Games/NES/Super Mario Bros (USA) [!]/` → `Super Mario Bros`

**Cleanup Pipeline:**

- Removes bracketed tags: `(...)`, `[...]`, `{...}`.
- Reorders leading articles (e.g., `Zelda, The` becomes `The Zelda`).
- Replaces underscores with spaces if no spaces exist.
- Truncates output to a maximum of 127 bytes.

### EBOOT.PBP Patching

Optional EBOOT patching (**Settings → XMB display → Also patch EBOOT.PBP**) modifies the package `EBOOT.PBP` directly for alternative launchers.

- Applies changes only within the `Output/` directory.
- Preserves original emulator source files.
- Auto-expands legacy 32-byte title fields to 128-byte fields when necessary.
- Non-standard PBP files (such as raw ELFs) are bypassed safely with warnings logged.

---

## Custom Themes

Add custom JSON files to the `Themes/` folder to extend application appearance.

```
{
  "name": "Sunset",
  "base": "Dark",
  "colors": {
    "accent": "#FF7A45",
    "bg": "#14100F"
  }
}
```

- **`base`**: Base theme (`Dark` or `Light`). Unspecified keys inherit from base.
- **Available keys**: `bg`, `sidebar`, `card`, `input`, `border`, `text`, `text_dim`, `accent`, `success`, `warning`, `error`.
- Color strings must use uppercase `#RRGGBB` hex syntax.

---

## Configuration Reference

Key settings in `config.json`:

- **`storage_root`**: PSP destination root (`ms0:/` or `ef0:/`).
- **`rom_compression`**: `true` to compress ROMs into ZIP archives; `false` for raw copies.
- **`xmb.title_from_folder`**: `true` to generate XMB titles from directory names.
- **`xmb.patch_eboot`**: `true` to inject assets/titles into `EBOOT.PBP`.
- **`pic0_add_shadow`**: `true` to apply blur drop-shadow to PIC0 overlays.
- **`systems`**: Dictionary of configured systems, paths, and file filters.

*Note: Corrupted configuration files are automatically backed up as* *`config.json.bak`* *and reinitialized.*

---

## Persistent Game IDs

PSPify generates persistent four-character identifiers (e.g., `SMB1`, `HSO1`) stored in `id_map.json`.

- Prevents memory alignment and pointer shifts in emulators using fixed-length config paths.
- Ensures output directory paths remain stable across rebuilds.
- Protects PSP save file paths from breaking when new games are added.

---

## Output Structure

Generated packages follow this layout:

```
Output/
└── CAT_<SYSTEM>/
    └── <4-character ID>/
        ├── PBOOT.PBP
        └── ...
```

Transfer the resulting `CAT_<SYSTEM>` folders to your PSP storage root (`ms0:/` or `ef0:/`).

---

## Troubleshooting \& FAQ

- **Audio tools not found**
    - Install FFmpeg and `atracdenc`, or specify their locations under **Settings → Audio tools**. Converter will proceed without audio if missing.
- **Unrecognized system folder**
    - Rename the folder under `Games/` to match an active system ID shown in the **Systems** tab.
- **Configuration template not found**
    - Ensure the corresponding template exists under `Config/`.
- **Games are skipped**
    - Check `PSPify.log`. Missing ROMs or invalid folder layouts are the primary causes.
- **Assets missing on PSP**
    - Verify asset file names match `ICON0`, `PIC0`, `PIC1`, or `SND0` (extensions are case-insensitive).
- **Application crashes**
    - Inspect `PSPify-crash.log` in the application root directory for stack traces.

---

## Development \& Building

### Core Modules

- **`pspify_core.py`**: Headless backend module handling configs, IDs, PBP assembly, and filesystem tasks.
- **`pspify_qt.py`**: PyQt5/PyQt6 abstraction layer.
- **`pspify_theme.py`**: Theme management, palettes, and icon styling.
- **`pspify_widgets.py`**: Custom GUI UI components.
- **`pspify_gui.py`**: Application entry point and window manager.

### Executing Tests

```
# Run unit tests
python -m unittest discover -s tests

# Run tests with real EBOOT binaries
PSPIFY_EBOOT_DIR=/path/to/eboots python -m unittest tests.test_real_ebooks
```

### Building Standalone Executables

```
pip install pyinstaller

# Standard PyQt6 Build
pyinstaller PSPify.spec

# Legacy PyQt5 Build
pyinstaller "PSPify (Legacy).spec"
```

Binaries will be output to the `dist/` directory.

---

## Third-Party Notices \& Credits

### Open Source Components

- **PyQt / Qt**: Interface framework (GPLv3 / LGPLv3).
- **Pillow**: Image processing engine (HPND).
- **Python**: Core runtime environment (PSF License).
- **Feather Icons**: UI icons (MIT License).
- **FFmpeg**: External audio decoding tool (Not bundled).
- **atracdenc**: External ATRAC3 encoding tool (Not bundled).

### Credits \& Acknowledgments

- **GBA2PSP**: PBOOT structure and binary audio processing references ([GitHub](https://github.com/sahlberg/gba2psp)).
- **TempGBA4PSP-Single-game**: Initial PBOOT layout reference ([GitHub](https://github.com/GrabowskiDev/TempGBA4PSP-Single-game)).

---

## License

PSPify is open-source software licensed under the **GNU General Public License v3.0**. See the [`LICENSE`](LICENSE) file for details.

