import ast
from typing import Set, Tuple


def make_async(code: str) -> Tuple[bool, str]:
    code_lines = code.splitlines()
    async_code = ["async def __async_cell__():"]
    global_vars = get_globals(code)
    if global_vars:
        async_code.append("    global " + ", ".join(global_vars))
    else:
        async_code.append("    # no global variable")
    async_code += ["    " + line for line in code_lines[:-1]]
    last_line = code_lines[-1]
    return_value = False
    if not last_line.startswith((" ", "\t")):
        try:
            n = ast.parse(last_line)
        except Exception:
            pass
        else:
            if n.body and type(n.body[0]) is ast.Expr:
                return_value = True
    if return_value:
        async_code.append("    globals().update(locals())")
        async_code.append("    return " + last_line)
    else:
        async_code.append("    " + last_line)
        async_code.append("    globals().update(locals())")
    return return_value, "\n".join(async_code)


def get_globals(code: str) -> Set[str]:
    try:
        root = ast.parse(code)
    except Exception:
        return set()
    c = GlobalUseCollector()
    c.visit(root)
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
