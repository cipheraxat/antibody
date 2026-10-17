from conftest import rule_file

from antibody.rules import load
from antibody.verify import counts_for_proof, prove

FSTRING_SQL = '    pattern: $CUR.execute(f"...", ...)\n'


def test_passes_when_rule_fires_on_the_bug_and_not_the_fix(sqli, engine):
    repo, fix = sqli
    proof = prove(load(rule_file(repo, "sql-fstring", FSTRING_SQL, fix)), repo.root, engine)
    assert proof.passed, proof.problems()
    assert [f.location for f in proof.fires_on] == ["app/search.py:2"]
    assert proof.flags_fix == []


def test_fails_when_rule_also_flags_the_fix(sqli, engine):
    repo, fix = sqli
    path = rule_file(repo, "any-execute", "    pattern: $CUR.execute(...)\n", fix)
    proof = prove(load(path), repo.root, engine)
    assert not proof.passed
    assert [f.location for f in proof.flags_fix] == ["app/search.py:2"]
    assert "fires on code the fix wrote: app/search.py:2" in proof.problems()


def test_fails_when_rule_never_fires(sqli, engine):
    repo, fix = sqli
    proof = prove(load(rule_file(repo, "shell", "    pattern: os.system(...)\n", fix)), repo.root, engine)
    assert not proof.passed
    assert "no matches in the code before the fix" in proof.problems()[0]


def test_guard_inserted_before_an_unchanged_sink(repo, engine):
    repo.write(
        "files.py",
        "import os\nBASE = '/srv'\n\ndef read(name):\n"
        "    path = os.path.join(BASE, name)\n"
        "    with open(path) as f:\n"
        "        return f.read()\n",
    )
    repo.commit("Serve files")
    repo.write(
        "files.py",
        "import os\nBASE = '/srv'\n\ndef read(name):\n"
        "    path = os.path.join(BASE, name)\n"
        "    if not os.path.realpath(path).startswith(BASE + os.sep):\n"
        "        raise ValueError('path escapes BASE')\n"
        "    with open(path) as f:\n"
        "        return f.read()\n",
    )
    fix = repo.commit("Reject paths that escape BASE")
    body = (
        "    patterns:\n"
        "      - pattern-inside: |\n"
        "          $P = os.path.join(...)\n"
        "          ...\n"
        "      - pattern-not-inside: |\n"
        "          if <... os.path.realpath($P) ...>:\n"
        "            ...\n"
        "          ...\n"
        "      - pattern: open($P, ...)\n"
    )
    proof = prove(load(rule_file(repo, "path-join-open", body, fix)), repo.root, engine)
    assert proof.passed, proof.problems()
    assert [f.location for f in proof.fires_on] == ["files.py:6"]


def test_reports_matches_the_fix_left_behind(repo, engine):
    query = "    cur.execute(f\"SELECT {x}\")\n"
    repo.write("db.py", "def a(cur, x):\n" + query + "\n\ndef b(cur, x):\n" + query)
    repo.commit("Add queries")
    repo.write("db.py", "def a(cur, x):\n    cur.execute('SELECT ?', (x,))\n\n\ndef b(cur, x):\n" + query)
    fix = repo.commit("Fix query in a")
    proof = prove(load(rule_file(repo, "sql-fstring", FSTRING_SQL, fix)), repo.root, engine)
    assert proof.passed
    assert [f.location for f in proof.fires_on] == ["db.py:2"]
    assert [f.location for f in proof.survivors] == ["db.py:6"]


def test_antibody_committed_with_its_fix_is_left_out(sqli, engine):
    repo, _ = sqli
    repo.write("app/search.py", repo.root.joinpath("app/search.py").read_text())
    repo.write("app/report.py", "def report(cur, owner):\n    cur.execute('SELECT 1', ())\n")
    path = rule_file(repo, "sql-fstring", FSTRING_SQL)
    repo.write(".antibodies/sql-fstring.py", '# ruleid: sql-fstring\ncur.execute(f"{x}")\n')
    fix = repo.commit("Fix report and add its antibody")
    antibody = load(path)
    antibody.set_source_commit(fix)
    proof = prove(antibody, repo.root, engine)
    assert proof.passed, proof.problems()
    assert proof.fixtures == 1


def test_fixture_problems_fail_the_proof(sqli, engine):
    repo, fix = sqli
    path = rule_file(repo, "sql-fstring", FSTRING_SQL, fix)
    repo.write(".antibodies/sql-fstring.py", '# ok: sql-fstring\ncur.execute(f"{x}")\n')
    proof = prove(load(path), repo.root, engine)
    assert not proof.passed
    assert proof.problems() == ["sql-fstring.py:2: matched a line marked ok"]


def test_stamp_is_written_once(sqli, engine):
    repo, fix = sqli
    path = rule_file(repo, "sql-fstring", FSTRING_SQL, fix)
    proof = prove(load(path), repo.root, engine)
    assert load(path).write_stamp(proof.stamp(engine))
    stamped = path.read_text()
    assert "verified:" in stamped and "- app/search.py:2" in stamped
    assert not load(path).write_stamp(proof.stamp(engine))
    assert path.read_text() == stamped


def test_counts_for_proof():
    assert counts_for_proof("app/search.py")
    assert counts_for_proof("src/testing_utils.py")
    assert not counts_for_proof("tests/test_search.py")
    assert not counts_for_proof("app/search_test.go")
    assert not counts_for_proof("web/search.spec.ts")
    assert not counts_for_proof(".antibodies/sql-fstring.py")
