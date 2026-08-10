"""Defensa SSRF para los scrapers: rechaza URLs que resuelven a IPs privadas,
loopback o link-local. Se valida antes de cada fetch y tras cada redirect."""
import ipaddress
import socket
from urllib.parse import urlparse

import httpx


class BlockedURLError(Exception):
    pass


def _ip_is_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def assert_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BlockedURLError(f"Esquema no permitido: {parsed.scheme}")
    host = parsed.hostname
    if not host:
        raise BlockedURLError("URL sin host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise BlockedURLError(f"No se pudo resolver {host}: {exc}")
    for info in infos:
        ip = info[4][0]
        if _ip_is_blocked(ip):
            raise BlockedURLError(f"{host} resuelve a una IP no permitida ({ip})")


def _guard_request(request: httpx.Request) -> None:
    # Se ejecuta también en cada redirect (follow_redirects) → cierra el bypass.
    assert_public_url(str(request.url))


def safe_client(**kwargs) -> httpx.AsyncClient:
    """AsyncClient que valida cada request (incluidos redirects) contra SSRF."""
    kwargs.setdefault("timeout", 30)
    kwargs.setdefault("follow_redirects", True)
    event_hooks = kwargs.pop("event_hooks", {})
    event_hooks.setdefault("request", []).append(_guard_request)
    return httpx.AsyncClient(event_hooks=event_hooks, **kwargs)
