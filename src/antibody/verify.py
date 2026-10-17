"""The proof: an antibody must fire on the mistake and stay silent on the fix.

The fix comes from a commit, from uncommitted changes, or, when the mistake never reached
git, from the antibody's fixture alone."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path, PurePosixPath

from . import gitutil
from .diffmap import diff_lines
from .engine import Engine, Finding, locations
from .fixtures import expectations
from .fixtures import problems as fixture_problems
from .rules import DIR, Antibody

DEFAULT_WINDOW = 25  # max lines between a match and the change for the match to count as the bug
BEFORE, AFTER, FIXTURES = "vulnerable", "fixed", "fixtures"  # scan-root subfolders
COMMIT, WORKTREE, FIXTURES_ONLY = "commit", "worktree", "fixtures"  # kinds of proof
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs"}
TEST_FILE = re.compile(r"^test_|(_test|\.test|_spec|\.spec)\.[^.]+$")


def counts_for_proof(path: str) -> bool:
    """Antibodies look at code, not at tests or at antibodies themselves."""
    parts = PurePosixPath(path).parts
    if parts[0] == DIR or any(p in TEST_DIRS for p in parts[:-1]):
        return False
    return not TEST_FILE.search(parts[-1])


@dataclass(frozen=True)
class Revisions:
    kind: str  # COMMIT, WORKTREE or FIXTURES_ONLY
    vulnerable: str | None = None
    fixed: str | None = None  # a commit, or gitutil.WORKTREE
    pin: bool = False  # an uncommitted fix that has since been committed


def revisions(antibody: Antibody, repo: Path) -> Revisions:
    """What the proof compares, going by the antibody's recorded source."""
    source = antibody.source
    if source.get("commit"):
        fixed = gitutil.resolve(repo, str(source["commit"]))
        vulnerable = gitutil.resolve(repo, str(source.get("vulnerable") or f"{fixed}^"))
        return Revisions(COMMIT, vulnerable, fixed)
    if source.get("base"):
        base = gitutil.resolve(repo, str(source["base"]))
        if gitutil.head(repo) == base:
            return Revisions(WORKTREE, base, gitutil.WORKTREE)
        # The fix has been committed since: prove it against everything from base to HEAD.
        return Revisions(COMMIT, base, gitutil.head(repo), pin=True)
    return Revisions(FIXTURES_ONLY)


@dataclass
class Proof:
    revisions: Revisions
    fixed: str = ""  # short forms, for display
    vulnerable: str = ""
    subject: str = ""
    fires_on: list[Finding] = field(default_factory=list)  # gone after the fix, near the change
    flags_fix: list[Finding] = field(default_factory=list)  # on lines the fix wrote
    survivors: list[Finding] = field(default_factory=list)  # still there after the fix
    far: list[Finding] = field(default_factory=list)  # gone after the fix, far from the change
    fixtures: int = 0
    fixture_problems: list[str] = field(default_factory=list)
    has_ruleid: bool = False  # some fixture line must match
    has_ok: bool = False  # some fixture line must not match

    @property
    def kind(self) -> str:
        return self.revisions.kind

    @property
    def passed(self) -> bool:
        return not self.problems()

    def problems(self) -> list[str]:
        problems = []
        if self.kind == FIXTURES_ONLY:
            if not (self.has_ruleid and self.has_ok):
                problems.append(
                    "with no fix in git, the fixture is the proof: it needs at least one "
                    "`ruleid:` line and one `ok:` line"
                )
            return problems + self.fixture_problems
        if not self.fires_on:
            if self.survivors:
                why = f"its matches are still there after the fix: {locations(self.survivors)}"
            elif self.far:
                why = f"it only matched outside the changed region: {locations(self.far)}"
            else:
                why = "no matches in the code before the fix"
            problems.append(f"never fires on the mistake ({why})")
        if self.flags_fix:
            problems.append(f"fires on code the fix wrote: {locations(self.flags_fix)}")
        return problems + self.fixture_problems

    def stamp(self, engine: Engine) -> dict:
        stamp: dict = {"engine": engine.label, "proof": self.kind}
        if self.kind == FIXTURES_ONLY:
            stamp["fixtures"] = self.fixtures
        else:
            stamp["vulnerable"] = self.vulnerable
            stamp["fixed"] = self.fixed
            stamp["fires_on"] = [f.location for f in self.fires_on]
        stamp["at"] = date.today().isoformat()
        return stamp

    def to_json(self) -> dict:
        return {
            "passed": self.passed,
            "proof": self.kind,
            "fixed": self.fixed,
            "vulnerable": self.vulnerable,
            "subject": self.subject,
            "fires_on": [f.location for f in self.fires_on],
            "flags_fix": [f.location for f in self.flags_fix],
            "survivors": [f.location for f in self.survivors],
            "far": [f.location for f in self.far],
            "fixtures": self.fixtures,
            "problems": self.problems(),
        }


