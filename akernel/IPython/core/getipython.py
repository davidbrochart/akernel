class IP:
    def __init__(self):
        from akernel.kernel import KERNEL

        self.kernel = KERNEL

    def showtraceback(self):
        pass

    def register_post_execute(self, func):
        pass


def get_ipython():
    return IP()
