"""`antibody learn`: gather the facts about a fix and write a skeleton antibody.

The agent writes the rule; `antibody verify` judges it. A fix is a commit, the uncommitted
changes in the working tree, or, for a mistake that never reached git, nothing at all:
then the antibody's fixture is the proof."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import gitutil
from .gitutil import Change
from .rules import DIR, AntibodyError, discover, load
from .verify import counts_for_proof

LANGUAGES = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".java": "java", ".go": "go", ".rb": "ruby", ".php": "php", ".rs": "rust",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".cs": "csharp", ".kt": "kotlin", ".scala": "scala", ".swift": "swift",
}  # fmt: skip
EXTENSIONS = {
    "python": "py", "javascript": "js", "typescript": "ts", "java": "java", "go": "go",
    "ruby": "rb", "php": "php", "rust": "rs", "c": "c", "cpp": "cpp", "csharp": "cs",
    "kotlin": "kt", "scala": "scala", "swift": "swift",
}  # fmt: skip
ALIASES = {"py": "python", "js": "javascript", "ts": "typescript", "golang": "go", "rb": "ruby"}
JS_FAMILY = {"javascript", "typescript"}
HASH_COMMENTS = {"python", "ruby"}
DIFF_LIMIT = 400  # lines of diff in a brief

SKELETON = """\
rules:
  - id: {id}
    message: >-
      TODO: what's wrong and what to do instead. Your coding agent reads this when it
      repeats the mistake.
    severity: ERROR
    languages: [{languages}]
    # Match only the known mistake first, then generalize one element at a time.
    pattern: TODO
    metadata:
      antibody:
        kind: bug  # bug, security or convention
{source}"""

TIPS = [
    "   - Wrong call or API: match the call, and `pattern-not` the right form.",
    "   - Missing check before a call: `pattern-not-inside` for the check.",
    "   - Untrusted input reaching a dangerous call: `mode: taint`, with the fix's",
    "     guard as a sanitizer.",
    "   - Don't anchor on names that only exist here unless the mistake is specific",
    "     to that API.",
]


@dataclass
class Brief:
    path: Path
    created: bool
    text: str


def language_of(path: str) -> str | None:
    return LANGUAGES.get(PurePosixPath(path).suffix)


def covers(languages: list[str], path: str) -> bool:
    """Whether a rule for `languages` can match `path`: a cheap check before the engine runs."""
    wanted = {ALIASES.get(lang.lower(), lang.lower()) for lang in languages}
    if wanted & {"generic", "regex"}:
        return True
    language = language_of(path)
    if language in JS_FAMILY:
        return bool(wanted & JS_FAMILY)
    return language in wanted


def learn(
    repo: Path,
    commit: str | None = None,
    antibody_id: str | None = None,
    fixtures_only: bool = False,
) -> Brief:
    """A skeleton and a brief for one fix: `commit`, else uncommitted changes, else HEAD."""
    if fixtures_only:
        if not antibody_id:
            raise AntibodyError("--fixtures-only needs --id: name the mistake")
        return _write(repo, repo / DIR / f"{antibody_id}.yml", [], "", None, None)
    head = gitutil.head(repo)
    if commit is None and head and _code_changes(repo, head, gitutil.WORKTREE):
        return _from_worktree(repo, head, antibody_id)
    return _from_commit(repo, commit or "HEAD", antibody_id)


def _from_commit(repo: Path, commit: str, antibody_id: str | None) -> Brief:
    fixed = gitutil.resolve(repo, commit)
    vulnerable = gitutil.resolve(repo, f"{fixed}^")
    subject = gitutil.subject(repo, fixed)
    path = _existing(repo, fixed) if antibody_id is None else None
    if path is None:
        path = repo / DIR / f"{antibody_id or _unique_id(repo, slugify(subject))}.yml"
    source = _source(commit=fixed, summary=subject, repo=gitutil.origin_url(repo))
    header = [
        f"Fix:         {fixed[:12]} {subject}",
        f"Before:      {vulnerable[:12]} (the fix's parent)",
    ]
    diff = gitutil.git(repo, "diff", "-U8", "--no-color", "-M", vulnerable, fixed).splitlines()
    more = f"run `git show {fixed[:12]}`"
    return _write(repo, path, _code_changes(repo, vulnerable, fixed), source, header, (diff, more))


def _from_worktree(repo: Path, head: str, antibody_id: str | None) -> Brief:
    changes = _code_changes(repo, head, gitutil.WORKTREE)
    first = next((c for c in changes if counts_for_proof(c.new_path or c.old_path)), changes[0])
    default = slugify("fix " + PurePosixPath(first.new_path or first.old_path).stem)
    path = repo / DIR / f"{antibody_id or _unique_id(repo, default)}.yml"
    header = [
        f"Fix:         uncommitted changes on top of {head[:12]}",
        f"Before:      {head[:12]} (HEAD)",
    ]
    diff = gitutil.git(repo, "diff", "-U8", "--no-color", "-M", head).splitlines()
    for new_file in gitutil.untracked(repo):
        if PurePosixPath(new_file).parts[0] != DIR:
            content = (repo / new_file).read_text(errors="replace").splitlines()
            diff += ["--- /dev/null (untracked)", f"+++ b/{new_file}", *[f"+{l}" for l in content]]
    return _write(repo, path, changes, _source(base=head), header, (diff, "run `git diff HEAD`"))


def _write(
    repo: Path,
    path: Path,
    changes: list[Change],
    source: str,
    header: list[str] | None,
    diff: tuple[list[str], str] | None,
) -> Brief:
    antibody_id = path.stem
    languages = _languages([c.new_path or c.old_path for c in changes]) or _repo_languages(repo)
    created = not path.exists()
    if created:
        path.parent.mkdir(exist_ok=True)
        path.write_text(
            SKELETON.format(id=antibody_id, languages=", ".join(languages), source=source)
        )
    rel = path.relative_to(repo) if path.is_relative_to(repo) else path
    ext = EXTENSIONS.get(languages[0], "txt")
    c = "#" if languages[0] in HASH_COMMENTS else "//"
    fixture = [
        f"Add a fixture next to it, {antibody_id}.{ext}: the mistake under a",
        f"   `{c} ruleid: {antibody_id}` line, the fixed form under `{c} ok: {antibody_id}`.",
    ]

    if diff is None:  # fixtures only: there is no fix in git to read
        header = ["Fix:         not in git, so the fixture is the proof"]
        steps = [
            [
                f"Write the fixture first, {antibody_id}.{ext}, from the conversation: the code",
                f"   that was wrong under a `{c} ruleid: {antibody_id}` line, the corrected code",
                f"   under `{c} ok: {antibody_id}`. Fix `languages` in {rel} if it's wrong.",
            ],
            ["Replace `pattern: TODO` with a rule that matches the wrong code, not the fix.", *TIPS],
        ]
    else:
        steps = [
            ["Say in one sentence what went wrong and what the fix does instead."],
            [
                f"Replace `pattern: TODO` in {rel} with a rule that matches the mistake.",
                "   Match only this case first, then generalize one element at a time.",
                *TIPS,
            ],
            fixture,
        ]
    steps += [
        [
            "Replace the TODO `message`: what's wrong and what to do instead. Your agent",
            "   reads it when it repeats the mistake. Set `kind` to bug, security or convention.",
        ],
        [f"Run `antibody verify {antibody_id}` until it passes. Change the rule, not the fixture."],
        [
            f"Run `antibody sweep {antibody_id}`. Fix real repeats, then",
            f"   `antibody baseline {antibody_id}` to accept whatever is left on purpose.",
        ],
    ]

    lines = [
        f"# Antibody brief: {antibody_id}",
        "",
        *header,
        f"Antibody:    {rel} ({'skeleton written' if created else 'exists, left as is'})",
        f"Languages:   {', '.join(languages)}",
        "",
    ]
    if changes:
        lines += ["## Changed files", *[f"  {ch.status} {ch.new_path or ch.old_path}" for ch in changes], ""]
    lines.append("## Your job")
    for number, step in enumerate(steps, start=1):
        lines += [f"{number}. {step[0]}", *step[1:]]
    if diff is not None:
        body, more = diff
        if len(body) > DIFF_LIMIT:
            body = body[:DIFF_LIMIT] + [f"... {len(body) - DIFF_LIMIT} more lines: {more}"]
        lines += ["", "## Diff", "```diff", *body, "```"]
    return Brief(path, created, "\n".join(lines))


def slugify(text: str, limit: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].rstrip("-")
    return slug or "antibody"


def _source(**fields: str | None) -> str:
    lines = [f"          {k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fields.items() if v]
    return "        source:\n" + "\n".join(lines) + "\n"


def _code_changes(repo: Path, old: str, new: str) -> list[Change]:
    return [
        c
        for c in gitutil.changed_files(repo, old, new)
        if PurePosixPath(c.new_path or c.old_path).parts[0] != DIR
    ]


def _languages(paths: list[str]) -> list[str]:
    code = [p for p in paths if language_of(p)]
    preferred = [p for p in code if counts_for_proof(p)] or code
    return sorted({language_of(p) for p in preferred})


def _repo_languages(repo: Path) -> list[str]:
    counts = Counter(filter(None, map(language_of, gitutil.git(repo, "ls-files", "-z").split("\0"))))
    return [counts.most_common(1)[0][0]] if counts else ["python"]


def _existing(repo: Path, fixed: str) -> Path | None:
    """An antibody already learned from this commit, so learning twice reuses it."""
    for path in discover(repo):
        try:
            if str(load(path).source.get("commit")) == fixed:
                return path
        except AntibodyError:
            continue
    return None


def _unique_id(repo: Path, base: str) -> str:
    candidate, n = base, 2
    while (repo / DIR / f"{candidate}.yml").exists():
        candidate, n = f"{base}-{n}", n + 1
    return candidate