def prove(antibody: Antibody, repo: Path, engine: Engine, window: int = DEFAULT_WINDOW) -> Proof:
    revs = revisions(antibody, repo)
    proof = Proof(revs)
    if revs.kind != FIXTURES_ONLY:
        proof.fixed = gitutil.short(repo, revs.fixed)
        proof.vulnerable = gitutil.short(repo, revs.vulnerable)
        proof.subject = gitutil.subject(repo, revs.fixed)

    # Both sides of the fix and the fixtures go through one engine run: startup dominates its cost.
    with tempfile.TemporaryDirectory(prefix="antibody-") as tmp:
        root = Path(tmp)
        changes, old, new = [], {}, {}
        if revs.kind != FIXTURES_ONLY:
            for change in gitutil.changed_files(repo, revs.vulnerable, revs.fixed):
                if not counts_for_proof(change.new_path or change.old_path):
                    continue
                old_lines = gitutil.materialize(repo, revs.vulnerable, change.old_path, root / BEFORE)
                new_lines = gitutil.materialize(repo, revs.fixed, change.new_path, root / AFTER)
                if (change.old_path and old_lines is None) or (change.new_path and new_lines is None):
                    continue  # binary, or not a regular file
                changes.append(change)
                old[change], new[change] = old_lines, new_lines
        texts = {}
        for fixture in antibody.fixtures():
            texts[fixture.name] = fixture.read_text(errors="replace")
            (root / FIXTURES).mkdir(exist_ok=True)
            (root / FIXTURES / fixture.name).write_text(texts[fixture.name])
        (root / ".semgrepignore").write_text("")  # scan every file we wrote, wherever it lives
        targets = [f"{BEFORE}/{c.old_path}" for c in changes if c.old_path]
        targets += [f"{AFTER}/{c.new_path}" for c in changes if c.new_path]
        targets += [f"{FIXTURES}/{name}" for name in texts]
        found = engine.scan([antibody.path], root, targets)

    sides: dict[str, list[Finding]] = {BEFORE: [], AFTER: [], FIXTURES: []}
    for f in found:
        if f.rule_id == antibody.id:
            side, _, path = f.path.partition("/")
            sides[side].append(replace(f, path=path))
    before, after = sides[BEFORE], sides[AFTER]

    diffs = {c: diff_lines(old[c], new[c]) for c in changes}
    by_old = {c.old_path: c for c in changes if c.old_path}
    by_new = {c.new_path: c for c in changes if c.new_path}
    after_starts = {(f.path, f.start_line) for f in after}

    for finding in before:
        change = by_old[finding.path]
        diff = diffs[change]
        moved_to = diff.old_to_new.get(finding.start_line)
        if moved_to is not None and (change.new_path, moved_to) in after_starts:
            proof.survivors.append(finding)
        elif diff.near_change(finding.start_line, finding.end_line, window):
            proof.fires_on.append(finding)
        else:
            proof.far.append(finding)
    proof.flags_fix = [
        f for f in after if diffs[by_new[f.path]].touches_added(f.start_line, f.end_line)
    ]

    for name, text in texts.items():
        must, must_not = expectations(text, antibody.id)
        proof.has_ruleid |= bool(must)
        proof.has_ok |= bool(must_not)
        found_lines = {f.start_line for f in sides[FIXTURES] if f.path == name}
        proof.fixture_problems += fixture_problems(name, text, antibody.id, found_lines)
    proof.fixtures = len(texts)
    return proof
