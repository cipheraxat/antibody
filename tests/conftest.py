import subprocess
from pathlib import Path

import pytest

from antibody.engine import EngineError, find_engine


@pytest.fixture(scope="session")
def engine():
    try:
        return find_engine()
    except EngineError as e:
        pytest.skip(str(e))


class Repo:
    def __init__(self, root: Path):
        self.root = root

    def git(self, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True, text=True
        )
        return proc.stdout.strip()

    def write(self, path: str, text: str) -> Path:
        dest = self.root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
        return dest

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    r = Repo(tmp_path / "repo")
    r.root.mkdir()
    r.git("init", "-q")
    r.git("config", "user.email", "dev@example.com")
    r.git("config", "user.name", "Dev")
    r.git("config", "commit.gpgsign", "false")
    return r


SEARCH_VULNERABLE = """\
def search(cur, term):
    cur.execute(f"SELECT * FROM items WHERE name = '{term}'")
    return cur.fetchall()
"""

SEARCH_FIXED = """\
def search(cur, term):
    cur.execute("SELECT * FROM items WHERE name = ?", (term,))
    return cur.fetchall()
"""

REPORT = """\
def report(cur, owner):
    cur.execute(f"SELECT * FROM reports WHERE owner = '{owner}'")
    return cur.fetchall()
"""


@pytest.fixture
def sqli(repo):
    """A repo where the fix parameterized one query and missed its twin in report.py."""
    repo.write("app/search.py", SEARCH_VULNERABLE)
    repo.write("app/report.py", REPORT)
    repo.commit("Add search and reports")
    repo.write("app/search.py", SEARCH_FIXED)
    # The fix's own test builds SQL with an f-string; tests stay out of the proof.
    repo.write("tests/test_search.py", 'def test_it(cur):\n    cur.execute(f"SELECT {1}")\n')
    fix = repo.commit("Use a parameterized query in search")
    return repo, fix


def rule_file(repo: Repo, rule_id: str, body: str, commit: str | None = None) -> Path:
    """Write .antibodies/<rule_id>.yml; `body` is the rule's pattern section, indented 4."""
    source = (
        f"    metadata:\n      antibody:\n        source:\n          commit: {commit}\n"
        if commit
        else ""
    )
    return repo.write(
        f".antibodies/{rule_id}.yml",
        f"rules:\n  - id: {rule_id}\n    message: test rule\n    severity: ERROR\n"
        f"    languages: [python]\n{body}{source}",
    )


FSTRING_SQL = '    pattern: $CUR.execute(f"...", ...)\n'


@pytest.fixture
def guarded(sqli, engine):
    """The sqli repo with a verified antibody for SQL built from f-strings."""
    from antibody.rules import load
    from antibody.verify import prove

    repo, fix = sqli
    path = rule_file(repo, "sql-fstring", FSTRING_SQL, fix)
    load(path).write_stamp(prove(load(path), repo.root, engine).stamp(engine))
    return repo, fix
