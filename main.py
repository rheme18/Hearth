"""Hearth 0.4.3 — local-first desktop archive.

Start with: python main.py
Runtime dependencies are listed in requirements.txt.
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import hashlib
from importlib import metadata
from contextlib import closing
from datetime import datetime, timedelta
import json
from io import BytesIO
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import webview
try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None
try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    PdfReader = PdfWriter = None

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys._MEIPASS)
    EXE_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
    EXE_DIR = APP_DIR

UI_DIR = APP_DIR / "ui"
if (EXE_DIR / "portable.dat").exists() or (EXE_DIR / "data").exists() or os.environ.get("HEARTH_PORTABLE") == "1":
    APP_DATA = EXE_DIR / "data"
else:
    APP_DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Hearth"

APP_DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DATA / "library.sqlite3"
TEXT_EXTS = {".txt", ".md", ".rst", ".log", ".csv", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".html", ".htm", ".css", ".js", ".ts", ".py", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".sh", ".ps1", ".sql", ".tex", ".eml"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
OFFICE_EXTS = {".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm"}
AUDIO_MIME = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".flac": "audio/flac"}
VIDEO_MIME = {".mp4": "video/mp4", ".webm": "video/webm", ".ogv": "video/ogg"}
SKIP_DIRS = {"$recycle.bin", "system volume information", "node_modules", ".git", "__pycache__", ".vs", ".idea", ".vscode", "dist", "build", "target", "bin", "obj", "packages", "venv", ".venv", "env", ".env", "node_modules", "bower_components", "jspm_packages", "web_modules"}
APP_VERSION = "0.4.3"
CONTENT_INDEX_VERSION = 3
_CACHED_RUNTIME_INFO = None


def _primary_work_area():
    """Return the primary display's usable rectangle in native pixels."""
    if os.name == "nt":
        try:
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        except (AttributeError, OSError, TypeError):
            pass
    screens = getattr(webview, "screens", [])
    if screens:
        screen = screens[0]
        try:
            return int(screen.x), int(screen.y), int(screen.x + screen.width), int(screen.y + screen.height)
        except (AttributeError, TypeError, ValueError):
            pass
    return None


def _center_shift(visible_bounds, work_area):
    left, top, right, bottom = visible_bounds
    work_left, work_top, work_right, work_bottom = work_area
    target_left = work_left + max(0, (work_right - work_left - (right - left)) // 2)
    target_top = work_top + max(0, (work_bottom - work_top - (bottom - top)) // 2)
    return target_left - left, target_top - top


IPC_PORT_FILE = APP_DATA / ".hearth_ipc"


def get_app_executable_command(subcommand=""):
    """Return the correct shell invocation for Hearth with optional arguments."""
    if getattr(sys, "frozen", False):
        exe = f'"{sys.executable}"'
    else:
        py = f'"{sys.executable}"'
        script = f'"{str((APP_DIR / "main.py").resolve())}"'
        exe = f'{py} {script}'
    return f'{exe} {subcommand}'.strip() if subcommand else exe


def get_app_icon_path():
    """Return the icon path for shortcuts and context menus."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    ico = (APP_DIR / "hearth.ico").resolve()
    return f'"{str(ico)}"' if ico.exists() else ""


def _delete_registry_tree(root, subkey):
    """Recursively delete a Windows registry subkey and all its children."""
    if os.name != "nt":
        return
    import winreg
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    sub = winreg.EnumKey(key, 0)
                    _delete_registry_tree(root, subkey + "\\" + sub)
                except OSError:
                    break
        winreg.DeleteKey(root, subkey)
    except OSError:
        pass


def sync_context_menu_registry(enabled: bool, lang: str = "en"):
    """Register or unregister 'Add to Hearth' / 'Hearth'a Ekle' in Windows Explorer context menu."""
    if os.name != "nt":
        return
    import winreg
    label = "Hearth'a Ekle" if lang == "tr" else "Add to Hearth"
    icon_val = get_app_icon_path()
    file_cmd = get_app_executable_command('"%1"')
    bg_cmd = get_app_executable_command('"%V"')

    targets = [
        (r"Software\Classes\*\shell\Hearth", file_cmd),
        (r"Software\Classes\Directory\shell\Hearth", file_cmd),
        (r"Software\Classes\Directory\Background\shell\Hearth", bg_cmd),
        (r"Software\Classes\Drive\shell\Hearth", file_cmd),
    ]

    if enabled:
        for subkey, cmd in targets:
            try:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, subkey) as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, label)
                    if icon_val:
                        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_val)
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, subkey + r"\command") as cmd_key:
                    winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd)
            except Exception:
                pass
    else:
        for subkey, _ in targets:
            _delete_registry_tree(winreg.HKEY_CURRENT_USER, subkey)


def try_send_to_running_instance(paths: list[str]) -> bool:
    """If another Hearth instance is running, pass paths to it and return True."""
    if not IPC_PORT_FILE.exists():
        return False
    try:
        port = int(IPC_PORT_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        try:
            IPC_PORT_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        return False

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.6) as s:
            payload = json.dumps({"action": "add_and_show", "paths": paths}).encode("utf-8")
            s.sendall(payload)
            s.settimeout(1.0)
            s.recv(1024)
            return True
    except (OSError, socket.timeout):
        try:
            IPC_PORT_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def start_ipc_server(api):
    """Start local IPC server to receive paths and commands from other instances."""
    try:
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(5)
        port = server_sock.getsockname()[1]
        IPC_PORT_FILE.write_text(str(port), encoding="utf-8")

        def loop():
            while not getattr(api, "_closing", False):
                try:
                    conn, _ = server_sock.accept()
                except OSError:
                    break
                try:
                    conn.settimeout(2.0)
                    data = conn.recv(65536)
                    if data:
                        msg = json.loads(data.decode("utf-8", errors="replace"))
                        if msg.get("action") == "add_and_show":
                            inc_paths = msg.get("paths", [])
                            if inc_paths:
                                api.queue_add_paths(inc_paths)
                            api.show_window()
                        conn.sendall(b'{"ok": true}')
                except Exception:
                    pass
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass

        t = threading.Thread(target=loop, name="hearth-ipc-server", daemon=True)
        t.start()
        return server_sock
    except Exception as exc:
        print(f"[IPC] Server error: {exc}", file=sys.stderr)
        return None


class TrayManager:
    """Manages the Windows notification tray icon and context menu."""

    def __init__(self, api):
        self.api = api
        self.notify_icon = None
        self.menu = None
        self.open_item = None
        self.exit_item = None
        self.init_tray()

    def init_tray(self):
        if os.name != "nt":
            return
        try:
            import clr
            clr.AddReference("System.Windows.Forms")
            clr.AddReference("System.Drawing")
            from System.Windows.Forms import (
                NotifyIcon, ContextMenuStrip, ToolStripMenuItem,
                ToolStripSeparator, MouseButtons
            )
            from System.Drawing import Icon

            self.notify_icon = NotifyIcon()
            icon_file = APP_DIR / "hearth.ico"
            if icon_file.exists():
                try:
                    self.notify_icon.Icon = Icon(str(icon_file.resolve()))
                except Exception:
                    pass
            self.notify_icon.Text = "Hearth"

            self.menu = ContextMenuStrip()
            self.open_item = ToolStripMenuItem()
            self.open_item.Click += lambda s, e: self.api.show_window()

            self.exit_item = ToolStripMenuItem()
            self.exit_item.Click += lambda s, e: self.api.exit_app()

            self.update_language(self.api.get_current_language())

            self.menu.Items.Add(self.open_item)
            self.menu.Items.Add(ToolStripSeparator())
            self.menu.Items.Add(self.exit_item)

            self.notify_icon.ContextMenuStrip = self.menu

            def on_tray_click(sender, event):
                try:
                    if hasattr(event, "Button") and event.Button == MouseButtons.Left:
                        self.api.show_window()
                except Exception:
                    self.api.show_window()

            self.notify_icon.Click += on_tray_click
            self.notify_icon.DoubleClick += on_tray_click
            self.notify_icon.Visible = True
        except Exception as exc:
            print(f"[Tray] Initialization note: {exc}", file=sys.stderr)

    def update_language(self, lang):
        if not self.open_item or not self.exit_item:
            return
        try:
            if lang == "tr":
                self.open_item.Text = "Hearth'i Aç"
                self.exit_item.Text = "Tamamen Kapat"
            else:
                self.open_item.Text = "Open Hearth"
                self.exit_item.Text = "Exit Hearth"
        except Exception:
            pass

    def cleanup(self):
        if self.notify_icon:
            try:
                self.notify_icon.Visible = False
                self.notify_icon.Dispose()
            except Exception:
                pass
            self.notify_icon = None


