from .comm import Comm


class CommManager:
    def __init__(self):
        from ..kernel import KERNEL

        self.kernel = KERNEL
        self.comms = {}
        self.targets = {}

    def register_target(self, target_name, callback):
        self.targets[target_name] = callback

    def unregister_target(self, target_name, callback):
        return self.targets.pop(target_name)

    def register_comm(self, comm):
        comm_id = comm.comm_id
        comm.kernel = self.kernel
        self.comms[comm_id] = comm
        return comm_id

    def unregister_comm(self, comm):
        comm = self.comms.pop(comm.comm_id)

    def get_comm(self, comm_id):
        return self.comms.get(comm_id, None)

    def comm_open(self, stream, ident, msg):
        content = msg["content"]
        comm_id = content["comm_id"]
        target_name = content["target_name"]
        f = self.targets.get(target_name, None)
        comm = Comm(
            comm_id=comm_id,
            primary=False,
            target_name=target_name,
        )
        self.register_comm(comm)
        if f is not None:
            f(comm, msg)
        else:
            comm.close()

    def comm_msg(self, stream, ident, msg):
        content = msg["content"]
        comm_id = content["comm_id"]
        comm = self.get_comm(comm_id)
        if comm is not None:
            comm.handle_msg(msg)

    def comm_close(self, stream, ident, msg):
        content = msg["content"]
        comm_id = content["comm_id"]
        comm = self.get_comm(comm_id)
        if comm is not None:
            self.comms[comm_id]._closed = True
            del self.comms[comm_id]
            comm.handle_close(msg)
