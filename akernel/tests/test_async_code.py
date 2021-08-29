from textwrap import dedent

from akernel.code import Transform


def test_globals_in_if():
    code = dedent(
        """
        if True:
            a = 1
        elif False:
            b = 2
        else:
            c = 3
        d = 4
        """
    ).strip()
    assert Transform(code).globals == set(("a", "b", "c", "d"))


def test_globals_in_for():
    code = dedent(
        """
        for i in [0]:
            a = 1
        """
    ).strip()
    assert Transform(code).globals == set(("a", "i"))


def test_globals_not_attribute():
    code = dedent(
        """
        class Foo:
            pass
        f = Foo()
        f.a = 1
        """
    ).strip()
    assert Transform(code).globals == set(("Foo", "f"))


def test_globals_not_in_func():
    code = dedent(
        """
        def foo():
            a = 1
        """
    ).strip()
    assert Transform(code).globals == set()


def test_globals_in_func():
    code = dedent(
        """
        def foo():
            global a
            a + 1
        """
    ).strip()
    assert Transform(code).globals == set(("a"))


def test_async_last_line_expr():
    code = dedent(
        """
        a
        """
    ).strip()
    expected = dedent(
        """
        async def __async_cell__():
            global a
            globals().update(locals())
            return a
        """
    ).strip()
    assert Transform(code).get_async_code() == expected


def test_async_last_line_not_expr():
    code = dedent(
        """
        a = 1
        """
    ).strip()
    expected = dedent(
        """
        async def __async_cell__():
            global a
            a = 1
            globals().update(locals())
        """
    ).strip()
    assert Transform(code).get_async_code() == expected
