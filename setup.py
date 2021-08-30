import os
from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
version_ns = {}
with open(os.path.join(here, "akernel", "_version.py")) as f:
    exec(f.read(), {}, version_ns)

def get_data_files():
    """Get the data files for the package.
    """
    data_files = [
        ('share/jupyter/kernels/akernel', ['share/jupyter/kernels/akernel/kernel.json']),
    ]
    return data_files

setup(
    name="akernel",
    version=version_ns["__version__"],
    url="https://github.com/davidbrochart/akernel.git",
    author="David Brochart",
    author_email="david.brochart@gmail.com",
    description="An asynchronous Python Jupyter kernel",
    long_description=open("README.md").read(),
    long_description_content_type='text/markdown',
    packages=find_packages(),
    python_requires=">=3.7",
    install_requires=[
        "pyzmq",
        "typer>=0.4.0",
        "click",
        "python-dateutil",
        "colorama",
        "gast",
    ],
    extras_require={
        "test": [
            "mypy",
            "flake8",
            "black",
            "pytest",
            "pytest-asyncio",
            "types-python-dateutil",
            "kernel_driver",
            "ipyx>=0.1.2",
        ],
        "react": [
            "ipyx>=0.1.2",
        ],
    },
    entry_points={
        "console_scripts": ["akernel = akernel.akernel:cli"],
    },
    classifiers=(
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ),
    data_files=get_data_files()
)
