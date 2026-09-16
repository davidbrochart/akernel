from __future__ import annotations
import __future__

import ast
from dataclasses import dataclass
from inspect import CO_COROUTINE
from types import CodeType
from typing import Any

from .traceback import get_traceback

FUTURE_FLAGS = sum(getattr(__future__, name).compiler_flag for name in __future__.all_feature_names)


@dataclass
class CompiledCell:
    body: CodeType
    expression: CodeType | None


def compile_cell(code: str, task_i: int = 0) -> CompiledCell:
    filename = f"<cell-{task_i}>"
    tree = ast.parse(code, filename=filename)
    flags = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
    # Validate the entire cell before executing any part of it. This also
    # determines future-import flags needed by the final expression.
    full_code = compile(tree, filename, "exec", flags=flags, dont_inherit=True)
    flags |= full_code.co_flags & FUTURE_FLAGS
    expression = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        expression = compile(
            ast.Expression(tree.body.pop().value),
            filename,
            "eval",
            flags=flags,
            dont_inherit=True,
        )
    body = compile(tree, filename, "exec", flags=flags, dont_inherit=True)
    return CompiledCell(body, expression)


def prepare_cell(code: str, task_i: int = 0, execution_count: int = 0):
    traceback = []
    exception = None
    cell = None
    try:
        cell = compile_cell(code, task_i)
    except SyntaxError as exc:
        exception = exc
        traceback = get_traceback(
            code, exception, None, execution_count, {f"<cell-{task_i}>": code}
        )
    return cell, traceback, exception


async def execute_cell(cell: CompiledCell, namespace: dict[str, Any]) -> Any:
    result = eval(cell.body, namespace)
    if cell.body.co_flags & CO_COROUTINE:
        await result
    if cell.expression is not None:
        result = eval(cell.expression, namespace)
        if cell.expression.co_flags & CO_COROUTINE:
            result = await result
        return result
    return None
