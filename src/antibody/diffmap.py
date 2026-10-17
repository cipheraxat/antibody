"""Line-level map between the vulnerable and fixed versions of one file."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

Range = tuple[int, int]  # 1-based, inclusive


@dataclass
class FileDiff:
    old_to_new: dict[int, int] = field(default_factory=dict)  # unchanged lines only
    old_sites: list[Range] = field(default_factory=list)  # where the fix touched the old file
    added: list[Range] = field(default_factory=list)  # lines the fix wrote in the new file

    def near_change(self, start: int, end: int, window: int) -> bool:
        return any(start <= hi + window and lo - window <= end for lo, hi in self.old_sites)

    def touches_added(self, start: int, end: int) -> bool:
        return any(start <= hi and lo <= end for lo, hi in self.added)


def diff_lines(old: list[str] | None, new: list[str] | None) -> FileDiff:
    """None means the file doesn't exist on that side (added or deleted by the fix)."""
    if old is None:
        return FileDiff(added=[(1, len(new))] if new else [])
    if new is None:
        return FileDiff(old_sites=[(1, len(old))] if old else [])

    diff = FileDiff()
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                diff.old_to_new[i1 + k + 1] = j1 + k + 1
            continue
        if i2 > i1:
            diff.old_sites.append((i1 + 1, i2))
        else:
            # A pure insertion sits between old lines i1 and i1 + 1.
            lo = max(i1, 1)
            diff.old_sites.append((lo, max(lo, min(i1 + 1, len(old)))))
        if j2 > j1:
            diff.added.append((j1 + 1, j2))
    return diff
