import importlib.metadata

try:
    __version__ = importlib.metadata.version("fps_akernel_task")
except importlib.metadata.PackageNotFoundError:
    __version__ = "unknown"
