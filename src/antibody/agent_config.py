"""What `antibody init` writes for each coding agent.

Every writer merges into the agent's own settings file, keeps what is already there, and
changes nothing if antibody is already set up."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from . import gitutil
from .rules import AntibodyError

SKILL_DIRS = {"any": ".agents/skills", "claude": ".claude/skills"}
START, END = "<!-- antibody:start -->", "<!-- antibody:end -->"
AGENTS_MD = """\
## Antibodies

This repo keeps learned mistakes as verified rules in `.antibodies/`
([antibody](https://github.com/cipheraxat/antibody)).

- After editing code, run `antibody check --since HEAD`. Fix every new match: its message
  says what to do instead. Ask the user before suppressing one with `# nosemgrep`.
- After you fix a bug, or when you're corrected on a mistake that could happen again,
  offer to turn it into an antibody by following `.agents/skills/antibody/SKILL.md`."""
PRE_COMMIT = """\
#!/bin/sh
# Installed by `antibody init --git-hook`: stop commits that bring back a learned mistake.
exec antibody check --staged
"""


@dataclass(frozen=True)
class Setup:
    settings: str  # the agent's settings file, relative to the repo
    event: str
    hook: dict
    matcher: str | None = None  # hook entries are grouped under a matcher
    top: tuple[tuple[str, object], ...] = ()  # top-level keys the file needs
    detect: tuple[str, ...] = ()  # paths that show the repo uses this agent
    when: str = ""
    trust: str = ""  # what the user still has to do before the hook runs


SETUPS = {
    "claude": Setup(
        ".claude/settings.json",
        "PostToolUse",
        {
            "type": "command",
            "command": "antibody",
            "args": ["hook", "claude"],
            "timeout": 60,
            "statusMessage": "antibody: checking edit",
        },
        matcher="Edit|Write",
        detect=(".claude", "CLAUDE.md"),
        when="after each edit",
    ),
    "codex": Setup(
        ".codex/hooks.json",
        "PostToolUse",
        {
            "type": "command",
            "command": "antibody hook codex",
            "timeout": 60,
            "statusMessage": "antibody: checking edit",
        },
        matcher="apply_patch|Edit|Write",
        detect=(".codex",),
        when="after each edit",
        trust="Codex runs project hooks once you trust them: run /hooks in Codex.",
    ),
    "gemini": Setup(
        ".gemini/settings.json",
        "AfterTool",
        {"name": "antibody", "type": "command", "command": "antibody hook gemini", "timeout": 60000},
        matcher="write_file|replace",
        detect=(".gemini", "GEMINI.md"),
        when="after each edit",
        trust="Gemini CLI asks before running a new project hook the first time.",
    ),
    "cursor": Setup(
        ".cursor/hooks.json",
        "stop",
        {"command": "antibody hook cursor", "timeout": 60, "loop_limit": 2},
        top=(("version", 1),),
        detect=(".cursor", ".cursorrules"),
        when="at the end of each turn",
        trust="Cursor runs project hooks in trusted workspaces.",
    ),
    "copilot": Setup(
        ".github/hooks/antibody.json",
        "agentStop",
        {"type": "command", "command": "antibody hook copilot", "timeoutSec": 60},
        top=(("version", 1),),
        detect=(".github/copilot-instructions.md", ".github/hooks"),
        when="at the end of each turn",
    ),
}


def detect(repo: Path) -> list[str]:
    """Agents this repo already shows signs of using."""
    return [agent for agent, setup in SETUPS.items() if any((repo / p).exists() for p in setup.detect)]


def install_hook(repo: Path, agent: str) -> bool:
    """Returns False if antibody's hook was already there."""
    setup = SETUPS[agent]
    path = repo / setup.settings
    data = _read_json(path)
    for key, value in setup.top:
        data.setdefault(key, value)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise AntibodyError(f"{path}: expected `hooks` to be an object; add the hook by hand")
    entries = hooks.setdefault(setup.event, [])
    if _has_antibody(entries):
        return False
    entries.append({"matcher": setup.matcher, "hooks": [setup.hook]} if setup.matcher else setup.hook)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return True


def install_skill(repo: Path, folder: str) -> Path | None:
    """Copy the agent skill into `folder`; None if it's already there."""
    dest = repo / folder / "antibody" / "SKILL.md"
    if dest.exists():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(resources.files("antibody").joinpath("skill/SKILL.md").read_text())
    return dest


def write_agents_md(repo: Path) -> str | None:
    """Add or refresh antibody's section of AGENTS.md. Returns what happened, or None."""
    path = repo / "AGENTS.md"
    block = f"{START}\n{AGENTS_MD}\n{END}"
    if not path.exists():
        path.write_text(block + "\n")
        return "created"
    text = path.read_text()
    if START in text and END in text:
        updated = text[: text.index(START)] + block + text[text.index(END) + len(END) :]
    else:
        updated = text.rstrip("\n") + "\n\n" + block + "\n"
    if updated == text:
        return None
    path.write_text(updated)
    return "updated"


def install_git_hook(repo: Path) -> Path | None:
    """Install a pre-commit hook running `antibody check --staged`; None if one exists."""
    hooks = Path(gitutil.git(repo, "rev-parse", "--git-path", "hooks").strip())
    path = (hooks if hooks.is_absolute() else repo / hooks) / "pre-commit"
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PRE_COMMIT)
    path.chmod(path.stat().st_mode | 0o111)
    return path


def _has_antibody(entries: list) -> bool:
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        for hook in [entry, *(entry.get("hooks") or [])]:
            if isinstance(hook, dict):
                words = [str(hook.get("command", "")), *map(str, hook.get("args") or [])]
                if "antibody" in " ".join(words) and "hook" in " ".join(words):
                    return True
    return False


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise AntibodyError(f"{path}: not valid JSON ({e}); add the hook by hand") from None
    if not isinstance(data, dict):
        raise AntibodyError(f"{path}: expected a JSON object; add the hook by hand")
    return data
