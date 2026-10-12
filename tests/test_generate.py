"""Generate missing letters (app/generate.py): system generated groups, used only once reviewed."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from fastapi.testclient import TestClient                           # noqa: E402
from letter_extractor.app import actions as A                      # noqa: E402
from letter_extractor.app import generate as G                     # noqa: E402
from letter_extractor.app import readers as R                      # noqa: E402
from letter_extractor.app.api import create_app                    # noqa: E402
from letter_extractor.app.centres import centres                   # noqa: E402
from letter_extractor.app.db import GENERATED, LetterGroup, Sample  # noqa: E402
from letter_extractor.app.export import export_book                # noqa: E402
from sqlalchemy import select                                       # noqa: E402

QUIET = dict(progress=None)


class GenerateTests(unittest.TestCase):
    """The synthetic book (tests/synthetic.make_letters_page): each line starts with a plain letter (x 80), then
    a letter with an aa bar (x 134), and its sixth letter has an anusvara dot above it (x 389). Labelled न, ता
    and तं, they let the system make ना (न + the bar of ता) and नं (न + the dot of तं)."""

    def setUp(self):
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()
        with self.lib.session() as s:
            smps = s.scalars(select(Sample).where(Sample.book_id == self.book, Sample.deleted.is_(False))).all()
            pick = lambda x0, x1: [x.id for x in smps if x0 <= x.x <= x1 and x.kind == "letter"]   # noqa: E731
            plain, bar, dot = pick(75, 90), pick(129, 140), pick(355, 375)
        self.assertEqual((len(plain), len(bar), len(dot)), (6, 6, 6))
        for ids, text in ((plain, "न"), (bar, "ता"), (dot, "तं")):
            A.label_samples(self.lib, self.book, ids, text)

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def group(self, label):
        with self.lib.session() as s:
            g = s.scalars(select(LetterGroup).where(LetterGroup.book_id == self.book, LetterGroup.label_dev == label)).first()
            if g is None:
                return None, []
            return g, s.scalars(select(Sample).where(Sample.group_id == g.id, Sample.deleted.is_(False))).all()

    def test_makes_the_missing_letters_it_can(self):
        r = G.generate(self.lib, self.book, **QUIET)
        made = {m["letter"]: m for m in r["made"]}
        self.assertEqual(set(made), {"ना", "नं"})
        why = {x["letter"]: x["why"] for x in r["skipped"]}
        self.assertIn("i sign", why["नि"])
        self.assertIn("no labelled क", why["का"])
        for label in ("ना", "नं"):
            g, smps = self.group(label)
            self.assertEqual((g.status, g.label_guj), ("auto", {"ना": "ના", "नं": "નં"}[label]))
            self.assertGreaterEqual(len(smps), G.AT_LEAST)
            folder = self.lib.book_dir(self.lib.get_book(self.book))
            for x in smps:
                self.assertEqual((x.source, x.page_id, x.line_id), (GENERATED, None, None))
                self.assertTrue((folder / x.image).is_file() and (folder / x.mask).is_file())
                self.assertTrue(x.rules.startswith("generated: न #"))
                self.assertIsNotNone(x.distance)
        # made once: the letters have a group now
        self.assertEqual(G.generate(self.lib, self.book, **QUIET)["made"], [])
        # one undo takes it all back
        A.undo(self.lib, self.book)
        self.assertEqual(self.group("ना")[0], None)
        with self.lib.session() as s:
            self.assertEqual(s.scalars(select(Sample).where(Sample.source == GENERATED, Sample.deleted.is_(False))).all(), [])

    def test_used_only_once_reviewed_and_generated_until_a_real_letter_joins(self):
        G.generate(self.lib, self.book, **QUIET)
        g, smps = self.group("ना")
        c = TestClient(create_app(self.lib, "t"))
        h = {"X-Token": "t"}

        def shown():
            return next(x for x in c.get(f"/api/books/{self.book}/groups", headers=h).json() if x["id"] == g.id)

        def trained():
            return {it[0] for it in R._letters(self.lib, [self.book], include_unreviewed=True, include_words=False)}

        def reading_centre():
            with self.lib.session() as s:
                return g.id in [x.id for x in centres(s, self.book, labelled_only=True)[0]]

        def exported():
            return export_book(self.lib, self.book, Path(self.tmp) / f"export{len(list(Path(self.tmp).glob('export*')))}")["generated"]

        n = len(smps)
        self.assertEqual((shown()["generated"], shown()["samples"]), (n, n))
        self.assertFalse(trained() & {x.id for x in smps}, "not trained on before review, even with unreviewed")
        self.assertFalse(reading_centre(), "not used to read before review")
        self.assertEqual(exported(), 0)

        A.set_status(self.lib, self.book, g.id, reviewed=True)
        self.assertEqual({x.id for x in smps} - trained(), set())
        self.assertTrue(reading_centre())
        self.assertEqual(exported(), n)
        self.assertEqual((shown()["generated"], shown()["samples"]), (n, n), "still system generated")

        _, plain = self.group("न")
        A.move_samples(self.lib, self.book, [plain[0].id], g.id)          # a real letter joins
        self.assertEqual((shown()["generated"], shown()["samples"]), (n, n + 1))
        c.close()

    def test_training_keeps_generated_letters_out_of_the_held_out_pages(self):
        G.generate(self.lib, self.book, **QUIET)
        for label in ("ना", "नं"):
            A.set_status(self.lib, self.book, self.group(label)[0].id, reviewed=True)
        r = R.train_reader(self.lib, [self.book], min_samples=5)
        self.assertGreaterEqual(r["labels"], 4)                       # न ता तं + the made ones
        self.assertTrue(np.isfinite(r["seconds"]))

    def test_variants_fill_a_small_group_and_send_it_back_to_review(self):
        g, real = self.group("न")
        self.assertEqual((g.status, len(real)), ("labelled", 6))
        r = G.variants(self.lib, self.book, g.id)
        self.assertEqual(r["made"], G.TOP_UP - 6)                 # filled up to 10
        self.assertEqual(r["built"], 0)                           # a consonant alone: changed copies only
        g2, now = self.group("न")
        self.assertEqual(g2.status, "auto", "to be looked at again")
        made = [x for x in now if x.source == GENERATED]
        self.assertEqual(len(made), 4)
        real_ids = {x.id for x in real}
        for x in made:
            self.assertRegex(x.rules, r"^generated: a varied copy of #\d+$")
            self.assertIn(int(x.rules.rsplit("#", 1)[1]), real_ids)
        with self.assertRaises(A.ActionError):                    # full now
            G.variants(self.lib, self.book, g.id)
        A.undo(self.lib, self.book)
        g3, back = self.group("न")
        self.assertEqual((g3.status, len(back)), ("labelled", 6))

    def test_variants_need_a_label_a_real_letter_and_an_open_group(self):
        G.generate(self.lib, self.book, **QUIET)
        made_only = self.group("ना")[0]
        with self.assertRaises(A.ActionError):                    # System generated: no real letter
            G.variants(self.lib, self.book, made_only.id)
        g = self.group("न")[0]
        A.set_status(self.lib, self.book, g.id, locked=True)
        with self.assertRaises(A.ActionError):
            G.variants(self.lib, self.book, g.id)

    def test_top_up_every_small_group_in_one_action(self):
        G.generate(self.lib, self.book, **QUIET)                  # System generated groups are left alone
        r = G.top_up(self.lib, self.book, **QUIET)
        self.assertEqual(sorted(d["label_guj"] for d in r["topped"]), sorted(["ન", "તા", "તં"]))
        self.assertEqual(r["samples"], 3 * 4)
        self.assertEqual(len(self.group("ना")[1]), len([x for x in self.group("ना")[1] if x.source == GENERATED]))
        self.assertEqual(G.top_up(self.lib, self.book, **QUIET)["groups"], 0)
        A.undo(self.lib, self.book)
        self.assertEqual(len(self.group("न")[1]), 6)

    def test_the_reader_makes_no_hidden_copies_of_variants(self):
        g = self.group("न")[0]
        G.variants(self.lib, self.book, g.id)
        A.set_status(self.lib, self.book, g.id, reviewed=True)
        items = [it for it in R._letters(self.lib, [self.book], False, False) if it[3] == "न"]
        self.assertEqual(len(items), 10)
        feats = R._Features(items, {"न": 0}, {"न": 3}, np.random.default_rng(0))
        extra = {it[7]: len(feats.extra[it[0]]) for it in items}
        self.assertEqual(extra, {"auto": 3, GENERATED: 0})

    def test_the_api_refuses_handwritten_books(self):
        c = TestClient(create_app(self.lib, "t"))
        h = {"X-Token": "t"}
        c.patch(f"/api/books/{self.book}", headers=h, json={"writing": "handwritten"})
        self.assertEqual(c.post(f"/api/books/{self.book}/generate-letters", headers=h).status_code, 400)
        c.close()


if __name__ == "__main__":
    unittest.main()
