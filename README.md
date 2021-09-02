[![Build Status](https://github.com/davidbrochart/akernel/workflows/CI/badge.svg)](https://github.com/davidbrochart/akernel/actions)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/davidbrochart/akernel/HEAD?urlpath=lab%2Ftree%2Fexamples%2Freactivity.ipynb)

# akernel

An asynchronous Python Jupyter kernel, with optional reactive programming.

## Install

```bash
pip install akernel
```

If you want to be able to use reactive programming:

```bash
pip install akernel[react]
```

Note that it will just add [ipyx](https://github.com/davidbrochart/ipyx), which you could also
install later if you want (`pip install ipyx`).

You can switch between reactive and non-reactive modes by entering (you will need to restart your kernel):

```bash
akernel install react  # enable reactive mode
akernel install async  # disable reactive mode (default)
```

## Motivation

[ipykernel](https://github.com/ipython/ipykernel) offers the ability to
[run asynchronous code from the REPL](https://ipython.readthedocs.io/en/stable/interactive/autoawait.html).
This means you can `await` at the top-level, outside of an async function. Unfortunately, this will still
block the kernel.

akernel changes this behavior by launching each cell in a task.

akernel now also supports reactive programming, although it is still experimental!

## Features

### Asynchronous execution

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

### Reactivity

One feature other notebooks offer is the ability to have variables react to other variables'
changes. [Observable notebooks](https://observablehq.com/@observablehq/how-observable-runs) are a
good example of this, and it can give a whole new user experience. For instance, you can run cells
out of order:

```python
# cell 1
a = b + 1  # "b" is not defined yet
a
```

Executing cell 1 won't result in an "undefined variable" error. Instead, the *result* of the
operation is undefined, and the output of cell 1 is `None`. You can then continue with the
definition of `b`:

```python
# cell 2
b = 2  # triggers the computation of "a" in cell 1
```

Now `a`, which depends on `b`, is automatically updated, and the output of cell 1 is `3`.

You can of course define much more complex data flows, by defining variables on top of other ones.

![screencast](https://user-images.githubusercontent.com/591645/131855258-35118507-6be2-44cb-9329-143ad8509405.gif)

## Limitations

It is still a work in progress, in particular:

- `stdout`/`stderr` redirection to the cell output is only supported through the `print` function.
- No rich representation for now, only the standard `__repr__` is supported. This means no
  matplotlib figure yet :-( But since ipywidgets work, why not using
  [ipympl](https://github.com/matplotlib/ipympl)? :-)
