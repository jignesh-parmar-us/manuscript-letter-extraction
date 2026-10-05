"""C11: the Tesseract job (with a fake Tesseract), readings, group votes and suggestions."""
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                                  # noqa: E402
from letter_extractor import io_utils                                          # noqa: E402
from letter_extractor.app import actions                                       # noqa: E402
from letter_extractor.app.db import Book, LetterGroup, Line, OcrReading, OcrRun, Sample   # noqa: E402
from letter_extractor.app.library import Cancelled                             # noqa: E402
from letter_extractor.app.suggest import group_readings, run_tesseract, sample_readings, vote   # noqa: E402
from letter_extractor.ocr.tesseract import Char, LineReading, Word             # noqa: E402
from sqlalchemy import func, select                                            # noqa: E402

LETTERS = ["क", "ख", "ग", "घ", "च", "छ", "ज", "झ", "ट", "ठ", "ड", "ढ", "त", "थ", "द", "ध", "न", "प"]


class FakeTesseract:
    """Reads each sample of a line as `text_of(sample)`, with a box exactly over the sample. Line
    images are recognised by their pixels, so the fake knows which samples are on them."""

    def __init__(self, lib, book_id, text_of, conf=95.0):
        self.lines, self.calls = {}, 0
        book = lib.get_book(book_id)
        margin = lib.book_config(book).line_margin_px
        with lib.session() as s:
            for line in s.scalars(select(Line).join(Sample, Sample.line_id == Line.id)
                                  .where(Sample.book_id == book_id).distinct()):
                rgb, _ = io_utils.load_image(lib.book_dir(book) / line.image)
                dx = max(0, line.x - margin)
                smps = s.scalars(select(Sample).where(Sample.line_id == line.id, Sample.deleted.is_(False))
                                 .order_by(Sample.x)).all()
                chars = [Char(text_of(x), (x.x - dx, 0, x.w, line.h), conf, [(text_of(x), conf)]) for x in smps]
                self.lines[hashlib.sha1(rgb.tobytes()).hexdigest()] = chars

    def __call__(self, rgb):
        self.calls += 1
        chars = self.lines[hashlib.sha1(rgb.tobytes()).hexdigest()]
        return LineReading(words=[Word(box=(0, 0, 1, 1), conf=95, chars=list(chars))], hocr="<html/>", scale=1.0)


class SuggestTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()
        with self.lib.session() as s:
            self.groups = [g.id for g in s.scalars(select(LetterGroup).where(LetterGroup.book_id == self.book)
                                                   .order_by(LetterGroup.id))]
        self.letter = {gid: LETTERS[i % len(LETTERS)] for i, gid in enumerate(self.groups)}

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def text_of(self, smp):
        return self.letter.get(smp.group_id, "ण")                # unsure samples: ण

    def run_fake(self, text_of=None, **kw):
        fake = FakeTesseract(self.lib, self.book, text_of or self.text_of)
        return run_tesseract(self.lib, self.book, reader=fake, workers=2, **kw), fake

    def ocr(self, group_ids=None):
        with self.lib.session() as s:
            book = s.get(Book, self.book)
            return group_readings(s, book, self.lib.book_config(book), group_ids)

    def big_groups(self):
        """Groups with at least 3 samples (enough votes for a suggestion)."""
        with self.lib.session() as s:
            return [g for g in self.groups if s.scalar(select(func.count(Sample.id)).where(
                Sample.group_id == g, Sample.deleted.is_(False))) >= 3]


