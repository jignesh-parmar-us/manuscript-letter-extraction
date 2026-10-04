"""C5d: the app launcher (settings, library folder) and the app endpoints that serve the screen."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.main import (AppContext, free_port, library_dir, load_settings,   # noqa: E402
                                       save_settings)

TOKEN = "tok"
H = {"X-Token": TOKEN}


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.settings = self.tmp / "conf" / "settings.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_settings_round_trip(self):
        self.assertEqual(load_settings(self.settings), {})
        save_settings({"library": "/a"}, self.settings)
        save_settings({"other": 1}, self.settings)
        self.assertEqual(load_settings(self.settings), {"library": "/a", "other": 1})
        self.settings.write_text("not json", encoding="utf-8")
        self.assertEqual(load_settings(self.settings), {}, "a broken settings file is ignored")

    def test_library_folder_choice(self):
        from letter_extractor.app.library import default_library_dir
        self.assertEqual(library_dir(None, self.settings), default_library_dir())
        save_settings({"library": str(self.tmp / "remembered")}, self.settings)
        self.assertEqual(library_dir(None, self.settings), self.tmp / "remembered")
        self.assertEqual(library_dir(str(self.tmp / "given"), self.settings), self.tmp / "given")

    def test_free_port(self):
        port = free_port()
        self.assertTrue(1024 < port < 65536)


class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, self.pages = appbook.fresh_copy()
        self.static = self.tmp / "static"
        (self.static / "assets").mkdir(parents=True)
        (self.static / "index.html").write_text("<html><head><title>x</title></head><body></body></html>",
                                                encoding="utf-8")
        (self.static / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
        self.context = AppContext(mode="browser", settings_file=self.tmp / "settings.json", static_dir=self.static)
        self.client = TestClient(create_app(self.lib, TOKEN, context=self.context))

    def tearDown(self):
        self.client.close()
        appbook.cleanup(self.tmp, self.lib)

    def test_screen_has_the_token_and_assets_are_served(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn('window.__TOKEN__ = "tok";</script></head>', r.text)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(self.client.get("/assets/app.js").status_code, 200)

    def test_missing_screen_says_how_to_build_it(self):
        empty = AppContext(static_dir=self.tmp / "nothing")
        r = TestClient(create_app(self.lib, TOKEN, context=empty)).get("/")
        self.assertEqual(r.status_code, 503)
        self.assertIn("npm run build", r.text)

    def test_app_info_and_folder_dialog(self):
        info = self.client.get("/api/app", headers=H).json()
        self.assertEqual((info["mode"], info["can_pick_folder"]), ("browser", False))
        self.assertEqual(info["library"], str(self.lib.root))
        self.assertEqual(self.client.post("/api/app/pick-folder", headers=H).status_code, 501)
        self.context.mode, self.context.pick_folder = "window", (lambda: "/chosen")
        self.assertEqual(self.client.post("/api/app/pick-folder", headers=H).json(), {"path": "/chosen"})
        self.assertTrue(self.client.get("/api/app", headers=H).json()["can_pick_folder"])

    def test_choose_library_is_remembered(self):
        r = self.client.post("/api/app/library", headers=H, json={"path": str(self.tmp / "other")}).json()
        self.assertTrue(r["restart_needed"])
        self.assertEqual(json.loads((self.tmp / "settings.json").read_text())["library"], str(self.tmp / "other"))
        same = self.client.post("/api/app/library", headers=H, json={"path": str(self.lib.root)}).json()
        self.assertFalse(same["restart_needed"])
        (self.tmp / "file.txt").write_text("x")
        self.assertEqual(self.client.post("/api/app/library", headers=H, json={"path": str(self.tmp / "file.txt")})
                         .status_code, 400)

    def test_book_settings(self):
        r = self.client.patch(f"/api/books/{self.book}/settings", headers=H,
                              json={"settings": {"group_distance": 0.6, "red": {"min_break_px": 3}}})
        s = r.json()["settings"]
        self.assertEqual((s["group_distance"], s["red"]["min_break_px"], s["digits"]), (0.6, 3, "gujarati"))
        bad = self.client.patch(f"/api/books/{self.book}/settings", headers=H, json={"settings": {"nope": 1}})
        self.assertEqual(bad.status_code, 400)
        back = self.client.patch(f"/api/books/{self.book}/settings", headers=H, json={"settings": None}).json()
        self.assertEqual(back["settings"]["group_distance"], 0.55)

    def test_app_endpoints_need_the_token(self):
        for method, url in (("get", "/api/app"), ("post", "/api/app/pick-folder"),
                            ("post", "/api/app/library")):
            self.assertEqual(getattr(self.client, method)(url).status_code, 401, url)


if __name__ == "__main__":
    unittest.main()
