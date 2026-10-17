"""Only new matches fail. `.antibodies/baseline.json` holds the matches accepted on purpose;
a revision can serve as a baseline too (`check --since`, and the hook, which uses HEAD)."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections import Counter
from dataclasses import replace
from pathlib import Path

from . import gitutil
from .engine import Engine, Finding
from .rules import DIR

FILE = "baseline.json"
Key = tuple[str, str, str]  # rule id, path, fingerprint of the matched code
Keyed = list[tuple[Key, Finding]]


def fingerprint(lines: list[str], finding: Finding) -> str:
    """The matched code with whitespace collapsed, hashed: moving or re-indenting it isn't new."""
    code = "\n".join(" ".join(line.split()) for line in lines[finding.start_line - 1 : finding.end_line])
    return hashlib.sha256(code.encode()).hexdigest()[:16]


def keyed(findings: list[Finding], root: Path) -> Keyed:
    lines: dict[str, list[str]] = {}
    out = []
    for finding in findings:
        if finding.path not in lines:
            try:
                lines[finding.path] = (root / finding.path).read_text(errors="replace").splitlines()
            except OSError:
                lines[finding.path] = []
        key = (finding.rule_id, finding.path, fingerprint(lines[finding.path], finding))
        out.append((key, finding))
    return out


def tally(pairs: Keyed) -> Counter[Key]:
    return Counter(key for key, _ in pairs)


def new_matches(pairs: Keyed, allowed: Counter[Key]) -> list[Finding]:
    """Matches beyond what `allowed` accepts for the same code, in file order.

    Counting means a second copy of an accepted line is still new."""
    seen: Counter[Key] = Counter()
    new = []
    for key, finding in sorted(pairs, key=lambda kf: (kf[1].path, kf[1].start_line)):
        seen[key] += 1
        if seen[key] > allowed[key]:
            new.append(finding)
    return new


def load(repo: Path) -> Counter[Key]:
    path = repo / DIR / FILE
    if not path.is_file():
        return Counter()
    matches = json.loads(path.read_text()).get("matches", {})
    return Counter(
        {
            (rule, file, fp): n
            for rule, files in matches.items()
            for file, fps in files.items()
            for fp, n in fps.items()
        }
    )


def save(repo: Path, counts: Counter[Key], rules: set[str]) -> Path:
    """Replace the entries for `rules` with `counts`, keeping other rules' entries."""
    merged = Counter({k: n for k, n in load(repo).items() if k[0] not in rules})
    merged.update({k: n for k, n in counts.items() if k[0] in rules})
    nested: dict = {}
    for (rule, file, fp), n in sorted(merged.items()):
        nested.setdefault(rule, {}).setdefault(file, {})[fp] = n
    path = repo / DIR / FILE
    path.write_text(json.dumps({"version": 1, "matches": nested}, indent=2) + "\n")
    return path


def stale(accepted: Counter[Key], current: Counter[Key], rules: set[str]) -> int:
    """Accepted matches that are gone, so the baseline could shrink."""
    return sum(max(0, n - current[k]) for k, n in accepted.items() if k[0] in rules)


def scan_against(
    engine: Engine, rules: list[Path], repo: Path, rev: str | None, paths: list[str]
) -> tuple[Keyed, Counter[Key]]:
    """Scan `paths` as they are on disk and as they were at `rev`, in one engine run.

    Returns the current matches and a tally of the matches at `rev` (empty if `rev` is None)."""
    with tempfile.TemporaryDirectory(prefix="antibody-") as tmp:
        root = Path(tmp)
        targets = []
        for path in paths:
            if gitutil.materialize(repo, gitutil.WORKTREE, path, root / "now") is not None:
                targets.append(f"now/{path}")
            if rev and gitutil.materialize(repo, rev, path, root / "then") is not None:
                targets.append(f"then/{path}")
        (root / ".semgrepignore").write_text("")  # we chose the files; scan all of them
        sides: dict[str, list[Finding]] = {"now": [], "then": []}
        for finding in engine.scan(rules, root, targets):
            side, _, path = finding.path.partition("/")
            sides[side].append(replace(finding, path=path))
        return keyed(sides["now"], root / "now"), tally(keyed(sides["then"], root / "then"))
