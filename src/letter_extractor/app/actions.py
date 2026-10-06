"""Review actions with undo and redo (C5c, FR-8).

Every action runs in one database transaction and is written to the `action` table with the state of
everything it touched **before** and **after** the change: for samples their group, deleted flag,
kind and distance; for groups their whole row (or "did not exist"). Undo writes the before-state back,
redo the after-state, so every action is undoable in the same way. A new action clears the redo
stack (the actions undone before it).

Actions:
- `move_samples`  samples to a group, or to unsure (group None)
- `new_group`     a new group from samples (also "split a group")
- `merge_groups`  the samples of other groups into one group; the other groups disappear
- `dissolve_group` all samples to unsure; the group disappears
- `set_label`     label typed in Devanagari or Gujarati (stored canonical, see mapping.py)
- `set_status`    reviewed and / or locked
- `delete_samples`, `restore_samples`  specks and false detections
- `accept_suggestions` labels one or many groups with their suggested labels, as one action (C12)
- `reject_suggestion`  the group stops getting that suggested label (C12)
- `label_samples`  samples to the group with a label, or to a new group that gets it (C12)
- `split_mixed`    letters of a group read as another letter, with another shape, to new groups (C12d)

Locked groups refuse every change except unlocking.
"""
from __future__ import annotations

import json
import unicodedata
from collections import Counter
from typing import Dict, Iterable, List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..mapping import LabelError, canonical_label, mapping_for
from .centres import members, recompute
from .db import Action, Book, LetterGroup, Sample, now
from .library import Library, LibraryError

SAMPLE_FIELDS = ("group_id", "deleted", "kind", "distance")
GROUP_FIELDS = ("code", "kind", "label_dev", "label_guj", "status", "locked", "rejected_dev")


class ActionError(LibraryError):
    """The action is not possible (the message says why)."""


def _sample_state(smp: Sample) -> Dict:
    return {f: getattr(smp, f) for f in SAMPLE_FIELDS}


def _group_state(g: Optional[LetterGroup]) -> Optional[Dict]:
    if g is None:
        return None
    return {"book_id": g.book_id, **{f: getattr(g, f) for f in GROUP_FIELDS}}


class _Change:
    """Records the state of the touched samples and groups before an action, then after it."""

    def __init__(self, s: Session, book_id: int):
        self.s, self.book_id = s, book_id
        self.samples_before: Dict[int, Dict] = {}
        self.groups_before: Dict[int, Optional[Dict]] = {}

    def samples(self, ids: Iterable[int], allow_deleted: bool = False) -> List[Sample]:
        ids = list(dict.fromkeys(int(i) for i in ids))
        if not ids:
            raise ActionError("No samples selected.")
        found = {smp.id: smp for smp in self.s.scalars(select(Sample).where(Sample.id.in_(ids)))}
        out = []
        for i in ids:
            smp = found.get(i)
            if smp is None or smp.book_id != self.book_id:
                raise ActionError(f"Sample {i} is not in this book.")
            if smp.deleted and not allow_deleted:
                raise ActionError(f"Sample {i} is deleted.")
            out.append(smp)
        for smp in out:
            self.touch_sample(smp)
            if smp.group_id is not None:
                self.group(smp.group_id)
        return out

    def touch_sample(self, smp: Sample) -> None:
        self.samples_before.setdefault(smp.id, _sample_state(smp))

    def created(self, smp: Sample) -> None:
        """A sample made by this action (C5f): before it, the sample "did not exist", which is
        recorded as deleted, so undo hides it and redo shows it again."""
        self.samples_before[smp.id] = {"group_id": None, "deleted": True, "kind": smp.kind, "distance": None}

    def group(self, group_id: int, editing_lock: bool = False) -> LetterGroup:
        g = self.s.get(LetterGroup, int(group_id))
        if g is None or g.book_id != self.book_id:
            raise ActionError(f"Group {group_id} is not in this book.")
        if g.locked and not editing_lock:
            raise ActionError(f"Group {g.code} is locked; unlock it first.")
        if g.id not in self.groups_before:
            self.groups_before[g.id] = _group_state(g)
            for m in members(self.s, g.id):          # their distances change with the group
                self.touch_sample(m)
        return g

    def new_group(self, kind: str) -> LetterGroup:
        codes = self.s.scalars(select(LetterGroup.code).where(LetterGroup.book_id == self.book_id))
        n = max((int(c[1:]) for c in codes if c[1:].isdigit()), default=0) + 1
        g = LetterGroup(book_id=self.book_id, code=f"g{n:04d}", kind=kind)
        self.s.add(g)
        self.s.flush()
        self.groups_before[g.id] = None
        return g

    def finish(self, kind: str, summary: Dict) -> Action:
        s = self.s
        s.flush()
        recompute(s, [gid for gid in self.groups_before])
        for sid in self.samples_before:
            smp = s.get(Sample, sid)
            if smp.group_id is None:
                smp.distance = None
        s.flush()
        samples_after = {sid: _sample_state(s.get(Sample, sid)) for sid in self.samples_before}
        groups_after = {gid: _group_state(s.get(LetterGroup, gid)) for gid in self.groups_before}
        # a new action clears the redo stack
        s.execute(delete(Action).where(Action.book_id == self.book_id, Action.undone.is_(True)))
        payload = {"summary": summary,
                   "samples_before": self.samples_before, "samples_after": samples_after,
                   "groups_before": self.groups_before, "groups_after": groups_after}
        action = Action(book_id=self.book_id, kind=kind, payload=json.dumps(payload, ensure_ascii=False))
        s.add(action)
        s.get(Book, self.book_id).updated_at = now()
        s.flush()
        return action


