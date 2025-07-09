import importlib.metadata

try:
    __version__ = importlib.metadata.version("akernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "unknown"
