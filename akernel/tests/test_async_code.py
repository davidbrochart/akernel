from textwrap import dedent

from akernel.code import get_globals


def test_vars_in_if():
    code = dedent(
        """\
        if True:
            a = 1
        elif False:
            b = 2
        else:
            c = 3
        d = 4
    """
    )
    assert get_globals(code=code) == set(("a", "b", "c", "d"))


def test_vars_in_for():
    code = dedent(
        """\
        for i in [0]:
            a = 1
    """
    )
    assert get_globals(code=code) == set(("a", "i"))


def test_vars_not_attribute():
    code = dedent(
        """\
        class Foo:
            pass
        f = Foo()
        f.a = 1
    """
    )
    assert get_globals(code=code) == set(("Foo", "f"))


def test_vars_not_in_func():
    code = dedent(
        """\
        def foo():
            a = 1
    """
    )
    assert get_globals(code=code) == set()
