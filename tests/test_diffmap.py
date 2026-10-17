from antibody.diffmap import diff_lines


def test_replaced_line():
    d = diff_lines(["a", "b", "c"], ["a", "B", "c"])
    assert d.old_to_new == {1: 1, 3: 3}
    assert d.old_sites == [(2, 2)]
    assert d.added == [(2, 2)]


def test_insertion_marks_the_lines_around_it():
    d = diff_lines(["a", "c"], ["a", "b", "c"])
    assert d.old_to_new == {1: 1, 2: 3}
    assert d.old_sites == [(1, 2)]
    assert d.added == [(2, 2)]


def test_insertion_at_top():
    d = diff_lines(["a"], ["z", "a"])
    assert d.old_to_new == {1: 2}
    assert d.old_sites == [(1, 1)]
    assert d.added == [(1, 1)]


def test_deletion():
    d = diff_lines(["a", "b", "c"], ["a", "c"])
    assert d.old_to_new == {1: 1, 3: 2}
    assert d.old_sites == [(2, 2)]
    assert d.added == []


def test_added_and_deleted_files():
    assert diff_lines(None, ["x", "y"]).added == [(1, 2)]
    assert diff_lines(["x"], None).old_sites == [(1, 1)]


def test_near_change_uses_window():
    old = [f"line {i}" for i in range(1, 41)]
    d = diff_lines(old, old[:9] + ["changed"] + old[10:])
    assert d.old_sites == [(10, 10)]
    assert d.near_change(30, 31, window=25)
    assert not d.near_change(36, 36, window=25)


def test_touches_added():
    d = diff_lines(["a", "b", "c"], ["a", "B", "c"])
    assert d.touches_added(1, 2)
    assert not d.touches_added(3, 3)
