"""Each agent's hook protocol, with events shaped as in that tool's hook documentation."""

import json
from pathlib import Path

import pytest
from conftest import REPORT

from antibody import agents, hook
from antibody.engine import EngineError

REPEAT_LOCATION = "app/report.py:7"


def repeat(repo) -> Path:
    """Bring the mistake back in report.py: a new match at line 7, next to an old one at 2."""
    path = repo.root / "app/report.py"
    path.write_text(REPORT + '\n\ndef again(cur, x):\n    cur.execute(f"SELECT {x}")\n')
    return path


def handle(agent: str, event: dict) -> agents.Reply:
    return agents.handle(agent, json.dumps(event))


def codex_edit(repo) -> dict:
    patch = "*** Begin Patch\n*** Update File: app/report.py\n@@\n+def again(cur, x):\n*** End Patch\n"
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "apply_patch",
        "cwd": str(repo.root),
        "tool_input": {"command": patch},
    }


def gemini_edit(path: Path) -> dict:
    return {
        "hook_event_name": "AfterTool",
        "tool_name": "write_file",
        "tool_input": {"file_path": str(path), "content": "..."},
    }


def test_codex_finds_the_file_in_the_patch_and_adds_context(guarded):
    repo, _ = guarded
    repeat(repo)
    reply = handle("codex", codex_edit(repo))
    output = json.loads(reply.stdout)["hookSpecificOutput"]
    assert reply.code == 0
    assert output["hookEventName"] == "PostToolUse"
    assert f"{REPEAT_LOCATION}  [sql-fstring]" in output["additionalContext"]


def test_codex_says_nothing_when_the_edit_is_clean(guarded):
    repo, _ = guarded
    assert handle("codex", codex_edit(repo)) == agents.Reply(stdout="{}")


def test_gemini_adds_context_after_write_file(guarded):
    repo, _ = guarded
    reply = handle("gemini", gemini_edit(repeat(repo)))
    output = json.loads(reply.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "AfterTool"
    assert REPEAT_LOCATION in output["additionalContext"]


def test_cursor_sends_a_followup_when_the_turn_ends(guarded):
    repo, _ = guarded
    repeat(repo)  # however the file changed, even through a shell command
    event = {"hook_event_name": "stop", "status": "completed", "loop_count": 0, "workspace_roots": [str(repo.root)]}
    message = json.loads(handle("cursor", event).stdout)["followup_message"]
    assert REPEAT_LOCATION in message and "Fix them, then finish" in message


def test_cursor_lets_the_agent_stop_after_two_followups_or_an_abort(guarded):
    repo, _ = guarded
    repeat(repo)
    roots = [str(repo.root)]
    assert handle("cursor", {"status": "completed", "loop_count": 2, "workspace_roots": roots}).stdout == "{}"
    assert handle("cursor", {"status": "aborted", "loop_count": 0, "workspace_roots": roots}).stdout == "{}"


def test_copilot_blocks_the_stop_once(guarded):
    repo, _ = guarded
    repeat(repo)
    output = json.loads(handle("copilot", {"cwd": str(repo.root), "stop_hook_active": False}).stdout)
    assert output["decision"] == "block" and REPEAT_LOCATION in output["reason"]
    assert handle("copilot", {"cwd": str(repo.root), "stop_hook_active": True}).stdout == "{}"


def test_turn_end_checks_catch_untracked_files(guarded):
    repo, _ = guarded
    repo.write("app/new.py", 'def q(cur, x):\n    cur.execute(f"SELECT {x}")\n')
    output = json.loads(handle("copilot", {"cwd": str(repo.root)}).stdout)
    assert "app/new.py:2" in output["reason"]


def test_claude_stop_hook_blocks_once(guarded):
    repo, _ = guarded
    repeat(repo)
    stop = {"hook_event_name": "Stop", "cwd": str(repo.root), "stop_hook_active": False}
    assert json.loads(handle("claude", stop).stdout)["decision"] == "block"
    assert handle("claude", {**stop, "stop_hook_active": True}) == agents.Reply()


@pytest.mark.parametrize("agent", agents.AGENTS)
def test_a_broken_engine_never_blocks_the_agent(guarded, monkeypatch, agent):
    repo, _ = guarded
    path = repeat(repo)

    def broken(*_):
        raise EngineError("no rule engine found")

    monkeypatch.setattr(hook, "find_engine", broken)
    event = {
        "hook_event_name": {"codex": "PostToolUse", "gemini": "AfterTool"}.get(agent, ""),
        "cwd": str(repo.root),
        "workspace_roots": [str(repo.root)],
        "tool_input": {"file_path": str(path)},
    }
    reply = handle(agent, event)
    assert reply.code != 2
    assert "decision" not in reply.stdout and "followup_message" not in reply.stdout
    assert "antibody hook: no rule engine found" in reply.stderr


def test_edited_paths_from_each_tool(tmp_path):
    assert agents.edited_paths({"tool_input": {"file_path": "/abs/a.py"}}) == [Path("/abs/a.py")]
    assert agents.edited_paths({"toolArgs": json.dumps({"filePath": "/abs/b.ts"})}) == [Path("/abs/b.ts")]
    patch = (
        "*** Begin Patch\n*** Add File: src/new.py\n+x = 1\n*** Update File: src/old.py\n"
        "*** Move to: src/moved.py\n*** Delete File: gone.py\n*** End Patch"
    )
    expected = [tmp_path / "src/new.py", tmp_path / "src/old.py", tmp_path / "src/moved.py"]
    assert agents.edited_paths({"cwd": str(tmp_path), "tool_input": {"command": patch}}) == expected
    as_argv = {"cwd": str(tmp_path), "tool_input": {"command": ["apply_patch", patch]}}
    assert agents.edited_paths(as_argv) == expected
