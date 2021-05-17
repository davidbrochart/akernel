import typer

from .kernel import Kernel
from .kernelspec import write_kernelspec


cli = typer.Typer()


@cli.command()
def install(
    kernel_name: str = typer.Argument(..., help="Name of the kernel to install.")
):
    write_kernelspec("akernel", kernel_name, "Python 3")


@cli.command()
def launch(
    kernel_name: str = typer.Argument(..., help="Name of the kernel to launch."),
    connection_file: str = typer.Option(..., "-f", help="Path to the connection file."),
):
    Kernel(kernel_name, connection_file)


if __name__ == "__main__":
    cli()
