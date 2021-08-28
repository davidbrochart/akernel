import ast
import gast  # type: ignore
from types import CodeType

body_globals_update_locals = gast.parse("globals().update(locals())").body


class Transform:
    def __init__(self, source: str) -> None:
        self.tree = ast.parse(source)
        self.gtree = gast.ast_to_gast(self.tree)
        c = GlobalUseCollector()
        c.visit(self.tree)
        self.globals = set(c.globals)

    def get_async_ast(self) -> ast.Module:
        last_statement = self.gtree.body[-1]
        return_value = type(last_statement) is gast.Expr
        new_body = []
        if self.globals:
            new_body += [gast.Global(names=list(self.globals))]
        if return_value:
            new_body += (
                self.gtree.body[:-1]
                + body_globals_update_locals
                + [gast.Return(value=last_statement.value)]
            )
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
        tree = gast.gast_to_ast(gtree)
        ast.fix_missing_locations(tree)
        return tree

    def get_async_code(self) -> str:
        tree = self.get_async_ast()
        code = ast.unparse(tree)
        return code

    def get_async_bytecode(self) -> CodeType:
        tree = self.get_async_ast()
        bytecode = compile(tree, filename="<string>", mode="exec")
        return bytecode

    def get_globals(self) -> set[str]:
        c = GlobalUseCollector()
        c.visit(self.tree)
        return set(c.globals)


# see https://stackoverflow.com/questions/43166571/
# getting-all-the-nodes-from-python-ast-that-correspond-to-a-particular-variable-w


class GlobalUseCollector(ast.NodeVisitor):
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
