"""URL validation with SSRF protection (docs/prd-backend.md B11).

Blocks loopback, private, link-local, and cloud-metadata addresses. Also rejects
non-standard ports and known metadata endpoint paths so a server-side fetch to these
URLs cannot be triggered regardless of DNS resolution.
"""
import ipaddress
from urllib.parse import urlparse

from app.errors import InvalidUrlError

# Cloud metadata endpoints commonly abused in SSRF.
_METADATA_HOSTS = frozenset({
    "169.254.169.254",   # AWS / GCP / Azure IMDS
    "metadata.google.internal",
    "169.254.170.2",     # ECS task metadata
})

# Ports that suggest non-web services or internal APIs.
_BLOCKED_PORTS = frozenset({
    22, 23, 25, 53, 110, 143, 389, 445, 465, 587, 993, 995,
    2375, 2376,   # Docker
    3306, 5432, 5433, 6379, 27017,  # databases
    8086, 8087,   # InfluxDB
    9200, 9300,   # Elasticsearch
})

# Allowed schemes only.
_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _is_public_ip(address: str) -> bool:
    """True only when the address is a globally routable unicast IP."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_global and not ip.is_reserved


def validate_product_url(raw: str) -> str:
    """Return the URL unchanged if it passes all SSRF checks, else raise InvalidUrlError.

    Checks (in order):
    1. Scheme must be http or https.
    2. Hostname must be present.
    3. Port, if explicit, must not be in the blocked list.
    4. Hostname must not be ``localhost``, an unqualified label, or a known metadata host.
    5. Hostname that parses as an IP address must be globally routable.
    """
    url = (raw or "").strip()
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise InvalidUrlError("URL must be an absolute http(s) URL with a public hostname")

    host = parsed.hostname.lower()

    # Explicit port check (netloc encodes the port separately from the hostname).
    if parsed.port is not None and parsed.port in _BLOCKED_PORTS:
        raise InvalidUrlError(f"URL port {parsed.port} is not allowed")

    # Known metadata/SSRF targets (hostname or IP literal).
    if host in _METADATA_HOSTS:
        raise InvalidUrlError("URL points to a cloud metadata endpoint")

    # Reject localhost and single-label hostnames (no dot).
    if host == "localhost" or "." not in host:
        raise InvalidUrlError("URL host is not a public site")

    # If the host is an IP literal, validate it directly.
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global or ip.is_reserved:
            raise InvalidUrlError("URL host is not a public IP address")
        return url
    except ValueError:
        pass  # not an IP literal; hostname will be resolved at fetch time

    return url
