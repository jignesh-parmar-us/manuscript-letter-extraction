"""C5c: the backend API, through FastAPI's test client."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402

TOKEN = "test-token"
H = {"X-Token": TOKEN}


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, self.pages = appbook.fresh_copy()
        self.client = TestClient(create_app(self.lib, TOKEN))

    def tearDown(self):
        self.client.close()
        appbook.cleanup(self.tmp, self.lib)

    def get(self, url, **kw):
        r = self.client.get(url, headers=H, **kw)
        return r

    def post(self, url, json=None):
        return self.client.post(url, headers=H, json=json)

    def wait(self, job, timeout=120):
        t0 = time.time()
        while job["status"] == "running":
            self.assertLess(time.time() - t0, timeout, "job did not finish")
            time.sleep(0.2)
            job = self.get(f"/api/jobs/{job['id']}").json()
        return job

    def groups(self):
        return self.get(f"/api/books/{self.book}/groups").json()


class AuthAndFilesTests(ApiTestCase):
    def test_token_is_required(self):
        self.assertEqual(self.client.get("/api/books").status_code, 401)
        self.assertEqual(self.client.get("/api/books", headers={"X-Token": "wrong"}).status_code, 401)
        self.assertEqual(self.get("/api/books").status_code, 200)
        self.assertEqual(self.client.get(f"/api/books?token={TOKEN}").status_code, 200)
        self.assertEqual(self.client.get("/api/version").status_code, 200)

    def test_letter_line_and_page_images(self):
        g = self.groups()[0]
        samples = self.get(f"/api/groups/{g['id']}/samples").json()["samples"]
        img = self.client.get(samples[0]["image"])            # the URL carries the token
        self.assertEqual((img.status_code, img.headers["content-type"]), (200, "image/png"))
        page = self.get(f"/api/books/{self.book}/pages").json()[0]
        self.assertEqual(self.client.get(page["image"]).status_code, 200)
        detail = self.get(f"/api/pages/{page['id']}").json()
        self.assertEqual(self.client.get(detail["lines"][0]["image"]).status_code, 200)
        self.assertEqual(self.client.get(samples[0]["image"].split("?")[0]).status_code, 401)
        files = {p["id"]: p["file"] for p in self.get(f"/api/books/{self.book}/pages").json()}
        self.assertTrue(all(x["page_file"] == files[x["page_id"]] for x in samples), "page name for the hover text")

    def test_no_files_outside_the_book(self):
        for path in ("../../library.db", "..%2F..%2Flibrary.db", "report.csv", "letters/p1/nothing.png"):
            self.assertEqual(self.get(f"/files/books/{self.book}/{path}").status_code, 404, path)
        self.assertEqual(self.get("/files/pages/99999").status_code, 404)


class BookTests(ApiTestCase):
    def test_books_crud(self):
        books = self.get("/api/books").json()
        self.assertEqual([b["name"] for b in books], ["Synthetic"])
        r = self.post("/api/books", {"name": "ગુજરાતી પોથી", "input_dir": str(self.pages)})
        self.assertEqual(r.status_code, 201)
        new = r.json()
        self.assertEqual(new["settings"]["group_distance"], 0.55)
        self.assertEqual(self.post("/api/books", {"name": "x", "input_dir": "/no/such/dir"}).status_code, 400)
        self.assertEqual(self.post("/api/books", {"name": "Synthetic", "input_dir": str(self.pages)}).status_code, 400)
        r = self.client.patch(f"/api/books/{new['id']}", headers=H, json={"name": "Renamed"})
        self.assertEqual(r.json()["name"], "Renamed")
        self.assertEqual(self.client.delete(f"/api/books/{new['id']}", headers=H).status_code, 204)
        self.assertEqual(self.get(f"/api/books/{new['id']}").status_code, 404)

    def test_writing(self):
        self.assertEqual(self.get(f"/api/books/{self.book}").json()["writing"], "handwritten")
        r = self.post("/api/books", {"name": "Print", "input_dir": str(self.pages), "writing": "printed"})
        self.assertEqual(r.json()["writing"], "printed")
        self.assertEqual(self.post("/api/books", {"name": "Bad", "input_dir": str(self.pages),
                                                  "writing": "typed"}).status_code, 422)
        r = self.client.patch(f"/api/books/{self.book}", headers=H, json={"writing": "printed"})
        self.assertEqual((r.json()["writing"], r.json()["name"]), ("printed", "Synthetic"))
        self.assertEqual(self.get("/api/books").json()[0]["writing"], "printed")

    def test_book_with_own_settings(self):
        r = self.post("/api/books", {"name": "Own", "input_dir": str(self.pages),
                                     "settings": {"digits": "western", "red": {"min_break_px": 3}}})
        s = r.json()["settings"]
        self.assertEqual((s["digits"], s["red"]["min_break_px"]), ("western", 3))
        self.assertEqual(self.post("/api/books", {"name": "Bad", "input_dir": str(self.pages),
                                                  "settings": {"nope": 1}}).status_code, 400)

    def test_page_problems(self):
        self.assertEqual(self.get(f"/api/books/{self.book}/page-problems").json(), [])
        appbook.add_page(self.pages, "p3.png")
        self.assertEqual(self.get(f"/api/books/{self.book}/page-problems").json(),
                         [{"file": "p3.png", "problem": "new"}])


class JobTests(ApiTestCase):
    def test_capture_with_progress_then_confirmation(self):
        job = self.post(f"/api/books/{self.book}/capture").json()
        self.assertEqual(job["total"], 2, "the page count is known from the start")
        job = self.wait(job)
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual((job["done"], job["total"], len(job["pages"])), (2, 2, 2))
        self.assertGreater(job["result"]["samples"], 0)
        gid = self.groups()[0]["id"]
        self.post(f"/api/books/{self.book}/actions/label", {"group_id": gid, "text": "क"})
        r = self.post(f"/api/books/{self.book}/capture")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "needs_confirmation"))
        job = self.wait(self.post(f"/api/books/{self.book}/capture", {"force": True}).json())
        self.assertEqual(job["status"], "done")

    def test_one_job_per_book_and_cancel(self):
        job = self.post(f"/api/books/{self.book}/capture").json()
        self.assertEqual(self.post(f"/api/books/{self.book}/capture").status_code, 400)
        self.post(f"/api/jobs/{job['id']}/cancel")
        job = self.wait(job)
        self.assertIn(job["status"], ("cancelled", "done"))       # a fast run may finish first
        self.assertEqual(self.get("/api/jobs/nope").status_code, 404)

    def test_add_pages_and_recut(self):
        appbook.add_page(self.pages, "p3.png")
        job = self.wait(self.post(f"/api/books/{self.book}/add-pages").json())
        self.assertEqual(job["result"]["files"], ["p3.png"])
        unsure = self.get(f"/api/books/{self.book}/unsure").json()
        self.assertGreater(unsure["total"], 0)
        self.assertTrue(any(x["suggestion"] for x in unsure["samples"]))
        page = self.get(f"/api/books/{self.book}/pages").json()[0]
        job = self.wait(self.post(f"/api/books/{self.book}/pages/{page['id']}/recut").json())
        self.assertEqual(job["status"], "done", job.get("error"))


class ReviewTests(ApiTestCase):
    def test_review_round_trip(self):
        groups = self.groups()
        g1, g2 = groups[0], groups[1]
        s1 = self.get(f"/api/groups/{g1['id']}/samples?limit=2").json()
        self.assertEqual(len(s1["samples"]), 2)
        self.assertGreaterEqual(s1["total"], 2)
        ids = [x["id"] for x in s1["samples"]]
        r = self.post(f"/api/books/{self.book}/actions/move", {"sample_ids": ids, "group_id": None}).json()
        self.assertEqual((r["undo"], r["redo"]), (1, 0))
        unsure_ids = {x["id"] for x in self.get(f"/api/books/{self.book}/unsure?limit=500").json()["samples"]}
        self.assertTrue(set(ids) <= unsure_ids)
        r = self.post(f"/api/books/{self.book}/actions/new-group", {"sample_ids": ids}).json()
        new_id = r["group_id"]
        self.post(f"/api/books/{self.book}/actions/merge", {"target_id": g1["id"], "source_ids": [new_id]})
        self.assertEqual(self.get(f"/api/groups/{new_id}").status_code, 404)
        r = self.post(f"/api/books/{self.book}/actions/label", {"group_id": g1["id"], "text": "કિ"}).json()
        self.assertEqual((r["label_dev"], r["label_guj"]), ("कि", "કિ"))
        bad = self.post(f"/api/books/{self.book}/actions/label", {"group_id": g2["id"], "text": "कि"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("already the label of group", bad.json()["detail"])
        self.post(f"/api/books/{self.book}/actions/status", {"group_id": g2["id"], "reviewed": True, "locked": True})
        locked = self.post(f"/api/books/{self.book}/actions/dissolve", {"group_id": g2["id"]})
        self.assertEqual(locked.status_code, 400)
        hist = self.get(f"/api/books/{self.book}/history").json()
        self.assertEqual([h["kind"] for h in hist], ["status", "label", "merge", "new_group", "move"])
        for _ in range(5):
            self.assertEqual(self.post(f"/api/books/{self.book}/undo").status_code, 200)
        self.assertEqual(self.post(f"/api/books/{self.book}/undo").status_code, 400)
        def without_time(gs):
            return [{k: v for k, v in g.items() if k != "updated_at"} for g in gs]
        self.assertEqual(without_time(self.groups()), without_time(groups), "undo of everything restores the groups")
        r = self.post(f"/api/books/{self.book}/redo").json()
        self.assertEqual((r["undo"], r["redo"]), (1, 4))

    def test_delete_restore_and_deleted_listing(self):
        g = self.groups()[0]
        sid = self.get(f"/api/groups/{g['id']}/samples?limit=1").json()["samples"][0]["id"]
        self.post(f"/api/books/{self.book}/actions/delete", {"sample_ids": [sid]})
        deleted = self.get(f"/api/books/{self.book}/unsure?deleted=true").json()
        self.assertEqual([x["id"] for x in deleted["samples"]], [sid])
        self.post(f"/api/books/{self.book}/actions/restore", {"sample_ids": [sid]})
        self.assertFalse(self.get(f"/api/samples/{sid}").json()["deleted"])

    def test_bad_requests(self):
        self.assertEqual(self.post(f"/api/books/{self.book}/actions/move", {"sample_ids": []}).status_code, 422)
        self.assertEqual(self.post(f"/api/books/{self.book}/actions/move",
                                   {"sample_ids": [999999], "group_id": None}).status_code, 400)
        self.assertEqual(self.get("/api/groups/999999").status_code, 404)
        self.assertEqual(self.get("/api/books/999/groups").status_code, 404)

    def test_label_check(self):
        ok = self.get("/api/label", params={"text": "ક્ષ", "book_id": self.book}).json()
        self.assertEqual((ok["ok"], ok["devanagari"], ok["category"]), (True, "क्ष", "conjuncts"))
        bad = self.get("/api/label", params={"text": "ि"}).json()
        self.assertFalse(bad["ok"])
        self.assertEqual(ok["used_by"], [])
        g = self.groups()[0]
        self.post(f"/api/books/{self.book}/actions/label", {"group_id": g["id"], "text": "क्ष"})
        used = self.get("/api/label", params={"text": "क्ष", "book_id": self.book}).json()["used_by"]
        self.assertEqual([(u["id"], u["samples"]) for u in used], [(g["id"], g["samples"])])
        word = self.get("/api/label", params={"text": "નમઃ"}).json()
        self.assertEqual((word["ok"], word["category"], word["letters"]), (True, "words", 2))

    def test_group_listing_fields(self):
        g = self.groups()[0]
        for key in ("id", "code", "kind", "label_dev", "label_guj", "status", "locked", "samples", "red", "black",
                    "spread", "example_id", "example_image"):
            self.assertIn(key, g)
        self.assertEqual(g["samples"], g["red"] + g["black"])


if __name__ == "__main__":
    unittest.main()