def _apply(s: Session, groups: Dict, samples: Dict) -> None:
    """Write a recorded state back: create / update groups, set samples, then remove groups that did
    not exist in that state."""
    for gid, state in groups.items():
        if state is None:
            continue
        g = s.get(LetterGroup, int(gid))
        if g is None:
            g = LetterGroup(id=int(gid), book_id=state["book_id"], code=state["code"])
            s.add(g)
        for f in GROUP_FIELDS:
            if f in state:                                # states recorded before C12 have no rejected_dev
                setattr(g, f, state[f])
    s.flush()
    for sid, state in samples.items():
        smp = s.get(Sample, int(sid))
        if smp is None:                                   # removed since (page cut again)
            continue
        for f in SAMPLE_FIELDS:
            setattr(smp, f, state[f])
    s.flush()
    for gid, state in groups.items():
        if state is None:
            g = s.get(LetterGroup, int(gid))
            if g is not None:
                s.delete(g)
    s.flush()


def _result(action: Action, **extra) -> Dict:
    return {"action_id": action.id, "kind": action.kind, **json.loads(action.payload)["summary"], **extra}


# ---- actions ---------------------------------------------------------------------------------
def move_samples(lib: Library, book_id: int, sample_ids: Iterable[int], group_id: Optional[int]) -> Dict:
    with lib.session() as s:
        ch = _Change(s, book_id)
        smps = ch.samples(sample_ids)
        target = ch.group(group_id) if group_id is not None else None
        for smp in smps:
            smp.group_id = target.id if target else None
            if target is not None:
                smp.kind = target.kind
        a = ch.finish("move", {"samples": len(smps), "to": target.code if target else "unsure"})
        return _result(a)


def new_group(lib: Library, book_id: int, sample_ids: Iterable[int]) -> Dict:
    with lib.session() as s:
        ch = _Change(s, book_id)
        smps = ch.samples(sample_ids)
        kind = Counter(smp.kind for smp in smps).most_common(1)[0][0]
        g = ch.new_group(kind)
        for smp in smps:
            smp.group_id, smp.kind = g.id, kind
        a = ch.finish("new_group", {"samples": len(smps), "group": g.code})
        return _result(a, group_id=g.id)


def merge_groups(lib: Library, book_id: int, target_id: int, source_ids: Iterable[int]) -> Dict:
    with lib.session() as s:
        ch = _Change(s, book_id)
        target = ch.group(target_id)
        sources = [ch.group(gid) for gid in dict.fromkeys(int(i) for i in source_ids) if gid != target.id]
        if not sources:
            raise ActionError("Choose at least one other group to merge.")
        moved = 0
        for g in sources:
            for m in members(s, g.id):
                m.group_id, m.kind = target.id, target.kind
                moved += 1
            for m in s.scalars(select(Sample).where(Sample.group_id == g.id)):   # deleted ones too
                ch.touch_sample(m)
                m.group_id = None
            s.flush()
            s.delete(g)
        a = ch.finish("merge", {"into": target.code, "groups": [g.code for g in sources], "samples": moved})
        return _result(a, group_id=target.id)


def dissolve_group(lib: Library, book_id: int, group_id: int) -> Dict:
    with lib.session() as s:
        ch = _Change(s, book_id)
        g = ch.group(group_id)
        code = g.code
        for m in s.scalars(select(Sample).where(Sample.group_id == g.id)):
            ch.touch_sample(m)
            m.group_id = None
        s.flush()
        s.delete(g)
        a = ch.finish("dissolve", {"group": code})
        return _result(a)


