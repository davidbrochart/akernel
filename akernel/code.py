import ast
from typing import Set


def make_async(code: str) -> str:
    code_lines = code.splitlines()
    async_code = ["async def __async_cell__():"]
    global_vars = get_globals(code)
    if global_vars:
        async_code += ["    global " + ", ".join(global_vars)]
    async_code += ["    __result__ = None"]
    async_code += ["    __exception__ = None"]
    async_code += ["    __interrupted__ = False"]
    async_code += ["    try:"]
    async_code += ["        " + line for line in code_lines[:-1]]
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
        async_code += ["        __result__ = " + last_line]
    else:
        async_code += ["        " + last_line]
    async_code += ["    except asyncio.CancelledError:"]
    async_code += ["        __exception__ = RuntimeError('Kernel interrupted')"]
    async_code += ["        __interrupted__ = True"]
    async_code += ["    except KeyboardInterrupt:"]
    async_code += ["        __exception__ = RuntimeError('Kernel interrupted')"]
    async_code += ["        __interrupted__ = True"]
    async_code += ["    except Exception as e:"]
    async_code += ["        __exception__ = e"]
    async_code += ["    globals().update(locals())"]
    async_code += ["    del globals()['__result__']"]
    async_code += ["    del globals()['__exception__']"]
    async_code += ["    if __exception__ is None:"]
    async_code += ["        return __result__"]
    async_code += ["    raise __exception__"]
    return "\n".join(async_code)


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
        assert self.context[-1][0] == "function"
        self.context[-1][1].update(node.names)

    def visit_Name(self, node):
        ctx, g = self.context[-1]
        if ctx == "global" or node.id in g:
            self.globals.append(node.id)
