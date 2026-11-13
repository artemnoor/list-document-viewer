from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


def is_trusted_internal_endpoint(base_url: str, allowed_hosts: list[str] | None = None) -> bool:
    """Return whether the configured LLM endpoint is loopback or explicitly internal.

    Hostnames outside localhost are accepted only by exact operator allowlist entry.
    This avoids trusting an arbitrary URL merely because LLM_TRUSTED_LOCAL is set.
    """
    try:
        parsed = urlsplit(base_url)
        host = (parsed.hostname or "").rstrip(".").lower()
        if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
            return False
        if parsed.query or parsed.fragment:
            return False
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        address = None
    except Exception:
        return False

    if address is not None:
        return address.is_loopback or address.is_private
    if host == "localhost" or host.endswith(".localhost"):
        return True
    trusted = {item.rstrip(".").lower() for item in (allowed_hosts or []) if item.strip()}
    return host in trusted
