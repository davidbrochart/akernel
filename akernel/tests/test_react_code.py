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
        for name_ipyxv in list(locals().keys()):
            if name_ipyxv.endswith('_ipyxv'):
                del locals()[name_ipyxv]
        if 'name_ipyxv' in locals():
            del name_ipyxv
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
        if isinstance(b, ipyx.X):
            b_ipyxv = b.v
        else:
            b_ipyxv = b
        if 'a' not in globals() and 'a' not in locals():
            a = b
        else:
            a.v = b_ipyxv
        for name_ipyxv in list(locals().keys()):
            if name_ipyxv.endswith('_ipyxv'):
                del locals()[name_ipyxv]
        if 'name_ipyxv' in locals():
            del name_ipyxv
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
        if isinstance(b, ipyx.X):
            b_ipyxv = b.v
        else:
            b_ipyxv = b
        if 'a' not in globals() and 'a' not in locals():
            a = ipyx.F(foo)(b)
        else:
            a.v = foo(b_ipyxv)
        for name_ipyxv in list(locals().keys()):
            if name_ipyxv.endswith('_ipyxv'):
                del locals()[name_ipyxv]
        if 'name_ipyxv' in locals():
            del name_ipyxv
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
        if isinstance(b, ipyx.X):
            b_ipyxv = b.v
        else:
            b_ipyxv = b
        if 'a' not in globals() and 'a' not in locals():
            a = ipyx.F(foo)(ipyx.F(bar)(b))
        else:
            a.v = foo(bar(b_ipyxv))
        for name_ipyxv in list(locals().keys()):
            if name_ipyxv.endswith('_ipyxv'):
                del locals()[name_ipyxv]
        if 'name_ipyxv' in locals():
            del name_ipyxv
        """
    ).strip()
    assert Transform(code, react=True).get_code() == expected
