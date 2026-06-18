import ipaddress
import socket
from urllib.parse import urlparse


def validate_public_url(url, resolver=socket.getaddrinfo):
    """Reject source URLs that could route the server to a local or private network."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("來源網址必須是有效的 HTTP 或 HTTPS 網址")
    if parsed.username or parsed.password:
        raise ValueError("來源網址不可包含登入資訊")

    try:
        addresses = {result[4][0] for result in resolver(parsed.hostname, parsed.port)}
    except socket.gaierror as error:
        raise ValueError("來源網址無法解析") from error

    if not addresses:
        raise ValueError("來源網址無法解析")

    for address in addresses:
        ip_address = ipaddress.ip_address(address)
        if not ip_address.is_global:
            raise ValueError("來源網址不可指向內部網路")
