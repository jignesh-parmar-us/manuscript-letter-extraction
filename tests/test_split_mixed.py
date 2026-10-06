"""C12d: mixed groups are split by their readings where the shapes agree, never by shape alone."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import appbook                                                                  # noqa: E402
from test_suggest import FakeTesseract                                         # noqa: E402
from letter_extractor.app import actions                                       # noqa: E402
from letter_extractor.app.db import Action, LetterGroup, Sample                # noqa: E402
from letter_extractor.app.suggest import run_tesseract                         # noqa: E402
from sqlalchemy import func, select                                            # noqa: E402


class SplitTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp, self.lib, self.book, _ = appbook.fresh_copy()
        with self.lib.session() as s:
            sizes = dict(s.execute(select(Sample.group_id, func.count(Sample.id))
                                   .where(Sample.book_id == self.book, Sample.deleted.is_(False),
                                          Sample.group_id.is_not(None)).group_by(Sample.group_id)).all())
        self.big = sorted((g for g, n in sizes.items() if n >= 6), key=lambda g: -sizes[g])
        if len(self.big) < 2:
            self.skipTest("the synthetic book has too few big groups")

    def tearDown(self):
        appbook.cleanup(self.tmp, self.lib)

    def members(self, gid):
        with self.lib.session() as s:
            return {x.id for x in s.scalars(select(Sample).where(Sample.group_id == gid, Sample.deleted.is_(False)))}

    def read(self, text_of):
        return run_tesseract(self.lib, self.book, reader=FakeTesseract(self.lib, self.book, text_of), workers=1)


class SplitTests(SplitTestCase):
    def test_two_letters_in_one_group_come_apart_after_reading(self):
        a, b = self.big[:2]
        ids_b = self.members(b)
        actions.merge_groups(self.lib, self.book, a, [b])                    # one mixed group
        r = self.read(lambda smp: "ख" if smp.id in ids_b else "क")
        self.assertEqual(r["groups_split"], 1)
        with self.lib.session() as s:
            new_group = {s.get(Sample, i).group_id for i in ids_b}
            self.assertEqual(len(new_group), 1)
            self.assertNotEqual(new_group.pop(), a)
            self.assertEqual(s.scalars(select(Action.kind).order_by(Action.id.desc())).first(), "split_mixed")
        actions.undo(self.lib, self.book)                                      # one undo puts them back
        self.assertTrue(ids_b <= self.members(a))

    def test_a_misreading_of_the_same_shape_stays(self):
        a = self.big[0]
        ids = sorted(self.members(a))
        half = set(ids[: len(ids) // 2])
        r = self.read(lambda smp: "का" if smp.id in half else "क")            # same shapes, two readings
        self.assertEqual(r["groups_split"], 0)
        self.assertEqual(self.members(a), set(ids))

    def test_one_reading_never_splits_however_the_shapes_vary(self):
        a, b = self.big[:2]
        ids = self.members(a) | self.members(b)
        actions.merge_groups(self.lib, self.book, a, [b])                    # two shapes, one reading
        r = self.read(lambda smp: "क")
        self.assertEqual(r["groups_split"], 0)
        self.assertEqual(self.members(a), ids)

    def test_too_few_letters_do_not_split(self):
        a, b = self.big[:2]
        few = set(sorted(self.members(b))[:3])
        actions.merge_groups(self.lib, self.book, a, [b])
        r = self.read(lambda smp: "ख" if smp.id in few else "क")
        self.assertEqual(r["groups_split"], 0)

    def test_locked_groups_are_left_alone(self):
        a, b = self.big[:2]
        ids_b = self.members(b)
        actions.merge_groups(self.lib, self.book, a, [b])
        actions.set_status(self.lib, self.book, a, locked=True)
        r = self.read(lambda smp: "ख" if smp.id in ids_b else "क")
        self.assertEqual(r["groups_split"], 0)
        self.assertTrue(ids_b <= self.members(a))

    def test_the_action_can_be_run_again_and_does_nothing_when_clean(self):
        a, b = self.big[:2]
        ids_b = self.members(b)
        self.read(lambda smp: "ख" if smp.id in ids_b else "क")               # nothing mixed yet
        actions.merge_groups(self.lib, self.book, a, [b])
        r = actions.split_mixed(self.lib, self.book)
        self.assertEqual(r["groups"], 1)
        self.assertEqual(actions.split_mixed(self.lib, self.book)["groups"], 0)


if __name__ == "__main__":
    unittest.main()
