"""Opt-in local transport policy, not an OS sandbox for third-party programs."""

from __future__ import annotations

import ipaddress
import os
import urllib.error
import urllib.parse
import urllib.request


def local_only_enabled() -> bool:
    value = os.environ.get("ECC_LOCAL_ONLY", "").strip().lower()
    if value not in {"", "0", "false", "1", "true"}:
        raise ValueError("Modo local: ECC_LOCAL_ONLY deve ser 1 ou 0.")
    return value in {"1", "true"}


def require_provider_allowed(provider: str) -> None:
    if local_only_enabled() and provider != "ollama":
        raise ValueError("Modo local: provedor externo bloqueado; selecione Ollama.")


def local_base_url(value: str) -> str:
    """Allow literal loopback only; normalize localhost without DNS lookup."""
    try:
        parsed = urllib.parse.urlsplit(value)
        host = parsed.hostname
        if host == "localhost":
            host = "127.0.0.1"
        if (
            parsed.scheme != "http" or not host
            or not ipaddress.ip_address(host).is_loopback
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or not (1 <= (parsed.port or 80) <= 65535)
        ):
            raise ValueError
        authority = f"[{host}]" if ":" in host else host
        return f"http://{authority}:{parsed.port or 80}"
    except ValueError:
        raise ValueError("Modo local: endpoint deve ser HTTP loopback sem credenciais ou caminho.") from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.URLError("Modo local: redirecionamento bloqueado.")


def open_local(request: urllib.request.Request, timeout: float):
    parsed = urllib.parse.urlsplit(request.full_url)
    local_base_url(urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", "")))
    if parsed.path not in {"/api/show", "/api/chat", "/api/tags", "/api/version"} or parsed.query or parsed.fragment:
        raise ValueError("Modo local: rota bloqueada.")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    return opener.open(request, timeout=timeout)
