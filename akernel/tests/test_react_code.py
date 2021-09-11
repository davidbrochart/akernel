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
            if isinstance(1, ipyx.X):
                a = 1
            else:
                a = ipyx.X(1)
        elif isinstance(a, ipyx.X):
            if isinstance(1, ipyx.X):
                a.v = 1 .v
            else:
                a.v = 1
        else:
            a = 1
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
            if isinstance(b, ipyx.X):
                a = b
            else:
                a = ipyx.X(b)
        elif isinstance(a, ipyx.X):
            if isinstance(b, ipyx.X):
                a.v = b.v
            else:
                a.v = b
        else:
            a = b
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
        if 'foo' not in globals() and 'foo' not in locals():
            foo = ipyx.X()
        if 'a' not in globals() and 'a' not in locals():
            if isinstance(ipyx.F(foo)(b), ipyx.X):
                a = ipyx.F(foo)(b)
            else:
                a = ipyx.X(ipyx.F(foo)(b))
        elif isinstance(a, ipyx.X):
            if isinstance(ipyx.F(foo)(b), ipyx.X):
                a.v = ipyx.F(foo)(b).v
            else:
                a.v = ipyx.F(foo)(b)
        else:
            a = ipyx.F(foo)(b)
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
        if 'foo' not in globals() and 'foo' not in locals():
            foo = ipyx.X()
        if 'b' not in globals() and 'b' not in locals():
            b = ipyx.X()
        if 'bar' not in globals() and 'bar' not in locals():
            bar = ipyx.X()
        if 'a' not in globals() and 'a' not in locals():
            if isinstance(ipyx.F(foo)(ipyx.F(bar)(b)), ipyx.X):
                a = ipyx.F(foo)(ipyx.F(bar)(b))
            else:
                a = ipyx.X(ipyx.F(foo)(ipyx.F(bar)(b)))
        elif isinstance(a, ipyx.X):
            if isinstance(ipyx.F(foo)(ipyx.F(bar)(b)), ipyx.X):
                a.v = ipyx.F(foo)(ipyx.F(bar)(b)).v
            else:
                a.v = ipyx.F(foo)(ipyx.F(bar)(b))
        else:
            a = ipyx.F(foo)(ipyx.F(bar)(b))
        """
    ).strip()
    assert Transform(code, react=True).get_code() == expected
