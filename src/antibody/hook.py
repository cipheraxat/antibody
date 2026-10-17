"""`antibody hook claude`: a Claude Code PostToolUse hook.

After Claude edits a file, run the verified antibodies that cover it. If the edit
introduced a match (one that isn't in HEAD or in the baseline), exit 2: Claude Code shows
the message to Claude, which fixes the code before moving on."""

from __future__ import annotations

import json
from pathlib import Path

from . import baseline, gitutil
from .engine import EngineError, find_engine
from .learn import covers
from .rules import Antibody, AntibodyError, discover, load
from .verify import counts_for_proof

BLOCK, OK, BROKEN = 2, 0, 1  # exit codes: Claude sees stderr only on 2; 1 tells the user


def claude(event: str, engine_name: str | None = None) -> tuple[int, str]:
    """Handle one PostToolUse event; returns (exit code, message for stderr)."""
    try:
        file_path = json.loads(event)["tool_input"]["file_path"]
    except (ValueError, KeyError, TypeError):
        return OK, ""  # not an edit of a file
    try:
        return _check(Path(file_path), engine_name)
    except (AntibodyError, EngineError, gitutil.GitError, OSError) as e:
        return BROKEN, f"antibody hook: {e}"


def _check(path: Path, engine_name: str | None) -> tuple[int, str]:
    if not path.is_file():
        return OK, ""
    try:
        repo = gitutil.toplevel(path.parent).resolve()
        rel = path.resolve().relative_to(repo).as_posix()
    except (gitutil.GitError, ValueError):
        return OK, ""  # not in a git repository we can map the file into
    if not counts_for_proof(rel):
        return OK, ""

    antibodies: dict[str, Antibody] = {}
    for rule_file in discover(repo):
        try:
            antibody = load(rule_file)
        except AntibodyError:
            continue  # one broken file shouldn't stop the others
        if antibody.verified and covers(antibody.languages, rel):
            antibodies[antibody.id] = antibody
    if not antibodies:
        return OK, ""  # nothing applies, so skip the engine entirely

    engine = find_engine(engine_name)
    rules = [a.path for a in antibodies.values()]
    now, at_head = baseline.scan_against(engine, rules, repo, gitutil.head(repo), [rel])
    now = [(key, f) for key, f in now if f.rule_id in antibodies]
    new = baseline.new_matches(now, at_head | baseline.load(repo))
    if not new:
        return OK, ""

    lines = ["antibody: this edit repeats a mistake that was fixed before"]
    for finding in new:
        antibody = antibodies[finding.rule_id]
        lines.append(f"  {finding.location}  [{antibody.id}]  {antibody.message}")
        lines.append(f"    learned from {_origin(antibody)}")
    lines.append("Fix the code. Ask the user before suppressing it with `# nosemgrep`.")
    return BLOCK, "\n".join(lines)


def _origin(antibody: Antibody) -> str:
    source = antibody.source
    if source.get("commit"):
        summary = source.get("summary")
        return str(source["commit"])[:12] + (f' "{summary}"' if summary else "")
    if source.get("base"):
        return "a fix that isn't committed yet"
    return f"a correction (see .antibodies/{antibody.path.name} and its fixture)"
