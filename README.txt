================================================================================
                                 PSPify v1.0
                      Retro Game to PSP Package Converter
================================================================================

PSPify is a small, open-source tool designed to make organizing and preparing
retro games on the PSP simple and enjoyable. It automates the process of
converting classic ROMs into standalone PSP-ready homebrew entries while
keeping your library clean and structured.

Note: PSPify does not include or distribute copyrighted materials, such as
ROMs, commercial emulators, or official PSP firmware. Users must provide
their own legally obtained files.

-------------------------------------------------------------------------------
1. REQUIREMENTS & SETUP
-------------------------------------------------------------------------------

Before running the tool, ensure your system is prepared:

A. FFmpeg (audio decoding): (https://ffmpeg.org)
   - Optional: only needed for the background music (SND0).
   - PSPify does NOT include FFmpeg. Install it yourself:
     * Ubuntu/Debian:  sudo apt update && sudo apt install ffmpeg
     * Fedora/RHEL:    sudo dnf install ffmpeg
     * Arch Linux:     sudo pacman -S ffmpeg
     * Windows:        winget install ffmpeg   (or download from ffmpeg.org)
     * macOS:          brew install ffmpeg
   - Verify by typing "ffmpeg -version" in a command prompt.

B. Atracdenc (Sony ATRAC3 encoder): (https://github.com/dcherednik/atracdenc)
   - Optional: only needed for the background music (SND0).
   - PSPify does NOT include atracdenc. Download a release (or build it from
     source) from https://github.com/dcherednik/atracdenc/releases

   For both tools, PSPify finds them in any of these places:
     1. the file you choose in Settings > Audio tools (Browse),
     2. the PSPify folder, or a "Tools" folder next to PSPify,
     3. any folder on your PATH.
   Settings > Audio tools shows whether each one was found and where.
   Without them games still convert; only the background music is skipped.

C. GAME CATEGORIES LITE (PSP Plugin):
   - Your PSP must have the "Game Categories Lite" plugin installed.
   - Set the 'Category Mode' to "Contextual" or "Multiple MS" in the
     plugin options to correctly view the CAT_ folders.

-------------------------------------------------------------------------------
2. ASSET NAMING RULES
-------------------------------------------------------------------------------

To ensure your game looks professional in the XMB, your asset files MUST use
these specific names:

- ICON0: The small square or landscape icon seen while scrolling.
- PIC0:  The logo/title overlay (appears on the right side).
- PIC1:  The full-screen background image.
- SND0:  The background music

Note: Only ONE ROM file should be present in each game folder. If there are
several, PSPify uses the first one (alphabetically) and mentions the others
in the log.

-------------------------------------------------------------------------------
3. SUPPORTED ASSET FORMATS
-------------------------------------------------------------------------------

PSPify supports a wide range of extensions to make asset collection easier:

AUDIO:
- .mp3, .wav, .ogg, .m4a, .aac, .flac, .opus, .wma, .mka, .webm, .at3

IMAGES:
- .png, .jpg, .jpeg, .bmp, .webp, .avif

-------------------------------------------------------------------------------
4. FOLDER STRUCTURE
-------------------------------------------------------------------------------

Your workspace should look like this:

[PSPify Folder]
  |  PSPify                   (The application)
  |  config.json              (Generated on first run)
  |  id_map.json              (Remembers each game's ID, generated on first run)
  |  Config/                  (Pre-Configured templates folder)
  |  Themes/                  (Optional: your own colour themes, see section 6)
  |
  +- Emulators/
  |   +- [Emulator Name]/     (Emulator files)
  |
  +- Games/
  |   +- [System ID]/         (System folder)
  |       +- [Game Name]/     (Contains your ROM and Assets)
  |
  +- Output/                  (Finished packages, copy these to your PSP)

-------------------------------------------------------------------------------
5. HOW TO USE
-------------------------------------------------------------------------------

A. SYSTEMS TAB:
   - Folders in /Games/ named after a system id are added
     automatically when PSPify starts. Use "Add system" for anything else.
   - Open a system card with the arrow button to edit it.
   - Select the Emulator folder you placed in /Emulators/.
   - IMPORTANT: Define the "ROM folder" relative to the emulator folder
     (e.g., if your ROMs go in /Emulators/Emu1/Roms/, enter "Roms").
   - Define the file extensions your emulator supports (e.g., .smc .sfc).
   - The status pill shows Ready, Incomplete (hover it to see why) or Disabled.
     Make sure your system is enabled before starting processing.

B. PROCESS TAB:
   - Once your Systems are configured and your /Games/ folders are ready,
     hit "Start". The tool batch-processes every game automatically, several
     at a time, and shows the progress of each system.
   - "Cancel" stops after the games that are already running.
   - When it finishes you can open the Output folder or the log (PSPify.log)
     straight from the summary.

C. SETTINGS TAB:
   - Pick a Theme and an accent colour.
   - Check or choose the audio tools (FFmpeg, atracdenc).
   - XMB display: the PIC0 shadow, the game title, and EBOOT patching
     (see section 5b).
   - Choose your "Storage Root" (ms0:/ for SD cards, ef0:/ for PSP Go).
   - Enable/Disable "PIC0 Shadows".
   - Shortcuts to open the Games, Emulators and Output folders.

-------------------------------------------------------------------------------
5b. XMB TITLE AND EBOOT PATCHING
-------------------------------------------------------------------------------

TITLE (Settings > XMB display > "Use the game's folder name as its title", on):
  Each game's title on the XMB comes from its folder name, so
      Games/NES/Super Mario Bros (USA) [!]/   ->   "Super Mario Bros"
  Tags in (round), [square] and {curly} brackets are removed, "Zelda, The" becomes
  "The Zelda", and underscores become spaces when the name has no spaces. If nothing
  usable is left, the template title is kept. Titles are limited to 127 bytes.
  Turn it off to keep the template title "PSPify" on every game.

EBOOT PATCHING (Settings > XMB display > "Also patch EBOOT.PBP ...", off by default):
  The XMB shows PBOOT.PBP, but other launchers read the emulator's EBOOT.PBP instead.
  With this option on, PSPify also puts the game's ICON0, PIC0, PIC1, SND0 and the
  title into the EBOOT.PBP of each package.
  - Only the copy inside Output/ changes. Your emulator folder is never touched, and
    the emulator program inside the file is copied through unchanged.
  - A picture or sound the game does not provide is left as the emulator's own.
  - Emulators differ (some have a title field of only 32 bytes): PSPify enlarges it
    to the standard 128 bytes when the game's title needs the room.
  - A file that is not a normal PBP (for example a bare ELF program) cannot hold an
    icon or title. It is left unchanged, the game still converts, and the Process tab
    and PSPify.log list it under WARNINGS.

-------------------------------------------------------------------------------
6. THEMES
-------------------------------------------------------------------------------

PSPify ships with Dark, Light, Midnight and Nord. You can add your own by
putting a .json file in the Themes folder next to the app and restarting:

  {
      "name": "Sunset",
      "base": "Dark",
      "colors": { "accent": "#FF7A45", "bg": "#14100F" }
  }

"base" is the built-in theme to start from. Every colour you leave out is
taken from it. Colours you can set: bg, sidebar, card, input, border, text,
text_dim, accent, success, warning, error (as #RRGGBB). Add "dark": false for
a light theme so the window title bar matches. Invalid files are ignored.

-------------------------------------------------------------------------------
7. CONFIGURATION (config.json)
-------------------------------------------------------------------------------

- "storage_root":
    * "ms0:/" -> Standard Memory Stick (All PSP models).
    * "ef0:/" -> Internal Storage (PSP Go models ONLY).

- "rom_compression":
    * true  -> ROMs are zipped. This saves space but some emulators may
               load slightly slower or not support .zip.
    * false -> ROMs are copied exactly as they are.

- "xmb":
    * "title_from_folder": true -> the XMB title is the cleaned game folder name.
    * "patch_eboot": false -> true also patches EBOOT.PBP (see section 5b).

- "pic0_add_shadow":
    * Adds a subtle Gaussian blur drop-shadow to the PIC0 (logo)
      asset, preventing it from blending into the background.

- "systems":
    * This block stores the unique ID, pathing, and extension
      registry for every console you have configured.

If config.json is ever damaged, PSPify keeps a copy as config.json.bak and
starts again with defaults.

-------------------------------------------------------------------------------
8. THE 4-CHARACTER ID SYSTEM
-------------------------------------------------------------------------------

PSPify uses a strict 4-character naming system (e.g., "SMB1", "HSO1").
This is a technical requirement.

Many PSP emulators store paths in binary configuration files using fixed-length
strings. If you changed the folder name length, the internal memory pointers
would shift, causing the emulator to crash. By staying at 4 characters, you
can safely "patch" the emulator to point to your specific game.

Each game keeps the same ID forever: PSPify remembers them in id_map.json, so
adding more games later never renames the packages you already copied to your
PSP (and with them, your save files). Delete id_map.json only if you want IDs
to be handed out from scratch.

-------------------------------------------------------------------------------
9. TROUBLESHOOTING
-------------------------------------------------------------------------------

- "Audio tools not found"
  Shown at startup. Games still convert but background music is skipped.
  If it lists Atracdenc or FFmpeg, install them (section 1) or choose them under
  Settings > Audio tools. No restart is needed after choosing them there.

- "Unrecognised folders"
  You have a folder in /Games/ that the app doesn't recognize.
  To avoid it, please name your system folders to match the system ID.
  You can find each system ID in the "System" list when you add a system.

- "Config template not found"
  The app found the emulator but couldn't find the configuration template in
  the /Config/ folder. Double-check that the file path in the Systems tab matches
  what is inside your /Config/ directory.

- Skipped games
  The Process tab lists skipped games with the reason (for example
  "No ROM file found."). The full list is in PSPify.log.

- "Not found" in the log
  If your conversion finishes but your game assets are not showing in the PSP,
  make sure that your assets names are correct (ICON0, PIC0, PIC1, SND0).

- Settings > Audio tools says "Not installed"
  Install the tool (section 1) or press Browse and choose its executable
  (ffmpeg / ffmpeg.exe, atracdenc / atracdenc.exe). "Auto" goes back to detection.

- "EBOOT: Not patched ..." in the Process tab / WARNINGS in the log
  EBOOT patching is on, but that emulator's EBOOT.PBP is not a normal PBP file (or
  cannot be written). The package still works with PBOOT.PBP; only the EBOOT keeps
  its own icon and title.

- Something crashed
  Unexpected errors are written to PSPify-crash.log next to the app.

-------------------------------------------------------------------------------
10. SYSTEM ID QUICK REFERENCE
-------------------------------------------------------------------------------

To get started quickly, here are the folder names for common systems:

- NES: NES          - SNES: SNES        - Game Boy: GBC     - GBA: GBA
- Genesis/MD: MD    - Master Sys: SMS   - Game Gear: GG     - N64: N64

(A full list of all supported systems is in the "System" list of the Systems tab).

-------------------------------------------------------------------------------
11. CREDITS
-------------------------------------------------------------------------------

GBA2PSP
http://github.com/sahlberg/gba2psp
PBOOT.PBP file processing and audio processing code are based on this project.

TempGBA4PSP-Single-game
https://github.com/GrabowskiDev/TempGBA4PSP-Single-game
The PBOOT.PBP structure in PSPify was initially sourced from this project and modified for custom assets.

FFmpeg
https://ffmpeg.org
Not included with PSPify; installed separately by the user. Used to decode music files.

atracdenc
https://github.com/dcherednik/atracdenc
Not included with PSPify; installed separately by the user. Used for Sony ATRAC3 encoding.

PyQt / Qt
https://www.riverbankcomputing.com/software/pyqt/
Used for the user interface.

See THIRD_PARTY_NOTICES.txt for all third-party notices (including the Feather
icons used for the interface).

PSPify itself is free software released under the GNU General Public License
v3 (see LICENSE.txt).

================================================================================
