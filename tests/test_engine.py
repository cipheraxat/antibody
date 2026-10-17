from antibody import engine


def test_the_engine_installed_with_antibody_comes_first(monkeypatch):
    monkeypatch.delenv("ANTIBODY_ENGINE", raising=False)
    monkeypatch.setattr(engine, "_beside", lambda n: f"/venv/bin/{n}" if n == "semgrep" else None)
    monkeypatch.setattr(engine, "_on_path", lambda n: f"/usr/local/bin/{n}")
    assert engine.find_engine() == engine.Engine("semgrep", "/venv/bin/semgrep")


def test_opengrep_comes_before_semgrep_on_path(monkeypatch):
    monkeypatch.delenv("ANTIBODY_ENGINE", raising=False)
    monkeypatch.setattr(engine, "_beside", lambda n: None)
    monkeypatch.setattr(engine, "_on_path", lambda n: f"/usr/local/bin/{n}")
    assert engine.find_engine() == engine.Engine("opengrep", "/usr/local/bin/opengrep")


def test_an_engine_path_in_the_environment_wins(monkeypatch, tmp_path):
    binary = tmp_path / "opengrep_osx_arm64"
    binary.write_text("")
    monkeypatch.setenv("ANTIBODY_ENGINE", str(binary))
    assert engine.find_engine() == engine.Engine("opengrep", str(binary))
