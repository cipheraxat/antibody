from collections import Counter

from conftest import rule_file

from antibody import baseline
from antibody.cli import main
from antibody.engine import Finding
from antibody.rules import load
from antibody.verify import prove

FSTRING_SQL = '    pattern: $CUR.execute(f"...", ...)\n'


def test_fingerprint_ignores_position_and_indentation():
    a = baseline.fingerprint(["x = 1", "  cur.execute(f'{q}')"], Finding("r", "p", 2, 2))
    b = baseline.fingerprint(["cur.execute(f'{q}')"], Finding("r", "p", 1, 1))
    assert a == b


def test_a_second_copy_of_an_accepted_match_is_new():
    key = ("r", "app.py", "abc")
    pairs = [(key, Finding("r", "app.py", 3, 3)), (key, Finding("r", "app.py", 9, 9))]
    assert baseline.new_matches(pairs, Counter({key: 1})) == [Finding("r", "app.py", 9, 9)]
    assert baseline.new_matches(pairs, Counter({key: 2})) == []


def test_save_replaces_only_the_named_rules(repo):
    (repo.root / ".antibodies").mkdir()
    baseline.save(repo.root, Counter({("a", "x.py", "1"): 1, ("b", "y.py", "2"): 2}), {"a", "b"})
    baseline.save(repo.root, Counter({("a", "z.py", "3"): 1}), {"a"})
    assert baseline.load(repo.root) == Counter({("a", "z.py", "3"): 1, ("b", "y.py", "2"): 2})


def test_check_fails_only_on_new_matches(sqli, engine, capsys):
    repo, fix = sqli
    path = rule_file(repo, "sql-fstring", FSTRING_SQL, fix)
    load(path).write_stamp(prove(load(path), repo.root, engine).stamp(engine))
    args = ["--repo", str(repo.root)]

    assert main(["check", *args]) == 1  # report.py repeats the mistake and nothing is accepted yet
    assert main(["baseline", *args]) == 0
    assert "accepted 1 match from 1 antibody" in capsys.readouterr().out
    assert main(["check", *args]) == 0
    assert "(1 accepted or older)" in capsys.readouterr().out

    repo.write("app/export.py", 'def export(cur, t):\n    cur.execute(f"SELECT * FROM {t}")\n')
    assert main(["check", *args]) == 1
    assert "app/export.py:2  [sql-fstring]" in capsys.readouterr().out

    assert main(["check", "--since", "HEAD", "--no-baseline", *args]) == 1  # new since HEAD
    repo.commit("Add export")
    assert main(["check", "--since", "HEAD", "--no-baseline", *args]) == 0  # nothing changed since
    assert main(["check", "--since", "HEAD~1", "--no-baseline", *args]) == 1
