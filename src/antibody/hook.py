"""The question every agent hook asks: did the agent just bring back a learned mistake?

A match counts only if it is new: not in HEAD's version of the file, and not accepted in
the baseline. `agents.py` turns the answer into each coding tool's hook protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import baseline, gitutil
from .engine import Finding, find_engine
from .learn import covers
from .rules import Antibody, AntibodyError, discover, load
from .verify import counts_for_proof

CLOSING = "Fix the code. Ask the user before suppressing a match with `# nosemgrep`."


@dataclass
class Verdict:
    new: list[Finding] = field(default_factory=list)
    antibodies: dict[str, Antibody] = field(default_factory=dict)

    def explain(self, lead: str) -> str:
        lines = [lead]
        for finding in self.new:
            antibody = self.antibodies[finding.rule_id]
            lines.append(f"  {finding.location}  [{antibody.id}]  {antibody.message}")
            lines.append(f"    learned from {_origin(antibody)}")
        lines.append(CLOSING)
        return "\n".join(lines)


def check_paths(paths: list[Path], engine_name: str | None = None) -> Verdict:
    """New matches in these files: what an edit hook asks after the agent writes them."""
    files = [p for p in paths if p.is_file()]
    repo = _repo_of(files[0]) if files else None
    if repo is None:
        return Verdict()
    rels = []
    for path in files:
        try:
            rel = path.resolve().relative_to(repo).as_posix()
        except ValueError:
            continue  # outside this repository
        if counts_for_proof(rel):
            rels.append(rel)
    return check(repo, rels, engine_name)


def check_turn(cwd: Path, engine_name: str | None = None) -> Verdict:
    """New matches anywhere the working tree differs from HEAD, untracked files included.

    What an end-of-turn hook asks. It sees every edit, including ones made by shell commands."""
    repo = _repo_of(cwd)
    head = gitutil.head(repo) if repo else None
    if head is None:
        return Verdict()
    paths = [
        c.new_path
        for c in gitutil.changed_files(repo, head, gitutil.WORKTREE)
        if c.new_path and counts_for_proof(c.new_path)
    ]
    return check(repo, paths, engine_name)


def check(repo: Path, rels: list[str], engine_name: str | None = None) -> Verdict:
    antibodies: dict[str, Antibody] = {}
    for rule_file in discover(repo):
        try:
            antibody = load(rule_file)
        except AntibodyError:
            continue  # one broken file shouldn't stop the others
        if antibody.verified and any(covers(antibody.languages, rel) for rel in rels):
            antibodies[antibody.id] = antibody
    if not antibodies:
        return Verdict()  # nothing applies, so the engine never starts

    engine = find_engine(engine_name)
    rules = [a.path for a in antibodies.values()]
    now, at_head = baseline.scan_against(engine, rules, repo, gitutil.head(repo), rels)
    now = [(key, f) for key, f in now if f.rule_id in antibodies]
    return Verdict(baseline.new_matches(now, at_head | baseline.load(repo)), antibodies)


def _repo_of(path: Path) -> Path | None:
    try:
        return gitutil.toplevel(path if path.is_dir() else path.parent).resolve()
    except gitutil.GitError:
        return None


def _origin(antibody: Antibody) -> str:
    source = antibody.source
    if source.get("commit"):
        summary = source.get("summary")
        return str(source["commit"])[:12] + (f' "{summary}"' if summary else "")
    if source.get("base"):
        return "a fix that isn't committed yet"
    return f"a correction (see .antibodies/{antibody.path.name} and its fixture)"