class JobTests(SuggestTestCase):
    def test_every_group_gets_its_reading(self):
        result, fake = self.run_fake()
        self.assertEqual(result["lines_failed"], 0)
        self.assertEqual(result["lines_refused"], 0)
        self.assertGreater(result["samples_matched"], 0.9 * result["samples"])
        self.assertEqual(fake.calls, result["lines"])
        ocr = self.ocr()
        big = self.big_groups()
        self.assertTrue(big)
        for gid in big:
            sug = ocr[gid]["suggestion"]
            self.assertEqual((sug["label_dev"], sug["share"]), (self.letter[gid], 1.0))
            self.assertEqual(sug["count"], sug["read"])
            self.assertEqual(sug["label_guj"], {"क": "ક", "ख": "ખ"}.get(self.letter[gid], sug["label_guj"]))
        self.assertEqual(result["groups_with_suggestion"], sum(v["suggestion"] is not None for v in ocr.values()))

    def test_hocr_is_kept_per_line(self):
        result, _ = self.run_fake()
        files = list((self.lib.book_dir(self.lib.get_book(self.book)) / "ocr").glob("*.hocr"))
        self.assertEqual(len(files), result["lines"])

    def test_new_run_replaces_the_old_one(self):
        self.run_fake()
        self.run_fake()
        with self.lib.session() as s:
            self.assertEqual(s.scalar(select(func.count(OcrRun.id)).where(OcrRun.book_id == self.book)), 1)

    def test_cancel_stores_nothing(self):
        fake = FakeTesseract(self.lib, self.book, self.text_of)
        with self.assertRaises(Cancelled):
            run_tesseract(self.lib, self.book, reader=fake, cancel=lambda: True, workers=1)
        with self.lib.session() as s:
            self.assertEqual(s.scalar(select(func.count(OcrReading.id))), 0)

    def test_readings_that_are_not_labels_are_dropped(self):
        result, _ = self.run_fake(text_of=lambda smp: "x")      # Latin: matched, but not a label
        self.assertEqual(result["samples_matched"], 0)
        self.assertGreater(result["readings_not_labels"], 0)

    def test_progress_per_line(self):
        seen = []
        fake = FakeTesseract(self.lib, self.book, self.text_of)
        result = run_tesseract(self.lib, self.book, reader=fake, workers=1,
                               progress=lambda done, total, r: seen.append((done, total, r.status)))
        self.assertEqual(len(seen), result["lines"])
        self.assertEqual(seen[-1][:2], (result["lines"], result["lines"]))


class GroupTests(SuggestTestCase):
    def test_labelled_group_gets_no_suggestion_but_keeps_its_readings(self):
        self.run_fake()
        gid = self.big_groups()[0]
        actions.set_label(self.lib, self.book, gid, "ङ")
        entry = self.ocr([gid])[gid]
        self.assertIsNone(entry["suggestion"])
        self.assertEqual(entry["readings"][0]["label_dev"], self.letter[gid])

    def test_suggestion_used_by_another_group_offers_a_merge(self):
        a, b = self.big_groups()[:2]
        self.letter[b] = self.letter[a]
        self.run_fake()
        actions.set_label(self.lib, self.book, a, self.letter[a])
        sug = self.ocr([b])[b]["suggestion"]
        with self.lib.session() as s:
            code = s.get(LetterGroup, a).code
        self.assertEqual(sug["merge_into"], {"id": a, "code": code})

    def test_rejected_label_is_not_suggested_again(self):
        self.run_fake()
        gid = self.big_groups()[0]
        with self.lib.session() as s:
            s.get(LetterGroup, gid).rejected_dev = self.letter[gid]
        self.assertIsNone(self.ocr([gid])[gid]["suggestion"])

    def test_mixed_group_shows_two_readings_and_no_suggestion(self):
        # by position, not by id: the synthetic book's two pages are identical images
        gid = self.big_groups()[0]
        self.run_fake(text_of=lambda smp: "ब" if smp.group_id == gid and smp.pos % 2 else self.text_of(smp))
        entry = self.ocr([gid])[gid]
        counts = {r["label_dev"]: r["count"] for r in entry["readings"]}
        self.assertEqual(set(counts), {"ब", self.letter[gid]})
        if max(counts.values()) < 0.6 * sum(counts.values()):
            self.assertIsNone(entry["suggestion"])

    def test_votes_follow_moved_samples(self):
        self.run_fake()
        a, b = self.big_groups()[:2]
        with self.lib.session() as s:
            moved = [x.id for x in s.scalars(select(Sample).where(Sample.group_id == b, Sample.deleted.is_(False)))]
        actions.move_samples(self.lib, self.book, moved, a)
        entry = self.ocr([a])[a]
        self.assertEqual({r["label_dev"] for r in entry["readings"]}, {self.letter[a], self.letter[b]})

    def test_unsure_samples_show_their_reading_on_printed_books_only(self):
        with self.lib.session() as s:
            unsure = [x.id for x in s.scalars(select(Sample).where(Sample.group_id == self.big_groups()[0]))][:2]
        actions.move_samples(self.lib, self.book, unsure, None)
        self.run_fake()
        with self.lib.session() as s:
            book = s.get(Book, self.book)
            cfg = self.lib.book_config(book)
            self.assertEqual(sample_readings(s, book, cfg, unsure), {})            # handwritten
        self.lib.set_book_writing(self.book, "printed")
        with self.lib.session() as s:
            book = s.get(Book, self.book)
            reads = sample_readings(s, book, cfg, unsure)
        self.assertEqual(set(reads), set(unsure))
        self.assertTrue(all(r["confidence"] >= cfg.suggest_min_confidence for r in reads.values()))


