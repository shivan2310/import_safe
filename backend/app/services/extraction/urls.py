import ipaddress
from urllib.parse import urlparse

from app.errors import InvalidUrlError


def validate_product_url(raw: str) -> str:
    url = (raw or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise InvalidUrlError("URL must be an absolute http(s) URL")
    host = parsed.hostname.lower()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if host == "localhost" or "." not in host:
            raise InvalidUrlError("URL host is not a public site")
        return url
    if not ip.is_global:
        raise InvalidUrlError("URL host is not a public site")
    return url
