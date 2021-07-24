class Ip:
    def __init__(self):
        from akernel.kernel import KERNEL

        self.kernel = KERNEL

    def showtraceback(self):
        pass

    def register_post_execute(self, func):
        pass


IP = None


def get_ipython():
    global IP
    if IP is None:
        IP = Ip()
    return IP
