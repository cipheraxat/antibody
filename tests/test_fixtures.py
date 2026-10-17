from antibody.fixtures import check_fixture, expectations


def test_expectations_python_and_js_comments():
    text = """\
# ruleid: r1
bad()
# ok: r1
good()
// ruleid: r1, r2
alsoBad()
# ruleid: other
unrelated()
"""
    must, must_not = expectations(text, "r1")
    assert must == {2, 6}
    assert must_not == {4}


def test_code_that_looks_like_an_annotation_is_still_code():
    must, must_not = expectations("# ruleid: r1\nok: bool = True\n", "r1")
    assert must == {2}
    assert must_not == set()


def test_check_fixture(engine, tmp_path):
    rule = tmp_path / "r1.yml"
    rule.write_text(
        "rules:\n  - id: r1\n    message: m\n    severity: ERROR\n    languages: [python]\n"
        "    pattern: eval(...)\n"
    )
    good = tmp_path / "r1.py"
    good.write_text("# ruleid: r1\neval(x)\n# ok: r1\nint(x)\n")
    assert check_fixture(engine, rule, "r1", good) == []

    bad = tmp_path / "r1.py"
    bad.write_text("# ok: r1\neval(x)\n# ruleid: r1\nint(x)\n")
    problems = check_fixture(engine, rule, "r1", bad)
    assert "r1.py:4: expected a match (ruleid)" in problems
    assert "r1.py:2: matched a line marked ok" in problems
