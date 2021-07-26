[![Build Status](https://github.com/davidbrochart/akernel/workflows/CI/badge.svg)](https://github.com/davidbrochart/akernel/actions)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

# akernel

An asynchronous Python Jupyter kernel.

## Motivation

[ipykernel](https://github.com/ipython/ipykernel) offers the ability to
[run asynchronous code from the REPL](https://ipython.readthedocs.io/en/stable/interactive/autoawait.html).
This means you can `await` at the top-level, outside of a function. Unfortunately, this will still
block the kernel.

akernel changes this behavior by launching each cell in a task.

## Features

akernel allows for asynchronous code execution. What this means is that when used in a Jupyter
notebook, you can run cells concurrently if the code is cooperative. For instance, you can run a
cell with the following code:

```python
# cell 1
for i in range(10):
    print("cell 1:", i)
    await asyncio.sleep(1)
```

Since this cell is `async` (it has an `await`), it will not block the execution of other cells.
So you can run another cell concurrently, provided that this cell is also cooperative:

```python
# cell 2
for j in range(10):
    print("cell 2:", j)
    await asyncio.sleep(1)
```

If cell 2 was blocking, cell 1 would pause until cell 2 was finished. You can see that by changing
`await asyncio.sleep(1)` into `time.sleep(1)` in cell 2.

You can make a cell wait for the previous one to be finished with:

```python
# cell 3
await __task__()  # wait for cell 2 to be finished
print("cell 2 has run")
```

## Limitations

It is still a work in progress, in particular:

- `stdout`/`stderr` redirection to the cell output is only supported through the `print` function.
- No rich representation for now, only the standard `__repr__` is supported. This means no
  matplotlib figure yet :-( But ipywidgets should work!
- If the cell code has multiline strings, they must be wrapped with the `textwrap.dedent` function.