class Library:
    def __init__(self):
        self.lock = threading.RLock()
        self.scan_lock = threading.Lock()
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        old_collections = False
        present = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='collections'").fetchone()
        if present:
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(collections)")}
            if "id" not in columns or "name" not in columns or "created" not in columns:
                if not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='collections_legacy'").fetchone():
                    self.db.execute("ALTER TABLE collections RENAME TO collections_legacy")
                old_collections = True
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS roots(path TEXT PRIMARY KEY, added_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, name TEXT NOT NULL, ext TEXT NOT NULL,
              size INTEGER NOT NULL, modified REAL NOT NULL, content TEXT NOT NULL, root TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS files_name ON files(name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS files_modified ON files(modified DESC);
            CREATE TABLE IF NOT EXISTS collections(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS smart_collections(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
              query TEXT NOT NULL DEFAULT '', filters TEXT NOT NULL DEFAULT '{}', category TEXT NOT NULL DEFAULT 'Everything', created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS collection_items(collection_id INTEGER NOT NULL, path TEXT NOT NULL,
              PRIMARY KEY(collection_id,path));
            CREATE TABLE IF NOT EXISTS prefs(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS favorites(path TEXT PRIMARY KEY, added_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, color TEXT NOT NULL DEFAULT '#a58d6d');
            CREATE TABLE IF NOT EXISTS file_tags(path TEXT NOT NULL, tag_id INTEGER NOT NULL,
              PRIMARY KEY(path,tag_id));
            CREATE UNIQUE INDEX IF NOT EXISTS tags_name_nocase ON tags(name COLLATE NOCASE);
            CREATE TABLE IF NOT EXISTS saved_searches(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
              query TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'Everything', filters TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS file_index_versions(path TEXT PRIMARY KEY, content_version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS file_hashes(path TEXT PRIMARY KEY, size INTEGER NOT NULL,
              modified REAL NOT NULL, sha256 TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS file_notes(path TEXT PRIMARY KEY, note TEXT NOT NULL,
              updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS undo_ops(id INTEGER PRIMARY KEY, action TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS activity_log(id INTEGER PRIMARY KEY, action TEXT NOT NULL, item_count INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'completed', created REAL NOT NULL);
        """)
        self.db.commit()
        saved_search_columns = {row[1] for row in self.db.execute("PRAGMA table_info(saved_searches)")}
        if "filters" not in saved_search_columns:
            self.db.execute("ALTER TABLE saved_searches ADD COLUMN filters TEXT NOT NULL DEFAULT '{}'")
            self.db.commit()
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='collections_legacy'").fetchone():
            old_collections = True
        if old_collections:
            legacy_rows = self.db.execute("SELECT path FROM collections_legacy").fetchall()
            for old in legacy_rows:
                old_path = old["path"]
                base_name = Path(old_path).name or "Saved place"
                name = base_name
                suffix = 2
                while self.db.execute("SELECT 1 FROM collections WHERE name=?", (name,)).fetchone():
                    name = f"{base_name} {suffix}"
                    suffix += 1
                cursor = self.db.execute("INSERT INTO collections(name,created) VALUES(?,?)", (name, time.time()))
                collection_id = cursor.lastrowid
                if os.path.isdir(old_path):
                    candidates = self.db.execute("SELECT path FROM files").fetchall()
                    for candidate in candidates:
                        try:
                            if os.path.commonpath([old_path, candidate["path"]]) == old_path:
                                self.db.execute("INSERT OR IGNORE INTO collection_items VALUES(?,?)", (collection_id, candidate["path"]))
                        except ValueError:
                            continue
                else:
                    self.db.execute("INSERT OR IGNORE INTO collection_items VALUES(?,?)", (collection_id, old_path))
            self.db.execute("DROP TABLE collections_legacy")
            self.db.commit()
        self.scan_status = {"running": False, "root": "", "count": 0, "message": "Ready"}

    def roots(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT path, added_at FROM roots ORDER BY added_at")]

    def add_root(self, path):
        path = os.path.normpath(path)
        if not os.path.isdir(path):
            return {"ok": False, "error": "That folder is no longer available."}
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO roots VALUES(?,?)", (path, time.time()))
            self.db.commit()
        threading.Thread(target=self.scan, args=(path,), daemon=True).start()
        return {"ok": True, "path": path}

    def add_dropped_paths(self, paths):
        folders, files = [], []
        for path in paths or []:
            if os.path.isdir(path):
                folders.append(path)
            elif os.path.isfile(path):
                files.append(path)
        for folder in folders:
            self.add_root(folder)
        indexed = 0
        indexed_paths = []
        for path in files:
            try:
                p = Path(path)
                stat = p.stat()
                ext = p.suffix.lower()
                body = self._extract_text(p, stat.st_size)
                root = next((r["path"] for r in self.roots() if HearthAPI._is_inside(path, r["path"])), "")
                with self.lock:
                    self.db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?)",
                                    (str(p), p.name, ext, stat.st_size, stat.st_mtime, body, root))
                    self.db.execute("INSERT OR REPLACE INTO file_index_versions VALUES(?,?)",
                                    (str(p), CONTENT_INDEX_VERSION))
                    self.db.execute("DELETE FROM file_hashes WHERE path=?", (str(p),))
                    self.db.commit()
                indexed += 1
                indexed_paths.append(str(p))
            except (OSError, UnicodeError):
                continue
        return {"ok": True, "folders": len(folders), "files": indexed,
                "folder_paths": folders, "file_paths": indexed_paths}

    @staticmethod
    def _extract_text(path, size):
        ext = Path(path).suffix.lower()
        try:
            if ext in TEXT_EXTS and size <= 1_000_000:
                return Path(path).read_text(encoding="utf-8", errors="replace")[:150_000]
            if ext in {".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm"} and size <= 60_000_000:
                return Library._extract_office_text(path, ext)
            if ext == ".pdf" and pdfium and size <= 60_000_000:
                with pdfium.PdfDocument(path) as document:
                    chunks = []
                    total_chars = 0
                    for page_number in range(len(document)):
                        page = document[page_number]
                        text_page = page.get_textpage()
                        text = text_page.get_text_bounded()
                        chunks.append(text)
                        total_chars += len(text)
                        text_page.close()
                        page.close()
                        if total_chars >= 150_000:
                            break
                    return "\n".join(chunks)[:150_000]
        except Exception:
            pass
        return ""

    @staticmethod
    def _extract_office_text(path, ext):
        try:
            with zipfile.ZipFile(path) as package:
                names = package.namelist()
                if ext in {".docx", ".docm"}:
                    members = ["word/document.xml"]
                elif ext in {".pptx", ".pptm"}:
                    members = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                                     key=lambda n: int(re.search(r"slide(\d+)", n).group(1)))
                else:
                    members = sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
                    if "xl/sharedStrings.xml" in names:
                        members.insert(0, "xl/sharedStrings.xml")
                if sum(package.getinfo(name).file_size for name in members) > 120_000_000:
                    return ""
                parts = []
                shared = []
                for member in members:
                    try:
                        root = ET.fromstring(package.read(member))
                    except ET.ParseError:
                        continue
                    local = member.rsplit("/", 1)[-1]
                    if local == "sharedStrings.xml":
                        shared = []
                        for item in root:
                            if not item.tag.endswith("}si"):
                                continue
                            texts = []
                            for node in item.iter():
                                if node.tag.endswith("}t") and node.text:
                                    texts.append(node.text)
                            shared.append("".join(texts))
                    elif local.startswith("sheet"):
                        for cell in root.iter():
                            if not cell.tag.endswith("}c"):
                                continue
                            value = None
                            v_child = next((child for child in cell if child.tag.endswith("}v")), None)
                            if v_child is not None:
                                value = v_child.text
                            if value is None:
                                inline = next((child for child in cell if child.tag.endswith("}is")), None)
                                if inline is not None:
                                    value = "".join(node.text or "" for node in inline.iter() if node.tag.endswith("}t"))
                            if value is not None and cell.attrib.get("t") == "s":
                                try:
                                    idx = int(value)
                                    if 0 <= idx < len(shared):
                                        value = shared[idx]
                                    else:
                                        value = ""
                                except (ValueError, IndexError):
                                    value = ""
                            if value:
                                parts.append(value)
                    else:
                        for node in root.iter():
                            if node.tag.endswith("}t") and node.text:
                                parts.append(node.text)
                    if sum(map(len, parts)) >= 150_000:
                        break
                return "\n".join(parts)[:150_000]
        except Exception:
            return ""

    def scan(self, root):
        with self.scan_lock:
            self.scan_status = {"running": True, "root": root, "count": 0, "message": "Looking through your files…"}
            try:
                with self.lock:
                    prefs = dict(self.db.execute("SELECT key,value FROM prefs WHERE key IN ('excluded_paths','excluded_extensions','max_content_mb')").fetchall())
            except (sqlite3.ProgrammingError, sqlite3.OperationalError):
                return
            try:
                excluded_paths = [os.path.normcase(os.path.abspath(p)) for p in json.loads(prefs.get("excluded_paths", "[]")) if isinstance(p, str)]
                excluded_extensions = {str(x).casefold() if str(x).startswith(".") else "." + str(x).casefold() for x in json.loads(prefs.get("excluded_extensions", "[]"))}
                max_content_bytes = max(1, min(512, int(prefs.get("max_content_mb", "60")))) * 1_048_576
            except (TypeError, ValueError, json.JSONDecodeError):
                excluded_paths, excluded_extensions, max_content_bytes = [], set(), 60 * 1_048_576

            def excluded_path(path):
                normalized = os.path.normcase(os.path.abspath(path))
                for blocked in excluded_paths:
                    try:
                        if os.path.commonpath((normalized, blocked)) == blocked:
                            return True
                    except ValueError:
                        continue
                return False

            count = 0
            for current, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not d.startswith(".") and not d.startswith("$") and not excluded_path(os.path.join(current, d))]
                for filename in files:
                    path = os.path.join(current, filename)
                    try:
                        stat = os.stat(path)
                        ext = Path(filename).suffix.lower()
                        if ext in excluded_extensions or excluded_path(path):
                            continue
                        with self.lock:
                            old = self.db.execute("SELECT size,modified FROM files WHERE path=?", (path,)).fetchone()
                            version = self.db.execute("SELECT content_version FROM file_index_versions WHERE path=?", (path,)).fetchone()
                        count += 1
                        if old and version and version["content_version"] == CONTENT_INDEX_VERSION and old["size"] == stat.st_size and old["modified"] == stat.st_mtime:
                            continue
                        body = self._extract_text(Path(path), stat.st_size) if stat.st_size <= max_content_bytes else ""
                        with self.lock:
                            self.db.execute("""INSERT INTO files VALUES(?,?,?,?,?,?,?)
                              ON CONFLICT(path) DO UPDATE SET name=excluded.name, ext=excluded.ext,
                              size=excluded.size, modified=excluded.modified, content=excluded.content, root=excluded.root""",
                              (path, filename, ext, stat.st_size, stat.st_mtime, body, root))
                            self.db.execute("DELETE FROM file_hashes WHERE path=?", (path,))
                            self.db.execute("INSERT OR REPLACE INTO file_index_versions VALUES(?,?)",
                                            (path, CONTENT_INDEX_VERSION))
                            if count % 25 == 0:
                                self.db.commit()
                                self.scan_status.update(count=count, message=f"Indexing · {count:,} files")
                    except OSError:
                        continue
            with self.lock:
                rows = self.db.execute("SELECT path FROM files WHERE root=?", (root,)).fetchall()
                gone = [(r["path"],) for r in rows if not os.path.exists(r["path"]) or excluded_path(r["path"]) or Path(r["path"]).suffix.casefold() in excluded_extensions]
                self.db.executemany("DELETE FROM files WHERE path=?", gone)
                self.db.executemany("DELETE FROM collection_items WHERE path=?", gone)
                self.db.executemany("DELETE FROM favorites WHERE path=?", gone)
                self.db.executemany("DELETE FROM file_tags WHERE path=?", gone)
                self.db.executemany("DELETE FROM file_index_versions WHERE path=?", gone)
                self.db.executemany("DELETE FROM file_hashes WHERE path=?", gone)
                self.db.commit()
            self.scan_status.update(running=False, count=count, message=f"{count:,} files ready")

    @staticmethod
    def _like_term(value):
        return "%" + str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    @staticmethod
    def _parse_search_query(query):
        fields = {"types": [], "tags": [], "after": [], "before": [], "folders": [], "sizes": [], "favorite": False, "on_this_day": False}
        terms = []
        tokens = re.findall(r'"[^"\\]*(?:\\.[^"\\]*)*"|\S+', query or "")
        for token in tokens:
            raw = token[1:-1] if len(token) >= 2 and token[0] == token[-1] == '"' else token
            lowered = raw.casefold()
            if lowered.startswith("type:") and raw[5:]:
                fields["types"].extend([x.strip().lower().lstrip(".") for x in raw[5:].split(",") if x.strip()])
            elif lowered.startswith("tag:") and raw[4:]:
                fields["tags"].append(raw[4:])
            elif lowered.startswith("after:") and raw[6:]:
                fields["after"].append(raw[6:])
            elif lowered.startswith("before:") and raw[7:]:
                fields["before"].append(raw[7:])
            elif lowered.startswith("folder:") and raw[7:]:
                fields["folders"].append(raw[7:])
            elif lowered == "is:favorite":
                fields["favorite"] = True
            elif lowered in {"on:today", "on:thisday"}:
                fields["on_this_day"] = True
            elif lowered.startswith("size:") or lowered.startswith("size"):
                size_match = re.fullmatch(r"size:?(>=|<=|>|<|=)(\d+(?:\.\d+)?)(b|kb|mb|gb|tb)?", lowered)
                if size_match:
                    number = float(size_match.group(2))
                    multiplier = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4, None: 1}[size_match.group(3)]
                    fields["sizes"].append((size_match.group(1), int(number * multiplier)))
                else:
                    terms.append(raw)
            else:
                terms.append(raw)
        return terms, fields

    def _file_where(self, query="", category="Everything", collection_id=None, folder_path=None, filters=None):
        where, args = [], []
        terms, fields = self._parse_search_query(query)
        for term in terms:
            pattern = self._like_term(term)
            where.append("(files.name LIKE ? ESCAPE '\\' COLLATE NOCASE OR files.path LIKE ? ESCAPE '\\' COLLATE NOCASE OR files.content LIKE ? ESCAPE '\\' COLLATE NOCASE OR EXISTS (SELECT 1 FROM file_tags ft JOIN tags t ON t.id=ft.tag_id WHERE ft.path=files.path AND t.name LIKE ? ESCAPE '\\' COLLATE NOCASE) OR EXISTS (SELECT 1 FROM file_notes fn WHERE fn.path=files.path AND fn.note LIKE ? ESCAPE '\\' COLLATE NOCASE))")
            args.extend([pattern] * 5)
        if fields["types"]:
            exts = list(dict.fromkeys("." + ext for ext in fields["types"]))
            where.append("files.ext IN (" + ",".join("?" for _ in exts) + ")")
            args.extend(exts)
        for tag in fields["tags"]:
            where.append("EXISTS (SELECT 1 FROM file_tags ft JOIN tags t ON t.id=ft.tag_id WHERE ft.path=files.path AND t.name LIKE ? ESCAPE '\\' COLLATE NOCASE)")
            args.append(self._like_term(tag))
        for date_value in fields["after"]:
            try:
                timestamp = datetime.fromisoformat(date_value).timestamp()
                where.append("files.modified>=?")
                args.append(timestamp)
            except ValueError:
                where.append("0")
        for date_value in fields["before"]:
            try:
                timestamp = (datetime.fromisoformat(date_value) + timedelta(days=1)).timestamp()
                where.append("files.modified<?")
                args.append(timestamp)
            except ValueError:
                where.append("0")
        for operator, size in fields["sizes"]:
            sql_operator = {">": ">", ">=": ">=", "<": "<", "<=": "<=", "=": "="}[operator]
            where.append(f"files.size {sql_operator} ?")
            args.append(size)
        for folder in fields["folders"]:
            folder = os.path.normpath(folder)
            if os.path.isabs(folder):
                where.append("(files.path=? OR files.path LIKE ? ESCAPE '\\')")
                args.extend([folder, self._like_term(folder + os.sep)[:-1] + "%"])
            else:
                pattern = self._like_term(os.sep + folder + os.sep)
                where.append("(files.path LIKE ? ESCAPE '\\' COLLATE NOCASE OR files.path LIKE ? ESCAPE '\\' COLLATE NOCASE)")
                args.extend([pattern, self._like_term(os.sep + folder)])
        if fields["favorite"]:
            where.append("EXISTS (SELECT 1 FROM favorites WHERE favorites.path=files.path)")
        categories = {
            "Documents": "ext IN ('.pdf','.doc','.docx','.txt','.md','.rtf','.odt')",
            "Images": "ext IN ('.png','.jpg','.jpeg','.gif','.bmp','.webp','.tif','.tiff')",
            "Audio": "ext IN ('.mp3','.wav','.m4a','.flac','.aac','.ogg')",
            "Video": "ext IN ('.mp4','.mov','.mkv','.avi','.webm')",
            "Spreadsheets": "ext IN ('.xlsx','.xls','.csv','.ods')",
        }
        if category in categories:
            where.append(categories[category])
        if category == "Favorites":
            where.append("EXISTS (SELECT 1 FROM favorites WHERE favorites.path=files.path)")
        if category == "Duplicates":
            where.append("files.path IN (SELECT path FROM file_hashes GROUP BY sha256 HAVING COUNT(*)>1)")
        if category in {"Recently added", "Recently modified"}:
            where.append("modified >= ?")
            args.append(time.time() - 30 * 86400)
        if fields.get("on_this_day") or category == "On This Day":
            where.append("strftime('%m-%d', datetime(files.modified, 'unixepoch', 'localtime')) = strftime('%m-%d', 'now', 'localtime')")
        join = ""
        if isinstance(collection_id, str) and collection_id.startswith("smart:"):
            try:
                smart_id = int(collection_id.split(":", 1)[1])
                with self.lock:
                    smart = self.db.execute("SELECT query,category,filters FROM smart_collections WHERE id=?", (smart_id,)).fetchone()
                if smart:
                    try:
                        smart_filters = json.loads(smart["filters"] or "{}")
                    except (TypeError, json.JSONDecodeError):
                        smart_filters = {}
                    smart_join, smart_clause, smart_args = self._file_where(
                        smart["query"], smart["category"], filters=smart_filters)
                    where.append(f"files.path IN (SELECT files.path FROM files{smart_join}{smart_clause})")
                    args.extend(smart_args)
                else:
                    where.append("0")
            except (ValueError, IndexError):
                where.append("0")
        elif collection_id:
            join = " JOIN collection_items ci ON ci.path=files.path"
            where.append("ci.collection_id=?")
            args.append(collection_id)
        if folder_path:
            folder_path = os.path.normpath(folder_path)
            where.append("(files.path=? OR files.path LIKE ?)")
            args.extend([folder_path, folder_path + os.sep + "%"])
        filters = filters or {}
        extensions = filters.get("extensions", filters.get("extension", []))
        if isinstance(extensions, str):
            extensions = [x.strip() for x in extensions.split(",") if x.strip()]
        extensions = list(dict.fromkeys((x.lower() if x.startswith(".") else "." + x.lower()) for x in extensions if isinstance(x, str) and x.strip())) if isinstance(extensions, list) else []
        if extensions:
            where.append("files.ext IN (" + ",".join("?" for _ in extensions) + ")")
            args.extend(extensions)
        filter_folder = (filters.get("folder") or "").strip()
        if filter_folder:
            filter_folder = os.path.normpath(filter_folder)
            where.append("(files.path=? OR files.path LIKE ? ESCAPE '\\')")
            args.extend([filter_folder, self._like_term(filter_folder + os.sep)[:-1] + "%"])
        try:
            if filters.get("date_from"):
                timestamp = datetime.fromisoformat(filters["date_from"]).timestamp()
                where.append("files.modified>=?")
                args.append(timestamp)
            if filters.get("date_to"):
                timestamp = (datetime.fromisoformat(filters["date_to"]) + timedelta(days=1)).timestamp()
                where.append("files.modified<?")
                args.append(timestamp)
            if filters.get("min_mb") not in (None, ""):
                where.append("files.size>=?")
                args.append(max(0, int(float(filters["min_mb"]) * 1_048_576)))
            if filters.get("max_mb") not in (None, ""):
                where.append("files.size<=?")
                args.append(max(0, int(float(filters["max_mb"]) * 1_048_576)))
        except (TypeError, ValueError, OverflowError):
            where.append("0")
        clause = " WHERE " + " AND ".join(where) if where else ""
        return join, clause, args

    def list_files(self, query="", category="Everything", sort="recent", collection_id=None, folder_path=None, filters=None, limit=200, offset=0):
        join, clause, args = self._file_where(query, category, collection_id, folder_path, filters)
        order = "files.name COLLATE NOCASE ASC, files.path COLLATE NOCASE ASC" if sort == "name" else "files.modified DESC, files.path COLLATE NOCASE ASC"
        limit = max(1, min(1000, int(limit)))
        offset = max(0, min(2_147_483_647, int(offset)))
        sql = "SELECT files.*, EXISTS(SELECT 1 FROM favorites WHERE favorites.path=files.path) AS is_favorite FROM files" + join + clause + f" ORDER BY {order} LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        with self.lock:
            rows = self.db.execute(sql, args).fetchall()
        return self._attach_tags([self.serialize_file(r) for r in rows])

    def count_matching_files(self, query="", category="Everything", collection_id=None, folder_path=None, filters=None):
        join, clause, args = self._file_where(query, category, collection_id, folder_path, filters)
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM files" + join + clause, args).fetchone()[0]

    def _attach_tags(self, files):
        if not files:
            return files
        paths = [item["path"] for item in files]
        by_path = {}
        with self.lock:
            for offset in range(0, len(paths), 400):
                batch = paths[offset:offset + 400]
                placeholders = ",".join("?" for _ in batch)
                rows = self.db.execute(f"SELECT ft.path,t.name,t.color FROM file_tags ft JOIN tags t ON t.id=ft.tag_id WHERE ft.path IN ({placeholders}) ORDER BY t.name COLLATE NOCASE", batch).fetchall()
                for row in rows:
                    by_path.setdefault(row["path"], []).append({"name": row["name"], "color": row["color"]})
        for item in files:
            item["tags"] = by_path.get(item["path"], [])
        return files

    @staticmethod
    def serialize_file(row):
        p = Path(row["path"])
        return {"path": row["path"], "name": row["name"], "ext": row["ext"], "size": row["size"],
                "modified": row["modified"], "folder": str(p.parent), "root": row["root"],
                "is_favorite": bool(row["is_favorite"]) if "is_favorite" in row.keys() else False}

    def preview(self, path):
        with self.lock:
            row = self.db.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone()
            favorite = self.db.execute("SELECT 1 FROM favorites WHERE path=?", (path,)).fetchone()
            note_row = self.db.execute("SELECT note FROM file_notes WHERE path=?", (path,)).fetchone()
        if not row or not os.path.exists(path):
            return {"ok": False, "error": "This file is no longer available."}
        ext = row["ext"]
        preview = {"ok": True, **self.serialize_file(row), "kind": "other", "content": "", "data": "",
                   "note": note_row["note"] if note_row else ""}
        preview["is_favorite"] = bool(favorite)
        preview["tags"] = self.tags_for_file(path)
        if ext in TEXT_EXTS:
            try:
                preview.update(kind="text", content=Path(path).read_text(encoding="utf-8", errors="replace")[:30000])
            except OSError:
                pass
        elif ext in OFFICE_EXTS:
            preview.update(kind="text", content=(row["content"] or "")[:30000])
        elif ext in IMAGE_EXTS and row["size"] < 12_000_000:
            try:
                mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp"}.get(ext, "application/octet-stream")
                preview.update(kind="image", data=f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii"))
            except OSError:
                pass
        elif ext == ".pdf":
            preview.update(kind="pdf", content=row["content"][:30_000])
            if pdfium:
                page_data = self.pdf_page(path, 0)
                if page_data.get("ok"):
                    preview.update(data=page_data["data"], pages=page_data["pages"], page=0)
        elif ext in AUDIO_MIME and row["size"] <= 20_000_000:
            try:
                preview.update(kind="audio", data=f"data:{AUDIO_MIME[ext]};base64," +
                               base64.b64encode(Path(path).read_bytes()).decode("ascii"))
            except OSError:
                pass
        elif ext in VIDEO_MIME and row["size"] <= 20_000_000:
            try:
                preview.update(kind="video", data=f"data:{VIDEO_MIME[ext]};base64," +
                               base64.b64encode(Path(path).read_bytes()).decode("ascii"))
            except OSError:
                pass
        return preview

    def pdf_page(self, path, page_number=0, zoom=1.2):
        if not pdfium:
            return {"ok": False, "error": "Install the project requirements to preview PDFs inside Hearth."}
        try:
            with pdfium.PdfDocument(path) as document:
                if page_number < 0 or page_number >= len(document):
                    return {"ok": False, "error": "Page is out of range."}
                page = document[page_number]
                bitmap = page.render(scale=zoom)
                image = bitmap.to_pil().convert("RGB")
                output = BytesIO()
                image.save(output, format="PNG", optimize=True)
                data = base64.b64encode(output.getvalue()).decode("ascii")
                page.close()
                return {"ok": True, "data": "data:image/png;base64," + data, "page": page_number, "pages": len(document)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def collections(self):
        with self.lock:
            manual = [dict(r) | {"key": str(r["id"]), "kind": "manual"} for r in self.db.execute("""SELECT c.id,c.name,
                (SELECT COUNT(*) FROM collection_items i WHERE i.collection_id=c.id) AS count
                FROM collections c ORDER BY c.created""")]
            smart_rows = [dict(r) for r in self.db.execute(
                "SELECT id,name,query,filters,category,created FROM smart_collections ORDER BY name COLLATE NOCASE")]
        for row in smart_rows:
            row["key"] = f"smart:{row['id']}"
            row["kind"] = "smart"
            try:
                filters = json.loads(row["filters"] or "{}")
            except (TypeError, json.JSONDecodeError):
                filters = {}
            row["count"] = self.count_matching_files(row["query"], row["category"], row["key"], filters=filters)
        return manual + smart_rows

    def saved_searches(self):
        with self.lock:
            rows = [dict(r) for r in self.db.execute(
                "SELECT id,name,query,category,filters,created FROM saved_searches ORDER BY name COLLATE NOCASE")]
        for row in rows:
            try:
                row["filters"] = json.loads(row["filters"] or "{}")
            except (TypeError, json.JSONDecodeError):
                row["filters"] = {}
        return rows

    def tags_for_file(self, path):
        with self.lock:
            return [dict(r) for r in self.db.execute(
                "SELECT t.id,t.name,t.color FROM file_tags ft JOIN tags t ON t.id=ft.tag_id WHERE ft.path=? ORDER BY t.name COLLATE NOCASE", (path,))]

    def find_duplicates(self):
        with self.lock:
            candidates = self.db.execute("SELECT path,size,modified FROM files WHERE size IN (SELECT size FROM files GROUP BY size HAVING COUNT(*)>1) ORDER BY size").fetchall()
        if not candidates:
            return {"groups": [], "files": 0, "group_count": 0}
        hashes = {}
        for row in candidates:
            path = row["path"]
            with self.lock:
                cached = self.db.execute("SELECT sha256 FROM file_hashes WHERE path=? AND size=? AND modified=?", (path, row["size"], row["modified"])).fetchone()
            digest = cached["sha256"] if cached else ""
            if not digest:
                try:
                    hasher = hashlib.sha256()
                    with open(path, "rb") as file:
                        for chunk in iter(lambda: file.read(1024 * 1024), b""):
                            hasher.update(chunk)
                    digest = hasher.hexdigest()
                    with self.lock:
                        self.db.execute("INSERT OR REPLACE INTO file_hashes VALUES(?,?,?,?)",
                                        (path, row["size"], row["modified"], digest))
                        self.db.commit()
                except OSError:
                    continue
            hashes.setdefault(digest, []).append(path)
        groups = [paths for paths in hashes.values() if len(paths) > 1]
        return {"groups": groups, "files": sum(map(len, groups)), "group_count": len(groups)}

    def find_duplicates_async(self, progress_callback=None, cancel_callback=None):
        """Background duplicate finding with progress callback.
        Returns job-like dict with groups when complete."""
        with self.lock:
            candidates = self.db.execute("SELECT path,size,modified FROM files WHERE size IN (SELECT size FROM files GROUP BY size HAVING COUNT(*)>1) ORDER BY size").fetchall()
        total = len(candidates)
        if total == 0:
            return {"groups": [], "files": 0, "group_count": 0, "completed": True}
        hashes = {}
        for idx, row in enumerate(candidates):
            if cancel_callback and cancel_callback():
                return {"groups": [], "files": 0, "group_count": 0, "completed": False, "cancelled": True}
            path = row["path"]
            with self.lock:
                cached = self.db.execute("SELECT sha256 FROM file_hashes WHERE path=? AND size=? AND modified=?", (path, row["size"], row["modified"])).fetchone()
            digest = cached["sha256"] if cached else ""
            if not digest:
                try:
                    hasher = hashlib.sha256()
                    with open(path, "rb") as file:
                        for chunk in iter(lambda: file.read(1024 * 1024), b""):
                            if cancel_callback and cancel_callback():
                                return {"groups": [], "files": 0, "group_count": 0, "completed": False, "cancelled": True}
                            hasher.update(chunk)
                    digest = hasher.hexdigest()
                    with self.lock:
                        self.db.execute("INSERT OR REPLACE INTO file_hashes VALUES(?,?,?,?)",
                                        (path, row["size"], row["modified"], digest))
                        self.db.commit()
                except OSError:
                    if progress_callback:
                        progress_callback(idx + 1, total, "skipped")
                    continue
            hashes.setdefault(digest, []).append(path)
            if progress_callback:
                progress_callback(idx + 1, total, "hashed")
        groups = [paths for paths in hashes.values() if len(paths) > 1]
        return {"groups": groups, "files": sum(map(len, groups)), "group_count": len(groups), "completed": True}


class HearthAPI:
    def __init__(self):
        # PyWebView walks public API attributes while exposing methods to JS.
        # Keep window, database, and other state private to avoid recursive scans.
        self._window = None
        self._library = Library()
        self._clipboard = []
        self._maximized = True
        self._drop_sequence = 0
        self._drop_event = None
        self._watch_lock = threading.RLock()
        self._observers = {}
        self._watch_timers = {}
        self._job_lock = threading.RLock()
        self._jobs = {}
        self._job_controls = {}
        self._job_specs = {}
        self._backup_timer = None
        self._backup_lock = threading.Lock()
        self._closing = False
        self._center_on_start = False
        self._force_quit = False
        self._start_minimized = False
        self._tray_manager = None
        self._ipc_server = None

    def bind(self, window):
        self._window = window
        # Register a weak reference so module-level helpers can find the native window
        global _api_weakref
        _api_weakref = _weakref.ref(self)

    def get_current_language(self):
        saved = self.get_preference("language", "")
        if saved in ("en", "tr"):
            return saved
        if os.name == "nt":
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Hearth") as key:
                    val, _ = winreg.QueryValueEx(key, "Language")
                    v = str(val).lower()
                    if "turk" in v or v == "tr":
                        self.set_preference("language", "tr")
                        return "tr"
                    elif "eng" in v or v == "en":
                        self.set_preference("language", "en")
                        return "en"
            except Exception:
                pass
            try:
                lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
                if (lang_id & 0xFF) == 0x1F:
                    self.set_preference("language", "tr")
                    return "tr"
            except Exception:
                pass
        self.set_preference("language", "en")
        return "en"

    def is_context_menu_enabled(self):
        if os.name != "nt":
            return False
        return self.get_preference("context_menu_enabled", "1") == "1"

    def is_startup_enabled(self):
        if os.name != "nt":
            return False
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                val, _ = winreg.QueryValueEx(key, "Hearth")
                return bool(val)
        except OSError:
            return False

    def get_system_options(self):
        return {
            "minimize_to_tray": self.get_preference("minimize_to_tray", "1") == "1",
            "startup_enabled": self.is_startup_enabled(),
            "context_menu_enabled": self.is_context_menu_enabled()
        }

    def set_system_option(self, option, enabled):
        enabled_bool = bool(enabled)
        val_str = "1" if enabled_bool else "0"
        if option == "minimize_to_tray":
            self.set_preference("minimize_to_tray", val_str)
            return {"ok": True, "options": self.get_system_options()}
        elif option == "startup_enabled":
            if os.name != "nt":
                return {"ok": False, "error": "Startup is only supported on Windows"}
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as key:
                    if enabled_bool:
                        cmd = get_app_executable_command("--minimized")
                        winreg.SetValueEx(key, "Hearth", 0, winreg.REG_SZ, cmd)
                    else:
                        try:
                            winreg.DeleteValue(key, "Hearth")
                        except OSError:
                            pass
                return {"ok": True, "options": self.get_system_options()}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        elif option == "context_menu_enabled":
            self.set_preference("context_menu_enabled", val_str)
            sync_context_menu_registry(enabled_bool, self.get_current_language())
            return {"ok": True, "options": self.get_system_options()}
        return {"ok": False, "error": f"Unknown option: {option}"}

    def show_window(self):
        if not self._window:
            return
        if os.name == "nt":
            try:
                hwnd = self._native_handle()
                if hwnd:
                    ctypes.windll.user32.ShowWindow(ctypes.c_void_p(hwnd), 9)
                    ctypes.windll.user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
            except Exception:
                pass
        try:
            self._window.show()
        except Exception:
            pass

    def hide_window(self):
        if not self._window:
            return
        if os.name == "nt":
            try:
                hwnd = self._native_handle()
                if hwnd:
                    ctypes.windll.user32.ShowWindow(ctypes.c_void_p(hwnd), 0)
            except Exception:
                pass
        try:
            self._window.hide()
        except Exception:
            pass

    def exit_app(self):
        self._force_quit = True
        if hasattr(self, "_tray_manager") and self._tray_manager:
            self._tray_manager.cleanup()
        self.stop_background()
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass

    def on_closing(self):
        if not getattr(self, "_force_quit", False) and self.get_preference("minimize_to_tray", "1") == "1":
            self.hide_window()
            return False
        self.stop_background()
        if hasattr(self, "_tray_manager") and self._tray_manager:
            self._tray_manager.cleanup()
        return True

    def get_state(self):
        curr_lang = self.get_current_language()
        is_port = (
            (EXE_DIR / "portable.dat").exists()
            or (EXE_DIR / "data").exists()
            or os.environ.get("HEARTH_PORTABLE") == "1"
        )
        return {"roots": self._library.roots(), "collections": self._library.collections(),
                "saved_searches": self._library.saved_searches(),
                "count": self.count_files(), "scan": self._library.scan_status,
                "files": self._library.list_files(), "theme": self.get_preference("theme", "dark"),
                "language": curr_lang,
                "has_seen_intro": (
                    self.get_preference("has_seen_intro", "0") == "1" and
                    self.get_preference("has_seen_intro_version", "") == APP_VERSION
                ),
                "system_options": self.get_system_options(),
                "density": self.get_preference("density", "comfortable"), "data_path": str(APP_DATA),
                "is_portable": is_port,
                "on_this_day_count": self._library.count_matching_files(category="On This Day"),
                "font_scale": self.get_preference("font_scale", "1"),
                "motion": self.get_preference("motion", "system"),
                "runtime": self.get_runtime_info(),
                "undo_options": self.get_undo_options(),
                "backup_options": self.get_backup_options(),
                "indexing_options": self.get_indexing_options()}

    @staticmethod
    def get_runtime_info():
        global _CACHED_RUNTIME_INFO
        if _CACHED_RUNTIME_INFO is not None:
            return _CACHED_RUNTIME_INFO
        versions = {}
        for package in ("pywebview", "pypdfium2", "Pillow", "watchdog", "pypdf"):
            try:
                versions[package] = metadata.version(package)
            except metadata.PackageNotFoundError:
                versions[package] = "not installed"
        _CACHED_RUNTIME_INFO = {"python": sys.version.split()[0], "dependencies": versions}
        return _CACHED_RUNTIME_INFO

    def get_backup_options(self):
        schedule = self.get_preference("backup_schedule", "off")
        if schedule not in {"off", "daily", "weekly"}:
            schedule = "off"
        return {"schedule": schedule, "directory": self.get_preference("backup_directory", "")}

    def save_backup_options(self, options):
        if not isinstance(options, dict):
            return {"ok": False, "error": "Backup settings must be an object."}
        schedule = options.get("schedule", "off")
        directory = os.path.abspath(str(options.get("directory", "")).strip()) if options.get("directory") else ""
        if schedule not in {"off", "daily", "weekly"}:
            return {"ok": False, "error": "Choose daily, weekly, or off for scheduled backups."}
        if schedule != "off" and (not directory or not os.path.isdir(directory)):
            return {"ok": False, "error": "Choose an existing backup folder before enabling scheduled backups."}
        with self._library.lock:
            self._library.db.executemany("INSERT OR REPLACE INTO prefs(key,value) VALUES(?,?)", [
                ("backup_schedule", schedule), ("backup_directory", directory),
                ("backup_schedule_started", str(time.time()))])
            self._library.db.commit()
        self._record_activity("backup-settings", 1)
        return {"ok": True, "options": self.get_backup_options()}

    def start_backup_scheduler(self):
        self._schedule_backup_check(3600)

    def _schedule_backup_check(self, delay):
        if self._closing:
            return
        timer = threading.Timer(delay, self._run_scheduled_backup)
        timer.daemon = True
        self._backup_timer = timer
        timer.start()

    def _run_scheduled_backup(self):
        try:
            options = self.get_backup_options()
            interval = {"daily": 86400, "weekly": 7 * 86400}.get(options["schedule"])
            if interval and options["directory"] and os.path.isdir(options["directory"]):
                try:
                    last = float(self.get_preference("last_backup_time", "0") or 0)
                    started = float(self.get_preference("backup_schedule_started", "0") or 0)
                except (TypeError, ValueError, OverflowError):
                    last, started = 0, time.time()
                if time.time() - max(last, started) >= interval and self._backup_lock.acquire(blocking=False):
                    try:
                        target = Path(options["directory"]) / f"Hearth-auto-{datetime.now():%Y-%m-%d-%H%M%S}.zip"
                        result = self._write_backup(target)
                        if result.get("ok"):
                            self._record_activity("scheduled-backup", 1)
                        else:
                            self._record_activity("scheduled-backup", 1, "failed")
                    finally:
                        self._backup_lock.release()
        finally:
            self._schedule_backup_check(3600)

    def get_undo_options(self):
        try:
            limit = max(1, min(5000, int(self.get_preference("undo_limit", "50"))))
            days = max(1, min(3650, int(self.get_preference("undo_days", "30"))))
        except (TypeError, ValueError):
            limit, days = 50, 30
        return {"limit": limit, "days": days}

    def save_undo_options(self, options):
        try:
            limit = max(1, min(5000, int(options.get("limit", 50))))
            days = max(1, min(3650, int(options.get("days", 30))))
        except (AttributeError, TypeError, ValueError, OverflowError) as exc:
            return {"ok": False, "error": f"Invalid undo retention settings: {exc}"}
        with self._library.lock:
            for key, value in (("undo_limit", limit), ("undo_days", days)):
                self._library.db.execute("INSERT OR REPLACE INTO prefs(key,value) VALUES(?,?)", (key, str(value)))
            cutoff = time.time() - days * 86400
            obsolete = self._library.db.execute(
                "SELECT id,action,payload FROM undo_ops WHERE created<? OR id NOT IN (SELECT id FROM undo_ops ORDER BY id DESC LIMIT ?)",
                (cutoff, limit)).fetchall()
            for row in obsolete:
                if row["action"] == "delete":
                    for item in json.loads(row["payload"]):
                        trash_path = Path(item.get("trash", ""))
                        if trash_path.parent == APP_DATA / "UndoTrash":
                            self._send_to_system_trash(trash_path)
                self._library.db.execute("DELETE FROM undo_ops WHERE id=?", (row["id"],))
            self._library.db.commit()
        return {"ok": True, "options": self.get_undo_options()}

    def get_indexing_options(self):
        defaults = {"excluded_paths": [], "excluded_extensions": [], "max_content_mb": 60}
        with self._library.lock:
            rows = dict(self._library.db.execute("SELECT key,value FROM prefs WHERE key IN ('excluded_paths','excluded_extensions','max_content_mb')").fetchall())
        for key in ("excluded_paths", "excluded_extensions"):
            try:
                value = json.loads(rows.get(key, "[]"))
                defaults[key] = value if isinstance(value, list) else []
            except (TypeError, json.JSONDecodeError):
                pass
        try:
            defaults["max_content_mb"] = max(1, min(512, int(rows.get("max_content_mb", "60"))))
        except (TypeError, ValueError):
            pass
        return defaults

    def save_indexing_options(self, options):
        if not isinstance(options, dict):
            return {"ok": False, "error": "Indexing options must be an object."}
        try:
            paths = list(dict.fromkeys(os.path.abspath(p) for p in options.get("excluded_paths", [])
                                       if isinstance(p, str) and p.strip()))[:200]
            extensions = list(dict.fromkeys((x.strip().lower() if x.strip().startswith(".") else "." + x.strip().lower())
                                            for x in options.get("excluded_extensions", [])
                                            if isinstance(x, str) and x.strip()))[:200]
            if any(not re.fullmatch(r"\.[a-z0-9]{1,12}", ext) for ext in extensions):
                return {"ok": False, "error": "One of the excluded file extensions is invalid."}
            max_mb = int(options.get("max_content_mb", 60))
            if not 1 <= max_mb <= 512:
                return {"ok": False, "error": "Content indexing size must be between 1 and 512 MB."}
        except (TypeError, ValueError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        with self._library.lock:
            for key, value in (("excluded_paths", paths), ("excluded_extensions", extensions), ("max_content_mb", max_mb)):
                self._library.db.execute("INSERT OR REPLACE INTO prefs(key,value) VALUES(?,?)",
                                         (key, json.dumps(value, ensure_ascii=False) if isinstance(value, list) else str(value)))
            self._library.db.execute("DELETE FROM file_index_versions")
            self._library.db.commit()
        self._record_activity("indexing-settings", 1)
        result = self.refresh_folders()
        return {"ok": True, "options": self.get_indexing_options(), "folders": result["folders"]}

    def count_files(self):
        with self._library.lock:
            return self._library.db.execute("SELECT COUNT(*) FROM files").fetchone()[0]

    def list_files(self, query="", category="Everything", sort="recent", collection_id=None, folder_path=None, filters=None, limit=200, offset=0):
        return self._library.list_files(query, category, sort, collection_id, folder_path, filters, limit, offset)

    def count_matching_files(self, query="", category="Everything", collection_id=None, folder_path=None, filters=None):
        return self._library.count_matching_files(query, category, collection_id, folder_path, filters)

    def preview(self, path):
        return self._library.preview(path)

    def get_on_this_day_files(self):
        """Return files modified on this calendar month and day in previous years."""
        today = datetime.now()
        files = self._library.list_files(category="On This Day", sort="recent", limit=500)
        enriched = []
        for f in files:
            file_dt = datetime.fromtimestamp(f.get("modified", 0))
            years_diff = today.year - file_dt.year
            item = dict(f)
            item["years_ago"] = max(0, years_diff)
            enriched.append(item)
        return enriched

    def compare_files(self, path1, path2):
        """Compare two files side-by-side: metadata, hashes, notes, and text preview."""
        p1 = os.path.normpath(str(path1 or ""))
        p2 = os.path.normpath(str(path2 or ""))
        if not os.path.isfile(p1) or not os.path.isfile(p2):
            return {"ok": False, "error": "One or both files do not exist."}

        try:
            stat1 = os.stat(p1)
            stat2 = os.stat(p2)
        except OSError as e:
            return {"ok": False, "error": f"Could not inspect file: {e}"}

        def calc_hash(p):
            h = hashlib.sha256()
            try:
                with open(p, "rb") as f:
                    while chunk := f.read(65536):
                        h.update(chunk)
                return h.hexdigest()
            except OSError:
                return ""

        hash1 = calc_hash(p1)
        hash2 = calc_hash(p2)
        is_identical = bool(hash1 and hash2 and hash1 == hash2)

        is_text1 = Path(p1).suffix.lower() in TEXT_EXTS
        is_text2 = Path(p2).suffix.lower() in TEXT_EXTS
        snippet1 = ""
        snippet2 = ""
        if is_text1 and is_text2 and stat1.st_size < 500_000 and stat2.st_size < 500_000:
            try:
                with open(p1, "r", encoding="utf-8", errors="replace") as f:
                    snippet1 = f.read(8000)
                with open(p2, "r", encoding="utf-8", errors="replace") as f:
                    snippet2 = f.read(8000)
            except Exception:
                pass

        note1 = self._library.preview(p1).get("note", "")
        note2 = self._library.preview(p2).get("note", "")

        return {
            "ok": True,
            "is_identical": is_identical,
            "file1": {
                "path": p1,
                "name": os.path.basename(p1),
                "size": stat1.st_size,
                "modified": stat1.st_mtime,
                "sha256": hash1,
                "is_text": is_text1,
                "snippet": snippet1,
                "note": note1
            },
            "file2": {
                "path": p2,
                "name": os.path.basename(p2),
                "size": stat2.st_size,
                "modified": stat2.st_mtime,
                "sha256": hash2,
                "is_text": is_text2,
                "snippet": snippet2,
                "note": note2
            }
        }

    def save_file_note(self, path, note):
        path = os.path.normpath(str(path or ""))
        note = str(note or "").replace("\x00", "").strip()
        if len(note) > 5000:
            return {"ok": False, "error": "Notes are limited to 5,000 characters."}
        with self._library.lock:
            indexed = self._library.db.execute("SELECT 1 FROM files WHERE path=?", (path,)).fetchone()
            if not indexed or not os.path.isfile(path):
                return {"ok": False, "error": "This file is no longer available in the library."}
            if note:
                self._library.db.execute(
                    "INSERT INTO file_notes(path,note,updated) VALUES(?,?,?) "
                    "ON CONFLICT(path) DO UPDATE SET note=excluded.note,updated=excluded.updated",
                    (path, note, time.time()))
            else:
                self._library.db.execute("DELETE FROM file_notes WHERE path=?", (path,))
            self._library.db.commit()
        return {"ok": True, "note": note}

    def find_duplicates(self):
        return self._library.find_duplicates()

    def start_duplicate_scan(self):
        with self._library.lock:
            total = self._library.db.execute(
                "SELECT COUNT(*) FROM files WHERE size IN (SELECT size FROM files GROUP BY size HAVING COUNT(*)>1)").fetchone()[0]
        def worker(job_id):
            try:
                result = self._library.find_duplicates_async(
                    lambda done, count, state: self._job_checkpoint(job_id) or self._update_job(job_id, completed=done),
                    cancel_callback=lambda: self._job_cancelled(job_id))
                if result.get("cancelled"):
                    self._update_job(job_id, status="cancelled", summary=None, finished=time.time())
                    return
                self._update_job(job_id, status="completed", summary=result, completed=total, finished=time.time())
                self._record_activity("duplicate-scan", result.get("files", 0))
            except InterruptedError:
                self._update_job(job_id, status="cancelled", finished=time.time())
            except Exception as exc:
                self._update_job(job_id, status="failed", errors=[str(exc)], finished=time.time())
        return self._start_job("duplicate-scan", total, worker, ("duplicates",))

    def delete_duplicate_copies(self, paths, keep_path):
        paths = list(dict.fromkeys(path for path in (paths or []) if isinstance(path, str)))[:500]
        if len(paths) < 2 or keep_path not in paths:
            return {"ok": False, "error": "Choose a duplicate group and one copy to keep."}
        with self._library.lock:
            indexed = {row[0] for row in self._library.db.execute(
                "SELECT path FROM files WHERE path IN (" + ",".join("?" for _ in paths) + ")", paths)}
        if indexed != set(paths):
            return {"ok": False, "error": "The selected duplicate group has changed. Refresh it and try again."}
        hashes = set()
        try:
            for path in paths:
                digest = hashlib.sha256()
                with open(path, "rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                hashes.add(digest.hexdigest())
        except OSError as exc:
            return {"ok": False, "error": f"Could not verify the duplicate group: {exc}"}
        if len(hashes) != 1:
            return {"ok": False, "error": "These files no longer have identical contents; nothing was deleted."}
        return self.bulk_action([path for path in paths if path != keep_path], "delete")

    def choose_images(self):
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
            file_types=("Images (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp;*.tif;*.tiff)",))
        return list(result or [])

    def choose_output_folder(self):
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER, allow_multiple=False)
        return result[0] if result else ""

    def choose_pdfs(self, allow_multiple=True):
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=allow_multiple,
            file_types=("PDF files (*.pdf)",))
        return list(result or [])

    def _start_job(self, kind, total, worker, spec=None):
        job_id = uuid.uuid4().hex
        with self._job_lock:
            self._jobs[job_id] = {"id": job_id, "kind": kind, "status": "running", "total": total,
                                  "completed": 0, "outputs": [], "errors": [], "started": time.time(), "paused": False}
            self._job_controls[job_id] = {"cancel": threading.Event(), "pause": threading.Event()}
            if spec:
                self._job_specs[job_id] = spec
        threading.Thread(target=worker, args=(job_id,), name=f"hearth-{kind}", daemon=True).start()
        return {"ok": True, "job_id": job_id}

    def _job_cancelled(self, job_id):
        with self._job_lock:
            control = self._job_controls.get(job_id)
            return not control or control["cancel"].is_set()

    def _job_checkpoint(self, job_id):
        with self._job_lock:
            control = self._job_controls.get(job_id)
        if not control or control["cancel"].is_set():
            raise InterruptedError("Job cancelled by user.")
        while control["pause"].is_set():
            if control["cancel"].wait(.2):
                raise InterruptedError("Job cancelled by user.")

    def pause_job(self, job_id):
        with self._job_lock:
            job = self._jobs.get(job_id)
            control = self._job_controls.get(job_id)
            if not job or job.get("status") != "running" or not control:
                return {"ok": False, "error": "This task cannot be paused."}
            control["pause"].set()
            job["paused"] = True
        return {"ok": True}

    def resume_job(self, job_id):
        with self._job_lock:
            job = self._jobs.get(job_id)
            control = self._job_controls.get(job_id)
            if not job or job.get("status") != "running" or not control:
                return {"ok": False, "error": "This task cannot be resumed."}
            control["pause"].clear()
            job["paused"] = False
        return {"ok": True}

    def cancel_job(self, job_id):
        with self._job_lock:
            job = self._jobs.get(job_id)
            control = self._job_controls.get(job_id)
            if not job or job.get("status") != "running" or not control:
                return {"ok": False, "error": "This task is no longer running."}
            control["cancel"].set()
            control["pause"].clear()
            job["status"] = "cancelling"
            job["paused"] = False
        return {"ok": True}

    def retry_job(self, job_id):
        with self._job_lock:
            job = self._jobs.get(job_id)
            spec = self._job_specs.get(job_id)
        if not job or job.get("status") == "running" or not spec:
            return {"ok": False, "error": "This task cannot be retried."}
        if spec[0] == "image":
            failed_paths = job.get("failed_paths") or spec[1]
            return self.start_image_conversion(failed_paths, *spec[2:])
        if spec[0] == "pdf":
            failed_paths = job.get("failed_paths") or spec[1]
            return self.start_pdf_tool(failed_paths, *spec[2:])
        if spec[0] == "duplicates":
            return self.start_duplicate_scan()
        return {"ok": False, "error": "This task cannot be retried."}

    def _update_job(self, job_id, **values):
        with self._job_lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(values)

    def get_job_status(self, job_id):
        with self._job_lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else {"ok": False, "error": "This task is no longer available."}

    def _record_activity(self, action, item_count=0, status="completed"):
        """Keep a local, path-free audit trail of user operations."""
        with self._library.lock:
            self._library.db.execute("INSERT INTO activity_log(action,item_count,status,created) VALUES(?,?,?,?)",
                                     (str(action)[:48], max(0, int(item_count)), str(status)[:24], time.time()))
            self._library.db.execute("DELETE FROM activity_log WHERE id NOT IN (SELECT id FROM activity_log ORDER BY id DESC LIMIT 1000)")
            self._library.db.commit()

    def get_activity_log(self, limit=100):
        limit = max(1, min(500, int(limit)))
        with self._library.lock:
            return [dict(row) for row in self._library.db.execute(
                "SELECT action,item_count,status,created FROM activity_log ORDER BY id DESC LIMIT ?", (limit,))]

    def _record_undo(self, action, payload):
        with self._library.lock:
            cursor = self._library.db.execute("INSERT INTO undo_ops(action,payload,created) VALUES(?,?,?)",
                                              (action, json.dumps(payload, ensure_ascii=False), time.time()))
            undo_id = cursor.lastrowid
            options = self.get_undo_options()
            obsolete = self._library.db.execute(
                "SELECT id,action,payload FROM undo_ops WHERE created<? OR id NOT IN (SELECT id FROM undo_ops ORDER BY id DESC LIMIT ?)",
                (time.time() - options["days"] * 86400, options["limit"])).fetchall()
            for old in obsolete:
                if old["action"] == "delete":
                    for item in json.loads(old["payload"]):
                        trash_path = Path(item.get("trash", ""))
                        if trash_path.parent == APP_DATA / "UndoTrash":
                            # If Windows refuses the recycle operation, leave the file
                            # untouched in Hearth's private undo directory.
                            self._send_to_system_trash(trash_path)
                self._library.db.execute("DELETE FROM undo_ops WHERE id=?", (old["id"],))
            item_count = len(payload) if isinstance(payload, list) else 1
            self._library.db.execute("INSERT INTO activity_log(action,item_count,status,created) VALUES(?,?,?,?)",
                                     (str(action)[:48], item_count, "completed", time.time()))
            self._library.db.execute("DELETE FROM activity_log WHERE id NOT IN (SELECT id FROM activity_log ORDER BY id DESC LIMIT 1000)")
            self._library.db.commit()
            return undo_id

    @staticmethod
    def _send_to_system_trash(path):
        path = Path(path)
        if not path.exists():
            return True
        try:
            if os.name == "nt":
                from ctypes import wintypes
                class SHFILEOPSTRUCTW(ctypes.Structure):
                    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR), ("fFlags", wintypes.WORD), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
                operation = SHFILEOPSTRUCTW(None, 3, str(path) + "\0\0", None, 0x0040 | 0x0010, False, None, None)
                code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
                return not code and not operation.fAnyOperationsAborted
            trash = Path.home() / ".local/share/Trash/files"
            trash.mkdir(parents=True, exist_ok=True)
            target = trash / f"{uuid.uuid4().hex}_{path.name}"
            shutil.move(str(path), str(target))
            return True
        except (OSError, AttributeError, TypeError):
            return False

    def _file_metadata(self, path):
        with self._library.lock:
            db = self._library.db
            return {"collections": [r[0] for r in db.execute("SELECT collection_id FROM collection_items WHERE path=?", (path,))],
                    "favorite": bool(db.execute("SELECT 1 FROM favorites WHERE path=?", (path,)).fetchone()),
                    "tags": [r[0] for r in db.execute("SELECT tag_id FROM file_tags WHERE path=?", (path,))]}

    def undo_last(self):
        with self._library.lock:
            row = self._library.db.execute("SELECT * FROM undo_ops ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return {"ok": False, "error": "There is nothing to undo."}
        payload = json.loads(row["payload"])
        try:
            if row["action"] == "rename":
                items = payload if isinstance(payload, list) else [payload]
                if any(os.path.exists(item["old"]) or not os.path.exists(item["new"]) for item in items):
                    raise FileExistsError("One or more files have changed since this action.")
                restored = []
                try:
                    for item in reversed(items):
                        shutil.move(item["new"], item["old"])
                        restored.append(item)
                        self._update_path(item["new"], item["old"])
                except Exception as undo_exc:
                    rollback_errors = []
                    for item in reversed(restored):
                        if os.path.exists(item["old"]) and not os.path.exists(item["new"]):
                            try:
                                shutil.move(item["old"], item["new"])
                                self._update_path(item["old"], item["new"])
                            except Exception as rollback_exc:
                                rollback_errors.append(f"{Path(item['old']).name}: {rollback_exc}")
                    pending = [item for item in items if os.path.exists(item["new"]) and not os.path.exists(item["old"])]
                    with self._library.lock:
                        if pending:
                            self._library.db.execute("UPDATE undo_ops SET payload=? WHERE id=?",
                                                     (json.dumps(pending if isinstance(payload, list) else pending[0], ensure_ascii=False), row["id"]))
                        else:
                            self._library.db.execute("DELETE FROM undo_ops WHERE id=?", (row["id"],))
                        self._library.db.commit()
                    detail = f"Undo stopped: {undo_exc}"
                    if rollback_errors:
                        detail += " | Files restored successfully: " + "; ".join(rollback_errors[:3])
                    raise RuntimeError(detail)
            elif row["action"] == "move":
                if any(os.path.exists(item["old"]) or not os.path.exists(item["new"]) for item in payload):
                    raise FileExistsError("One or more files have changed since this action.")
                restored = []
                try:
                    for item in reversed(payload):
                        shutil.move(item["new"], item["old"])
                        restored.append(item)
                        self._update_path(item["new"], item["old"])
                except Exception as undo_exc:
                    rollback_errors = []
                    for item in reversed(restored):
                        if os.path.exists(item["old"]) and not os.path.exists(item["new"]):
                            try:
                                shutil.move(item["old"], item["new"])
                                self._update_path(item["old"], item["new"])
                            except Exception as rollback_exc:
                                rollback_errors.append(f"{Path(item['old']).name}: {rollback_exc}")
                    pending = [item for item in payload if os.path.exists(item["new"]) and not os.path.exists(item["old"])]
                    with self._library.lock:
                        if pending:
                            self._library.db.execute("UPDATE undo_ops SET payload=? WHERE id=?",
                                                     (json.dumps(pending, ensure_ascii=False), row["id"]))
                        else:
                            self._library.db.execute("DELETE FROM undo_ops WHERE id=?", (row["id"],))
                        self._library.db.commit()
                    detail = f"Undo stopped: {undo_exc}"
                    if rollback_errors:
                        detail += " | Files restored successfully: " + "; ".join(rollback_errors[:3])
                    raise RuntimeError(detail)
            elif row["action"] == "copy":
                for path in payload:
                    if os.path.isfile(path): os.remove(path)
                    with self._library.lock:
                        for table in ("files", "collection_items", "favorites", "file_tags", "file_index_versions", "file_hashes"):
                            col = "path"
                            self._library.db.execute(f"DELETE FROM {table} WHERE {col}=?", (path,))
                        self._library.db.commit()
            elif row["action"] == "delete":
                if any(os.path.exists(item["old"]) or not os.path.exists(item["trash"]) for item in payload):
                    raise FileExistsError("A restore location is occupied or an undo copy is missing.")
                restored = []
                try:
                    for item in payload:
                        Path(item["old"]).parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(item["trash"], item["old"])
                        restored.append(item)
                        self._index_destination(item["old"])
                        metadata = item.get("metadata", {})
                        with self._library.lock:
                            for cid in metadata.get("collections", []):
                                self._library.db.execute("INSERT OR IGNORE INTO collection_items VALUES(?,?)", (cid, item["old"]))
                            if metadata.get("favorite"):
                                self._library.db.execute("INSERT OR IGNORE INTO favorites VALUES(?,?)", (item["old"], time.time()))
                            for tag_id in metadata.get("tags", []):
                                self._library.db.execute("INSERT OR IGNORE INTO file_tags VALUES(?,?)", (item["old"], tag_id))
                            self._library.db.commit()
                except Exception as restore_exc:
                    rollback_errors = []
                    for item in reversed(restored):
                        try:
                            if os.path.exists(item["old"]) and not os.path.exists(item["trash"]):
                                shutil.move(item["old"], item["trash"])
                                with self._library.lock:
                                    for table in ("files", "collection_items", "favorites", "file_tags", "file_index_versions", "file_hashes"):
                                        self._library.db.execute(f"DELETE FROM {table} WHERE path=?", (item["old"],))
                                    self._library.db.commit()
                        except Exception as rollback_exc:
                            rollback_errors.append(f"{Path(item['old']).name}: {rollback_exc}")
                    # Keep only files still waiting in UndoTrash. Files whose
                    # rollback failed are already restored and must not block a retry.
                    pending = [item for item in payload if os.path.exists(item["trash"]) and not os.path.exists(item["old"])]
                    with self._library.lock:
                        if pending:
                            self._library.db.execute("UPDATE undo_ops SET payload=? WHERE id=?",
                                                     (json.dumps(pending, ensure_ascii=False), row["id"]))
                        else:
                            self._library.db.execute("DELETE FROM undo_ops WHERE id=?", (row["id"],))
                        self._library.db.commit()
                    detail = f"Restore stopped: {restore_exc}"
                    if rollback_errors:
                        detail += " | Some files were restored successfully: " + "; ".join(rollback_errors[:3])
                    raise RuntimeError(detail)
            elif row["action"] == "metadata":
                with self._library.lock:
                    if any(not self._library.db.execute("SELECT 1 FROM files WHERE path=?",(item["path"],)).fetchone() for item in payload):
                        raise FileNotFoundError("One or more files are no longer in the library.")
                    for item in payload:
                        path=item["path"]
                        self._library.db.execute("DELETE FROM favorites WHERE path=?",(path,))
                        if item.get("favorite"):
                            self._library.db.execute("INSERT INTO favorites(path,added_at) VALUES(?,?)",(path,time.time()))
                        self._library.db.execute("DELETE FROM file_tags WHERE path=?",(path,))
                        self._library.db.executemany("INSERT OR IGNORE INTO file_tags(path,tag_id) VALUES(?,?)",[(path,t) for t in item.get("tags",[])])
                        self._library.db.execute("DELETE FROM collection_items WHERE path=?",(path,))
                        self._library.db.executemany("INSERT OR IGNORE INTO collection_items(collection_id,path) VALUES(?,?)",[(c,path) for c in item.get("collections",[])])
                    self._library.db.commit()
            with self._library.lock:
                self._library.db.execute("DELETE FROM undo_ops WHERE id=?", (row["id"],)); self._library.db.commit()
            self._record_activity("undo-" + row["action"], len(payload) if isinstance(payload, list) else 1)
            return {"ok": True}
        except Exception as exc:
            with self._library.lock:
                self._library.db.rollback()
            return {"ok": False, "error": f"Undo could not be completed: {exc}"}

    @staticmethod
    def _unused_output(path):
        path = Path(path)
        if not path.exists():
            return path
        for n in range(2, 10000):
            candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
            if not candidate.exists():
                return candidate
        raise OSError("Could not find a free output file name.")

    def start_image_conversion(self, paths, output_format, quality=88, output_directory=None):
        formats = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "webp": ".webp", "bmp": ".bmp", "tiff": ".tiff"}
        output_ext = formats.get(str(output_format or "").lower())
        if not output_ext:
            return {"ok": False, "error": "Choose a supported image format."}
        paths = list(dict.fromkeys(path for path in (paths or []) if isinstance(path, str) and Path(path).suffix.lower() in IMAGE_EXTS))
        if not paths:
            return {"ok": False, "error": "Choose at least one supported image."}
        quality = max(1, min(100, int(quality)))
        output_directory = os.path.abspath(output_directory) if output_directory else None
        if output_directory and not os.path.isdir(output_directory):
            return {"ok": False, "error": "Choose an existing output folder."}

        def worker(job_id):
            try:
                from PIL import Image, ImageOps
            except ImportError:
                self._update_job(job_id, status="failed", errors=["Install the project requirements to convert images."])
                return
            outputs, errors, failed_paths = [], [], []
            for index, source in enumerate(paths, 1):
                try:
                    self._job_checkpoint(job_id)
                except InterruptedError:
                    failed_paths.extend(paths[index - 1:])
                    break
                try:
                    image_path = Path(source)
                    with Image.open(image_path) as opened:
                        if getattr(opened, "n_frames", 1) > 1:
                            raise ValueError("Animated images are skipped to preserve every frame.")
                        image = ImageOps.exif_transpose(opened)
                        if output_ext == ".jpg" and image.mode not in ("RGB", "L"):
                            rgba = image.convert("RGBA")
                            background = Image.new("RGB", rgba.size, (255, 255, 255))
                            background.paste(rgba, mask=rgba.getchannel("A"))
                            image = background
                        output_dir = Path(output_directory) if output_directory else image_path.parent
                        output_dir.mkdir(parents=True, exist_ok=True)
                        target = self._unused_output(output_dir / f"{image_path.stem}-converted{output_ext}")
                        temporary = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.tmp{target.suffix}")
                        options = {"quality": quality, "optimize": True} if output_ext in {".jpg", ".webp"} else {}
                        if output_ext == ".png":
                            options = {"optimize": True, "compress_level": 9}
                        fmt = {".jpg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".tiff": "TIFF", ".bmp": "BMP"}[output_ext]
                        try:
                            image.save(temporary, format=fmt, **options)
                            os.replace(temporary, target)
                        finally:
                            temporary.unlink(missing_ok=True)
                    self._index_destination(str(target))
                    outputs.append(str(target))
                except Exception as exc:
                    errors.append(f"{Path(source).name}: {exc}")
                    failed_paths.append(source)
                self._update_job(job_id, completed=index, outputs=list(outputs), errors=list(errors), failed_paths=list(dict.fromkeys(failed_paths)))
            cancelled = self._job_cancelled(job_id)
            status = "cancelled" if cancelled else "completed_with_errors" if outputs and errors else "completed" if outputs else "failed"
            self._update_job(job_id, status=status, failed_paths=list(dict.fromkeys(failed_paths)), finished=time.time())
            if outputs:
                self._record_activity("image-conversion", len(outputs), status)

        return self._start_job("image-convert", len(paths), worker, ("image", paths, output_format, quality, output_directory))

    def start_pdf_tool(self, paths, operation, page_ranges="", rotation=90, output_directory=None):
        if not PdfReader or not PdfWriter:
            return {"ok": False, "error": "Install the project requirements to use PDF tools."}
        valid = list(dict.fromkeys(path for path in (paths or []) if isinstance(path, str) and Path(path).suffix.lower() == ".pdf"))
        operations = {"merge", "split", "extract", "delete-pages", "reorder", "rotate", "optimize"}
        if not valid:
            return {"ok": False, "error": "Choose at least one PDF file."}
        if operation == "merge" and len(valid) < 2:
            return {"ok": False, "error": "Choose two or more PDFs to merge."}
        if operation in {"split", "extract", "delete-pages", "reorder"} and len(valid) != 1:
            return {"ok": False, "error": "Choose exactly one PDF for this page operation."}
        if operation not in operations:
            return {"ok": False, "error": "Choose a supported PDF operation."}
        output_directory = os.path.abspath(output_directory) if output_directory else None
        if output_directory and not os.path.isdir(output_directory):
            return {"ok": False, "error": "Choose an existing output folder."}
        try:
            rotation = int(rotation) % 360
            if operation == "rotate" and rotation not in {90, 180, 270}:
                raise ValueError
        except (TypeError, ValueError):
            return {"ok": False, "error": "Choose a rotation of 90, 180, or 270 degrees."}

        def ranges_for(value, page_count, default_all=True):
            ranges = []
            for part in (value or "").split(","):
                part = part.strip()
                if not part:
                    continue
                bounds = part.split("-", 1)
                first = int(bounds[0])
                last = int(bounds[1]) if len(bounds) == 2 else first
                if first < 1 or last < first or last > page_count:
                    raise ValueError(f"Page range {part} is outside the PDF (1–{page_count}).")
                ranges.extend(range(first - 1, last))
            if not ranges and default_all:
                ranges = list(range(page_count))
            if len(set(ranges)) != len(ranges):
                raise ValueError("Page ranges cannot contain duplicates.")
            return ranges

        def write_writer(writer, base):
            output_dir = Path(output_directory) if output_directory else Path(base).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            target = self._unused_output(output_dir / Path(base).name)
            temporary = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.tmp{target.suffix}")
            try:
                with temporary.open("wb") as output:
                    writer.write(output)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            self._index_destination(str(target))
            return str(target)

        def worker(job_id):
            outputs, errors, failed_paths = [], [], []
            sources = valid if operation != "merge" else [None]
            for index, source_group in enumerate(sources, 1):
                try:
                    self._job_checkpoint(job_id)
                except InterruptedError:
                    if operation != "merge":
                        failed_paths.extend(valid[index - 1:])
                    break
                try:
                    if operation == "merge":
                        writer = PdfWriter()
                        for source in valid:
                            self._job_checkpoint(job_id)
                            if Path(source).stat().st_size > 1_000_000_000:
                                raise ValueError(f"{Path(source).name} exceeds the 1 GB PDF processing limit.")
                            reader = PdfReader(source, strict=False)
                            if reader.is_encrypted:
                                raise ValueError(f"{Path(source).name} is password protected.")
                            writer.append(reader)
                        base = Path(valid[0]).with_name(f"{Path(valid[0]).stem}-merged.pdf")
                        outputs.append(write_writer(writer, base))
                    else:
                        if Path(source_group).stat().st_size > 1_000_000_000:
                            raise ValueError(f"{Path(source_group).name} exceeds the 1 GB PDF processing limit.")
                        reader = PdfReader(source_group, strict=False)
                        if reader.is_encrypted:
                            raise ValueError(f"{Path(source_group).name} is password protected.")
                        pages = reader.pages
                        if not pages:
                            raise ValueError(f"{Path(source_group).name} has no pages.")
                        writer = PdfWriter()
                        if operation == "split":
                            ordered = ranges_for(page_ranges, len(pages))
                            requested_parts = []
                            for part in (page_ranges or "").split(","):
                                part = part.strip()
                                if not part:
                                    continue
                                bounds = part.split("-", 1)
                                first = int(bounds[0]); last = int(bounds[1]) if len(bounds) == 2 else first
                                requested_parts.append(list(range(first - 1, last)))
                            if not requested_parts:
                                requested_parts = [ordered]
                            for part_index, page_indexes in enumerate(requested_parts, 1):
                                self._job_checkpoint(job_id)
                                part_writer = PdfWriter()
                                for page_index in page_indexes:
                                    self._job_checkpoint(job_id)
                                    part_writer.add_page(pages[page_index])
                                base = Path(source_group).with_name(f"{Path(source_group).stem}-part-{part_index}.pdf")
                                outputs.append(write_writer(part_writer, base))
                        elif operation in {"extract", "delete-pages", "reorder"}:
                            indexes = ranges_for(page_ranges, len(pages), default_all=False)
                            if not indexes:
                                raise ValueError("Enter page numbers or ranges, for example 1-3,5.")
                            if operation == "extract":
                                final_indexes = indexes; suffix = "extracted"
                            elif operation == "delete-pages":
                                removed = set(indexes)
                                final_indexes = [i for i in range(len(pages)) if i not in removed]
                                if not final_indexes:
                                    raise ValueError("At least one page must remain in the output.")
                                suffix = "pages-removed"
                            else:
                                if set(indexes) != set(range(len(pages))) or len(indexes) != len(pages):
                                    raise ValueError("Reorder must list every page exactly once.")
                                final_indexes = indexes; suffix = "reordered"
                            for page_index in final_indexes:
                                self._job_checkpoint(job_id)
                                writer.add_page(pages[page_index])
                            base = Path(source_group).with_name(f"{Path(source_group).stem}-{suffix}.pdf")
                            outputs.append(write_writer(writer, base))
                        else:
                            writer.append(reader)
                            if operation == "rotate":
                                for page in writer.pages:
                                    self._job_checkpoint(job_id); page.rotate(rotation)
                                suffix = "rotated"
                            else:
                                for page in writer.pages:
                                    self._job_checkpoint(job_id); page.compress_content_streams()
                                writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
                                suffix = "optimized"
                            base = Path(source_group).with_name(f"{Path(source_group).stem}-{suffix}.pdf")
                            outputs.append(write_writer(writer, base))
                except InterruptedError:
                    break
                except Exception as exc:
                    label = ", ".join(Path(x).name for x in valid) if operation == "merge" else Path(source_group).name
                    errors.append(f"{label}: {exc}")
                    failed_paths.extend(valid if operation == "merge" else [source_group])
                self._update_job(job_id, completed=index, outputs=list(outputs), errors=list(errors), failed_paths=list(dict.fromkeys(failed_paths)))
            cancelled = self._job_cancelled(job_id)
            status = "cancelled" if cancelled else "completed_with_errors" if outputs and errors else "completed" if outputs else "failed"
            self._update_job(job_id, status=status, outputs=outputs, errors=errors,
                             failed_paths=list(dict.fromkeys(failed_paths)), finished=time.time())
            if outputs:
                self._record_activity(f"pdf-{operation}", len(outputs), status)

        return self._start_job(f"pdf-{operation}", len(valid), worker,
                               ("pdf", valid, operation, page_ranges, rotation, output_directory))

    def toggle_favorite(self, path, record_undo=True):
        previous=self._file_metadata(path)
        with self._library.lock:
            exists = self._library.db.execute("SELECT 1 FROM files WHERE path=?", (path,)).fetchone()
            if not exists:
                return {"ok": False, "error": "This file is no longer in the library."}
            favorite = self._library.db.execute("SELECT 1 FROM favorites WHERE path=?", (path,)).fetchone()
            if favorite:
                self._library.db.execute("DELETE FROM favorites WHERE path=?", (path,))
                is_favorite = False
            else:
                self._library.db.execute("INSERT INTO favorites(path,added_at) VALUES(?,?)", (path, time.time()))
                is_favorite = True
            self._library.db.commit()
        if record_undo: self._record_undo("metadata",[{"path":path,**previous}])
        return {"ok": True, "is_favorite": is_favorite}

    def save_search(self, name, query, category="Everything", filters=None, search_id=None):
        name, query = (name or "").strip(), (query or "").strip()
        category = category or "Everything"
        filters = filters if isinstance(filters, dict) else {}
        if not name or (not query and category == "Everything" and not filters):
            return {"ok": False, "error": "Give the saved search a name and at least one query or filter."}
        try:
            with self._library.lock:
                duplicate = self._library.db.execute(
                    "SELECT id FROM saved_searches WHERE name=? COLLATE NOCASE AND (? IS NULL OR id<>?)",
                    (name, search_id, search_id)).fetchone()
                if duplicate:
                    return {"ok": False, "error": "A saved search already has that name."}
                if search_id:
                    cursor = self._library.db.execute(
                        "UPDATE saved_searches SET name=?,query=?,category=?,filters=? WHERE id=?",
                        (name, query, category, json.dumps(filters, ensure_ascii=False), int(search_id)))
                    if not cursor.rowcount:
                        return {"ok": False, "error": "This saved search is no longer available."}
                else:
                    self._library.db.execute("INSERT INTO saved_searches(name,query,category,filters,created) VALUES(?,?,?,?,?)",
                                             (name, query, category, json.dumps(filters, ensure_ascii=False), time.time()))
                self._library.db.commit()
            self._record_activity("saved-search", 1)
            return {"ok": True, "saved_searches": self._library.saved_searches()}
        except sqlite3.IntegrityError:
            return {"ok": False, "error": "A saved search already has that name."}

    def delete_saved_search(self, search_id):
        with self._library.lock:
            self._library.db.execute("DELETE FROM saved_searches WHERE id=?", (int(search_id),))
            self._library.db.commit()
        self._record_activity("saved-search-delete", 1)
        return self._library.saved_searches()

    def set_file_tags(self, path, names, record_undo=True):
        if not isinstance(names, list):
            return {"ok": False, "error": "Tags must be a list."}
        clean = list(dict.fromkeys(name.strip()[:32] for name in names if isinstance(name, str) and name.strip()))[:12]
        previous=self._file_metadata(path)
        with self._library.lock:
            if not self._library.db.execute("SELECT 1 FROM files WHERE path=?", (path,)).fetchone():
                return {"ok": False, "error": "This file is no longer in the library."}
            self._library.db.execute("DELETE FROM file_tags WHERE path=?", (path,))
            for name in clean:
                self._library.db.execute("INSERT OR IGNORE INTO tags(name) VALUES(?)", (name,))
                tag = self._library.db.execute("SELECT id FROM tags WHERE name=? COLLATE NOCASE", (name,)).fetchone()
                if tag:
                    self._library.db.execute("INSERT OR IGNORE INTO file_tags(path,tag_id) VALUES(?,?)", (path, tag["id"]))
            self._library.db.commit()
        if record_undo: self._record_undo("metadata",[{"path":path,**previous}])
        return {"ok": True, "tags": self._library.tags_for_file(path)}

    def list_tags(self):
        with self._library.lock:
            return [dict(row) for row in self._library.db.execute(
                "SELECT t.id,t.name,t.color,COUNT(ft.path) AS file_count FROM tags t LEFT JOIN file_tags ft ON ft.tag_id=t.id GROUP BY t.id ORDER BY t.name COLLATE NOCASE")]

    def rename_tag(self, tag_id, name):
        name = (name or "").strip()[:60]
        if not name:
            return {"ok": False, "error": "Give this tag a name."}
        try:
            with self._library.lock:
                cursor = self._library.db.execute("UPDATE tags SET name=? WHERE id=?", (name, int(tag_id)))
                if not cursor.rowcount:
                    return {"ok": False, "error": "This tag is no longer available."}
                self._library.db.commit()
            self._record_activity("tag-rename", 1)
            return {"ok": True, "tags": self.list_tags()}
        except (sqlite3.IntegrityError, TypeError, ValueError) as exc:
            return {"ok": False, "error": f"A tag with that name already exists: {exc}"}

    def delete_tag(self, tag_id):
        with self._library.lock:
            tag = self._library.db.execute("SELECT id FROM tags WHERE id=?", (int(tag_id),)).fetchone()
            if not tag:
                return {"ok": False, "error": "This tag is no longer available."}
            self._library.db.execute("DELETE FROM file_tags WHERE tag_id=?", (int(tag_id),))
            self._library.db.execute("DELETE FROM tags WHERE id=?", (int(tag_id),))
            self._library.db.commit()
        self._record_activity("tag-delete", 1)
        return {"ok": True, "tags": self.list_tags()}

    def pdf_page(self, path, page_number=0, zoom=1.2):
        return self._library.pdf_page(path, int(page_number), float(zoom))

    def rotate_pdf_page_copy(self, path, page_number, rotation=90):
        """Save a copy of a PDF with only the selected page rotated."""
        if not PdfReader or not PdfWriter:
            return {"ok": False, "error": "Install the project requirements to edit PDFs."}
        try:
            page_number = int(page_number)
            rotation = int(rotation)
            if rotation not in {-270, -180, -90, 90, 180, 270}:
                return {"ok": False, "error": "Choose a rotation of 90, 180, or 270 degrees."}
            source = Path(path)
            if source.suffix.lower() != ".pdf" or not source.is_file():
                return {"ok": False, "error": "This PDF is no longer available."}
            reader = PdfReader(str(source), strict=False)
            if reader.is_encrypted:
                return {"ok": False, "error": "Password-protected PDFs cannot be edited here."}
            if page_number < 0 or page_number >= len(reader.pages):
                return {"ok": False, "error": "Page is out of range."}
            writer = PdfWriter()
            writer.append(reader)
            writer.pages[page_number].rotate(rotation)
            target = self._unused_output(
                source.with_name(f"{source.stem}-page-{page_number + 1}-edited.pdf"))
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            try:
                with temporary.open("wb") as output:
                    writer.write(output)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            self._index_destination(str(target))
            return {"ok": True, "path": str(target)}
        except (OSError, ValueError, IndexError) as exc:
            return {"ok": False, "error": str(exc)}

    def choose_folders(self):
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER, allow_multiple=True)
        return list(result or [])

    def choose_files(self):
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True)
        return list(result or [])

    def add_folders(self, paths=None):
        paths = paths or self.choose_folders()
        added = []
        for path in paths or []:
            result = self._library.add_root(path)
            if result.get("ok"):
                added.append(result["path"])
                self._start_watcher(result["path"])
        return {"ok": True, "added": added}

    def add_files(self, paths=None):
        if paths is None:
            paths = self.choose_files()
        return self.queue_add_paths(paths or [])

    def add_dropped_paths(self, paths):
        return self._library.add_dropped_paths(paths)

    def queue_add_paths(self, paths):
        paths = list(dict.fromkeys(os.path.normpath(path) for path in paths if isinstance(path, str)))
        if not paths:
            return {"ok": False, "cancelled": True}
        self.register_drop_event({"ok": True, "processing": True, "folders": 0, "files": len(paths)})

        def process():
            try:
                result = self._library.add_dropped_paths(paths)
                for root in result.get("folder_paths", []):
                    self._start_watcher(root)
            except Exception as exc:
                result = {"ok": False, "folders": 0, "files": 0, "error": str(exc)}
            self.register_drop_event(result)

        threading.Thread(target=process, name="hearth-add-items", daemon=True).start()
        return {"ok": True, "processing": True}

    def remove_folder(self, path):
        self._stop_watcher(path)
        with self._library.lock:
            matching = "SELECT path FROM files WHERE root=?"
            self._library.db.execute(f"DELETE FROM favorites WHERE path IN ({matching})", (path,))
            self._library.db.execute(f"DELETE FROM file_tags WHERE path IN ({matching})", (path,))
            self._library.db.execute(f"DELETE FROM file_index_versions WHERE path IN ({matching})", (path,))
            self._library.db.execute(f"DELETE FROM file_hashes WHERE path IN ({matching})", (path,))
            self._library.db.execute("DELETE FROM collection_items WHERE path IN (SELECT path FROM files WHERE root=?)", (path,))
            self._library.db.execute("DELETE FROM roots WHERE path=?", (path,))
            self._library.db.execute("DELETE FROM files WHERE root=?", (path,))
            self._library.db.commit()
        return self.get_state()

    def get_scan_status(self):
        return {**self._library.scan_status, "count_total": self.count_files(),
                "drop_event": self._drop_event}

    def get_diagnostics(self):
        """Return diagnostic information for troubleshooting."""
        with self._library.lock:
            db_size = os.path.getsize(DB_PATH) if DB_PATH.exists() else 0
            wal_size = os.path.getsize(DB_PATH.with_suffix('.sqlite3-wal')) if DB_PATH.with_suffix('.sqlite3-wal').exists() else 0
            shm_size = os.path.getsize(DB_PATH.with_suffix('.sqlite3-shm')) if DB_PATH.with_suffix('.sqlite3-shm').exists() else 0
            file_count = self._library.db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            root_count = self._library.db.execute("SELECT COUNT(*) FROM roots").fetchone()[0]
            collection_count = self._library.db.execute("SELECT COUNT(*) FROM collections").fetchone()[0]
            tag_count = self._library.db.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
            favorite_count = self._library.db.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
            undo_count = self._library.db.execute("SELECT COUNT(*) FROM undo_ops").fetchone()[0]
            hash_count = self._library.db.execute("SELECT COUNT(*) FROM file_hashes").fetchone()[0]
            unversioned_count = self._library.db.execute("SELECT COUNT(*) FROM files f LEFT JOIN file_index_versions v ON v.path=f.path WHERE v.path IS NULL OR v.content_version<>?", (CONTENT_INDEX_VERSION,)).fetchone()[0]
            root_paths = [r[0] for r in self._library.db.execute("SELECT path FROM roots")]
            file_paths = [r[0] for r in self._library.db.execute("SELECT path FROM files")]
            integrity = self._library.db.execute("PRAGMA integrity_check").fetchone()[0]
        missing_files = sum(not os.path.exists(path) for path in file_paths)
        missing_roots = sum(not os.path.isdir(path) for path in root_paths)
        try:
            free_bytes = shutil.disk_usage(APP_DATA).free
        except OSError:
            free_bytes = None
        with self._job_lock:
            running_jobs = sum(job.get("status") in {"running", "cancelling"} for job in self._jobs.values())
        try:
            last_backup_time = float(self.get_preference("last_backup_time", "0") or 0)
            last_backup_bytes = max(0, int(self.get_preference("last_backup_bytes", "0") or 0))
        except (TypeError, ValueError, OverflowError):
            last_backup_time, last_backup_bytes = 0, 0
        return {
            "ok": True,
            "database": {
                "path": str(DB_PATH),
                "size_bytes": db_size,
                "wal_size_bytes": wal_size,
                "shm_size_bytes": shm_size,
                "integrity": integrity
            },
            "counts": {
                "files": file_count,
                "roots": root_count,
                "collections": collection_count,
                "tags": tag_count,
                "favorites": favorite_count,
                "undo_operations": undo_count,
                "file_hashes": hash_count
            },
            "health": {"missing_files": missing_files, "missing_roots": missing_roots,
                       "stale_index_rows": unversioned_count, "free_bytes": free_bytes,
                       "active_jobs": running_jobs, "scan_running": bool(self._library.scan_status.get("running")),
                       "last_backup_time": last_backup_time, "last_backup_bytes": last_backup_bytes},
            "watchers": {
                "active": len(self._observers),
                "paths": list(self._observers.keys())
            },
            "app_data": str(APP_DATA),
            "version": APP_VERSION,
            "python": sys.version.split()[0]
        }

    def export_diagnostics(self):
        filename = f"Hearth-diagnostics-{datetime.now():%Y-%m-%d}.json"
        result = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename,
                                                 file_types=("JSON file (*.json)",))
        if not result:
            return {"ok": False, "cancelled": True}
        target = Path(result if isinstance(result, str) else result[0])
        report = self.get_diagnostics()
        # Keep this support file useful without disclosing library paths or names.
        report["database"].pop("path", None)
        report["watchers"].pop("paths", None)
        report.pop("app_data", None)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, target)
            return {"ok": True, "path": str(target)}
        except (OSError, TypeError, ValueError) as exc:
            temporary.unlink(missing_ok=True)
            return {"ok": False, "error": str(exc)}

    def refresh_folders(self):
        roots = [r["path"] for r in self._library.roots() if os.path.isdir(r["path"])]
        for root in roots:
            self._start_watcher(root)
            threading.Thread(target=self._library.scan, args=(root,), daemon=True).start()
        return {"ok": True, "folders": len(roots)}

    def _start_watcher(self, root):
        root = os.path.normpath(root)
        with self._watch_lock:
            if root in self._observers or not os.path.isdir(root):
                return
            try:
                from watchdog.events import FileSystemEventHandler
                from watchdog.observers import Observer

                api = self
                class HearthWatchHandler(FileSystemEventHandler):
                    def on_any_event(self, event):
                        if event.event_type not in {"opened", "closed_no_write"}:
                            api._schedule_rescan(root)

                observer = Observer()
                observer.schedule(HearthWatchHandler(), root, recursive=True)
                observer.start()
                self._observers[root] = observer
            except (ImportError, OSError, RuntimeError):
                return

    def _schedule_rescan(self, root):
        with self._watch_lock:
            previous = self._watch_timers.pop(root, None)
            if previous:
                previous.cancel()
            timer = threading.Timer(1.25, self._rescan_watched_root, args=(root,))
            timer.daemon = True
            self._watch_timers[root] = timer
            timer.start()

    def _stop_watcher(self, root):
        root = os.path.normpath(root)
        with self._watch_lock:
            timer = self._watch_timers.pop(root, None)
            observer = self._observers.pop(root, None)
        if timer:
            timer.cancel()
        if observer:
            observer.stop()
            observer.join(timeout=2)

    def _rescan_watched_root(self, root):
        with self._watch_lock:
            self._watch_timers.pop(root, None)
        if os.path.isdir(root) and any(r["path"] == root for r in self._library.roots()):
            self._library.scan(root)

    def open_file(self, path):
        try:
            if os.name == "nt":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def reveal_file(self, path):
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", str(Path(path).parent)])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def rename_file(self, path, new_name, record_undo=True):
        if not new_name or Path(new_name).name != new_name or new_name in {".", ".."}:
            return {"ok": False, "error": "Please enter a valid file name."}
        destination = str(Path(path).with_name(new_name))
        moved = False
        try:
            os.rename(path, destination)
            moved = True
            self._update_path(path, destination)
            if record_undo:
                self._record_undo("rename", {"old": path, "new": destination})
            return {"ok": True}
        except Exception as exc:
            if moved and os.path.exists(destination) and not os.path.exists(path):
                try:
                    os.rename(destination, path)
                    self._update_path(destination, path)
                except Exception as rollback_exc:
                    try:
                        self._record_undo("rename", {"old": path, "new": destination})
                    except Exception:
                        pass
                    return {"ok": False, "error": f"Rename recovery needed: {rollback_exc}"}
            return {"ok": False, "error": str(exc)}

    def copy_file(self, path):
        target = self._choose_destination()
        if not target:
            return {"ok": False, "cancelled": True}
        dest = os.path.join(target, os.path.basename(path))
        try:
            if os.path.exists(dest):
                return {"ok": False, "error": "A file with that name already exists in the selected folder."}
            shutil.copy2(path, dest)
            self._index_destination(dest)
            self._record_undo("copy", [dest])
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    def move_file(self, path):
        target = self._choose_destination()
        if not target:
            return {"ok": False, "cancelled": True}
        dest = os.path.join(target, os.path.basename(path))
        try:
            if os.path.exists(dest):
                return {"ok": False, "error": "A file with that name already exists in the selected folder."}
            shutil.move(path, dest)
            self._update_path(path, dest)
            self._index_destination(dest)
            self._record_undo("move", [{"old": path, "new": dest}])
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    def _choose_destination(self):
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER, allow_multiple=False)
        return result[0] if result else None

    def _index_destination(self, dest):
        roots = [r["path"] for r in self._library.roots()]
        root = next((r for r in roots if self._is_inside(dest, r)), "")
        path = Path(dest)
        try:
            stat = path.stat()
            body = self._library._extract_text(path, stat.st_size)
        except OSError:
            return
        with self._library.lock:
            self._library.db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?)", (dest, path.name, path.suffix.lower(), stat.st_size, stat.st_mtime, body, root))
            self._library.db.execute("INSERT OR REPLACE INTO file_index_versions VALUES(?,?)", (dest, CONTENT_INDEX_VERSION))
            self._library.db.execute("DELETE FROM file_hashes WHERE path=?", (dest,))
            self._library.db.commit()

    def _update_path(self, old, new):
        destination_root = next((r["path"] for r in self._library.roots() if self._is_inside(new, r["path"])), None)
        with self._library.lock:
            try:
                row = self._library.db.execute("SELECT * FROM files WHERE path=?", (old,)).fetchone()
                if row:
                    stat = os.stat(new)
                    self._library.db.execute("UPDATE files SET path=?, name=?, size=?, modified=?, root=? WHERE path=?", (new, Path(new).name, stat.st_size, stat.st_mtime, destination_root or "", old))
                    self._library.db.execute("UPDATE collection_items SET path=? WHERE path=?", (new, old))
                    self._library.db.execute("UPDATE favorites SET path=? WHERE path=?", (new, old))
                    self._library.db.execute("UPDATE file_tags SET path=? WHERE path=?", (new, old))
                    self._library.db.execute("UPDATE file_index_versions SET path=? WHERE path=?", (new, old))
                    self._library.db.execute("UPDATE file_hashes SET path=?, size=?, modified=? WHERE path=?", (new, stat.st_size, stat.st_mtime, old))
                    self._library.db.execute("UPDATE file_notes SET path=? WHERE path=?", (new, old))
                self._library.db.commit()
            except Exception:
                self._library.db.rollback()
                raise

    @staticmethod
    def _is_inside(path, root):
        try:
            common = os.path.commonpath([os.path.abspath(path), os.path.abspath(root)])
            expected = os.path.abspath(root)
            return common.casefold() == expected.casefold() if os.name == "nt" else common == expected
        except ValueError: return False

    def delete_file(self, path, confirm=True):
        result = self.bulk_action([path], "delete")
        if result.get("ok"):
            return {"ok": True}
        return {"ok": False, "error": result.get("error", "File could not be deleted.")}

    def bulk_action(self, paths, action, option=None):
        paths = list(dict.fromkeys(path for path in (paths or []) if isinstance(path, str)))[:500]
        if not paths:
            return {"ok": False, "error": "Select at least one file."}
        if action == "collection":
            with self._library.lock:
                paths=[path for path in paths if self._library.db.execute("SELECT 1 FROM files WHERE path=?",(path,)).fetchone()]
                if not self._library.db.execute("SELECT 1 FROM collections WHERE id=?",(int(option),)).fetchone():
                    return {"ok":False,"error":"This collection is no longer available."}
            if not paths:return {"ok":False,"error":"The selected files are no longer available."}
            before=[{"path":path,**self._file_metadata(path)} for path in paths]
            with self._library.lock:
                self._library.db.executemany("INSERT OR IGNORE INTO collection_items VALUES(?,?)",
                                             [(int(option), path) for path in paths])
                self._library.db.commit()
            self._record_undo("metadata",before)
            return {"ok": True, "completed": len(paths), "collections": self._library.collections()}
        if action == "tag":
            with self._library.lock:
                paths=[path for path in paths if self._library.db.execute("SELECT 1 FROM files WHERE path=?",(path,)).fetchone()]
            if not paths:return {"ok":False,"error":"The selected files are no longer available."}
            before=[{"path":path,**self._file_metadata(path)} for path in paths]
            completed = 0
            for path in paths:
                result = self.set_file_tags(path, option if isinstance(option, list) else [], record_undo=False)
                completed += int(bool(result.get("ok")))
            if completed: self._record_undo("metadata",before)
            return {"ok": completed > 0, "completed": completed}
        if action == "favorite":
            with self._library.lock:
                paths=[path for path in paths if self._library.db.execute("SELECT 1 FROM files WHERE path=?",(path,)).fetchone()]
            if not paths:return {"ok":False,"error":"The selected files are no longer available."}
            before=[{"path":path,**self._file_metadata(path)} for path in paths]
            completed = 0
            for path in paths:
                result = self.toggle_favorite(path, record_undo=False)
                completed += int(bool(result.get("ok")))
            if completed: self._record_undo("metadata",before)
            return {"ok": True, "completed": completed}
        if action == "rename":
            prefix = (option or "").strip()
            if not prefix:
                return {"ok": False, "error": "Enter a name prefix."}
            successes = 0
            errors = []
            undo_items = []
            for path in paths:
                source = Path(path)
                new_path=f"{prefix} - {source.stem}{source.suffix}"
                result = self.rename_file(path, new_path, record_undo=False)
                if result.get("ok"):
                    successes += 1
                    undo_items.append({"old":path,"new":str(source.with_name(new_path))})
                else:
                    errors.append(f"{source.name}: {result.get('error', 'failed')}")
            if undo_items:
                self._record_undo("rename", undo_items)
            return {"ok": successes > 0, "completed": successes, "errors": errors[:5]}
        if action in {"copy", "move"}:
            destination = self._choose_destination()
            if not destination:
                return {"ok": False, "cancelled": True}
            successes = 0
            errors = []
            undo_items = []
            for path in paths:
                try:
                    name = Path(path).name
                    target = Path(destination) / name
                    suffix = 2
                    while target.exists():
                        target = Path(destination) / f"{Path(name).stem} ({suffix}){Path(name).suffix}"
                        suffix += 1
                    shutil.copy2(path, target) if action == "copy" else shutil.move(path, target)
                    undo_items.append(str(target) if action == "copy" else {"old": path, "new": str(target)})
                    if action == "move":
                        self._update_path(path, str(target))
                    self._index_destination(str(target))
                    successes += 1
                except OSError as exc:
                    errors.append(f"{Path(path).name}: {exc}")
            if undo_items: self._record_undo(action, undo_items)
            return {"ok": successes > 0, "completed": successes, "errors": errors[:5]}
        if action == "delete":
            existing = [path for path in paths if os.path.isfile(path)]
            if not existing:
                return {"ok": False, "error": "The selected files are no longer available."}
            undo_items = []
            undo_id = None
            try:
                trash_root = APP_DATA / "UndoTrash"; trash_root.mkdir(parents=True, exist_ok=True)
                for path in existing:
                    trashed = trash_root / f"{uuid.uuid4().hex}_{Path(path).name}"
                    metadata = self._file_metadata(path)
                    try:
                        shutil.move(path, str(trashed))
                    except Exception:
                        # Cross-volume shutil.move may leave a partial destination
                        # when copying fails. Remove that fragment if the source
                        # still exists; otherwise preserve it as a recoverable move.
                        if trashed.exists():
                            if os.path.exists(path):
                                trashed.unlink(missing_ok=True)
                            else:
                                undo_items.append({"old": path, "trash": str(trashed), "metadata": metadata})
                        raise
                    undo_items.append({"old": path, "trash": str(trashed), "metadata": metadata})
                undo_id = self._record_undo("delete", undo_items)
                with self._library.lock:
                    self._library.db.executemany("DELETE FROM files WHERE path=?", [(path,) for path in existing])
                    self._library.db.executemany("DELETE FROM collection_items WHERE path=?", [(path,) for path in existing])
                    self._library.db.executemany("DELETE FROM favorites WHERE path=?", [(path,) for path in existing])
                    self._library.db.executemany("DELETE FROM file_tags WHERE path=?", [(path,) for path in existing])
                    self._library.db.executemany("DELETE FROM file_index_versions WHERE path=?", [(path,) for path in existing])
                    self._library.db.executemany("DELETE FROM file_hashes WHERE path=?", [(path,) for path in existing])
                    self._library.db.commit()
                return {"ok": True, "completed": len(existing)}
            except Exception as exc:
                # A failed move can happen after earlier files have already reached
                # UndoTrash. Put those files back; if a rollback itself fails,
                # retain a valid undo record and remove only the stranded paths
                # from the library index so the UI never points at missing files.
                with self._library.lock:
                    self._library.db.rollback()
                    if undo_id is not None:
                        self._library.db.execute("DELETE FROM undo_ops WHERE id=?", (undo_id,))
                        self._library.db.commit()
                stranded = []
                rollback_errors = []
                for item in reversed(undo_items):
                    try:
                        if os.path.exists(item["trash"]) and not os.path.exists(item["old"]):
                            Path(item["old"]).parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(item["trash"], item["old"])
                        elif os.path.exists(item["trash"]):
                            stranded.append(item)
                            rollback_errors.append(f"{Path(item['old']).name}: original path is occupied")
                    except Exception as rollback_exc:
                        stranded.append(item)
                        rollback_errors.append(f"{Path(item['old']).name}: {rollback_exc}")
                if stranded:
                    try:
                        self._record_undo("delete", stranded)
                        with self._library.lock:
                            for table in ("files", "collection_items", "favorites", "file_tags", "file_index_versions", "file_hashes"):
                                self._library.db.executemany(f"DELETE FROM {table} WHERE path=?", [(item["old"],) for item in stranded])
                            self._library.db.commit()
                    except Exception as recovery_exc:
                        rollback_errors.append(f"Recovery record could not be saved: {recovery_exc}")
                detail = f"Bulk delete stopped and was rolled back: {exc}"
                if rollback_errors:
                    detail += " | Recovery needed: " + "; ".join(rollback_errors[:3])
                return {"ok": False, "error": detail}
        return {"ok": False, "error": "Unknown bulk operation."}

    def create_collection(self, name):
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "Give your collection a name."}
        try:
            with self._library.lock:
                if self._library.db.execute(
                    "SELECT 1 FROM collections WHERE name=? COLLATE NOCASE UNION ALL SELECT 1 FROM smart_collections WHERE name=? COLLATE NOCASE LIMIT 1",
                    (name, name)).fetchone():
                    return {"ok": False, "error": "A collection with that name already exists."}
                self._library.db.execute("INSERT INTO collections(name,created) VALUES(?,?)", (name, time.time()))
                self._library.db.commit()
            return {"ok": True, "collections": self._library.collections()}
        except sqlite3.IntegrityError:
            return {"ok": False, "error": "A collection with that name already exists."}

    def save_smart_collection(self, name, query="", category="Everything", filters=None, smart_id=None):
        name = (name or "").strip()[:60]
        if not name:
            return {"ok": False, "error": "Give your smart collection a name."}
        if not isinstance(filters, (dict, type(None))):
            return {"ok": False, "error": "Smart collection filters must be an object."}
        try:
            with self._library.lock:
                if smart_id:
                    if self._library.db.execute(
                        "SELECT 1 FROM collections WHERE name=? COLLATE NOCASE UNION ALL SELECT 1 FROM smart_collections WHERE name=? COLLATE NOCASE AND id<>? LIMIT 1",
                        (name, name, int(smart_id))).fetchone():
                        return {"ok": False, "error": "A collection with that name already exists."}
                    cursor = self._library.db.execute(
                        "UPDATE smart_collections SET name=?,query=?,category=?,filters=? WHERE id=?",
                        (name, (query or "").strip()[:1000], category or "Everything",
                         json.dumps(filters or {}, ensure_ascii=False), int(smart_id)))
                    if not cursor.rowcount:
                        return {"ok": False, "error": "This smart collection is no longer available."}
                else:
                    if self._library.db.execute(
                        "SELECT 1 FROM collections WHERE name=? COLLATE NOCASE UNION ALL SELECT 1 FROM smart_collections WHERE name=? COLLATE NOCASE LIMIT 1",
                        (name, name)).fetchone():
                        return {"ok": False, "error": "A collection with that name already exists."}
                    self._library.db.execute(
                        "INSERT INTO smart_collections(name,query,category,filters,created) VALUES(?,?,?,?,?)",
                        (name, (query or "").strip()[:1000], category or "Everything",
                         json.dumps(filters or {}, ensure_ascii=False), time.time()))
                self._library.db.commit()
            self._record_activity("smart-collection", 1)
            return {"ok": True, "collections": self._library.collections()}
        except sqlite3.IntegrityError:
            return {"ok": False, "error": "A collection with that name already exists."}
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def delete_smart_collection(self, smart_id):
        with self._library.lock:
            cursor = self._library.db.execute("DELETE FROM smart_collections WHERE id=?", (int(smart_id),))
            self._library.db.commit()
        if cursor.rowcount:
            self._record_activity("smart-collection-delete", 1)
        return self._library.collections()

    def delete_collection(self, collection_id):
        with self._library.lock:
            self._library.db.execute("DELETE FROM collections WHERE id=?", (collection_id,))
            self._library.db.execute("DELETE FROM collection_items WHERE collection_id=?", (collection_id,))
            self._library.db.commit()
        return self._library.collections()

    def add_to_collection(self, collection_id, path):
        with self._library.lock:
            if not self._library.db.execute("SELECT 1 FROM files WHERE path=?", (path,)).fetchone():
                return {"ok":False,"error":"This file is no longer available."}
            if not self._library.db.execute("SELECT 1 FROM collections WHERE id=?", (collection_id,)).fetchone():
                return {"ok":False,"error":"This collection is no longer available."}
        previous=self._file_metadata(path)
        with self._library.lock:
            self._library.db.execute("INSERT OR IGNORE INTO collection_items VALUES(?,?)", (collection_id, path))
            self._library.db.commit()
        self._record_undo("metadata",[{"path":path,**previous}])
        return self._library.collections()

    def copy_to_clipboard(self, path, cut=False):
        self._clipboard = [(path, bool(cut))]
        if os.name == "nt" and os.path.exists(path):
            try:
                import clr
                if hasattr(clr, "AddReference"):
                    clr.AddReference('System.Windows.Forms')
                    from System.Windows.Forms import Clipboard, DataObject
                    from System.Collections.Specialized import StringCollection
                    sc = StringCollection()
                    sc.Add(os.path.abspath(path))
                    data = DataObject()
                    data.SetFileDropList(sc)
                    Clipboard.SetDataObject(data, True)
            except Exception:
                pass
        return {"ok": True, "cut": bool(cut)}

    def window_ready(self):
        """Called by JavaScript when the UI is rendered and ready to show."""
        close_native_splash()
        if not getattr(self, "_start_minimized", False):
            try:
                hwnd_val = self._native_handle()
                native = getattr(self._window, "native", None) if hasattr(self, "_window") else None
                if self._center_on_start and native:
                    self._center_native_window(ctypes.c_void_p(hwnd_val))
                # Must show on WinForms UI thread; use BeginInvoke when native is available
                if native:
                    try:
                        from System.Windows.Forms import MethodInvoker
                        def _show():
                            try:
                                native.Visible = True
                                native.Show()
                                native.BringToFront()
                                if hwnd_val:
                                    ctypes.windll.user32.SetForegroundWindow(ctypes.c_void_p(hwnd_val))
                            except Exception:
                                pass
                        native.BeginInvoke(MethodInvoker(_show))
                    except Exception:
                        try: self._window.show()
                        except Exception: pass
                else:
                    try: self._window.show()
                    except AttributeError: pass
            except Exception:
                try: self._window.show()
                except Exception: pass
        return {"ok": True}

    def export_to_desktop(self, paths):
        """Directly copy the specified files to the desktop."""
        if not paths:
            return {"ok": False, "error": "No files specified"}
        if isinstance(paths, str):
            paths = [paths]
        desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
        exported = []
        for p in paths:
            p = os.path.normpath(p)
            if os.path.exists(p):
                dest = desktop / os.path.basename(p)
                if dest.exists() and dest.resolve() != Path(p).resolve():
                    stem, ext = dest.stem, dest.suffix
                    idx = 1
                    while (desktop / f"{stem} ({idx}){ext}").exists():
                        idx += 1
                    dest = desktop / f"{stem} ({idx}){ext}"
                try:
                    shutil.copy2(p, dest)
                    exported.append(str(dest))
                except Exception as exc:
                    return {"ok": False, "error": str(exc)}
        return {"ok": True, "count": len(exported), "destination": str(desktop)}

    def start_drag(self, paths):
        """Initiate native Windows OLE drag-and-drop to Explorer, Desktop, or other apps.

        Uses a pure-ctypes COM SHDoDragDrop on a dedicated STA thread so that
        WebView2's internal mouse capture cannot block the operation.
        """
        if not paths:
            return {"ok": False, "error": "No files specified"}
        if isinstance(paths, str):
            paths = [paths]
        valid_paths = [os.path.normpath(p) for p in paths if os.path.exists(p)]
        if not valid_paths:
            return {"ok": False, "error": "Files do not exist"}

        if os.name == "nt":
            try:
                _start_shell_drag(valid_paths)
                return {"ok": True, "count": len(valid_paths), "paths": valid_paths}
            except Exception as exc:
                import logging
                logging.getLogger("hearth").error("start_drag error: %s", exc)

        return {"ok": True, "count": len(valid_paths), "paths": valid_paths}

    def paste_here(self, folder):
        if not self._clipboard:
            return {"ok": False, "error": "Nothing to paste."}
        path, cut = self._clipboard.pop(0)
        dest = os.path.join(folder, os.path.basename(path))
        try:
            shutil.move(path, dest) if cut else shutil.copy2(path, dest)
            if cut: self._update_path(path, dest)
            self._index_destination(dest)
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    def save_backup(self):
        filename = f"Hearth-backup-{datetime.now():%Y-%m-%d}.zip"
        result = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename, file_types=("ZIP archive (*.zip)",))
        if not result:
            return {"ok": False, "cancelled": True}
        target = result if isinstance(result, str) else result[0]
        return self._write_backup(Path(target))

    def _write_backup(self, target):
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            # SQLite's backup API captures one consistent snapshot, including WAL data,
            # without racing concurrent index or metadata writes.
            with tempfile.TemporaryDirectory(dir=APP_DATA) as snapshot_dir:
                snapshot = Path(snapshot_dir) / "library.sqlite3"
                with self._library.lock, closing(sqlite3.connect(snapshot)) as snapshot_db:
                    self._library.db.backup(snapshot_db)
                digest = hashlib.sha256()
                with snapshot.open("rb") as database_file:
                    for chunk in iter(lambda: database_file.read(1024 * 1024), b""):
                        digest.update(chunk)
                manifest = {"format": "hearth-library-backup", "version": APP_VERSION,
                            "database_bytes": snapshot.stat().st_size, "database_sha256": digest.hexdigest(),
                            "created": datetime.now().astimezone().isoformat()}
                with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                    archive.write(snapshot, "library.sqlite3")
                    archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            os.replace(temporary, target)
            self.set_preference("last_backup_time", str(time.time()))
            self.set_preference("last_backup_bytes", str(target.stat().st_size))
            return {"ok": True, "path": str(target)}
        except Exception as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            return {"ok": False, "error": str(exc)}

    def restore_backup(self):
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False,
                                                 file_types=("Hearth backup (*.zip)",))
        if not result:
            return {"ok": False, "cancelled": True}
        backup_path = result if isinstance(result, str) else result[0]
        try:
            with tempfile.TemporaryDirectory(dir=APP_DATA) as temp_dir:
                candidate = Path(temp_dir) / "restore.sqlite3"
                safety = Path(temp_dir) / "before-restore.sqlite3"
                with zipfile.ZipFile(backup_path, "r") as archive:
                    names = archive.namelist()
                    if len(names) != len(set(names)) or "library.sqlite3" not in names:
                        return {"ok": False, "error": "This backup has an invalid or duplicated file list."}
                    member = archive.getinfo("library.sqlite3")
                    if member.file_size > 2_000_000_000:
                        return {"ok": False, "error": "This backup is larger than Hearth can restore."}
                    if member.compress_size and member.file_size / member.compress_size > 2000:
                        return {"ok": False, "error": "This backup has an unsafe compression ratio."}
                    digest = hashlib.sha256()
                    copied = 0
                    with archive.open(member) as source_file, candidate.open("wb") as target_file:
                        while True:
                            chunk = source_file.read(1024 * 1024)
                            if not chunk:
                                break
                            copied += len(chunk)
                            if copied > 2_000_000_000:
                                return {"ok": False, "error": "This backup is larger than Hearth can restore."}
                            digest.update(chunk)
                            target_file.write(chunk)
                    if "manifest.json" in names:
                        if archive.getinfo("manifest.json").file_size > 64_000:
                            return {"ok": False, "error": "The backup manifest is invalid."}
                        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                        if not isinstance(manifest, dict):
                            return {"ok": False, "error": "The backup manifest is invalid."}
                        if (manifest.get("format") != "hearth-library-backup" or
                                int(manifest.get("database_bytes", -1)) != copied or
                                manifest.get("database_sha256") != digest.hexdigest()):
                            return {"ok": False, "error": "The backup checksum does not match its library database."}
                    elif set(names) != {"library.sqlite3"}:
                        return {"ok": False, "error": "This backup contains unsupported files."}
                with closing(sqlite3.connect(candidate)) as source_db:
                    integrity = source_db.execute("PRAGMA integrity_check").fetchone()[0]
                    tables = {r[0] for r in source_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    required_columns = {
                        "roots": {"path", "added_at"},
                        "files": {"path", "name", "ext", "size", "modified", "content", "root"},
                        "collections": {"id", "name", "created"},
                        "prefs": {"key", "value"},
                    }
                    schema_ok = all(
                        table in tables and required.issubset(
                            {column[1] for column in source_db.execute(f"PRAGMA table_info({table})")}
                        )
                        for table, required in required_columns.items()
                    )
                    if integrity != "ok" or not schema_ok:
                        return {"ok": False, "error": "This file is not a valid Hearth library backup."}
                    safety_dir = APP_DATA / "PreRestoreBackups"
                    safety_dir.mkdir(parents=True, exist_ok=True)
                    safety_copy = safety_dir / f"library-before-restore-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.sqlite3"
                    with self._library.lock:
                        with closing(sqlite3.connect(safety)) as safety_db:
                            self._library.db.backup(safety_db)
                        os.replace(safety, safety_copy)
                        try:
                            source_db.backup(self._library.db)
                            self._library.db.executescript("""
                                CREATE TABLE IF NOT EXISTS favorites(path TEXT PRIMARY KEY, added_at REAL NOT NULL);
                                CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, color TEXT NOT NULL DEFAULT '#a58d6d');
                                CREATE TABLE IF NOT EXISTS file_tags(path TEXT NOT NULL, tag_id INTEGER NOT NULL, PRIMARY KEY(path,tag_id));
                                CREATE TABLE IF NOT EXISTS file_notes(path TEXT PRIMARY KEY, note TEXT NOT NULL, updated REAL NOT NULL);
                                CREATE TABLE IF NOT EXISTS saved_searches(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                                  query TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'Everything', filters TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL);
                                CREATE TABLE IF NOT EXISTS file_index_versions(path TEXT PRIMARY KEY, content_version INTEGER NOT NULL);
                                CREATE TABLE IF NOT EXISTS file_hashes(path TEXT PRIMARY KEY, size INTEGER NOT NULL, modified REAL NOT NULL, sha256 TEXT NOT NULL);
                                CREATE TABLE IF NOT EXISTS undo_ops(id INTEGER PRIMARY KEY, action TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL);
                                CREATE TABLE IF NOT EXISTS smart_collections(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                                  query TEXT NOT NULL DEFAULT '', filters TEXT NOT NULL DEFAULT '{}', category TEXT NOT NULL DEFAULT 'Everything', created REAL NOT NULL);
                                CREATE TABLE IF NOT EXISTS activity_log(id INTEGER PRIMARY KEY, action TEXT NOT NULL, item_count INTEGER NOT NULL DEFAULT 0,
                                  status TEXT NOT NULL DEFAULT 'completed', created REAL NOT NULL);
                                CREATE UNIQUE INDEX IF NOT EXISTS tags_name_nocase ON tags(name COLLATE NOCASE);
                            """)
                            restored_search_columns = {row[1] for row in self._library.db.execute("PRAGMA table_info(saved_searches)")}
                            if "filters" not in restored_search_columns:
                                self._library.db.execute("ALTER TABLE saved_searches ADD COLUMN filters TEXT NOT NULL DEFAULT '{}'")
                            self._library.db.commit()
                        except Exception:
                            with closing(sqlite3.connect(safety)) as safety_db:
                                safety_db.backup(self._library.db)
                            self._library.db.commit()
                            raise
            self._record_activity("backup-restore", 1)
            return {"ok": True, "state": self.get_state(), "safety_copy": str(safety_copy)}
        except (OSError, sqlite3.Error, zipfile.BadZipFile, KeyError, json.JSONDecodeError,
                TypeError, ValueError, OverflowError, RuntimeError) as exc:
            return {"ok": False, "error": str(exc)}

    def open_data_folder(self):
        try:
            if os.name == "nt":
                os.startfile(APP_DATA)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(APP_DATA)])
            else:
                subprocess.Popen(["xdg-open", str(APP_DATA)])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_preference(self, key, default=""):
        with self._library.lock:
            row = self._library.db.execute("SELECT value FROM prefs WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_preference(self, key, value):
        with self._library.lock:
            self._library.db.execute("INSERT OR REPLACE INTO prefs VALUES(?,?)", (key, str(value)))
            self._library.db.commit()
        if key == "has_seen_intro" and str(value) == "1":
            with self._library.lock:
                self._library.db.execute("INSERT OR REPLACE INTO prefs VALUES(?,?)", ("has_seen_intro_version", APP_VERSION))
                self._library.db.commit()
        if key == "language":
            lang_str = str(value)
            if os.name == "nt":
                try:
                    import winreg
                    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Hearth") as reg_key:
                        winreg.SetValueEx(reg_key, "Language", 0, winreg.REG_SZ, "turkish" if lang_str == "tr" else "english")
                except Exception:
                    pass
            if hasattr(self, "_tray_manager") and self._tray_manager:
                self._tray_manager.update_language(lang_str)
            if self.is_context_menu_enabled():
                sync_context_menu_registry(True, lang_str)
        return True

    def get_window_bounds(self):
        fallback = {"width": 920, "height": 612, "x": None, "y": None}
        try:
            stored = json.loads(self.get_preference("window_bounds", "{}"))
            width = max(900, min(2400, int(stored.get("width", fallback["width"]))))
            height = max(600, min(1800, int(stored.get("height", fallback["height"]))))
            x, y = stored.get("x"), stored.get("y")
            x = int(x) if x is not None else None
            y = int(y) if y is not None else None
            # Avoid restoring a window wholly beyond common desktop coordinate bounds.
            if x is not None and (abs(x) > 20000 or abs(y or 0) > 20000):
                x = y = None
            if (x is None) != (y is None):
                x = y = None
            screens = getattr(webview, "screens", [])
            if x is not None and screens and not any(
                x < screen.x + screen.width - 80 and x + width > screen.x and
                y < screen.y + screen.height - 48 and y + height > screen.y
                for screen in screens
            ):
                x = y = None
            self._center_on_start = x is None
            if x is None:
                work_area = _primary_work_area()
                if work_area:
                    left, top, right, bottom = work_area
                    x = left + max(0, (right - left - width) // 2)
                    y = top + max(0, (bottom - top - height) // 2)
            return {"width": width, "height": height, "x": x, "y": y}
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback

    def save_window_bounds(self):
        try:
            native = self._window.native
            state = str(native.WindowState).rsplit(".", 1)[-1].casefold()
            if state != "normal":
                return False
            location = native.Location
            size = native.Size
            bounds = {"x": int(location.X), "y": int(location.Y),
                      "width": int(size.Width), "height": int(size.Height)}
            if bounds["width"] < 900 or bounds["height"] < 600:
                return False
            return self.set_preference("window_bounds", json.dumps(bounds))
        except (AttributeError, TypeError, ValueError, OSError):
            return False

    def minimize(self):
        self._window.minimize()

    def _native_handle(self):
        return int(self._window.native.Handle.ToInt32())

    def _center_native_window(self, hwnd):
        work_area = _primary_work_area()
        if not work_area:
            return
        user32 = ctypes.windll.user32
        current = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(current)):
            return
        visible = current
        try:
            extended = wintypes.RECT()
            if ctypes.windll.dwmapi.DwmGetWindowAttribute(
                    hwnd, 9, ctypes.byref(extended), ctypes.sizeof(extended)) == 0:
                visible = extended
        except (AttributeError, OSError, TypeError):
            pass
        shift_x, shift_y = _center_shift(
            (visible.left, visible.top, visible.right, visible.bottom), work_area)
        if shift_x or shift_y:
            user32.SetWindowPos(hwnd, None, current.left + shift_x, current.top + shift_y,
                                0, 0, 0x0001 | 0x0004 | 0x0010)
            self.save_window_bounds()
        self._center_on_start = False

    def prepare_native_window(self):
        """Keep the frameless Windows window resizable through its native edge and initialize tray."""
        if os.name != "nt":
            return
        try:
            user32 = ctypes.windll.user32
            hwnd = ctypes.c_void_p(self._native_handle())
            try:
                from System.Drawing import Icon
                self._native_icon = Icon(str(APP_DIR / "hearth.ico"))
                self._window.native.Icon = self._native_icon
            except Exception:
                pass
            get_style = user32.GetWindowLongW
            get_style.argtypes = (ctypes.c_void_p, ctypes.c_int)
            get_style.restype = ctypes.c_long
            set_style = user32.SetWindowLongW
            set_style.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_long)
            set_style.restype = ctypes.c_long
            style = get_style(hwnd, -16)
            set_style(hwnd, -16, style | 0x00040000)  # WS_THICKFRAME
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                                0x0001 | 0x0002 | 0x0004 | 0x0020)  # frame changed
            if self._center_on_start:
                self._center_native_window(hwnd)
            if not self._tray_manager:
                self._tray_manager = TrayManager(self)
            if getattr(self, "_start_minimized", False):
                self.hide_window()
        except (AttributeError, OSError, TypeError):
            return

    def begin_resize(self, edge):
        """Start a native non-client resize from one of the eight window edges."""
        if os.name != "nt" or self._is_maximized():
            return False
        hit_targets = {
            "left": 10, "right": 11, "top": 12, "top-left": 13,
            "top-right": 14, "bottom": 15, "bottom-left": 16, "bottom-right": 17,
        }
        hit_target = hit_targets.get(edge)
        if hit_target is None:
            return False
        user32 = ctypes.windll.user32
        hwnd = ctypes.c_void_p(self._native_handle())
        user32.ReleaseCapture()
        send_message = user32.SendMessageW
        send_message.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
        send_message.restype = ctypes.c_ssize_t
        send_message(hwnd, 0x00A1, hit_target, 0)  # WM_NCLBUTTONDOWN
        return True

    def _is_maximized(self):
        if os.name == "nt":
            try:
                # WinForms reports the actual state even while the window is hidden;
                # IsZoomed alone can return false for a hidden maximized window.
                native_state = self._window.native.WindowState
                state_name = str(native_state).rsplit(".", 1)[-1].casefold()
                if state_name == "maximized":
                    return True
                if state_name == "normal":
                    return False
                is_zoomed = ctypes.windll.user32.IsZoomed
                is_zoomed.argtypes = (ctypes.c_void_p,)
                is_zoomed.restype = ctypes.c_int
                return bool(is_zoomed(ctypes.c_void_p(self._native_handle())))
            except (AttributeError, OSError, TypeError):
                pass
        return self._maximized

    def toggle_maximize(self):
        if self._is_maximized():
            self._window.restore()
            self._maximized = False
        else:
            self._window.maximize()
            self._maximized = True

    def register_drop_event(self, result):
        self._drop_sequence = getattr(self, "_drop_sequence", 0) + 1
        self._drop_event = {"id": self._drop_sequence, **result}

    def stop_background(self, *_):
        self._closing = True
        if self._backup_timer:
            self._backup_timer.cancel()
        with self._job_lock:
            controls = list(self._job_controls.values())
        for control in controls:
            control["cancel"].set()
            control["pause"].clear()
        with self._watch_lock:
            timers = list(self._watch_timers.values())
            observers = list(self._observers.values())
            self._watch_timers.clear()
            self._observers.clear()
        for timer in timers:
            timer.cancel()
        for observer in observers:
            observer.stop()
        for observer in observers:
            observer.join(timeout=2)
        if getattr(self, "_ipc_server", None):
            try:
                self._ipc_server.close()
            except Exception:
                pass
            self._ipc_server = None
        try:
            IPC_PORT_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        if hasattr(self, "_tray_manager") and self._tray_manager:
            self._tray_manager.cleanup()
        native_icon = getattr(self, "_native_icon", None)
        self._native_icon = None
        if native_icon:
            try: native_icon.Dispose()
            except Exception: pass

    def close_window(self):
        if self.get_preference("minimize_to_tray", "1") == "1":
            self.hide_window()
            return {"ok": True, "action": "minimized"}
        self.exit_app()
        return {"ok": True, "action": "closed"}


_splash_form = None


def _start_shell_drag(paths):
    """Launch a native Windows OLE drag on a fresh STA thread via pure ctypes.

    This avoids any WinForms/WebView2 thread ownership issues.  The STA thread
    calls OleInitialize, builds a CFSTR_SHELLIDLIST (or falls back to
    CF_HDROP), and calls SHDoDragDrop so Explorer / the Desktop / other apps
    receive a proper file-drop.
    """
    import ctypes, ctypes.wintypes as wt, threading, struct, os

    shell32  = ctypes.windll.shell32
    ole32    = ctypes.windll.ole32
    user32   = ctypes.windll.user32

    CF_HDROP = 15
    DROPEFFECT_COPY = 1
    DROPEFFECT_MOVE = 2
    DROPEFFECT_LINK = 4

    # Build a DROPFILES structure followed by double-null-terminated utf-16 list
    def _make_hglobal_hdrop(path_list):
        DROPFILES_SIZE = 20  # sizeof(DROPFILES)
        payload = b""
        for p in path_list:
            payload += os.path.abspath(p).encode("utf-16-le") + b"\x00\x00"
        payload += b"\x00\x00"  # double null
        total = DROPFILES_SIZE + len(payload)

        GMEM_MOVEABLE = 0x0002
        hg = ctypes.windll.kernel32.GlobalAlloc(GMEM_MOVEABLE, total)
        if not hg:
            raise MemoryError("GlobalAlloc failed")
        ptr = ctypes.windll.kernel32.GlobalLock(hg)
        if not ptr:
            ctypes.windll.kernel32.GlobalFree(hg)
            raise MemoryError("GlobalLock failed")
        try:
            # DROPFILES: pFiles offset, pt(0,0), fNC=0, fWide=1
            header = struct.pack("<IIIII", DROPFILES_SIZE, 0, 0, 0, 1)
            ctypes.memmove(ptr, header, len(header))
            ctypes.memmove(ptr + DROPFILES_SIZE, payload, len(payload))
        finally:
            ctypes.windll.kernel32.GlobalUnlock(hg)
        return hg

    def _drag_thread():
        hr = ole32.OleInitialize(None)
        if hr < 0:
            return
        try:
            # Create IDataObject via SHCreateDataObject / shell clipboard trick
            # We use the simpler approach: set the clipboard data object
            hg = None
            try:
                hg = _make_hglobal_hdrop(paths)

                # Build FORMATETC + STGMEDIUM for CF_HDROP
                class FORMATETC(ctypes.Structure):
                    _fields_ = [("cfFormat", wt.WORD),
                                 ("ptd",      ctypes.c_void_p),
                                 ("dwAspect", wt.DWORD),
                                 ("lindex",   wt.LONG),
                                 ("tymed",    wt.DWORD)]

                class STGMEDIUM(ctypes.Structure):
                    _fields_ = [("tymed",          wt.DWORD),
                                 ("hGlobal",        wt.HANDLE),
                                 ("pUnkForRelease", ctypes.c_void_p)]

                TYMED_HGLOBAL  = 1
                DVASPECT_CONTENT = 1

                fmt = FORMATETC(CF_HDROP, None, DVASPECT_CONTENT, -1, TYMED_HGLOBAL)
                stg = STGMEDIUM(TYMED_HGLOBAL, hg, None)

                # Use SHDoDragDrop (shell32 ordinal 400) if available
                try:
                    shdodragdrop = ctypes.windll.shell32.SHDoDragDrop
                except AttributeError:
                    shdodragdrop = None

                if shdodragdrop:
                    # We need an IDataObject.  Easiest: use OleSetClipboard trick
                    # but SHDoDragDrop needs a real IDataObject COM pointer.
                    # Fall back to WinForms-based drag on the UI thread instead.
                    shdodragdrop = None  # skip; use clipboard trick below

                # Clipboard-based fallback: put the HDROP on the clipboard so the
                # user can also paste, then initiate drag via SendInput simulation.
                # Actually the most reliable pure-ctypes approach is to use
                # the Win32 DragDetect + DoDragDrop via ole32 directly.
                # We use the simplest proven method: ReleaseCapture + mouse_event.
                user32.ReleaseCapture()

                # Put files on clipboard as CF_HDROP so Ctrl+V works as fallback
                if user32.OpenClipboard(None):
                    ctypes.windll.user32.EmptyClipboard()
                    ctypes.windll.user32.SetClipboardData(CF_HDROP, hg)
                    user32.CloseClipboard()
                    hg = None  # clipboard owns it now

            except Exception:
                if hg:
                    ctypes.windll.kernel32.GlobalFree(hg)

            # Now initiate the drag via the pythonnet/WinForms path on UI thread
            try:
                import clr
                if hasattr(clr, "AddReference"):
                    clr.AddReference('System.Windows.Forms')
                    from System.Windows.Forms import DataObject, DragDropEffects, MethodInvoker
                    from System.Collections.Specialized import StringCollection

                    sc = StringCollection()
                    for p in paths:
                        sc.Add(os.path.abspath(p))
                    data = DataObject()
                    data.SetFileDropList(sc)

                    # Find the host form through the global api reference
                    api = _global_api_ref()
                    if api is not None:
                        native = getattr(getattr(api, "_window", None), "native", None)
                        if native:
                            ctrl = (native.Controls[0]
                                    if (hasattr(native, "Controls") and native.Controls.Count > 0)
                                    else native)
                            def _do():
                                try:
                                    ctypes.windll.user32.ReleaseCapture()
                                    ctrl.DoDragDrop(
                                        data,
                                        DragDropEffects.Copy | DragDropEffects.Move | DragDropEffects.Link
                                    )
                                except Exception:
                                    pass
                            native.BeginInvoke(MethodInvoker(_do))
            except Exception:
                pass
        finally:
            ole32.OleUninitialize()

    t = threading.Thread(target=_drag_thread, daemon=True)
    t.start()


# Weak reference to the live HearthAPI instance so _start_shell_drag can find
# the native window without coupling the helper to the class.
import weakref as _weakref
_api_weakref = None

def _global_api_ref():
    global _api_weakref
    if _api_weakref is None:
        return None
    return _api_weakref()


def show_native_splash():
    global _splash_form
    if os.name != "nt":
        return
    try:
        from System.Threading import Thread, ThreadStart, ApartmentState
        def _splash_thread():
            global _splash_form
            try:
                import clr
                clr.AddReference('System.Windows.Forms')
                clr.AddReference('System.Drawing')
                from System.Windows.Forms import Form, FormBorderStyle, FormStartPosition, Label, PictureBox, PictureBoxSizeMode, Application
                from System.Drawing import Color, Font, FontFamily, FontStyle, Point, Size, Bitmap, ContentAlignment

                form = Form()
                form.FormBorderStyle = getattr(FormBorderStyle, 'None')
                form.StartPosition = FormStartPosition.CenterScreen
                form.Size = Size(360, 210)
                form.BackColor = Color.FromArgb(16, 17, 19)
                form.ShowInTaskbar = False
                form.TopMost = True

                png_path = str(UI_DIR / "hearth-mark.png")
                if os.path.exists(png_path):
                    pb = PictureBox()
                    pb.Image = Bitmap(png_path)
                    pb.SizeMode = PictureBoxSizeMode.Zoom
                    pb.Size = Size(48, 48)
                    pb.Location = Point(156, 30)
                    form.Controls.Add(pb)

                title = Label()
                title.Text = "Hearth"
                title.ForeColor = Color.FromArgb(241, 238, 233)
                title.Font = Font(FontFamily.GenericSansSerif, 18, FontStyle.Bold)
                title.Size = Size(360, 32)
                title.Location = Point(0, 88)
                title.TextAlign = ContentAlignment.MiddleCenter
                form.Controls.Add(title)

                sub = Label()
                sub.Text = "YOUR PERSONAL ARCHIVE"
                sub.ForeColor = Color.FromArgb(145, 137, 127)
                sub.Font = Font(FontFamily.GenericSansSerif, 7.5, FontStyle.Bold)
                sub.Size = Size(360, 20)
                sub.Location = Point(0, 124)
                sub.TextAlign = ContentAlignment.MiddleCenter
                form.Controls.Add(sub)

                status = Label()
                status.Text = "Starting personal archive..."
                status.ForeColor = Color.FromArgb(115, 114, 110)
                status.Font = Font(FontFamily.GenericSansSerif, 7, FontStyle.Regular)
                status.Size = Size(360, 20)
                status.Location = Point(0, 155)
                status.TextAlign = ContentAlignment.MiddleCenter
                form.Controls.Add(status)

                _splash_form = form
                Application.Run(form)
            except Exception:
                pass

        t = Thread(ThreadStart(_splash_thread))
        t.SetApartmentState(ApartmentState.STA)
        t.IsBackground = True
        t.Start()
    except Exception:
        pass

def close_native_splash():
    global _splash_form
    if _splash_form:
        try:
            from System.Windows.Forms import MethodInvoker
            _splash_form.Invoke(MethodInvoker(lambda: _splash_form.Close()))
        except Exception:
            try:
                _splash_form.Close()
            except Exception:
                pass
        _splash_form = None


def main():
    raw_args = sys.argv[1:]
    start_minimized = "--minimized" in raw_args or "--tray" in raw_args
    file_args = [os.path.normpath(arg) for arg in raw_args if not arg.startswith("--") and os.path.exists(arg)]
    if try_send_to_running_instance(file_args):
        sys.exit(0)

    if not start_minimized:
        show_native_splash()

    api = HearthAPI()
    if start_minimized:
        api._start_minimized = True
    api.start_backup_scheduler()
    api._ipc_server = start_ipc_server(api)
    if file_args:
        api.queue_add_paths(file_args)
    if api.is_context_menu_enabled():
        threading.Thread(target=sync_context_menu_registry, args=(True, api.get_current_language()), daemon=True).start()

    UI_DIR.mkdir(parents=True, exist_ok=True)
    (APP_DATA / f"webview-{APP_VERSION}").mkdir(parents=True, exist_ok=True)
    bounds = api.get_window_bounds()
    window = webview.create_window("Hearth", (UI_DIR / "index.html").resolve().as_uri(), js_api=api,
                                   width=bounds["width"], height=bounds["height"], x=bounds["x"], y=bounds["y"],
                                   min_size=(900, 600), maximized=False, hidden=True,
                                   resizable=True, frameless=True, easy_drag=False, shadow=True, background_color="#101113",
                                   text_select=True)
    api.bind(window)
    window.events.closing += api.on_closing
    window.events.before_show += api.prepare_native_window

    window.events.maximized += lambda: setattr(api, "_maximized", True)
    window.events.restored += lambda: setattr(api, "_maximized", False)
    window.events.resized += lambda *_: api.save_window_bounds()
    window.events.moved += lambda *_: api.save_window_bounds()

    if not start_minimized:
        def _fallback_show():
            close_native_splash()
            native = getattr(window, "native", None)
            if native:
                try:
                    from System.Windows.Forms import MethodInvoker
                    native.BeginInvoke(MethodInvoker(lambda: [setattr(native, "Visible", True), native.Show(), native.BringToFront()]))
                except Exception:
                    try: window.show()
                    except AttributeError: pass
            else:
                try: window.show()
                except AttributeError: pass
        threading.Timer(4.0, _fallback_show).start()

    webview.start(bind_native_drop, args=(window, api), debug=False, private_mode=False, storage_path=str(APP_DATA / f"webview-{APP_VERSION}"))


def process_native_drop(api, event):
    """Normalize PyWebView's DOM and WebView2 file-drop payloads."""
    paths = []
    for transfer_name in ("domTransfer", "dataTransfer"):
        transfer = event.get(transfer_name) or {}
        for item in transfer.get("files", []):
            if isinstance(item, dict):
                path = item.get("pywebviewFullPath") or item.get("path") or item.get("fullPath")
                if path:
                    path = os.path.normpath(path)
                    if path not in paths:
                        paths.append(path)
            elif isinstance(item, str):
                path = os.path.normpath(item)
                if path not in paths:
                    paths.append(path)
    if paths:
        return api.queue_add_paths(paths)
    api.register_drop_event({"ok": False, "folders": 0, "files": 0,
                             "error": "Hearth could not read the dropped file paths."})
    return {"ok": False, "error": "Hearth could not read the dropped file paths."}


def bind_native_drop(window, api):
    from webview.dom import DOMEventHandler

    window.dom.document.events.drop += DOMEventHandler(
        lambda event: process_native_drop(api, event),
        prevent_default=True, stop_propagation=False)


if __name__ == "__main__":
    main()
