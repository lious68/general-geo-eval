"""Bounded public-only HTTPS/HTTP fetching, with DNS pinned per redirect hop."""
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit, urljoin

MAX_BYTES = 2 * 1024 * 1024


def resolve_public(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Unsupported URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in (80, 443):
        raise ValueError("Unsupported port")
    addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("No address")
    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if not ip.is_global or (getattr(ip, "ipv4_mapped", None) and not ip.ipv4_mapped.is_global):
            raise ValueError("Non-public address")
    return parsed, port, addresses[0][4][0]


def fetch_html(url):
    for _ in range(6):
        parsed, port, address = resolve_public(url)
        conn = http.client.HTTPConnection(parsed.hostname, port, timeout=12)
        try:
            sock = socket.create_connection((address, port), timeout=12)
            if parsed.scheme == "https":
                try:
                    sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
                except Exception:
                    sock.close()
                    raise
            conn.sock = sock
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            conn.request("GET", target, headers={"User-Agent": "GEO citation verification", "Accept": "text/html", "Accept-Encoding": "identity"})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    return None
                url = urljoin(url, location)
                continue
            if response.status != 200 or "html" not in response.getheader("Content-Type", "").lower():
                return None
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                return None
            encoding = response.headers.get_content_charset() or "utf-8"
            return data.decode(encoding, errors="replace")
        finally:
            conn.close()
    return None
