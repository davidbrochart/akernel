import copy

import gast  # type: ignore
from types import CodeType
from textwrap import dedent


code_declare = dedent(
    """
    if 'var' not in globals() and 'var' not in locals():
        var = ipyx.X(n='var')
    """
).strip()

code_assign = dedent(
    """
    __ipyx_tmp__ = rhs
    if 'lhs' not in globals() and 'lhs' not in locals():
        if isinstance(__ipyx_tmp__, ipyx.X):
            if isinstance(__ipyx_tmp__.v, ipywidgets.Widget):
                lhs = __ipyx_tmp__.v
            else:
                lhs = __ipyx_tmp__
                lhs.n = 'lhs'
        else:
            lhs = ipyx.X(__ipyx_tmp__)
            lhs.n = 'lhs'
    elif isinstance(lhs, ipyx.X):
        if isinstance(__ipyx_tmp__, ipyx.X):
            lhs.v = __ipyx_tmp__.v
        else:
            lhs.v = __ipyx_tmp__
    elif isinstance(__ipyx_tmp__, ipyx.X) and isinstance(__ipyx_tmp__.v, ipywidgets.Widget):
        lhs = __ipyx_tmp__.v
    else:
        lhs = __ipyx_tmp__
    """
).strip()

code_return = dedent(
    """
    __ipyx_tmp__ = expr
    if isinstance(__ipyx_tmp__, ipyx.X):
        return __ipyx_tmp__.w
    return __ipyx_tmp__
    """
).strip()

body_declare = gast.parse(code_declare).body
body_assign = gast.parse(code_assign).body
body_return = gast.parse(code_return).body


def get_declare_body(lhs: str):
    body = copy.deepcopy(body_declare)
    body[0].test.values[0].left.value = lhs  # type: ignore
    body[0].test.values[1].left.value = lhs  # type: ignore
    body[0].body[0].targets[0].id = lhs  # type: ignore
    body[0].body[0].value.keywords[0].value.value = lhs  # type: ignore
    return body


def get_assign_body(lhs: str, rhs):
    body = copy.deepcopy(body_assign)
    body[0].value = rhs
    body[1].test.values[0].left.value = lhs  # type: ignore
    body[1].test.values[1].left.value = lhs  # type: ignore
    body[1].body[0].body[0].body[0].targets[0].id = lhs  # type: ignore
    body[1].body[0].body[0].orelse[0].targets[0].id = lhs  # type: ignore
    body[1].body[0].body[0].orelse[1].targets[0].value.id = lhs  # type: ignore
    body[1].body[0].body[0].orelse[1].value.value = lhs  # type: ignore
    body[1].body[0].orelse[0].targets[0].id = lhs  # type: ignore
    body[1].body[0].orelse[1].targets[0].value.id = lhs  # type: ignore
    body[1].body[0].orelse[1].value.value = lhs  # type: ignore
    body[1].orelse[0].test.args[0].id = lhs  # type: ignore
    body[1].orelse[0].body[0].body[0].targets[0].value.id = lhs  # type: ignore
    body[1].orelse[0].body[0].orelse[0].targets[0].value.id = lhs  # type: ignore
    body[1].orelse[0].orelse[0].body[0].targets[0].id = lhs  # type: ignore
    body[1].orelse[0].orelse[0].orelse[0].targets[0].id = lhs  # type: ignore
    return body


def get_return_body(val):
    body = copy.deepcopy(body_return)
    body[0].value = val
    return body


body_globals_update_locals = gast.parse("globals().update(locals())").body


class Transform:
    def __init__(self, code: str, react: bool = False) -> None:
        self.gtree = gast.parse(code)
        self.react = react
        c = GlobalUseCollector()
        c.visit(self.gtree)
        self.globals = set(c.globals)
        self.last_statement = self.gtree.body[-1]
        if react:
            self.make_react()

    def get_async_ast(self) -> gast.Module:
        new_body = []
        if self.globals:
            new_body += [gast.Global(names=list(self.globals))]
        if isinstance(self.last_statement, gast.Expr):
            self.gtree.body.remove(self.last_statement)
            if self.react:
                last_statement = get_return_body(self.last_statement.value)
            else:
                last_statement = [gast.Return(value=self.last_statement.value)]
            new_body += self.gtree.body + body_globals_update_locals + last_statement
        else:
            new_body += self.gtree.body + body_globals_update_locals
        body = [
            gast.AsyncFunctionDef(
                name="__async_cell__",
                args=gast.arguments(
                    args=[],
                    posonlyargs=[],
                    vararg=None,
                    kwonlyargs=[],
                    kw_defaults=[],
                    kwarg=None,
                    defaults=[],
                ),
                body=new_body,
                decorator_list=[],
                returns=None,
                type_comment=None,
            ),
        ]
        gtree = gast.Module(body=body, type_ignores=[])
        gast.fix_missing_locations(gtree)
        return gtree

    def get_code(self) -> str:
        return gast.unparse(self.gtree)

    def get_async_code(self) -> str:
        gtree = self.get_async_ast()
        return gast.unparse(gtree)

    def get_async_bytecode(self) -> CodeType:
        gtree = self.get_async_ast()
        tree = gast.gast_to_ast(gtree)
        bytecode = compile(tree, filename="<string>", mode="exec")
        return bytecode

    def make_react(self):
        for node in gast.walk(self.gtree):
            if not isinstance(node, gast.FunctionDef) and hasattr(node, "body"):
                new_body = []
                for statement in node.body:
                    if isinstance(statement, gast.Assign):
                        if len(statement.targets) == 1 and isinstance(
                            statement.targets[0], gast.Name
                        ):
                            # RHS
                            rhs_calls = [
                                n
                                for n in gast.walk(statement.value)
                                if isinstance(n, gast.Call)
                            ]
                            for n in rhs_calls:
                                ipyx_name = gast.Name(id="ipyx", ctx=gast.Load())
                                n.func = gast.Call(
                                    func=gast.Attribute(
                                        value=ipyx_name, attr="F", ctx=gast.Load()
                                    ),
                                    args=[n.func],
                                    keywords=[],
                                )
                            rhs_name_ids = [
                                n.id
                                for n in gast.walk(statement.value)
                                if isinstance(n, gast.Name) and n.id != "ipyx"
                            ]
                            for name_id in rhs_name_ids:
                                new_body += get_declare_body(name_id)
                            # LHS
                            new_body += get_assign_body(
                                statement.targets[0].id,
                                statement.value,
                            )
                            continue
                    new_body.append(statement)
                if new_body:
                    node.body = new_body


# see https://stackoverflow.com/questions/43166571/
# getting-all-the-nodes-from-python-ast-that-correspond-to-a-particular-variable-w


class GlobalUseCollector(gast.NodeVisitor):
    def __init__(self):
        self.globals = []
        # track context name and set of names marked as `global`
        self.context = [("global", ())]

    def visit_FunctionDef(self, node):
        self.context.append(("function", set()))
        self.generic_visit(node)
        self.context.pop()

    # treat coroutines the same way
    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.context.append(("class", ()))
        self.generic_visit(node)
        self.context.pop()

    def visit_Lambda(self, node):
        # lambdas are just functions, albeit with no statements, so no assignments
        self.context.append(("function", ()))
        self.generic_visit(node)
        self.context.pop()

    def visit_Global(self, node):
        if self.context[-1][0] == "function":
            self.context[-1][1].update(node.names)

    def visit_Name(self, node):
        ctx, g = self.context[-1]
        if ctx == "global" or node.id in g:
            self.globals.append(node.id)
