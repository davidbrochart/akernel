[![Build Status](https://github.com/davidbrochart/akernel/workflows/CI/badge.svg)](https://github.com/davidbrochart/akernel/actions)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

# akernel

An asynchronous Python Jupyter kernel.

## Features

`akernel` allows for asynchronous code execution. What this means is that when used in a Jupyter
notebook, you can run cells concurrently if the code is cooperative. For instance, you can run a
cell with the following code:

```python
# cell 1
for i in range(10):
    print("cell 1:", i)
    await asyncio.sleep(1)
```

Since this cell is `async` (it has an `await`), it will not block the execution of other cells.
So you can run another cell "in parallel", provided that this cell is also cooperative:

```python
# cell 2
for j in range(10):
    print("cell 2:", j)
    await asyncio.sleep(1)
```

If cell 2 was blocking, cell 1 would pause until cell 2 was finished. You can see that by changing
`await asyncio.sleep(1)` into `time.sleep(1)` in cell 2.

## Limitations

It is still a work in progress, and a bit hacky. In particular:

- Error tracebacks are a bit messy.
- If a cell wants to access a variable of another running cell, this variable must exist before the
  execution of both cells.
- `stdout`/`stderr` redirection to the cell output is only supported through the `print` function.
- The display hook only supports the standard `__repr__` for now (no fancy HTML output or widget
  yet).
- If the cell code has multiline strings, they must be wrapped with the `textwrap.dedent` function.
