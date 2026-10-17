import json

from antibody.cli import main


def run(capsys, repo, *args):
    code = main([*args, "--repo", str(repo.root)])
    return code, capsys.readouterr().out


def test_end_to_end(sqli, capsys):
    repo, fix = sqli
    assert run(capsys, repo, "init")[0] == 0

    code, out = run(capsys, repo, "learn", fix)
    assert code == 0
    assert "# Antibody brief: use-a-parameterized-query-in-search" in out
    assert "-    cur.execute(f\"SELECT * FROM items" in out
    skeleton = repo.root / ".antibodies/use-a-parameterized-query-in-search.yml"
    assert f'commit: "{fix}"' in skeleton.read_text()

    # Learning from the same fix again reuses the skeleton instead of making a second one.
    run(capsys, repo, "learn", fix)
    assert len(list((repo.root / ".antibodies").glob("*.yml"))) == 1

    # The skeleton's TODO pattern never fires, so verify fails until the agent writes a rule.
    assert run(capsys, repo, "verify", "use-a-parameterized-query-in-search")[0] == 1

    skeleton.write_text(skeleton.read_text().replace("pattern: TODO", 'pattern: $CUR.execute(f"...", ...)'))
    code, out = run(capsys, repo, "verify", "use-a-parameterized-query-in-search")
    assert code == 0, out
    assert "fires on    app/search.py:2" in out and "stamped" in out

    code, out = run(capsys, repo, "sweep", "use-a-parameterized-query-in-search")
    assert "1 match" in out and "app/report.py:2" in out

    code, out = run(capsys, repo, "check")
    assert code == 1
    assert "app/report.py:2  [use-a-parameterized-query-in-search]" in out

    code, out = run(capsys, repo, "list", "--json")
    assert json.loads(out)[0]["verified"] is True


def test_check_skips_unverified(sqli, capsys):
    repo, fix = sqli
    run(capsys, repo, "learn", fix)
    code, out = run(capsys, repo, "check")
    assert code == 0
    assert "1 unverified antibody skipped" in out


def test_check_writes_sarif(sqli, capsys, tmp_path):
    repo, _ = sqli
    repo.write(
        ".antibodies/sql-fstring.yml",
        "rules:\n  - id: sql-fstring\n    message: m\n    severity: ERROR\n"
        '    languages: [python]\n    pattern: $CUR.execute(f"...", ...)\n',
    )
    sarif = tmp_path / "out.sarif"
    code, _ = run(capsys, repo, "check", "--include-unverified", "--sarif", str(sarif))
    assert code == 1
    assert json.loads(sarif.read_text())["runs"][0]["results"]


def test_sweep_skips_fixtures_and_tests(sqli, capsys):
    repo, _ = sqli
    repo.write(
        ".antibodies/sql-fstring.yml",
        "rules:\n  - id: sql-fstring\n    message: m\n    severity: ERROR\n"
        '    languages: [python]\n    pattern: $CUR.execute(f"...", ...)\n',
    )
    repo.write(".antibodies/sql-fstring.py", '# ruleid: sql-fstring\ncur.execute(f"{x}")\n')
    _, out = run(capsys, repo, "sweep", "sql-fstring")
    assert "1 match" in out and "app/report.py:2" in out  # not the fixture, not tests/test_search.py


def test_verify_needs_ids_or_all(sqli, capsys):
    repo, _ = sqli
    assert run(capsys, repo, "verify")[0] == 2


def test_init_for_claude_adds_the_hook_and_keeps_existing_settings(sqli, capsys):
    repo, _ = sqli
    settings = repo.root / ".claude/settings.json"
    existing = {"model": "opus", "hooks": {"PostToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "prettier"}]}]}}
    repo.write(".claude/settings.json", json.dumps(existing))

    code, out = run(capsys, repo, "init", "--agent", "claude")
    assert code == 0 and "updated .claude/settings.json" in out
    data = json.loads(settings.read_text())
    assert data["model"] == "opus"
    groups = data["hooks"]["PostToolUse"]
    assert groups[0] == existing["hooks"]["PostToolUse"][0]
    assert groups[1]["matcher"] == "Edit|Write"
    assert groups[1]["hooks"][0]["args"] == ["hook", "claude"]
    assert (repo.root / ".claude/skills/antibody/SKILL.md").is_file()

    run(capsys, repo, "init", "--agent", "claude")  # a second run changes nothing
    assert len(json.loads(settings.read_text())["hooks"]["PostToolUse"]) == 2
