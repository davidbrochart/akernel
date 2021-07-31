from textwrap import dedent

from akernel.code import Transform


def test_assign_constant():
    code = dedent(
        """
        a = 1
        """
    ).strip()
    expected = dedent(
        """
        if 'a' not in globals() and 'a' not in locals():
            a = 1
        else:
            a.v = 1
        """
    ).strip()
    assert Transform(code, react=True).get_code() == expected


def test_assign_variable():
    code = dedent(
        """
        a = b
        """
    ).strip()
    expected = dedent(
        """
        if 'b' not in globals() and 'b' not in locals():
            b = ipyx.X()
        if 'a' not in globals() and 'a' not in locals():
            a = b
        else:
            a.v = b
        """
    ).strip()
    assert Transform(code, react=True).get_code() == expected


def test_assign_call():
    code = dedent(
        """
        a = foo(b)
        """
    ).strip()
    expected = dedent(
        """
        if 'b' not in globals() and 'b' not in locals():
            b = ipyx.X()
        if 'a' not in globals() and 'a' not in locals():
            a = ipyx.F(foo)(b)
        else:
            a.v = foo(b.v)
        """
    ).strip()
    assert Transform(code, react=True).get_code() == expected


def test_assign_nested_call():
    code = dedent(
        """
        a = foo(bar(b))
        """
    ).strip()
    expected = dedent(
        """
        if 'b' not in globals() and 'b' not in locals():
            b = ipyx.X()
        if 'a' not in globals() and 'a' not in locals():
            a = ipyx.F(foo)(ipyx.F(bar)(b))
        else:
            a.v = foo(bar(b.v))
        """
    ).strip()
    assert Transform(code, react=True).get_code() == expected
