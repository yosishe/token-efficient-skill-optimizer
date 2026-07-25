"""Block accidental Python network access during deterministic CI tests."""

import os
import socket


if os.environ.get("TESO_BLOCK_NETWORK") == "1":
    class NetworkBlockedError(RuntimeError):
        pass


    def _blocked(*_args, **_kwargs):
        raise NetworkBlockedError(
            "network access is disabled in the deterministic test phase")


    socket.create_connection = _blocked
    socket.getaddrinfo = _blocked
    socket.socket.connect = _blocked
    socket.socket.connect_ex = _blocked
    socket.socket.sendto = _blocked
    if hasattr(socket.socket, "sendmsg"):
        socket.socket.sendmsg = _blocked
