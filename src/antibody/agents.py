"""Each coding agent's hook protocol, on top of the shared check in `hook.py`.

Edit hooks (Claude Code, Codex, Gemini CLI) are told which file the agent edited and answer
right after the edit. End-of-turn hooks (Cursor, GitHub Copilot) check every file the turn
changed and send the agent back to fix new matches before it finishes."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import gitutil, hook
from .engine import EngineError
from .rules import AntibodyError

AGENTS = ("claude", "codex", "gemini", "cursor", "copilot")
EDIT_LEAD = "antibody: this edit repeats a mistake that was fixed before"
TURN_LEAD = "antibody: your changes repeat mistakes that were fixed before. Fix them, then finish."
PATCH_FILE = re.compile(r"^\*\*\* (?:Update File|Add File|Move to): (.+?)\s*$", re.MULTILINE)
MAX_FOLLOWUPS = 2  # Cursor: follow-ups sent before letting the agent stop anyway


@dataclass(frozen=True)
class Reply:
    code: int = 0
    stdout: str = ""
    stderr: str = ""


def handle(agent: str, raw_event: str, engine_name: str | None = None) -> Reply:
    """Answer one hook event from `agent`, read from stdin as JSON."""
    try:
        event = json.loads(raw_event) if raw_event.strip() else {}
    except ValueError:
        event = {}
    if not isinstance(event, dict):
        event = {}
    respond, quiet, broken = ADAPTERS[agent]
    try:
        return respond(event, engine_name)
    except (AntibodyError, EngineError, gitutil.GitError, OSError) as e:
        # A broken antibody must never block the agent. Fail open and tell the user.
        return Reply(broken, quiet, f"antibody hook: {e}")


def edited_paths(event: dict) -> list[Path]:
    """Files an edit event touched: a path argument, or the files in a Codex patch."""
    args = event.get("tool_input") or event.get("toolArgs") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {"command": args}
    found: list[str] = []
    if isinstance(args, dict):
        for key in ("file_path", "filePath", "path", "absolute_path"):
            if isinstance(args.get(key), str):
                found.append(args[key])
        patch = args.get("command") or args.get("patch") or args.get("input")
        if isinstance(patch, list):
            patch = "\n".join(map(str, patch))
        if isinstance(patch, str):
            found += PATCH_FILE.findall(patch)
    base = _cwd(event)
    return list(dict.fromkeys(p if p.is_absolute() else base / p for p in map(Path, found)))


def _claude(event: dict, engine_name: str | None) -> Reply:
    if _event_name(event) in ("Stop", "SubagentStop"):
        return _block_stop(event, engine_name)
    verdict = hook.check_paths(edited_paths(event), engine_name)
    return Reply(2, "", verdict.explain(EDIT_LEAD)) if verdict.new else Reply()


def _codex(event: dict, engine_name: str | None) -> Reply:
    if _event_name(event) == "Stop":
        return _block_stop(event, engine_name, quiet="{}")
    return _add_context(event, engine_name, "PostToolUse")


def _gemini(event: dict, engine_name: str | None) -> Reply:
    if _event_name(event) not in ("AfterTool", ""):
        return Reply(stdout="{}")
    return _add_context(event, engine_name, "AfterTool")


def _cursor(event: dict, engine_name: str | None) -> Reply:
    finished = event.get("status", "completed") == "completed"
    if not finished or int(event.get("loop_count") or 0) >= MAX_FOLLOWUPS:
        return Reply(stdout="{}")
    verdict = hook.check_turn(_cwd(event), engine_name)
    if not verdict.new:
        return Reply(stdout="{}")
    return Reply(stdout=json.dumps({"followup_message": verdict.explain(TURN_LEAD)}))


def _copilot(event: dict, engine_name: str | None) -> Reply:
    return _block_stop(event, engine_name, quiet="{}")


def _block_stop(event: dict, engine_name: str | None, quiet: str = "") -> Reply:
    """Make the agent keep going until new matches are fixed, at most once per stop."""
    if event.get("stop_hook_active") or event.get("stopHookActive"):
        return Reply(stdout=quiet)  # already sent back once; CI and pre-commit still catch it
    verdict = hook.check_turn(_cwd(event), engine_name)
    if not verdict.new:
        return Reply(stdout=quiet)
    return Reply(stdout=json.dumps({"decision": "block", "reason": verdict.explain(TURN_LEAD)}))


def _add_context(event: dict, engine_name: str | None, event_name: str) -> Reply:
    verdict = hook.check_paths(edited_paths(event), engine_name)
    if not verdict.new:
        return Reply(stdout="{}")
    context = {"hookEventName": event_name, "additionalContext": verdict.explain(EDIT_LEAD)}
    return Reply(stdout=json.dumps({"hookSpecificOutput": context}))


def _event_name(event: dict) -> str:
    return str(event.get("hook_event_name") or event.get("hookEventName") or "")


def _cwd(event: dict) -> Path:
    roots = event.get("workspace_roots") or []
    for candidate in (event.get("cwd"), roots[0] if roots else None):
        if isinstance(candidate, str) and Path(candidate).is_dir():
            return Path(candidate)
    return Path(os.getcwd())


# agent -> (respond, stdout when there's nothing to say, exit code when antibody itself fails)
ADAPTERS: dict[str, tuple[Callable[[dict, str | None], Reply], str, int]] = {
    "claude": (_claude, "", 1),  # 1: a non-blocking error the user sees
    "codex": (_codex, "{}", 1),
    "gemini": (_gemini, "{}", 1),  # any code but 2 is a warning
    "cursor": (_cursor, "{}", 1),  # fails open
    "copilot": (_copilot, "{}", 0),  # agentStop's handling of other codes isn't documented
}
