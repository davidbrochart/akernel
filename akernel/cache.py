import os
import pickle
import sys
import zlib
from typing import Optional

from zict import File, Func, LRU  # type: ignore


def cache(cache_dir: Optional[str]):
    if not cache_dir:
        cache_dir = os.path.join(
            sys.prefix, "share", "jupyter", "kernels", "akernel", "cache"
        )

    l4 = File(cache_dir, mode="a")
    l3 = Func(zlib.compress, zlib.decompress, l4)
    l2 = Func(pickle.dumps, pickle.loads, l3)
    l1 = LRU(100, l2)

    return l1
