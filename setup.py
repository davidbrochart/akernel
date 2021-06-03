from setuptools import setup

def get_data_files():
    """Get the data files for the package.
    """
    data_files = [
        ('share/jupyter/kernels/akernel', ['share/jupyter/kernels/akernel/kernel.json']),
    ]
    return data_files

setup(
    name="akernel",
    version="0.0.3",
    url="https://github.com/davidbrochart/akernel.git",
    author="David Brochart",
    author_email="david.brochart@gmail.com",
    description="An asynchronous Python Jupyter kernel",
    packages=["akernel"],
    python_requires=">=3.7",
    install_requires=[
        "pyzmq",
        "typer",
        "click<8",
        "python-dateutil",
    ],
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
