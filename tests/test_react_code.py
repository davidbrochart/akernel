from textwrap import dedent

from akernel.code import Transform, code_assign, code_declare


def test_assign_constant():
    code = dedent(
        """
        a = 1
        """
    ).strip()
    expected = code_assign.replace("lhs", "a").replace("rhs.v", "1 .v").replace("rhs", "1")
    assert Transform(code, react=True).get_code() == expected


def test_assign_variable():
    code = dedent(
        """
        a = b
        """
    ).strip()
    expected = (
        code_declare.replace("var", "b")
        + "\n"
        + code_assign.replace("lhs", "a").replace("rhs", "b")
    )
    assert Transform(code, react=True).get_code() == expected


def test_assign_call():
    code = dedent(
        """
        a = foo(b)
        """
    ).strip()
    expected = (
        code_declare.replace("var", "b")
        + "\n"
        + code_declare.replace("var", "foo")
        + "\n"
        + code_assign.replace("lhs", "a").replace("rhs", "ipyx.F(foo)(b)")
    )
    assert Transform(code, react=True).get_code() == expected


def test_assign_nested_call():
    code = dedent(
        """
        a = foo(bar(b))
        """
    ).strip()
    expected = (
        code_declare.replace("var", "foo")
        + "\n"
        + code_declare.replace("var", "b")
        + "\n"
        + code_declare.replace("var", "bar")
        + "\n"
        + code_assign.replace("lhs", "a").replace("rhs", "ipyx.F(foo)(ipyx.F(bar)(b))")
    )
    assert Transform(code, react=True).get_code() == expected
