"""C5c: review actions, undo / redo, suggestions, adding pages and cutting a page again."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                      # noqa: E402
from letter_extractor.app import actions as A                      # noqa: E402
from letter_extractor.app.centres import suggestions               # noqa: E402
from letter_extractor.app.db import Action, LetterGroup, Page, Sample   # noqa: E402
from letter_extractor.app.library import BookHasReviewError, Cancelled  # noqa: E402
from sqlalchemy import func, select                                 # noqa: E402


class ActionTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, self.pages = appbook.fresh_copy()
        self.groups = appbook.groups_with_members(self.lib, self.book)
        self.assertGreaterEqual(len(self.groups), 3, "the synthetic book needs a few groups")
        ids = sorted(self.groups, key=lambda g: -len(self.groups[g]))
        self.g1, self.g2, self.g3 = ids[:3]

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def state(self):
        return appbook.state(self.lib, self.book)

    def assert_undo_redo_exact(self, do):
        before = self.state()
        do()
        after = self.state()
        self.assertNotEqual(before, after, "the action changed nothing")
        A.undo(self.lib, self.book)
        self.assertEqual(self.state(), before, "undo did not restore the exact state")
        A.redo(self.lib, self.book)
        self.assertEqual(self.state(), after, "redo did not restore the exact state")


class UndoRedoTests(ActionTestCase):
    def test_move_to_unsure(self):
        smp = self.groups[self.g1][:2]
        self.assert_undo_redo_exact(lambda: A.move_samples(self.lib, self.book, smp, None))

    def test_move_to_other_group(self):
        smp = self.groups[self.g1][:1]
        self.assert_undo_redo_exact(lambda: A.move_samples(self.lib, self.book, smp, self.g2))

    def test_new_group(self):
        smp = self.groups[self.g1][:1] + self.groups[self.g2][:1]
        self.assert_undo_redo_exact(lambda: A.new_group(self.lib, self.book, smp))

    def test_merge(self):
        self.assert_undo_redo_exact(lambda: A.merge_groups(self.lib, self.book, self.g1, [self.g2, self.g3]))

    def test_dissolve(self):
        self.assert_undo_redo_exact(lambda: A.dissolve_group(self.lib, self.book, self.g2))

    def test_label(self):
        self.assert_undo_redo_exact(lambda: A.set_label(self.lib, self.book, self.g1, "કિ"))

    def test_status_and_lock(self):
        self.assert_undo_redo_exact(lambda: A.set_status(self.lib, self.book, self.g1, reviewed=True, locked=True))

    def test_reviewing_a_label_given_automatically(self):
        from letter_extractor.app.db import LetterGroup
        with self.lib.session() as s:                            # as capture or Fix cuts leave it
            g = s.get(LetterGroup, self.g1)
            g.label_dev, g.label_guj, g.status = "की", "કી", "auto"
        A.set_status(self.lib, self.book, self.g1, reviewed=True)
        with self.lib.session() as s:
            self.assertEqual(s.get(LetterGroup, self.g1).status, "labelled")
        A.set_status(self.lib, self.book, self.g1, reviewed=False)
        with self.lib.session() as s:
            g = s.get(LetterGroup, self.g1)
            self.assertEqual((g.status, g.label_dev), ("auto", "की"))       # the label stays, not reviewed
        A.undo(self.lib, self.book)
        with self.lib.session() as s:
            self.assertEqual(s.get(LetterGroup, self.g1).status, "labelled")

    def test_delete_and_restore(self):
        smp = self.groups[self.g1][:1]
        self.assert_undo_redo_exact(lambda: A.delete_samples(self.lib, self.book, smp))
        self.assert_undo_redo_exact(lambda: A.restore_samples(self.lib, self.book, smp))

    def test_many_actions_then_undo_all(self):
        start = self.state()
        A.set_label(self.lib, self.book, self.g1, "क")
        A.move_samples(self.lib, self.book, self.groups[self.g2][:2], None)
        r = A.new_group(self.lib, self.book, self.groups[self.g2][:2])
        A.merge_groups(self.lib, self.book, self.g3, [r["group_id"]])
        A.delete_samples(self.lib, self.book, self.groups[self.g1][:1])
        A.dissolve_group(self.lib, self.book, self.g2)
        for _ in range(6):
            A.undo(self.lib, self.book)
        self.assertEqual(self.state(), start)
        with self.assertRaises(A.ActionError):
            A.undo(self.lib, self.book)

    def test_new_action_clears_redo(self):
        A.set_label(self.lib, self.book, self.g1, "क")
        A.undo(self.lib, self.book)
        self.assertEqual(A.can_undo_redo(self.lib, self.book), {"undo": 0, "redo": 1})
        A.set_label(self.lib, self.book, self.g2, "ख")
        self.assertEqual(A.can_undo_redo(self.lib, self.book), {"undo": 1, "redo": 0})
        with self.assertRaises(A.ActionError):
            A.redo(self.lib, self.book)


class ActionRuleTests(ActionTestCase):
    def test_label_in_both_scripts_and_refused_labels(self):
        A.set_label(self.lib, self.book, self.g1, "શ્રી")
        with self.lib.session() as s:
            g = s.get(LetterGroup, self.g1)
            self.assertEqual((g.label_dev, g.label_guj, g.status), ("श्री", "શ્રી", "labelled"))
        before = self.state()
        with self.assertRaises(A.ActionError) as e:
            A.set_label(self.lib, self.book, self.g1, "काि")              # a vowel sign with no letter
        self.assertIn("'ि' needs a letter before it", str(e.exception))
        self.assertEqual(self.state(), before, "a refused action must change nothing")
        A.set_label(self.lib, self.book, self.g1, "")
        with self.lib.session() as s:
            g = s.get(LetterGroup, self.g1)
            self.assertEqual((g.label_dev, g.status), ("", "reviewed"))

    def test_word_labels(self):
        A.set_label(self.lib, self.book, self.g1, "નમઃ")                  # a whole word, typed in Gujarati
        with self.lib.session() as s:
            self.assertEqual(s.get(LetterGroup, self.g1).label_dev, "नमः")
        with self.assertRaises(A.ActionError):
            A.set_label(self.lib, self.book, self.g2, "क" * 13)            # longer than MAX_WORD

    def test_one_group_per_label(self):
        A.set_label(self.lib, self.book, self.g1, "क")
        before = self.state()
        with self.assertRaises(A.ActionError) as e:
            A.set_label(self.lib, self.book, self.g2, "ક")                 # the same letter, typed in Gujarati
        self.assertIn("already the label of group", str(e.exception))
        self.assertEqual(self.state(), before)
        A.set_label(self.lib, self.book, self.g1, "क")                     # its own label again is fine
        A.merge_groups(self.lib, self.book, self.g1, [self.g2])           # what the screen offers instead

    def test_locked_group_refuses_changes(self):
        A.set_status(self.lib, self.book, self.g1, locked=True)
        for do in (lambda: A.set_label(self.lib, self.book, self.g1, "क"),
                   lambda: A.move_samples(self.lib, self.book, self.groups[self.g1][:1], None),
                   lambda: A.move_samples(self.lib, self.book, self.groups[self.g2][:1], self.g1),
                   lambda: A.merge_groups(self.lib, self.book, self.g2, [self.g1]),
                   lambda: A.dissolve_group(self.lib, self.book, self.g1)):
            with self.assertRaises(A.ActionError):
                do()
        A.set_status(self.lib, self.book, self.g1, locked=False)
        A.set_label(self.lib, self.book, self.g1, "क")

    def test_new_group_codes_and_kind(self):
        r = A.new_group(self.lib, self.book, self.groups[self.g1][:2])
        with self.lib.session() as s:
            codes = sorted(s.scalars(select(LetterGroup.code).where(LetterGroup.book_id == self.book)))
            g = s.get(LetterGroup, r["group_id"])
            self.assertEqual(g.code, codes[-1])
            self.assertEqual(len(set(codes)), len(codes))
            self.assertEqual(r["group"], g.code)

    def test_distances_follow_the_groups(self):
        moved = self.groups[self.g2][0]
        A.move_samples(self.lib, self.book, [moved], self.g1)
        with self.lib.session() as s:
            mem = s.scalars(select(Sample).where(Sample.group_id == self.g1)).all()
            self.assertTrue(all(m.distance is not None for m in mem))
            far = max(mem, key=lambda m: m.distance)
            self.assertEqual(far.id, moved, "the foreign sample is furthest from the centre")
        A.move_samples(self.lib, self.book, [moved], None)
        with self.lib.session() as s:
            self.assertIsNone(s.get(Sample, moved).distance)

    def test_deleted_samples_leave_their_group(self):
        smp = self.groups[self.g1][0]
        A.delete_samples(self.lib, self.book, [smp])
        self.assertNotIn(smp, appbook.groups_with_members(self.lib, self.book)[self.g1])
        with self.assertRaises(A.ActionError):
            A.move_samples(self.lib, self.book, [smp], self.g2)
        A.restore_samples(self.lib, self.book, [smp])
        with self.lib.session() as s:
            x = s.get(Sample, smp)
            self.assertEqual((x.deleted, x.group_id), (False, None))

    def test_samples_and_groups_of_another_book_are_refused(self):
        other = self.lib.create_book("Other", self.pages)
        for do in (lambda: A.move_samples(self.lib, other.id, self.groups[self.g1][:1], None),
                   lambda: A.set_label(self.lib, other.id, self.g1, "क"),
                   lambda: A.move_samples(self.lib, self.book, [999999], None)):
            with self.assertRaises(A.ActionError):
                do()

    def test_suggestion_points_back_to_the_group(self):
        smp = self.groups[self.g1][0]
        A.move_samples(self.lib, self.book, [smp], None)
        with self.lib.session() as s:
            x = s.get(Sample, smp)
            sug = suggestions(s, self.book, [x], 0.55)
        self.assertEqual(sug[smp]["group_id"], self.g1)

    def test_history(self):
        A.set_label(self.lib, self.book, self.g1, "क")
        A.move_samples(self.lib, self.book, self.groups[self.g2][:1], None)
        h = A.history(self.lib, self.book)
        self.assertEqual([x["kind"] for x in h], ["move", "label"])


class PageTests(ActionTestCase):
    def test_add_new_pages_changes_nothing_else(self):
        before = self.state()
        appbook.add_page(self.pages, "p3.png")
        r = self.lib.add_new_pages(self.book)
        self.assertEqual(r["files"], ["p3.png"])
        samples_after, groups_after = self.state()
        self.assertEqual(groups_after, before[1])
        old_ids = {x[0] for x in before[0]}
        self.assertEqual([x for x in samples_after if x[0] in old_ids], before[0])
        new = [x for x in samples_after if x[0] not in old_ids]
        self.assertEqual(len(new), r["samples"])
        self.assertTrue(all(x[1] is None for x in new), "new samples start as unsure")
        with self.lib.session() as s:
            new_samples = [s.get(Sample, x[0]) for x in new]
            sug = suggestions(s, self.book, new_samples, 0.55)
        self.assertGreater(len(sug), 0.8 * len(new), "most new samples get a suggested group")
        self.assertEqual(self.lib.add_new_pages(self.book)["pages"], 0)

    def test_recut_page_without_manual_work(self):
        with self.lib.session() as s:
            p1 = s.scalar(select(Page.id).where(Page.book_id == self.book, Page.file == "p1.png"))
            p2_samples = s.scalars(select(Sample.id).join(Page).where(Page.file == "p2.png")).all()
        r = self.lib.recut_page(self.book, p1)
        self.assertEqual(r["files"], ["p1.png"])
        with self.lib.session() as s:
            self.assertEqual(sorted(s.scalars(select(Sample.id).join(Page).where(Page.file == "p2.png"))),
                             sorted(p2_samples), "other pages keep their samples")
            new = s.scalars(select(Sample).join(Page).where(Page.file == "p1.png")).all()
            self.assertTrue(new and all(x.group_id is None for x in new))
            folder = self.lib.book_dir(self.lib.get_book(self.book))
            self.assertTrue(all((folder / x.image).is_file() for x in new))

    def test_recut_page_with_manual_work_needs_confirmation(self):
        with self.lib.session() as s:
            smp = s.scalars(select(Sample).join(Page).where(Page.file == "p1.png",
                                                            Sample.group_id.is_not(None))).first()
            gid, p1 = smp.group_id, smp.page_id
        A.set_label(self.lib, self.book, gid, "क")
        with self.assertRaises(BookHasReviewError):
            self.lib.recut_page(self.book, p1)
        self.lib.recut_page(self.book, p1, force=True)
        with self.lib.session() as s:
            self.assertEqual(s.scalar(select(func.count(Action.id))), 0, "history cleared")
            self.assertEqual(s.get(LetterGroup, gid).label_dev, "क", "labelled group kept")

    def test_cancelled_capture_changes_nothing(self):
        before = self.state()
        folder = self.lib.book_dir(self.lib.get_book(self.book))
        files_before = sorted(p.relative_to(folder) for p in folder.rglob("*.png"))
        with self.assertRaises(Cancelled):
            self.lib.capture(self.book, cancel=lambda: True)
        self.assertEqual(self.state(), before)
        self.assertEqual(sorted(p.relative_to(folder) for p in folder.rglob("*.png")), files_before)
        self.assertFalse((folder / ".work").exists())


if __name__ == "__main__":
    unittest.main()
