import pickle
import zlib

from zict import File, Func, LRU  # type: ignore

l4 = File(".akernel_cache/", mode="a")
l3 = Func(zlib.compress, zlib.decompress, l4)
l2 = Func(pickle.dumps, pickle.loads, l3)
l1 = LRU(100, l2)