def set_label(lib: Library, book_id: int, group_id: int, text: str) -> Dict:
    """Label typed in Devanagari or Gujarati; an empty text clears the label."""
    with lib.session() as s:
        book = s.get(Book, book_id)
        m = mapping_for(lib.book_config(book))
        ch = _Change(s, book_id)
        g = ch.group(group_id)
        if text.strip():
            try:
                dev = canonical_label(text, m, words=True)
            except LabelError as e:
                raise ActionError(f"Not a letter: {e}") from e
            other = s.scalars(select(LetterGroup).where(LetterGroup.book_id == book_id, LetterGroup.id != g.id,
                                                        LetterGroup.label_dev == dev)).first()
            if other is not None:                       # one group per label: merge instead
                raise ActionError(f"'{m.gujarati(dev)}' is already the label of group {other.code}; "
                                  f"merge this group into it instead.")
            g.label_dev, g.label_guj, g.status = dev, m.gujarati(dev), "labelled"
        else:
            g.label_dev = g.label_guj = ""
            if g.status == "labelled":
                g.status = "reviewed"
        a = ch.finish("label", {"group": g.code, "label_dev": g.label_dev, "label_guj": g.label_guj})
        return _result(a, group_id=g.id)


def accept_suggestions(lib: Library, book_id: int, items: List[Dict]) -> Dict:
    """Label groups with the suggestions the user saw ({group_id, label_dev} each), as one action.
    Groups that got a label meanwhile, are locked, or whose label another group has (one label,
    one group) are skipped and named in the result."""
    with lib.session() as s:
        book = s.get(Book, book_id)
        m = mapping_for(lib.book_config(book))
        ch = _Change(s, book_id)
        used = set(s.scalars(select(LetterGroup.label_dev).where(LetterGroup.book_id == book_id,
                                                                 LetterGroup.label_dev != "")))
        labelled, skipped = [], []
        for item in items:
            g = s.get(LetterGroup, int(item["group_id"]))
            if g is None or g.book_id != book_id:
                raise ActionError(f"Group {item['group_id']} is not in this book.")
            try:
                dev = canonical_label(item["label_dev"], m, words=True)
            except LabelError as e:
                raise ActionError(f"Not a letter: {e}") from e
            if g.label_dev or g.locked or dev in used:
                skipped.append(g.code)
                continue
            g = ch.group(g.id)
            g.label_dev, g.label_guj, g.status = dev, m.gujarati(dev), "labelled"
            used.add(dev)
            labelled.append(g.code)
        if not labelled:
            raise ActionError("No group could be labelled: they are labelled or locked already, "
                              "or another group has the label.")
        a = ch.finish("accept_suggestions", {"groups": len(labelled), "skipped": skipped})
        return _result(a, labelled=labelled)


def reject_suggestion(lib: Library, book_id: int, group_id: int, label_dev: str) -> Dict:
    """The group keeps no label and is not suggested `label_dev` again (another reading can be)."""
    with lib.session() as s:
        ch = _Change(s, book_id)
        g = ch.group(group_id)
        g.rejected_dev = unicodedata.normalize("NFC", label_dev.strip())
        a = ch.finish("reject_suggestion", {"group": g.code, "label_dev": g.rejected_dev})
        return _result(a, group_id=g.id)


def label_samples(lib: Library, book_id: int, sample_ids: Iterable[int], text: str) -> Dict:
    """Move samples to the group with this label (the largest unlocked one), or to a new group
    that gets the label: one action, so one undo."""
    with lib.session() as s:
        book = s.get(Book, book_id)
        m = mapping_for(lib.book_config(book))
        try:
            dev = canonical_label(text, m, words=True)
        except LabelError as e:
            raise ActionError(f"Not a letter: {e}") from e
        ch = _Change(s, book_id)
        smps = ch.samples(sample_ids)
        same = s.scalars(select(LetterGroup).where(LetterGroup.book_id == book_id, LetterGroup.label_dev == dev)).all()
        open_ = [g for g in same if not g.locked]
        if same and not open_:
            raise ActionError(f"The group {same[0].code} with the label {m.gujarati(dev)} is locked; unlock it first.")
        if open_:
            target = ch.group(max(open_, key=lambda g: len(members(s, g.id))).id)
            new = False
        else:
            target = ch.new_group(Counter(smp.kind for smp in smps).most_common(1)[0][0])
            target.label_dev, target.label_guj, target.status = dev, m.gujarati(dev), "labelled"
            new = True
        for smp in smps:
            smp.group_id, smp.kind = target.id, target.kind
        a = ch.finish("label_samples", {"samples": len(smps), "to": target.code, "label_dev": dev, "new": new})
        return _result(a, group_id=target.id)


