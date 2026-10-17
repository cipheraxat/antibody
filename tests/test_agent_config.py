import json
import os

import pytest

from antibody import agent_config
from antibody.agent_config import (
    SETUPS,
    START,
    detect,
    install_git_hook,
    install_hook,
    write_agents_md,
)
from antibody.cli import main
from antibody.rules import AntibodyError


def read(repo, path) -> dict:
    return json.loads((repo.root / path).read_text())


def test_every_agent_hook_is_added_once(repo):
    for agent, setup in SETUPS.items():
        assert install_hook(repo.root, agent)
        assert not install_hook(repo.root, agent)
        assert len(read(repo, setup.settings)["hooks"][setup.event]) == 1


def test_each_agent_gets_its_own_format(repo):
    for agent in SETUPS:
        install_hook(repo.root, agent)
    claude = read(repo, ".claude/settings.json")["hooks"]["PostToolUse"][0]
    assert claude["matcher"] == "Edit|Write" and claude["hooks"][0]["args"] == ["hook", "claude"]
    codex = read(repo, ".codex/hooks.json")["hooks"]["PostToolUse"][0]
    assert codex["matcher"] == "apply_patch|Edit|Write"
    assert codex["hooks"][0]["command"] == "antibody hook codex"
    gemini = read(repo, ".gemini/settings.json")["hooks"]["AfterTool"][0]
    assert gemini["matcher"] == "write_file|replace" and gemini["hooks"][0]["timeout"] == 60000
    cursor = read(repo, ".cursor/hooks.json")
    assert cursor["version"] == 1 and cursor["hooks"]["stop"][0]["command"] == "antibody hook cursor"
    copilot = read(repo, ".github/hooks/antibody.json")
    assert copilot["version"] == 1 and copilot["hooks"]["agentStop"][0]["command"] == "antibody hook copilot"


def test_existing_settings_and_hooks_are_kept(repo):
    existing = {
        "model": "gemini-3-pro",
        "hooks": {"AfterTool": [{"matcher": "run_shell_command", "hooks": [{"type": "command", "command": "audit"}]}]},
    }
    repo.write(".gemini/settings.json", json.dumps(existing))
    install_hook(repo.root, "gemini")
    data = read(repo, ".gemini/settings.json")
    assert data["model"] == "gemini-3-pro"
    assert data["hooks"]["AfterTool"][0] == existing["hooks"]["AfterTool"][0]
    assert len(data["hooks"]["AfterTool"]) == 2


def test_a_settings_file_that_isnt_json_is_left_alone(repo):
    repo.write(".cursor/hooks.json", "{ not json")
    with pytest.raises(AntibodyError, match="add the hook by hand"):
        install_hook(repo.root, "cursor")
    assert (repo.root / ".cursor/hooks.json").read_text() == "{ not json"


def test_detect_finds_the_agents_a_repo_uses(repo):
    repo.write("CLAUDE.md", "# notes\n")
    (repo.root / ".cursor").mkdir()
    repo.write(".github/copilot-instructions.md", "be nice\n")
    assert detect(repo.root) == ["claude", "cursor", "copilot"]


def test_agents_md_section_is_added_then_kept_current(repo):
    repo.write("AGENTS.md", "# Project\n\nRun the tests with make.\n")
    assert write_agents_md(repo.root) == "updated"
    path = repo.root / "AGENTS.md"
    text = path.read_text()
    assert text.startswith("# Project") and START in text and "antibody check --since HEAD" in text
    assert write_agents_md(repo.root) is None  # nothing changed
    path.write_text(text.replace("antibody check --since HEAD", "stale advice"))
    assert write_agents_md(repo.root) == "updated"
    assert "stale advice" not in path.read_text() and path.read_text().count(START) == 1


def test_git_hook_is_installed_once(repo):
    path = install_git_hook(repo.root)
    assert path and os.access(path, os.X_OK) and "antibody check --staged" in path.read_text()
    assert install_git_hook(repo.root) is None


def test_init_sets_up_the_detected_agents_and_any_agent(repo, capsys):
    (repo.root / ".cursor").mkdir()
    assert main(["init", "--repo", str(repo.root)]) == 0
    out = capsys.readouterr().out
    for path in (".antibodies", ".agents/skills/antibody/SKILL.md", "AGENTS.md", ".cursor/hooks.json"):
        assert (repo.root / path).exists() and path in out
    assert not (repo.root / ".claude").exists()
    assert "cursor hook: checks at the end of each turn" in out


def test_init_all_and_unknown_agents(repo, capsys):
    assert main(["init", "--agent", "all", "--repo", str(repo.root)]) == 0
    assert all((repo.root / s.settings).exists() for s in SETUPS.values())
    assert (repo.root / agent_config.SKILL_DIRS["claude"] / "antibody/SKILL.md").exists()
    assert main(["init", "--agent", "claude,vim", "--repo", str(repo.root)]) == 2
    assert "unknown agent vim" in capsys.readouterr().err
