from setuptools import setup

setup(
    name="akernel",
    version="0.0.2",
    url="https://github.com/davidbrochart/akernel.git",
    author="David Brochart",
    author_email="david.brochart@gmail.com",
    description="Asynchronous Python Jupyter kernel",
    packages=["akernel"],
    python_requires=">=3.7",
    install_requires=[
        "pyzmq",
        "typer",
        "kernel_driver",
    ],
    entry_points={
        "console_scripts": ["akernel = akernel.akernel:cli"],
    },
    classifiers=(
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ),
)
