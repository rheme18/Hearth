from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

SANDBOX = tempfile.TemporaryDirectory(prefix="hearth-tests-")
os.environ["LOCALAPPDATA"] = SANDBOX.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


class FakeWindow:
    def __init__(self):
        self.selected = None
    def create_file_dialog(self, *args, **kwargs):
        return self.selected


class HearthFlows(unittest.TestCase):
    def setUp(self):
        if hasattr(self, "api"):
            self.api._library.db.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(main.DB_PATH) + suffix).unlink(missing_ok=True)
        self.api = main.HearthAPI()
        self.temp = tempfile.TemporaryDirectory(prefix="hearth-fixture-")
        self.root = Path(self.temp.name)
        self.window = FakeWindow()
        self.api.bind(self.window)

    def tearDown(self):
        for root in list(self.api._observers):
            self.api._stop_watcher(root)
        self.api._library.db.close()
        self.temp.cleanup()

    def make_file(self, name, data=b"plain content"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def add(self, *paths):
        result = self.api.add_dropped_paths([str(p) for p in paths])
        self.assertTrue(result.get("ok"), result)
        return result

    def test_private_file_memory_notes_are_searchable_and_follow_renames(self):
        path = self.make_file("field-notes.txt", b"original source text")
        self.add(path)
        note = "Keep for the cedar cabin renovation"
        saved = self.api.save_file_note(str(path), note)
        self.assertEqual(saved, {"ok": True, "note": note})
        self.assertEqual(self.api.count_matching_files(query="cedar renovation"), 1)
        self.assertEqual(self.api.preview(str(path))["note"], note)
        renamed = path.with_name("cabin-reference.txt")
        self.assertTrue(self.api.rename_file(str(path), renamed.name)["ok"])
        self.assertEqual(self.api.count_matching_files(query="cedar"), 1)
        self.assertEqual(self.api.preview(str(renamed))["note"], note)
        self.assertFalse(self.api.save_file_note(str(renamed), "x" * 5001)["ok"])
        self.assertEqual(self.api.save_file_note(str(renamed), "")["note"], "")
        self.assertEqual(self.api.count_matching_files(query="cedar"), 0)

    def test_add_search_filters_pagination_favorites_tags_saved_and_smart(self):
        a = self.make_file("Receipts/tax.txt", b"annual tax receipt")
        b = self.make_file("Receipts/other.txt", b"ordinary memo")
        c = self.make_file("Photos/picture.png", b"fake image")
        self.add(a, b, c)
        self.assertEqual(self.api.count_matching_files(query="tax tag:tax"), 0)
        self.assertEqual(len(self.api.list_files(query="type:txt folder:Receipts")), 2)  # loose files are indexed immediately
        self.api.add_folders([str(self.root)])
        self.assertEqual(self.api.count_matching_files(query="type:txt folder:Receipts"), 2)
        self.assertEqual(self.api.count_matching_files(query="type:txt,png"), 3)
        self.assertEqual(self.api.count_matching_files(query="after:not-a-date"), 0)
        combined = {"extensions": ["txt", ".png"], "date_from": "2000-01-01", "date_to": "2099-01-01",
                    "min_mb": 0, "max_mb": 1, "folder": str(self.root)}
        self.assertEqual(self.api.count_matching_files(filters=combined), 3)
        self.assertEqual(len(self.api.list_files(limit=1, offset=0)), 1)
        self.assertEqual(len(self.api.list_files(limit=1, offset=1)), 1)
        self.assertEqual(self.api.toggle_favorite(str(a))["is_favorite"], True)
        tagged = self.api.set_file_tags(str(a), ["tax"])
        self.assertTrue(tagged.get("ok"), tagged)
        self.assertEqual(self.api.count_matching_files(query="tag:tax"), 1)
        saved = self.api.save_search("Tax receipts", "tag:tax", "Everything", {})
        self.assertTrue(saved.get("ok"), saved)
        smart = self.api.save_smart_collection("Text files", "type:txt", "Everything", {})
        self.assertTrue(smart.get("ok"), smart)
        smart_row = next(x for x in self.api._library.collections() if x.get("kind") == "smart")
        self.assertEqual(smart_row["count"], 2)
        self.assertEqual(self.api.count_matching_files(category="Favorites"), 1)

    def test_office_text_duplicate_review_and_reversible_delete(self):
        a = self.make_file("one.txt", b"same bytes")
        b = self.make_file("sub/two.txt", b"same bytes")
        self.add(a, b)
        self.assertEqual(self.api.find_duplicates()["group_count"], 1)
        deleted = self.api.delete_duplicate_copies([str(a), str(b)], str(a))
        self.assertTrue(deleted.get("ok"), deleted)
        self.assertTrue(a.exists())
        self.assertFalse(b.exists())
        self.assertTrue(self.api.undo_last().get("ok"))
        self.assertTrue(b.exists())
        docx = self.make_file("notes.docx")
        with zipfile.ZipFile(docx, "w") as z:
            z.writestr("word/document.xml", '<w:document xmlns:w="urn:w"><w:body><w:p><w:r><w:t>private phrase</w:t></w:r></w:p></w:body></w:document>')
        self.add(docx)
        preview = self.api.preview(str(docx))
        self.assertTrue(preview["ok"])
        self.assertIn("private phrase", preview["content"])
        self.assertEqual(self.api.count_matching_files(query="private phrase"), 1)
        xlsx = self.make_file("table.xlsx")
        with zipfile.ZipFile(xlsx, "w") as z:
            z.writestr("xl/sharedStrings.xml", '<sst xmlns="urn:x"><si><t>spreadsheet phrase</t></si></sst>')
            z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="urn:x"><sheetData><row><c t="s"><v>0</v></c></row></sheetData></worksheet>')
        pptx = self.make_file("slides.pptx")
        with zipfile.ZipFile(pptx, "w") as z:
            z.writestr("ppt/slides/slide1.xml", '<p:sld xmlns:p="urn:p" xmlns:a="urn:a"><a:t>presentation phrase</a:t></p:sld>')
        self.add(xlsx, pptx)
        self.assertEqual(self.api.count_matching_files(query="spreadsheet phrase"), 1)
        self.assertEqual(self.api.count_matching_files(query="presentation phrase"), 1)

    def test_pdf_tools_outputs_and_rotation_editor(self):
        p = self.root / "source.pdf"
        writer = main.PdfWriter()
        for width in (300, 310, 320):
            writer.add_blank_page(width=width, height=400)
        with p.open("wb") as f:
            writer.write(f)
        self.add(p)
        output = self.root / "out"
        output.mkdir()
        result = self.api.start_pdf_tool([str(p)], "extract", "1,3", 90, str(output))
        self.assertTrue(result["ok"], result)
        job = self.wait_job(result["job_id"])
        self.assertEqual(job["status"], "completed", job)
        extracted = Path(job["outputs"][0])
        self.assertEqual(len(main.PdfReader(extracted).pages), 2)
        operations = [("split", "1-2,3", 2), ("delete-pages", "2", 1), ("reorder", "3,2,1", 1), ("rotate", "", 1), ("optimize", "", 1)]
        for operation, ranges, expected in operations:
            started = self.api.start_pdf_tool([str(p)], operation, ranges, 90, str(output))
            self.assertTrue(started["ok"], started)
            done = self.wait_job(started["job_id"])
            self.assertEqual(done["status"], "completed", done)
            if operation == "split":
                counts = sorted(len(main.PdfReader(path).pages) for path in done["outputs"])
                self.assertEqual(counts, [1, 2])
            else:
                self.assertEqual(len(main.PdfReader(done["outputs"][0]).pages), 2 if operation == "delete-pages" else 3)
                if operation == "reorder":
                    self.assertEqual(float(main.PdfReader(done["outputs"][0]).pages[0].mediabox.width), 320)
                if operation == "rotate":
                    self.assertEqual(main.PdfReader(done["outputs"][0]).pages[0].get("/Rotate"), 90)
        other = self.root / "second.pdf"
        second = main.PdfWriter(); second.add_blank_page(width=300, height=400)
        with other.open("wb") as f: second.write(f)
        merged = self.api.start_pdf_tool([str(p), str(other)], "merge", output_directory=str(output))
        self.assertTrue(merged["ok"], merged)
        merged_job = self.wait_job(merged["job_id"])
        self.assertEqual(merged_job["status"], "completed", merged_job)
        self.assertEqual(len(main.PdfReader(merged_job["outputs"][0]).pages), 4)
        rotated = self.api.rotate_pdf_page_copy(str(p), 1, 90)
        self.assertTrue(rotated["ok"], rotated)
        self.assertNotEqual(rotated["path"], str(p))
        self.assertEqual(len(main.PdfReader(rotated["path"]).pages), 3)

    def test_image_conversion_backup_restore_and_bad_manifest(self):
        from PIL import Image
        src = self.root / "pixel.png"
        Image.new("RGBA", (8, 8), (255, 0, 0, 120)).save(src)
        out = self.root / "converted"
        out.mkdir()
        result = self.api.start_image_conversion([str(src)], "jpeg", 85, str(out))
        self.assertTrue(result["ok"], result)
        job = self.wait_job(result["job_id"])
        self.assertEqual(job["status"], "completed", job)
        with Image.open(job["outputs"][0]) as converted:
            self.assertEqual(converted.format, "JPEG")
        for image_format, expected_format in (("png", "PNG"), ("webp", "WEBP"), ("tiff", "TIFF"), ("bmp", "BMP")):
            converted = self.api.start_image_conversion([str(src)], image_format, 88, str(out))
            self.assertTrue(converted["ok"], converted)
            converted_job = self.wait_job(converted["job_id"])
            self.assertEqual(converted_job["status"], "completed", converted_job)
            with Image.open(converted_job["outputs"][0]) as result_image:
                self.assertEqual(result_image.format, expected_format)
        animated = self.root / "animated.gif"
        first = Image.new("RGB", (4, 4), "red"); second = Image.new("RGB", (4, 4), "blue")
        first.save(animated, save_all=True, append_images=[second], duration=100, loop=0)
        skipped = self.api.start_image_conversion([str(animated)], "png", 88, str(out))
        skipped_job = self.wait_job(skipped["job_id"])
        self.assertEqual(skipped_job["status"], "failed")
        self.assertTrue(animated.exists())
        self.add(src)
        backup = self.root / "good.zip"
        self.window.selected = str(backup)
        self.assertTrue(self.api.save_backup()["ok"])
        self.make_file("extra.txt")
        self.add(self.root / "extra.txt")
        self.window.selected = str(backup)
        restored = self.api.restore_backup()
        self.assertTrue(restored.get("ok"), restored)
        self.assertTrue(Path(restored["safety_copy"]).exists())
        bad = self.root / "bad.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("library.sqlite3", b"not sqlite")
            z.writestr("manifest.json", "[]")
        self.window.selected = str(bad)
        rejected = self.api.restore_backup()
        self.assertFalse(rejected.get("ok"))

    def test_batch_file_and_metadata_operations_undo_together(self):
        first = self.make_file("batch-a.txt", b"alpha")
        second = self.make_file("batch-b.txt", b"beta")
        self.add(first, second)
        paths = [str(first), str(second)]
        self.assertEqual(self.api.bulk_action(paths, "favorite")["completed"], 2)
        collection = self.api.create_collection("Batch set")["collections"][0]
        self.assertEqual(self.api.bulk_action(paths, "collection", collection["id"])["completed"], 2)
        self.assertTrue(self.api.undo_last()["ok"])
        self.assertEqual(self.api._library.collections()[0]["count"], 0)
        self.assertEqual(self.api.bulk_action(paths, "tag", ["batch"])["completed"], 2)
        renamed = self.api.bulk_action(paths, "rename", "Batch")
        self.assertEqual(renamed["completed"], 2)
        renamed_paths = [str(self.root / "Batch - batch-a.txt"), str(self.root / "Batch - batch-b.txt")]
        self.assertTrue(all(Path(p).exists() for p in renamed_paths))
        self.assertTrue(self.api.undo_last()["ok"])
        self.assertTrue(all(Path(p).exists() for p in paths))
        copy_dir = self.root / "copies"; copy_dir.mkdir()
        self.window.selected = [str(copy_dir)]
        self.assertEqual(self.api.bulk_action(paths, "copy")["completed"], 2)
        self.assertTrue((copy_dir / "batch-a.txt").exists())
        self.assertTrue(self.api.undo_last()["ok"])
        self.assertFalse((copy_dir / "batch-a.txt").exists())
        move_dir = self.root / "moved"; move_dir.mkdir()
        self.window.selected = [str(move_dir)]
        self.assertEqual(self.api.bulk_action(paths, "move")["completed"], 2)
        self.assertTrue((move_dir / "batch-a.txt").exists())
        self.assertTrue(self.api.undo_last()["ok"])
        self.assertTrue(first.exists() and second.exists())
        self.assertEqual(self.api.bulk_action(paths, "delete")["completed"], 2)
        self.assertTrue(self.api.undo_last()["ok"])
        self.assertTrue(first.exists() and second.exists())

    def test_connected_folder_watcher_indexes_changes_and_removals(self):
        root = self.root / "watched"
        root.mkdir()
        initial = root / "initial.txt"
        initial.write_text("first", encoding="utf-8")
        added = self.api.add_folders([str(root)])
        self.assertEqual(len(added["added"]), 1)
        self.wait_for(lambda: self.api.count_matching_files() == 1)
        changed = root / "later.txt"
        changed.write_text("watcher phrase", encoding="utf-8")
        self.wait_for(lambda: self.api.count_matching_files(query="watcher phrase") == 1)
        changed.unlink()
        self.wait_for(lambda: self.api.count_matching_files() == 1)

    def test_tags_can_be_renamed_and_deleted_across_library(self):
        path = self.make_file("tagged.txt")
        self.add(path)
        self.assertTrue(self.api.set_file_tags(str(path), ["old-tag"])["ok"])
        tag = self.api.list_tags()[0]
        renamed = self.api.rename_tag(tag["id"], "new-tag")
        self.assertTrue(renamed["ok"], renamed)
        self.assertEqual(self.api._library.tags_for_file(str(path))[0]["name"], "new-tag")
        self.assertTrue(self.api.delete_tag(tag["id"])["ok"])
        self.assertEqual(self.api._library.tags_for_file(str(path)), [])

    def test_undo_retention_is_configurable_and_bounded(self):
        a = self.make_file("retain-a.txt")
        b = self.make_file("retain-b.txt")
        self.add(a, b)
        self.assertTrue(self.api.save_undo_options({"limit": 1, "days": 7})["ok"])
        self.api.toggle_favorite(str(a))
        self.api.toggle_favorite(str(b))
        with self.api._library.lock:
            count = self.api._library.db.execute("SELECT COUNT(*) FROM undo_ops").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(self.api.get_state()["undo_options"], {"limit": 1, "days": 7})
        self.assertEqual(self.api.save_undo_options({"limit": 99999, "days": 0})["options"], {"limit": 5000, "days": 1})

    def test_opt_in_scheduled_backup_creates_local_verified_archive(self):
        folder = self.root / "scheduled"
        folder.mkdir()
        self.assertEqual(self.api.get_backup_options()["schedule"], "off")
        self.assertFalse(self.api.save_backup_options({"schedule": "daily", "directory": ""})["ok"])
        saved = self.api.save_backup_options({"schedule": "daily", "directory": str(folder)})
        self.assertTrue(saved["ok"], saved)
        self.api.set_preference("backup_schedule_started", str(time.time() - 2 * 86400))
        self.api._schedule_backup_check = lambda delay: None
        self.api._run_scheduled_backup()
        archives = list(folder.glob("Hearth-auto-*.zip"))
        self.assertEqual(len(archives), 1)
        with zipfile.ZipFile(archives[0]) as archive:
            self.assertIn("library.sqlite3", archive.namelist())
            self.assertIn("manifest.json", archive.namelist())
        self.assertGreater(self.api.get_diagnostics()["health"]["last_backup_time"], 0)
        self.assertTrue(self.api.save_backup_options({"schedule": "off", "directory": ""})["ok"])

    def test_diagnostic_export_omits_paths_and_file_content(self):
        private = self.make_file("private-name.txt", b"secret extracted words")
        self.add(private)
        target = self.root / "diagnostics.json"
        self.window.selected = str(target)
        exported = self.api.export_diagnostics()
        self.assertTrue(exported["ok"], exported)
        report = target.read_text(encoding="utf-8")
        self.assertNotIn(str(private), report)
        self.assertNotIn("secret extracted words", report)
        self.assertNotIn(str(main.APP_DATA), report)

    def test_first_launch_window_is_centered_normal_size_and_resizable(self):
        self.assertEqual(main._center_shift((508, 188, 1400, 782), (0, 0, 1920, 1040)), (6, 35))
        class Event:
            def __iadd__(self, callback):
                return self
        class Events:
            before_show = Event(); closing = Event(); maximized = Event(); restored = Event(); resized = Event(); moved = Event()
        class Window:
            events = Events()
        captured = {}
        original_create, original_start = main.webview.create_window, main.webview.start
        original_work_area = main._primary_work_area
        captured_api = []
        def create(*args, **kwargs):
            captured.update(kwargs); captured_api.append(kwargs["js_api"])
            return Window()
        main.webview.create_window = create
        main.webview.start = lambda *args, **kwargs: None
        main._primary_work_area = lambda: (0, 0, 1440, 900)
        try:
            main.main()
            self.assertEqual((captured["width"], captured["height"]), (920, 612))
            self.assertEqual((captured["x"], captured["y"]), (260, 144))
            self.assertFalse(captured["maximized"])
            self.assertTrue(captured["resizable"])
            api = captured_api[0]
        finally:
            main.webview.create_window, main.webview.start = original_create, original_start
            main._primary_work_area = original_work_area
        api.stop_background(); api._library.db.close()

    def test_mixed_explorer_drop_payload_keeps_all_items(self):
        folder = self.root / "dropped-folder"
        folder.mkdir()
        loose = self.root / "loose.txt"
        loose.write_text("drop", encoding="utf-8")
        captured = []
        self.api.queue_add_paths = lambda paths: captured.extend(paths) or {"ok": True}
        event = {"domTransfer": {"files": [
            {"pywebviewFullPath": str(folder)},
            {"path": str(loose)},
        ]}}
        result = main.process_native_drop(self.api, event)
        self.assertTrue(result["ok"])
        self.assertEqual(set(captured), {str(folder), str(loose)})

    def test_dropping_a_loose_file_indexes_it_in_everything(self):
        loose = self.make_file("single-drop.txt", b"file drop reaches the all files library")
        result = self.api._library.add_dropped_paths([str(loose)])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["folders"], 0)
        self.assertEqual(result["files"], 1)
        self.assertEqual(result["file_paths"], [str(loose)])
        self.assertEqual(self.api.count_matching_files(query="file drop"), 1)

    def test_window_defaults_and_settings_validation(self):
        original_work_area = main._primary_work_area
        main._primary_work_area = lambda: (10, 20, 1450, 920)
        try:
            bounds = self.api.get_window_bounds()
        finally:
            main._primary_work_area = original_work_area
        self.assertEqual(bounds, {"width": 920, "height": 612, "x": 270, "y": 164})
        bad = self.api.save_indexing_options({"excluded_extensions": ["../bad"], "excluded_paths": [], "max_content_mb": 60})
        self.assertFalse(bad["ok"])
        saved = self.api.save_indexing_options({"excluded_extensions": ["tmp"], "excluded_paths": [], "max_content_mb": 4})
        self.assertTrue(saved["ok"], saved)
        self.assertEqual(saved["options"]["excluded_extensions"], [".tmp"])

    def test_system_options_tray_and_intro_state(self):
        state = self.api.get_state()
        self.assertIn("has_seen_intro", state)
        self.assertFalse(state["has_seen_intro"])
        self.assertIn("system_options", state)
        self.assertTrue(state["system_options"]["minimize_to_tray"])

        # Test setting has_seen_intro
        self.api.set_preference("has_seen_intro", "1")
        self.assertTrue(self.api.get_state()["has_seen_intro"])

        # Test toggling minimize to tray
        res = self.api.set_system_option("minimize_to_tray", False)
        self.assertTrue(res["ok"])
        self.assertFalse(self.api.get_system_options()["minimize_to_tray"])

        # Test close_window behavior
        # When minimize_to_tray is False:
        close_res = self.api.close_window()
        self.assertEqual(close_res.get("action"), "closed")

        # When minimize_to_tray is True:
        self.api.set_system_option("minimize_to_tray", True)
        close_res2 = self.api.close_window()
        self.assertEqual(close_res2.get("action"), "minimized")

    def test_language_and_context_menu_settings(self):
        self.api.set_preference("language", "tr")
        self.assertEqual(self.api.get_current_language(), "tr")
        self.api.set_preference("language", "en")
        self.assertEqual(self.api.get_current_language(), "en")

        res = self.api.set_system_option("context_menu_enabled", True)
        self.assertTrue(res["ok"])
        self.assertTrue(self.api.is_context_menu_enabled())

    def test_on_this_day_and_file_compare_and_version(self):
        self.assertEqual(main.APP_VERSION, "0.4.3")
        a = self.make_file("doc1.txt", b"First document line")
        b = self.make_file("doc2.txt", b"First document line")
        c = self.make_file("doc3.txt", b"Different content")
        self.add(a, b, c)

        # Test compare identical files
        comp1 = self.api.compare_files(str(a), str(b))
        self.assertTrue(comp1["ok"])
        self.assertTrue(comp1["is_identical"])
        self.assertEqual(comp1["file1"]["size"], comp1["file2"]["size"])

        # Test compare different files
        comp2 = self.api.compare_files(str(a), str(c))
        self.assertTrue(comp2["ok"])
        self.assertFalse(comp2["is_identical"])

        # Test On This Day
        otd = self.api.get_on_this_day_files()
        self.assertIsInstance(otd, list)
        state = self.api.get_state()
        self.assertIn("on_this_day_count", state)
        self.assertIn("is_portable", state)

    def test_start_drag_and_clipboard(self):
        # Empty paths
        res_empty = self.api.start_drag([])
        self.assertFalse(res_empty["ok"])

        # Nonexistent paths
        res_none = self.api.start_drag(["nonexistent_path_xyz_123.txt"])
        self.assertFalse(res_none["ok"])

        # Valid file
        f = self.make_file("drag_test.txt", b"Drag test payload")
        res_drag = self.api.start_drag([str(f)])
        self.assertTrue(res_drag["ok"])
        self.assertEqual(res_drag["count"], 1)

        # Single string path
        res_single = self.api.start_drag(str(f))
        self.assertTrue(res_single["ok"])

        # Native clipboard copy
        res_clip = self.api.copy_to_clipboard(str(f))
        self.assertTrue(res_clip["ok"])

        # Export to desktop
        res_exp = self.api.export_to_desktop([str(f)])
        self.assertTrue(res_exp["ok"])
        self.assertEqual(res_exp["count"], 1)

        # Window ready
        res_ready = self.api.window_ready()
        self.assertTrue(res_ready["ok"])

    def wait_for(self, predicate, timeout=8):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return
            time.sleep(.05)
        self.fail("Timed out waiting for the expected file-system update")

    def wait_job(self, job_id, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.api.get_job_status(job_id)
            if job["status"] not in ("running", "cancelling"):
                return job
            time.sleep(.03)
        self.fail("Background job did not finish")


if __name__ == "__main__":
    unittest.main()

