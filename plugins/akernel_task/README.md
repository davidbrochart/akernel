# fps-akernel-task

An FPS plugin for the kernel task API.

## Development installation

Install both packages from the repository root, in the environment running Jupyverse:

```bash
python -m pip install -e . -e plugins/akernel_task
```

Installing only the plugin can resolve its `akernel` dependency from PyPI instead
of this checkout. While working on unreleased kernel API changes, the plugin and
kernel must come from the same checkout. Restart Jupyverse after reinstalling.