class VoteTests(unittest.TestCase):
    def test_winner(self):
        v = vote([("क", 90), ("क", 90), ("क", 90), ("ख", 90)], 3, 0.6)
        self.assertEqual((v["label_dev"], v["share"], v["count"], v["read"]), ("क", 0.75, 3, 4))

    def test_too_few_votes(self):
        self.assertIsNone(vote([("क", 90), ("क", 90)], 3, 0.6))

    def test_tie(self):
        self.assertIsNone(vote([("क", 90), ("क", 90), ("ख", 90), ("ख", 90)], 3, 0.4))

    def test_share_below_the_minimum(self):
        self.assertIsNone(vote([("क", 90), ("क", 90), ("ख", 90), ("ग", 90)], 3, 0.6))

    def test_weighted_by_confidence(self):
        v = vote([("क", 95), ("क", 95), ("ख", 10), ("ख", 10)], 3, 0.6)
        self.assertEqual(v["label_dev"], "क")



class ReviewActionTests(SuggestTestCase):
    """C12: accepting and rejecting suggestions, labelling samples, selecting by reading, accuracy."""

    def label_of(self, gid):
        with self.lib.session() as s:
            return s.get(LetterGroup, gid).label_dev

    def test_accept_many_as_one_undoable_action(self):
        self.run_fake()
        ocr = self.ocr()
        items = [{"group_id": g, "label_dev": v["suggestion"]["label_dev"]} for g, v in ocr.items() if v["suggestion"]]
        before = appbook.state(self.lib, self.book)
        r = actions.accept_suggestions(self.lib, self.book, items)
        self.assertEqual(r["groups"], len(items))
        for item in items:
            self.assertEqual(self.label_of(item["group_id"]), item["label_dev"])
        actions.undo(self.lib, self.book)
        self.assertEqual(appbook.state(self.lib, self.book), before)
        actions.redo(self.lib, self.book)
        self.assertEqual(self.label_of(items[0]["group_id"]), items[0]["label_dev"])

    def test_accept_skips_a_label_another_group_has(self):
        a, b = self.big_groups()[:2]
        actions.set_label(self.lib, self.book, a, "क")
        r = actions.accept_suggestions(self.lib, self.book, [{"group_id": b, "label_dev": "क"},
                                                             {"group_id": self.big_groups()[2], "label_dev": "ख"}])
        self.assertEqual(r["groups"], 1)
        self.assertEqual(len(r["skipped"]), 1)
        self.assertEqual(self.label_of(b), "")

    def test_accept_refuses_when_nothing_can_be_labelled(self):
        gid = self.big_groups()[0]
        actions.set_label(self.lib, self.book, gid, "क")
        with self.assertRaises(actions.ActionError):
            actions.accept_suggestions(self.lib, self.book, [{"group_id": gid, "label_dev": "ख"}])

    def test_reject_is_undoable_and_hides_the_suggestion(self):
        self.run_fake()
        gid = self.big_groups()[0]
        actions.reject_suggestion(self.lib, self.book, gid, self.letter[gid])
        self.assertIsNone(self.ocr([gid])[gid]["suggestion"])
        actions.undo(self.lib, self.book)
        self.assertEqual(self.ocr([gid])[gid]["suggestion"]["label_dev"], self.letter[gid])

    def test_undo_of_an_action_recorded_before_rejected_dev_existed(self):
        gid = self.big_groups()[0]
        actions.set_label(self.lib, self.book, gid, "क")
        with self.lib.session() as s:                       # as an action from C11 or earlier looks
            import json
            from letter_extractor.app.db import Action
            a = s.scalars(select(Action).order_by(Action.id.desc())).first()
            data = json.loads(a.payload)
            for state in list(data["groups_before"].values()) + list(data["groups_after"].values()):
                state.pop("rejected_dev", None)
            a.payload = json.dumps(data)
        actions.undo(self.lib, self.book)
        self.assertEqual(self.label_of(gid), "")

    def test_label_samples_into_the_labelled_group_or_a_new_one(self):
        a, b = self.big_groups()[:2]
        actions.set_label(self.lib, self.book, a, "क")
        with self.lib.session() as s:
            ids = [x.id for x in s.scalars(select(Sample).where(Sample.group_id == b))][:2]
        r = actions.label_samples(self.lib, self.book, ids, "ક")              # Gujarati input
        self.assertEqual(r["group_id"], a)
        r = actions.label_samples(self.lib, self.book, ids, "ख")
        self.assertTrue(r["new"])
        self.assertEqual(self.label_of(r["group_id"]), "ख")
        actions.undo(self.lib, self.book)
        with self.lib.session() as s:
            self.assertIsNone(s.get(LetterGroup, r["group_id"]))
            self.assertEqual({s.get(Sample, i).group_id for i in ids}, {a})

    def test_samples_read_as(self):
        from letter_extractor.app.suggest import samples_read_as
        gid = self.big_groups()[0]
        self.run_fake(text_of=lambda smp: "ब" if smp.group_id == gid and smp.pos % 2 else self.text_of(smp))
        with self.lib.session() as s:
            book = s.get(Book, self.book)
            ids = samples_read_as(s, book, gid, "ब")
            self.assertTrue(ids)
            self.assertTrue(all(s.get(Sample, i).pos % 2 for i in ids))
            self.assertEqual(samples_read_as(s, book, gid, "ञ"), [])

    def test_accuracy_against_the_labels(self):
        from letter_extractor.app.suggest import suggestion_accuracy
        self.run_fake()
        a, b = self.big_groups()[:2]
        actions.set_label(self.lib, self.book, a, self.letter[a])                # right
        actions.set_label(self.lib, self.book, b, "ञ")                           # the reading says otherwise
        with self.lib.session() as s:
            book = s.get(Book, self.book)
            acc = suggestion_accuracy(s, book, self.lib.book_config(book))
        self.assertEqual((acc["labelled"], acc["suggested"], acc["right"]), (2, 2, 1))
        self.assertEqual(acc["bands"][0], {"band": "90% or more", "right": 1, "wrong": 1})
        self.assertEqual(acc["wrong"][0]["suggested"], {"क": "ક", "ख": "ખ"}.get(self.letter[b], acc["wrong"][0]["suggested"]))


if __name__ == "__main__":
    unittest.main()
