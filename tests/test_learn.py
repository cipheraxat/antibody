from conftest import SEARCH_FIXED, SEARCH_VULNERABLE

from antibody.cli import main
from antibody.learn import covers, learn
from antibody.rules import load
from antibody.verify import COMMIT, FIXTURES_ONLY, WORKTREE, prove

FSTRING_SQL = 'pattern: $CUR.execute(f"...", ...)'


def fill(path, pattern=FSTRING_SQL):
    path.write_text(path.read_text().replace("pattern: TODO", pattern))


def test_uncommitted_fix_is_proven_then_pinned_once_committed(repo, engine, capsys):
    repo.write("app/search.py", SEARCH_VULNERABLE)
    base = repo.commit("Add search")
    repo.write("app/search.py", SEARCH_FIXED)  # the fix, not committed yet
    repo.write("app/params.py", "def bind(term):\n    return (term,)\n")  # an untracked file

    brief = learn(repo.root, antibody_id="sql-fstring")
    assert "uncommitted changes on top of" in brief.text
    assert "+++ b/app/params.py" in brief.text
    assert load(brief.path).source["base"] == base

    fill(brief.path)
    proof = prove(load(brief.path), repo.root, engine)
    assert proof.passed, proof.problems()
    assert proof.kind == WORKTREE
    assert [f.location for f in proof.fires_on] == ["app/search.py:2"]

    fix = repo.commit("Parameterize search")
    assert main(["verify", "sql-fstring", "--repo", str(repo.root)]) == 0
    assert "pinned" in capsys.readouterr().out
    antibody = load(brief.path)
    assert antibody.source["commit"] == fix and antibody.source["vulnerable"] == base
    assert "base" not in antibody.source
    assert antibody.verified["proof"] == COMMIT


def test_clean_tree_learns_from_head(sqli):
    repo, _ = sqli
    assert learn(repo.root).path.name == "use-a-parameterized-query-in-search.yml"


def test_fixtures_only_needs_both_kinds_of_line(repo, engine):
    repo.write("app/log.py", "import logging\nlog = logging.getLogger(__name__)\n")
    repo.commit("Add logging")
    brief = learn(repo.root, antibody_id="no-print", fixtures_only=True)
    assert "the fixture is the proof" in brief.text
    assert "languages: [python]" in brief.path.read_text()
    fill(brief.path, "pattern: print(...)")

    fixture = brief.path.with_suffix(".py")
    fixture.write_text("# ruleid: no-print\nprint('saved', order)\n")
    proof = prove(load(brief.path), repo.root, engine)
    assert not proof.passed
    assert "needs at least one `ruleid:` line and one `ok:` line" in proof.problems()[0]

    fixture.write_text("# ruleid: no-print\nprint('saved', order)\n# ok: no-print\nlog.info('saved %s', order)\n")
    proof = prove(load(brief.path), repo.root, engine)
    assert proof.passed, proof.problems()
    assert proof.kind == FIXTURES_ONLY
    assert proof.stamp(engine)["fixtures"] == 1


def test_covers():
    assert covers(["python"], "app/x.py")
    assert covers(["js"], "web/x.tsx")
    assert covers(["generic"], "notes.md")
    assert not covers(["python"], "README.md")
