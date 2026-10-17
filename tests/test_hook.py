import io
import json

import pytest
from conftest import REPORT

from antibody import agents, hook
from antibody.cli import main


def edit(path) -> str:
    return json.dumps(
        {"hook_event_name": "PostToolUse", "tool_name": "Edit", "tool_input": {"file_path": str(path)}}
    )


def claude(event: str) -> agents.Reply:
    return agents.handle("claude", event)


def test_blocks_an_edit_that_repeats_the_mistake(guarded):
    repo, fix = guarded
    report = repo.root / "app/report.py"
    report.write_text(REPORT + '\n\ndef again(cur, x):\n    cur.execute(f"SELECT {x}")\n')
    reply = claude(edit(report))
    assert reply.code == 2
    assert "app/report.py:7  [sql-fstring]" in reply.stderr
    assert f"learned from {fix[:12]}" in reply.stderr


def test_old_matches_in_an_edited_file_dont_block(guarded):
    repo, _ = guarded
    report = repo.root / "app/report.py"
    report.write_text(REPORT + "\n# an unrelated edit\n")  # report.py:2 matched before this edit
    assert claude(edit(report)) == agents.Reply()


def test_nosemgrep_with_the_antibody_id_lets_an_edit_through(guarded):
    # The hook's message offers this escape hatch, so it has to work despite Semgrep
    # prefixing local rule ids with their file path.
    repo, _ = guarded
    path = repo.write(
        "app/new.py", 'def q(cur, x):\n    cur.execute(f"SELECT {x}")  # nosemgrep: sql-fstring\n'
    )
    assert claude(edit(path)) == agents.Reply()


def test_files_no_antibody_covers_never_start_the_engine(guarded, monkeypatch):
    repo, _ = guarded
    monkeypatch.setattr(hook, "find_engine", lambda *_: pytest.fail("engine started"))
    readme = repo.write("README.md", "# notes\n")
    assert claude(edit(readme)) == agents.Reply()
    test_file = repo.write("tests/test_more.py", 'cur.execute(f"{x}")\n')
    assert claude(edit(test_file)) == agents.Reply()


def test_events_without_a_file_are_ignored(tmp_path):
    assert claude("not json") == agents.Reply()
    assert claude(json.dumps({"tool_input": {"command": "ls"}})) == agents.Reply()
    assert claude(edit(tmp_path / "missing.py")) == agents.Reply()


def test_cli_passes_the_exit_code_and_message_through(guarded, monkeypatch, capsys):
    repo, _ = guarded
    path = repo.write("app/new.py", 'def q(cur, x):\n    cur.execute(f"SELECT {x}")\n')
    monkeypatch.setattr("sys.stdin", io.StringIO(edit(path)))
    assert main(["hook", "claude"]) == 2
    assert "app/new.py:2  [sql-fstring]" in capsys.readouterr().err
