<div align="center">

<img src="ui/hearth-mark.png" alt="Hearth Logo" width="108" />

# Hearth

**English** • [Türkçe](README.tr.md) *(Bilingual UI & Search Engine)*

<br/>

**A calm, local-first file library & workspace for Windows.**

Point Hearth at your folders: it indexes deep document text, metadata, and previews in sub-milliseconds without moving or touching a single file.  
Zero telemetry. No cloud dependency. 100% offline.

<br/>

[![License: MIT](https://img.shields.io/badge/License-MIT-cbb8a0?style=flat&logo=opensourceinitiative&logoColor=101113)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D4?style=flat&logo=windows11&logoColor=white)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Release](https://img.shields.io/badge/Release-v0.4.3-bfa588?style=flat&logo=github&logoColor=white)](https://github.com/rheme18/Hearth/releases)
<br/>
[![GitHub Stars](https://img.shields.io/github/stars/rheme18/Hearth?style=flat&logo=github&color=4EAA79)](https://github.com/rheme18/Hearth/stargazers)
[![Tests](https://img.shields.io/badge/Tests-19%20Passing-4EAA79?style=flat&logo=pytest&logoColor=white)](tests/)
[![UI Engine](https://img.shields.io/badge/UI-WebView2%20%2B%20SQLite%20WAL-101113?style=flat)](https://github.com/rheme18/Hearth)

<br/>

[Overview](#-overview) • [Key Features](#-key-features) • [Installation](#-installation) • [Search Syntax](#-search-syntax) • [Shortcuts](#-keyboard-shortcuts)
<br/>
[Architecture](#-architecture--technology-stack) • [Build from Source](#-building-from-source) • [Contributing](#-contributing) • [License](#-license)

</div>

---

## 🌟 Overview

**Hearth** is a modern, high-performance, local-first personal archive designed to replace chaotic folders with a quiet, structured, and instant digital home. 

Whether you manage legal PDFs, source code repositories, research notes, financial spreadsheets, or high-res photography, Hearth indexes file metadata and deep document text entirely on your device with zero cloud dependency.

> 🔒 **Private by Design:** Files never leave your machine. Search indexing, content extraction, thumbnail generation, PDF transformations, and image manipulations run 100% locally on your CPU.

<img width="1366" height="768" alt="Ekran Görüntüsü (2)" src="https://github.com/user-attachments/assets/6889b27d-172c-44ea-8e13-dfe685744ad1" />

---

## ✨ Key Features

### 📂 Unified File Ingestion & Drag-and-Drop
- **Drop Anything, Anywhere:** Fluid, zero-lag drag-and-drop for both loose files and entire nested directory structures directly from Windows Explorer, the Desktop, or other apps.
- **Native OLE Drag-Out:** Drag single or multiple files directly out of Hearth into emails, chat apps, Explorer folders, or browser uploads.
- **Deep Content Indexing:** Real-time background indexing extracts text from `.pdf`, `.docx`, `.xlsx`, `.pptx`, `.txt`, `.md`, `.csv`, `.json`, `.py`, and 30+ document formats.
- **Watchdog Sync:** Connected folders stay continuously synchronized in real-time as files are created, updated, or deleted on disk.

### ⚡ Lightning-Fast Search & Discovery
- **Sub-Millisecond Search:** Instant SQLite full-text search across file names, deep body contents, and personal notes.
- **Smart Collections:** Dynamic smart folders that automatically track files matching persistent search queries (e.g. `type:pdf after:2024-01-01`).
- **On This Day (Time Capsule):** Surfaces cherished memories, photos, and project milestones created on today's calendar date in past years.
- **Advanced Query Syntax:** Filter precisely with operators like `type:image`, `tag:tax`, `folder:Receipts`, `size:>10mb`, or `on:today`.

### 🛠️ Built-in Document & Media Tools
- **Complete PDF Suite:** Merge multiple documents, split by custom page ranges, extract/delete/reorder pages, rotate individual sheets (90°/180°/270°), and optimize file sizes.
- **Fast Image Converter:** Convert images between PNG, JPEG, WebP, TIFF, and BMP with fine-grained compression quality presets.
- **Spacebar QuickLook:** macOS-style instant preview modal with keyboard navigation (`←` / `→`) and text selection.
- **File Comparison:** Side-by-side SHA-256 hash match, size verification, timestamp diff, and text snippet comparison.
- **Duplicate Hunter:** Identifies byte-for-byte identical duplicates across your entire library to reclaim storage safely.

### 🎨 Craft & Aesthetics
- **Warm Obsidian Theme:** Elegant `#101113` dark canvas illuminated by warm ember and bronze accents, with full light mode support.
- **Fluid Micro-Animations:** Tactile button presses, smooth 3D file card elevation on hover, and crystal-clear drag overlays.
- **Internationalization:** Full bilingual interface supporting both English and Turkish (`tr`) with live runtime switching.
- **Reversible Deletion:** Deleted library files are safely moved to the Windows Recycle Bin with instant undo (`Ctrl+Z`).

<img width="1366" height="768" alt="Ekran Görüntüsü (4)" src="https://github.com/user-attachments/assets/70e86d07-a839-4079-88f0-de8144014f86" />

---

## 🚀 Installation

### Option 1: Windows Setup Installer (Recommended)
Download **`Hearth-0.4.3-Setup.exe`** from the [GitHub Releases](https://github.com/rheme18/Hearth/releases) page.
- Clean Inno Setup installer with modern dark styling.
- Creates Start Menu & Desktop shortcuts.
- Integrates an optional *"Add to Hearth"* shortcut into the Windows Explorer right-click context menu.

### Option 2: Standalone Portable ZIP
Download **`Hearth-0.4.3-Portable.zip`** from [Releases](https://github.com/rheme18/Hearth/releases).
- Extract anywhere (e.g. USB flash drive or external SSD).
- Zero installation, no registry modifications required.
- Keeps all databases and caches self-contained in a local `data/` directory.

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|:---|:---|
| <kbd>Space</kbd> | Toggle **QuickLook** file preview |
| <kbd>Ctrl</kbd> + <kbd>K</kbd> | Focus global search bar |
| <kbd>Ctrl</kbd> + <kbd>,</kbd> | Open Settings & Preferences |
| <kbd>Ctrl</kbd> + <kbd>Z</kbd> | **Undo** last delete or file operation |
| <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>A</kbd> | Add files dialog |
| <kbd>F1</kbd> or <kbd>Ctrl</kbd> + <kbd>/</kbd> | Show Keyboard Shortcuts cheat sheet |
| <kbd>Delete</kbd> | Move selected file(s) to Recycle Bin |
| <kbd>Escape</kbd> | Close active modal, clear search, or hide context menu |

---

## 🔎 Search Syntax

Hearth features an expressive, query-engine inspired syntax:

| Query Example | Description |
|:---|:---|
| `contract 2024` | Matches "contract" and "2024" in file name, content, or notes |
| `"annual report"` | Matches the exact quoted phrase |
| `type:pdf,docx` | Filters strictly to PDF and Word documents |
| `tag:finance` | Shows only files tagged with "finance" |
| `folder:Invoices` | Restricts search to files residing in folders matching "Invoices" |
| `after:2024-01-01` | Files modified after January 1, 2024 |
| `size:>50mb` | Files larger than 50 Megabytes |
| `is:favorite` | Shows bookmarked / favorited files |
| `on:today` | Activates Time Capsule (files created on this day in past years) |

---

## 🏗️ Architecture & Technology Stack

Hearth pairs a native Windows C# / Python foundation with a lightweight, secure WebView2 frontend:

```
Hearth/
├── main.py               # Core runtime: SQLite WAL engine, Windows OLE bridge, API endpoints
├── ui/
│   ├── index.html        # Clean semantic application shell & titlebar
│   ├── app.js            # Reactive application controller & event coordination
│   ├── styles.css        # Base design tokens, layout grid & dark/light palettes
│   └── refinements.css   # Fluid spring animations, card elevation & drop styling
├── installer/
│   └── Hearth.iss        # Inno Setup 7 compilation script (multilingual)
├── tests/
│   └── test_hearth.py    # Complete test suite (19 passing unit tests)
├── make_portable.py      # Automated portable package builder
└── requirements.txt      # Pinned production dependencies
```

<img width="1366" height="768" alt="Ekran Görüntüsü (5)" src="https://github.com/user-attachments/assets/1ac60f4a-8fb2-462f-9524-b679d4af2510" />

### Core Technologies
- **Runtime:** Python 3.12 (64-bit)
- **UI Presentation:** Microsoft Edge WebView2 Evergreen via `pywebview 6.2.1`
- **Native OS Bridge:** `pythonnet` (WinForms OLE Drag-and-Drop, shell interop)
- **Database Engine:** SQLite 3 with Write-Ahead Logging (`WAL` mode)
- **Document Processing:** `pypdfium2` & `pypdf` (hardware-accelerated PDF rendering)
- **Image Manipulation:** `Pillow` (lossless and perceptual WebP/PNG/JPEG pipelines)
- **Directory Monitoring:** `watchdog` (Windows ReadDirectoryChangesW backend)

---

## 🔨 Building from Source

### Prerequisites
- Windows 10 or 11 (64-bit)
- [Python 3.12](https://www.python.org/downloads/)
- [Microsoft WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) *(Preinstalled on Windows 11)*
- [Inno Setup 7.1+](https://jrsoftware.org/isinfo.php) *(Optional, for setup compiler)*

### 1. Clone the Repository
```powershell
git clone https://github.com/rheme18/Hearth.git
cd Hearth
```

### 2. Set Up Virtual Environment
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Run Development Build
```powershell
python main.py
```

### 4. Run Test Suite
```powershell
pytest tests/ -v
```

### 5. Compile Binary & Packages
```powershell
# 1. Compile PyInstaller Standalone Executable
pyinstaller --noconfirm Hearth.spec

# 2. Package Portable ZIP Archive
python make_portable.py

# 3. (Optional) Compile Setup Installer
ISCC.exe installer\Hearth.iss
```

---

## 🤝 Contributing

Contributions make open-source software thrive. Whether it is reporting a bug, improving documentation, or proposing new features:

1. **Fork** the project
2. Create your feature branch (`git checkout -b feat/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: Add amazing feature'`)
4. Push to the branch (`git push origin feat/amazing-feature`)
5. Open a **Pull Request**

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for complete details.

<br/>

<div align="center">

Crafted with care for your files. **Hearth** — *Everything, in its right place.*

</div>
