import typer

from .kernel import Kernel
from .kernelspec import write_kernelspec


cli = typer.Typer()


@cli.command()
def install(mode: str = typer.Argument(..., help="Mode of the kernel to install.")):
    display_name = f"Python 3 (akernel-{mode})"
    write_kernelspec("akernel", mode, display_name)


@cli.command()
def launch(
    mode: str = typer.Argument(..., help="Mode of the kernel to launch."),
    connection_file: str = typer.Option(..., "-f", help="Path to the connection file."),
):
    Kernel(mode, connection_file)


if __name__ == "__main__":
    cli()
