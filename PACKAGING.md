# Hearth — packaging checklist

The installer definition targets Windows x64 and assumes a one-folder PyInstaller build. Its modern dark wizard uses Hearth artwork, offers English (default) and Turkish, requires MIT license acceptance, and offers to launch Hearth after installation. The installer does not bundle or install WebView2; it checks for the Evergreen runtime and explains how to install it if absent. No signing certificate is configured.

## Build

1. Install Python 3.12, Inno Setup 7.1.1, and the Microsoft WebView2 Evergreen Runtime.
2. Run `build.ps1` from the project root. It creates an isolated `.build-env`, installs the pinned runtime plus PyInstaller 6.22.3, then builds `dist\Hearth`.
3. Run Inno Setup Compiler on `installer\Hearth.iss` to produce `dist\installer\Hearth-0.4.0-Setup.exe`.

## Before shipping

- Test on a clean Windows user profile (not just the developer machine): first launch, WebView2 missing/present, upgrade from 0.2.x data, and fresh reinstall.
- Exercise Explorer mixed file/folder drop, edge/corner resize, maximize/restore, native dialogs, large/locked files, and orderly shutdown on the packaged build.
- Test setup and uninstall, shortcuts/icon, MIT and font license notices, and preservation of `%LOCALAPPDATA%\Hearth` on uninstall.
- Inspect the packaged file list and runtime behavior; confirm no source library data, test fixtures, or private user files are included.
- Sign the installer and executable if a publisher certificate is available; otherwise identify the package as unsigned.

The 0.4.0 setup was silently installed into a temporary directory with isolated local app data. Its executable started and initialized a fresh local database; the automated suite passed all 15 flow tests, including first-launch window geometry, mixed file/folder drops, indexing, undo, backups, PDF operations, and private file notes. This is a local smoke check, not clean-machine qualification. A clean Windows profile or VM is still needed to verify Explorer drag-and-drop, upgrade from 0.2.x data, missing-WebView2 guidance, interactive setup and uninstall/reinstall, and broader installed-app behavior. The executable and setup are unsigned. Inno Setup 7 is free for non-commercial use; commercial use requires an Inno Setup commercial license.