def split_mixed(lib: Library, book_id: int, engine: Optional[str] = None) -> Dict:
    """Split mixed groups by their readings where the shapes agree (suggest.mixed_splits): each set
    of letters read as another letter goes to a new group of its own (unlabelled: it gets its own
    suggestion). One action; nothing is recorded when there is nothing to split."""
    from .suggest import mixed_splits
    with lib.session() as s:
        book = s.get(Book, book_id)
        found = mixed_splits(s, book, lib.book_config(book), engine)
        if not found:
            return {"groups": 0, "samples": 0, "action_id": None}
        ch = _Change(s, book_id)
        moved = 0
        for gid, text, ids in found:
            smps = ch.samples(ids)
            g = ch.new_group(smps[0].kind)
            for smp in smps:
                smp.group_id = g.id
            moved += len(smps)
        a = ch.finish("split_mixed", {"groups": len(found), "samples": moved})
        return _result(a)


def set_status(lib: Library, book_id: int, group_id: int, reviewed: Optional[bool] = None,
               locked: Optional[bool] = None) -> Dict:
    with lib.session() as s:
        ch = _Change(s, book_id)
        g = ch.group(group_id, editing_lock=True)
        if g.locked and locked is not False:
            raise ActionError(f"Group {g.code} is locked; unlock it first.")
        if reviewed is not None and not g.label_dev:
            g.status = "reviewed" if reviewed else "auto"
        if locked is not None:
            g.locked = bool(locked)
        a = ch.finish("status", {"group": g.code, "status": g.status, "locked": g.locked})
        return _result(a, group_id=g.id)


def delete_samples(lib: Library, book_id: int, sample_ids: Iterable[int]) -> Dict:
    with lib.session() as s:
        ch = _Change(s, book_id)
        smps = ch.samples(sample_ids)
        for smp in smps:
            smp.deleted, smp.group_id = True, None
        a = ch.finish("delete", {"samples": len(smps)})
        return _result(a)


def restore_samples(lib: Library, book_id: int, sample_ids: Iterable[int]) -> Dict:
    """Deleted samples come back as unsure."""
    with lib.session() as s:
        ch = _Change(s, book_id)
        smps = ch.samples(sample_ids, allow_deleted=True)
        for smp in smps:
            smp.deleted = False
        a = ch.finish("restore", {"samples": len(smps)})
        return _result(a)


# ---- undo, redo, history -------------------------------------------------------------------
def undo(lib: Library, book_id: int) -> Dict:
    with lib.session() as s:
        a = s.scalars(select(Action).where(Action.book_id == book_id, Action.undone.is_(False))
                      .order_by(Action.id.desc())).first()
        if a is None:
            raise ActionError("Nothing to undo.")
        data = json.loads(a.payload)
        _apply(s, data["groups_before"], data["samples_before"])
        a.undone = True
        s.get(Book, book_id).updated_at = now()
        return {"undone": a.kind, **data["summary"]}


def redo(lib: Library, book_id: int) -> Dict:
    with lib.session() as s:
        a = s.scalars(select(Action).where(Action.book_id == book_id, Action.undone.is_(True))
                      .order_by(Action.id)).first()
        if a is None:
            raise ActionError("Nothing to redo.")
        data = json.loads(a.payload)
        _apply(s, data["groups_after"], data["samples_after"])
        a.undone = False
        s.get(Book, book_id).updated_at = now()
        return {"redone": a.kind, **data["summary"]}


def history(lib: Library, book_id: int, limit: int = 50) -> List[Dict]:
    with lib.session() as s:
        rows = s.scalars(select(Action).where(Action.book_id == book_id).order_by(Action.id.desc())
                         .limit(limit)).all()
        return [{"id": a.id, "kind": a.kind, "undone": a.undone, "created_at": a.created_at.isoformat(),
                 **json.loads(a.payload)["summary"]} for a in rows]


def can_undo_redo(lib: Library, book_id: int) -> Dict:
    with lib.session() as s:
        n_undo = s.scalar(select(func.count(Action.id)).where(Action.book_id == book_id, Action.undone.is_(False)))
        n_redo = s.scalar(select(func.count(Action.id)).where(Action.book_id == book_id, Action.undone.is_(True)))
        return {"undo": int(n_undo or 0), "redo": int(n_redo or 0)}
