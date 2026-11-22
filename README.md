<div align="center">

<img src="ui/hearth-mark.png" alt="Hearth Logo" width="96" />

# Hearth

**Your personal, local-first file archive — beautifully organized, privately yours.**

<br/>

[![License: MIT](https://img.shields.io/badge/License-MIT-c8a97a?style=for-the-badge&logo=opensourceinitiative&logoColor=white)](LICENSE)
[![Windows 10/11](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?style=for-the-badge&logo=windows11&logoColor=white)](https://www.microsoft.com/windows)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Version](https://img.shields.io/badge/Version-0.4.3-b5a08a?style=for-the-badge&logo=github&logoColor=white)](CHANGELOG.md)

</div>

---

## What is Hearth?

Hearth is a **local-first desktop archive application** for Windows. It gives you a warm, focused place to drop, organize, search, and revisit your files — without cloud sync, subscriptions, or privacy trade-offs.

Think of it as a personal file library that lives entirely on your machine: instant full-text search across documents, PDFs, images, and Office files; intelligent tagging and collections; built-in PDF tools; image conversion; and a "time capsule" that surfaces files you created on the same calendar day in past years.

---

## ✨ Features

### 📁 File Management
- **Drag & Drop** — Drop files or entire folders onto Hearth from Explorer, the Desktop, or any application.
- **Native Drag-out** — Drag files from Hearth back to Explorer, the Desktop, messaging apps, or browsers. Multi-selection supported.
- **Clipboard Integration** — Copy files to the Windows clipboard; paste directly into Explorer with `Ctrl+V`.
- **Reversible Delete** — Deleted files go to the system Recycle Bin with full undo support.
- **Rename & Move** — Rename files in-place; Hearth tracks the new path automatically.
- **Context Menu** — Optional "Add to Hearth" entry in the Windows Explorer right-click menu.

### 🔍 Search & Discovery
- **Full-Text Search** — Indexes `.txt`, `.md`, `.pdf`, `.docx`, `.xlsx`, `.pptx`, and 30+ other formats.
- **Smart Filters** — Filter by type, date range, folder, file size, tags, favorites, and more.
- **Saved Searches** — Persist any query as a named search for one-click re-use.
- **Smart Collections** — Dynamic collections that auto-populate based on a live query.
- **On This Day** — Surfaces files you created on today's calendar day in previous years (Time Capsule).
- **Search Syntax** — Rich query language: `type:pdf`, `tag:tax`, `folder:Receipts`, `after:2024-01-01`, `on:today`, and more.

### 🏷️ Organization
- **Tags** — Color-coded tags; assign multiple tags per file; filter by any combination.
- **Favorites** — Star files for quick access.
- **Collections** — Manually curated groupings; files can belong to multiple collections.
- **Private Notes** — Add a personal memory note to any file; notes are searchable and follow renames.

### 📄 PDF Tools
- **Merge** — Combine multiple PDFs into one.
- **Split** — Split by page range (e.g., `1-2,3`).
- **Extract Pages** — Pull specific pages into a new file.
- **Delete Pages** — Remove unwanted pages.
- **Reorder Pages** — Rearrange page order.
- **Rotate Pages** — Rotate individual pages by 90°/180°/270°.
- **Optimize** — Reduce file size.
- **Page Preview** — Thumbnail carousel with per-page rotation editor.

### 🖼️ Image Tools
- **Format Conversion** — Convert between PNG, JPEG, WebP, TIFF, and BMP with quality control.

### 🔎 QuickLook
- Press `Space` on any focused file for an instant preview modal.
- Navigate with `←` / `→` arrow keys; close with `Escape` or `Space`.

### ⚖️ File Comparison
- Select two files to get a side-by-side comparison: SHA-256 hash match, size, date, and text snippet diff.

### 🔁 Duplicate Finder
- Detects exact duplicates by content hash; review groups and remove copies with one click (undoable).

### 💾 Backup & Restore
- Export and restore the entire library database as a `.zip` archive.

### 🌐 Multilingual
- Full English and Turkish (`tr`) UI; language toggles in settings with no restart required.

### 🎨 UI & Animations
- Dark warm theme (`#101113` background, ember-gold accents).
- Smooth micro-animations: drag aura glow, refresh spin, splash pulse, toast spring.
- Fully respects `prefers-reduced-motion` for accessibility.
- System tray icon for quick access and background operation.
- Resizable, edge/corner-draggable frameless window.

---

## 📸 Screenshots

> *Screenshots coming soon — feel free to open a PR with your favorites!*

---

## 🚀 Getting Started

### Option 1 — Installer (Recommended)

Download the latest `Hearth-0.4.3-Setup.exe` from the [Releases](../../releases) page and run it.

### Option 2 — Portable

Download `Hearth-0.4.3-Portable.zip`, extract it anywhere, and run `Hearth.exe`.  
Create a file named `portable.dat` next to the executable to keep all data in the same folder (great for USB drives).

### Option 3 — Run from Source

```powershell
# Requires Python 3.12 and the Microsoft WebView2 Evergreen Runtime
git clone https://github.com/your-username/Hearth.git
cd Hearth
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

---

## 🔨 Building

> **Prerequisites:** Python 3.12, [Inno Setup 7.1.1](https://jrsoftware.org/isinfo.php), [Microsoft WebView2 Evergreen Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)

```powershell
# From the project root — creates dist\Hearth\
.\build.ps1

# Then compile the installer with Inno Setup
# Open installer\Hearth.iss in Inno Setup Compiler and press Build
```

The build script creates an isolated `.build-env` virtual environment, installs pinned runtime dependencies plus PyInstaller 6.22.3, and produces the standalone `dist\Hearth\` folder.

---

## 🧪 Testing

```powershell
python -m pytest tests/
```

19 unit tests cover: file indexing, search filters, pagination, favorites, tags, saved searches, smart collections, PDF tools, image conversion, duplicate detection, undo/redo, backup/restore, private notes, and more.

---

## 🏗️ Architecture

```
Hearth/
├── main.py               # Python backend — SQLite library, file ops, PDF/image tools, Windows APIs
├── ui/
│   ├── index.html        # App shell & splash screen
│   ├── app.js            # Frontend logic (~4 500 lines, vanilla JS)
│   ├── styles.css        # Base theme
│   └── refinements.css   # Micro-animations & polish
├── installer/
│   └── Hearth.iss        # Inno Setup script
├── tests/
│   └── test_hearth.py    # Unit tests (19 passing)
└── requirements.txt
```

**Technology stack:**

| Layer | Technology |
|---|---|
| Backend | Python 3.12 |
| UI runtime | pywebview 6.2.1 (WebView2 / Chromium) |
| Database | SQLite 3 (WAL mode) |
| PDF | pypdfium2 5.15.2, pypdf 7.1.1 |
| Images | Pillow 12.3.0 |
| File watching | watchdog 7.1.0 |
| Packaging | PyInstaller 6.22.3 + Inno Setup 7.1.1 |

---

## 🗺️ Roadmap

- [ ] Global keyboard shortcut to bring Hearth to focus
- [ ] File tagging via drag from Explorer
- [ ] Export collections as ZIP archives
- [ ] Plugin / extension API
- [ ] macOS / Linux support (contributions welcome)

---

## 🤝 Contributing

Contributions are welcome! Please open an issue before submitting a pull request so we can discuss the approach.

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m 'feat: add my feature'`
4. Push to the branch: `git push origin feature/my-feature`
5. Open a Pull Request

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for the full text.

---

<div align="center">

Made with 🔥 by the Hearth contributors

</div>
