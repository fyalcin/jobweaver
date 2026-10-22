"""Fetching a job page a User pasted, without letting the server be pointed at itself or the local network.

Only http and https; every address the host name resolves to must be a public internet address (this refuses
loopback, private, link-local, cloud-metadata and Tailscale/CGNAT ranges); redirects are followed by hand so
each hop is checked again. Jobweaver names itself in the User-Agent instead of pretending to be a browser.

Known limitation: the name is resolved once for the check and again by `requests`, so a hostile DNS server
could answer differently the second time (DNS rebinding). See ARCHITECTURE.md, "Known limitations".
"""
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests

USER_AGENT = "Jobweaver/1.0 (+https://github.com/fyalcin/jobweaver)"
MAX_REDIRECTS = 5


class UnsafeURL(ValueError):
    """The URL may not be fetched."""


def check_url(url: str) -> None:
    """Raise UnsafeURL unless `url` is http(s) and its host resolves only to public addresses."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeURL("only http:// and https:// links can be fetched")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise UnsafeURL(f"cannot resolve {parsed.hostname}: {exc}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if not address.is_global:
            raise UnsafeURL(f"{parsed.hostname} points to a non-public address ({address}); it will not be fetched")


def fetch_page(url: str, timeout: int = 15) -> requests.Response:
    """GET `url` with every hop checked by `check_url`; raises UnsafeURL or requests' own errors."""
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "de-AT,de;q=0.9,en;q=0.8"}
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url)
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=False)
        if not response.is_redirect:
            response.raise_for_status()
            return response
        url = urljoin(url, response.headers.get("Location", ""))
    raise UnsafeURL(f"more than {MAX_REDIRECTS} redirects")
