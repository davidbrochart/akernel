class IP:
    def __init__(self):
        from ...kernel import KERNEL

        self.kernel = KERNEL


def get_ipython():
    return IP()
