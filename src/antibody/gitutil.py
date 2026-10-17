"""Thin wrappers over the git CLI."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

WORKTREE = "WORKTREE"  # a revision meaning "the files on disk", untracked files included
INDEX = "INDEX"  # a revision meaning "what is staged for the next commit"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git's empty tree: "before the first commit"


class GitError(RuntimeError):
    """A git command failed."""


@dataclass(frozen=True)
class Change:
    status: str  # A, M, D, R (renamed) or C (copied)
    old_path: str | None  # None when the file was added
    new_path: str | None  # None when the file was deleted


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def toplevel(path: Path) -> Path:
    try:
        return Path(git(path, "rev-parse", "--show-toplevel").strip())
    except GitError:
        raise GitError(f"{path} is not inside a git repository") from None


def resolve(repo: Path, rev: str) -> str:
    try:
        return git(repo, "rev-parse", "--verify", f"{rev}^{{commit}}").strip()
    except GitError:
        hint = " (shallow clone? fetch more history)" if rev.endswith("^") else ""
        raise GitError(f"unknown commit {rev!r} in {repo}{hint}") from None


def head(repo: Path) -> str | None:
    """The commit HEAD points at, or None in a repository with no commits yet."""
    try:
        return resolve(repo, "HEAD")
    except GitError:
        return None


def short(repo: Path, rev: str) -> str:
    if rev in (WORKTREE, INDEX):
        return rev.lower()
    return git(repo, "rev-parse", "--short=12", rev).strip()


def subject(repo: Path, rev: str) -> str:
    """The commit subject, or for a GitHub merge commit the PR title in its body."""
    if rev == WORKTREE:
        return "uncommitted changes"
    message = git(repo, "log", "-1", "--format=%B", rev).strip().splitlines()
    first = message[0] if message else ""
    if first.startswith(("Merge pull request", "Merge branch")):
        return next((line.strip() for line in message[1:] if line.strip()), first)
    return first


def origin_url(repo: Path) -> str | None:
    try:
        return git(repo, "config", "--get", "remote.origin.url").strip() or None
    except GitError:
        return None


def changed_files(repo: Path, old: str, new: str) -> list[Change]:
    """Files that differ between two revisions. `new` may be WORKTREE or INDEX."""
    if new == INDEX:
        return _parse_name_status(git(repo, "diff", "--cached", "--name-status", "-z", "-M", old))
    if new != WORKTREE:
        return _parse_name_status(git(repo, "diff", "--name-status", "-z", "-M", old, new))
    changes = _parse_name_status(git(repo, "diff", "--name-status", "-z", "-M", old))
    return changes + [Change("A", None, path) for path in untracked(repo)]


def untracked(repo: Path) -> list[str]:
    """New files git doesn't know about yet, minus ignored ones."""
    return [p for p in git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0") if p]


def _parse_name_status(output: str) -> list[Change]:
    tokens = output.split("\0")
    changes: list[Change] = []
    i = 0
    while i < len(tokens) and tokens[i]:
        status = tokens[i][0]
        if status in "RC":
            src, dst = tokens[i + 1], tokens[i + 2]
            i += 3
            # A copy leaves the original in place, so only the new file is part of the change.
            changes.append(Change(status, src if status == "R" else None, dst))
        else:
            path = tokens[i + 1]
            i += 2
            changes.append(
                Change(status, None if status == "A" else path, None if status == "D" else path)
            )
    return changes


def read(repo: Path, rev: str, path: str) -> bytes | None:
    """File contents at a revision, or None when it isn't a regular file there."""
    if rev == WORKTREE:
        file = repo / path
        return file.read_bytes() if file.is_file() else None
    spec = f":{path}" if rev == INDEX else f"{rev}:{path}"
    proc = subprocess.run(
        ["git", "cat-file", "blob", spec], cwd=repo, capture_output=True, check=False
    )
    return proc.stdout if proc.returncode == 0 else None


def materialize(repo: Path, rev: str, path: str | None, root: Path) -> list[str] | None:
    """Write a text file as of `rev` to root/path and return its lines.

    None when there is no such file at `rev`, or it is binary."""
    if path is None:
        return None
    data = read(repo, rev, path)
    if data is None or b"\0" in data[:8192]:
        return None
    dest = root / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return data.decode("utf-8", errors="replace").splitlines()
