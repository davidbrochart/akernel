from setuptools import setup

setup(
    name="quenelles",
    version="0.0.1",
    url="https://github.com/davidbrochart/quenelles.git",
    author="David Brochart",
    author_email="david.brochart@gmail.com",
    description="Jupyter kernels that have gone bad",
    packages=["quenelles"],
    python_requires=">=3.7",
    install_requires=[
        "pyzmq",
        "typer",
        "rich",
        "kernel_driver",
    ],
    entry_points={
        "console_scripts": ["quenelles = quenelles.quenelles:cli"],
    },
    classifiers=(
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ),
)
