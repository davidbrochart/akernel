from typing import Optional

import typer

from .kernel import Kernel
from .kernelspec import write_kernelspec


cli = typer.Typer()


@cli.command()
def install(
    mode: str = typer.Argument("", help="Mode of the kernel to install."),
    cache_dir: Optional[str] = typer.Option(
        None, "-c", help="Path to the cache directory, if mode is 'cache'."
    ),
):
    name = "akernel"
    if mode:
        name += f"-{mode}"
    display_name = f"Python 3 ({name})"
    write_kernelspec("akernel", mode, display_name, cache_dir)


@cli.command()
def launch(
    mode: str = typer.Argument("", help="Mode of the kernel to launch."),
    cache_dir: Optional[str] = typer.Option(
        None, "-c", help="Path to the cache directory, if mode is 'cache'."
    ),
    connection_file: str = typer.Option(..., "-f", help="Path to the connection file."),
):
    Kernel(mode, cache_dir, connection_file)


if __name__ == "__main__":
    cli()
