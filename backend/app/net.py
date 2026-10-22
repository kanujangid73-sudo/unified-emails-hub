"""Checks on hosts users ask the server to connect to.

IMAP and SMTP hosts are typed in by users. Without a check, someone could point the server at
an address on its own private network (a database, a cloud metadata service) and use the
error messages to probe it. This is server-side request forgery (SSRF).
"""

import ipaddress
import socket

from .config import settings


class UnsafeHostError(ValueError):
    pass


def check_public_host(host: str, port: int) -> None:
    """Raise UnsafeHostError unless every address `host` resolves to is on the public internet."""
    if settings.allow_private_hosts:
        return
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeHostError(f"Unknown host {host!r}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise UnsafeHostError(f"{host!r} is not a public internet address")
