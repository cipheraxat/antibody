import io
import json

import pytest
from conftest import REPORT, rule_file

from antibody import hook
from antibody.cli import main
from antibody.rules import load
from antibody.verify import prove

FSTRING_SQL = '    pattern: $CUR.execute(f"...", ...)\n'


def edit(path) -> str:
    return json.dumps(
        {"hook_event_name": "PostToolUse", "tool_name": "Edit", "tool_input": {"file_path": str(path)}}
    )


@pytest.fixture
def guarded(sqli, engine):
    """The sqli repo with a verified antibody for SQL built from f-strings."""
    repo, fix = sqli
    path = rule_file(repo, "sql-fstring", FSTRING_SQL, fix)
    load(path).write_stamp(prove(load(path), repo.root, engine).stamp(engine))
    return repo, fix


def test_blocks_an_edit_that_repeats_the_mistake(guarded):
    repo, fix = guarded
    report = repo.root / "app/report.py"
    report.write_text(REPORT + '\n\ndef again(cur, x):\n    cur.execute(f"SELECT {x}")\n')
    code, message = hook.claude(edit(report))
    assert code == 2
    assert "app/report.py:7  [sql-fstring]" in message
    assert f"learned from {fix[:12]}" in message


def test_old_matches_in_an_edited_file_dont_block(guarded):
    repo, _ = guarded
    report = repo.root / "app/report.py"
    report.write_text(REPORT + "\n# an unrelated edit\n")  # report.py:2 matched before this edit
    assert hook.claude(edit(report)) == (0, "")


def test_files_no_antibody_covers_never_start_the_engine(guarded, monkeypatch):
    repo, _ = guarded
    monkeypatch.setattr(hook, "find_engine", lambda *_: pytest.fail("engine started"))
    readme = repo.write("README.md", "# notes\n")
    assert hook.claude(edit(readme)) == (0, "")
    test_file = repo.write("tests/test_more.py", 'cur.execute(f"{x}")\n')
    assert hook.claude(edit(test_file)) == (0, "")


def test_events_without_a_file_are_ignored(tmp_path):
    assert hook.claude("not json") == (0, "")
    assert hook.claude(json.dumps({"tool_input": {"command": "ls"}})) == (0, "")
    assert hook.claude(edit(tmp_path / "missing.py")) == (0, "")


def test_cli_passes_the_exit_code_and_message_through(guarded, monkeypatch, capsys):
    repo, _ = guarded
    path = repo.write("app/new.py", 'def q(cur, x):\n    cur.execute(f"SELECT {x}")\n')
    monkeypatch.setattr("sys.stdin", io.StringIO(edit(path)))
    assert main(["hook", "claude"]) == 2
    assert "app/new.py:2  [sql-fstring]" in capsys.readouterr().err
