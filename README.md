[![Build Status](https://github.com/davidbrochart/akernel/workflows/CI/badge.svg)](https://github.com/davidbrochart/akernel/actions)

# akernel

An asynchronous Python Jupyter kernel built on AnyIO:
- runs in a separate process or in-process.
- supports top-level `await`.

## Install

For a standalone, out-of-process kernel, install the `subprocess` extra:

```bash
pip install "akernel[subprocess]"
```

This will give you a `Python 3 (akernel)` in JupyterLab.

`akernel` can also run in-process with [Jupyverse](https://github.com/jupyter-server/jupyverse).
Install it with:

```bash
pip install "fps-akernel-task"
```

This will give you both `Python 3 (akernel-task)` and `Python 3 (akernel-thread)` kernels
in JupyterLab.

| Kernelspec | Execution in Jupyverse | Interrupt mode |
| --- | --- | --- |
| `akernel` | Separate process | Signal |
| `akernel-task` | In-process, on the server event loop | Message |
| `akernel-thread` | In-process, in a worker thread | Message |

To refresh the kernelspecs in an existing installation, run:

```bash
akernel install --mode process
akernel install --mode task
akernel install --mode thread
```

The default mode is `process`.

## In-process kernels

`akernel-task` runs in Jupyverse's process, so running blocking user code in the kernel
will also block Jupyverse.

`akernel-thread` is an in-process kernel that runs user code in a separate thread,
which won't block Jupyverse.

## Limitations

- Cell output redirection currently uses the kernel's `print` function rather
  than capturing all writes to `stdout` and `stderr`.
- In-process kernels cannot be interrupted while running blocking code.
