"""Keep tests off the internet while letting the machine talk to itself.

Page tests patch `socket.socket.connect` with `connect` here:

    unittest.mock.patch("socket.socket.connect", offline.connect)

Any address outside this machine fails at once with "offline in tests".
Loopback (127.0.0.1, ::1, localhost) and local Unix sockets go through:
on Windows, asyncio's event loop (which Streamlit's AppTest starts) makes
its self-pipe with `socket.socketpair()`, and that is a loopback connect.
"""
from __future__ import annotations

import ipaddress
import socket
import sys

_REAL_CONNECT = socket.socket.connect
MESSAGE = "offline in tests"


def is_loopback(address) -> bool:
    """True for an address on this machine: loopback IPs, localhost, Unix paths."""
    if isinstance(address, (str, bytes)):          # AF_UNIX path
        return True
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    host = str(host).strip("[]").split("%", 1)[0]
    if host.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback


def connect(self, address):
    """`socket.socket.connect` for tests: loopback only, anything else raises."""
    if is_loopback(address):
        return _REAL_CONNECT(self, address)
    raise RuntimeError(MESSAGE)


def no_ai_sink():
    """Point ai_spend at no database, and every module that holds it at the
    current copy. An app run (dashboard.py) sets it to that run's scratch
    database, and codefresh may have reloaded modules since, so ai_gateway can
    hold an older copy than `import ai_spend` gives - a later test would then
    be refused "unchecked" by a database that is gone."""
    import gc
    import types
    current = sys.modules.get("ai_spend")
    for obj in gc.get_objects():
        if not isinstance(obj, types.ModuleType):
            continue
        if obj.__name__ == "ai_spend" and callable(getattr(obj, "use_db", None)):
            obj.use_db(None)
        held = obj.__dict__.get("ai_spend")
        if current is not None and isinstance(held, types.ModuleType) and held is not current:
            obj.ai_spend = current
