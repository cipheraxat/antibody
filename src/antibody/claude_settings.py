"""Add antibody's edit hook to a Claude Code settings file, leaving everything else alone."""

from __future__ import annotations

import json
from pathlib import Path

from .rules import AntibodyError

MATCHER = "Edit|Write"
HOOK = {
    "type": "command",
    "command": "antibody",
    "args": ["hook", "claude"],
    "timeout": 60,
    "statusMessage": "antibody: checking edit",
}


def install_hook(settings: Path) -> bool:
    """Returns False if the hook was already there."""
    try:
        data = json.loads(settings.read_text()) if settings.exists() else {}
    except json.JSONDecodeError as e:
        raise AntibodyError(f"{settings}: not valid JSON ({e}); add the hook by hand") from None
    if not isinstance(data, dict):
        raise AntibodyError(f"{settings}: expected a JSON object")
    groups = data.setdefault("hooks", {}).setdefault("PostToolUse", [])
    for group in groups:
        for hook in group.get("hooks", []):
            if hook.get("command") == "antibody" and hook.get("args", [])[:1] == ["hook"]:
                return False
    groups.append({"matcher": MATCHER, "hooks": [HOOK]})
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(data, indent=2) + "\n")
    return True
