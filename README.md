[![Build Status](https://github.com/davidbrochart/akernel/workflows/CI/badge.svg)](https://github.com/davidbrochart/akernel/actions)

# akernel

An asynchronous Python Jupyter kernel built on AnyIO. Cells execute sequentially
and share one namespace. Top-level `await` lets cooperative cell code yield while
the kernel handles messages and interrupts.

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

This will give you both `Python 3 (akernel)` and `Python 3 (akernel-thread)` kernels
in JupyterLab.

## In-process kernels

They run in Jupyverse's process, so running blocking user code in the kernel
will also block Jupyverse. `akernel-thread` is an in-process kernel that runs
user code in a separate thread, which won't block Jupyverse.

## Limitations

- Cell output redirection currently uses the kernel's `print` function rather
  than capturing all writes to `stdout` and `stderr`.
- In-process kernels cannot be interrupted while running blocking code.
