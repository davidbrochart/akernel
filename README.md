[![Build Status](https://github.com/davidbrochart/akernel/workflows/CI/badge.svg)](https://github.com/davidbrochart/akernel/actions)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/davidbrochart/akernel/HEAD?urlpath=lab%2Ftree%2Fexamples%2Freactivity.ipynb)

# akernel

A Python Jupyter kernel, with different flavors:
- concurrent cell execution,
- reactive programming,
- cell execution caching,
- multi-kernel emulation.

## Install

```bash
pip install akernel
# pip install akernel[react]  # if you want to be able to use reactive programming
# pip install akernel[cache]  # if you want to be able to use cell execution caching
```

You can parameterize akernel's execution mode:

```bash
akernel install  # default (chained cell execution mode)
akernel install concurrent  # concurrent cell execution mode
akernel install react  # reactive programming mode
akernel install cache  # cell execution caching  mode
akernel install multi  # multi-kernel emulation mode
akernel install cache-multi-react-concurrent  # you can combine several modes
```

## Motivation

[ipykernel](https://github.com/ipython/ipykernel) offers the ability to
[run asynchronous code from the REPL](https://ipython.readthedocs.io/en/stable/interactive/autoawait.html).
This means you can `await` at the top-level, outside of an async function. Unfortunately, this will still
block the kernel.

akernel changes this behavior by launching each cell in a task. By default, cell tasks are chained, which
means that a cell will start executing after the previous one is done. You might wonder, is it not the same
as ipykernel then? Well, not quite. In ipykernel, when an async cell is executing, it also blocks the
processing of
[Comm messages](https://jupyter-client.readthedocs.io/en/stable/messaging.html#custom-messages), which
prevents the kernel from interacting with e.g. JupyterLab widgets (see
[here](https://github.com/ipython/ipykernel/issues/646) and
[there](https://github.com/ipython/ipykernel/issues/696)). In akernel, it will not be the case.

If you want to go all the way and have cells execute concurrently, you can also do so (see below).

## Features

### Concurrent execution

First, set the concurrent execution mode in order to have async cells execute concurrently
(you could also do that at install-time with `akernel install concurrent`):

```python
__unchain_execution__()
# __chain_execution__()
```

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

### Reactive programming

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

### Cell execution caching

With this mode, cell execution is cached so that the next time a cell is run, its outputs are retrieved from cache (if its inputs didn't change). Inputs and outputs are inferred from the cell code.

### Multi-kernel emulation mode

This mode emulates multiple kernels inside the same kernel. Kernel isolation is achieved by using the session ID of execution requests. You can thus connect multiple notebooks to the same kernel, and they won't share execution state.

This is particularly useful if cells are async, because they won't block the kernel. The same kernel can thus be "shared" and used by potentially a lot of notebooks, greatly reducing resource usage.

## Limitations

It is still a work in progress, in particular:

- `stdout`/`stderr` redirection to the cell output is only supported through the `print` function.
- No rich representation for now, only the standard `__repr__` is supported. This means no
  matplotlib figure yet :-( But since ipywidgets work, why not using
  [ipympl](https://github.com/matplotlib/ipympl)? :-)
