"""Bounded public HTTP fetching, separate from deliberately configured model endpoints.

Each hop resolves once, validates every answer, then connects to a numeric sockaddr.
The original hostname supplies HTTP Host, TLS SNI and certificate verification.
A short-lived exec helper gives DNS, headers and body one cancellable wall deadline.
"""
import base64
import http.client
import ipaddress
import json
import math
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit, quote
import zlib

import requests

USER_AGENT = "Jobweaver/1.0 (+https://github.com/fyalcin/jobweaver)"
MAX_REDIRECTS = 5
MAX_WIRE_BYTES = 4 * 1024 * 1024
MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_TRANSFER_BYTES = MAX_WIRE_BYTES + 256 * 1024
MAX_TIMEOUT = 40
PAGE_TYPES = ("text/html", "application/xhtml+xml")
JSON_TYPES = ("application/json", "text/json")
XML_TYPES = ("application/xml", "text/xml", "application/rss+xml", "application/atom+xml")
# Per backend process; admission never queues an unbounded number of helper processes.
_FETCH_SLOTS = threading.BoundedSemaphore(4)
_MAX_RESULT_BYTES = MAX_BODY_BYTES * 2 + 256 * 1024


class UnsafeURL(ValueError):
    """The URL or response violates the public fetch policy."""


class _TransferLimitExceeded(Exception):
    # http.client treats ValueError as malformed chunk syntax. Keep this signal
    # separate until it has crossed the HTTP parser, then expose UnsafeURL.
    pass


def _parse_url(url):
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise UnsafeURL("invalid URL")
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise UnsafeURL("only http:// and https:// links can be fetched")
        if parsed.username is not None or parsed.password is not None or "%" in parsed.hostname:
            raise UnsafeURL("URL credentials and scoped addresses are not allowed")
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if parsed.port == 0:
            raise UnsafeURL("invalid port")
    except (ValueError, UnicodeError) as exc:
        raise UnsafeURL("invalid URL authority") from exc
    return parsed, host, port


def _public_address(value):
    address = ipaddress.ip_address(value)
    effective = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped else address
    if (not effective.is_global or effective.is_multicast or effective.is_reserved
            or effective.is_unspecified or address.is_multicast):
        raise UnsafeURL(f"non-public address ({address}); it will not be fetched")
    return address


def _resolve(host, port):
    # Numeric literals need no DNS. Private literals cannot be rewritten by DNS.
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
        except (socket.gaierror, UnicodeError) as exc:
            raise UnsafeURL(f"cannot resolve {host}") from exc
    else:
        answers = [(socket.AF_INET6 if address.version == 6 else socket.AF_INET,
                    socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (str(address), port))]
    if not answers:
        raise UnsafeURL(f"cannot resolve {host}")
    validated = []
    for family, _, _, _, sockaddr in answers:
        if family not in (socket.AF_INET, socket.AF_INET6) or "%" in sockaddr[0]:
            raise UnsafeURL("unsupported address")
        address = _public_address(sockaddr[0])
        # Rebuild numeric addresses so resolver-supplied ports/scopes cannot change them.
        validated.append((family, (str(address), port, 0, 0) if family == socket.AF_INET6 else (str(address), port)))
    return validated


def check_url(url: str) -> None:
    """Validate a destination only; fetching repeats validation in its helper."""
    _, host, port = _parse_url(url)
    _resolve(host, port)


class _TransferBudget:
    """Count HTTP bytes before header parsing or chunk framing removal."""
    def __init__(self):
        self.remaining = MAX_TRANSFER_BYTES


class _LimitedReader:
    def __init__(self, stream, budget):
        self.stream, self.budget = stream, budget

    def _read(self, method, amount=-1):
        limit = self.budget.remaining + 1
        data = method(min(amount, limit) if amount >= 0 else limit)
        self.budget.remaining -= len(data)
        if self.budget.remaining < 0:
            raise _TransferLimitExceeded("response exceeds total HTTP transfer limit")
        return data

    def read(self, amount=-1):
        return self._read(self.stream.read, amount)

    def readline(self, amount=-1):
        return self._read(self.stream.readline, amount)

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def close(self):
        self.stream.close()

    def flush(self):
        self.stream.flush()


class _LimitedResponse(http.client.HTTPResponse):
    def __init__(self, sock, *args, budget, **kwargs):
        class ResponseSocket:
            def makefile(self, *args, **kwargs):
                return _LimitedReader(sock.makefile(*args, **kwargs), budget)
        super().__init__(ResponseSocket(), *args, **kwargs)


class _PinnedConnection(http.client.HTTPConnection):
    """No hostname lookup occurs between validation and socket.connect."""
    def __init__(self, host, port, destination, timeout, secure):
        self.default_port = 443 if secure else 80
        super().__init__(host, port, timeout=timeout)
        self.destination, self.secure = destination, secure

    def connect(self):
        family, sockaddr = self.destination
        self.sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            self.sock.settimeout(self.timeout)
            self.sock.connect(sockaddr)
            if self.secure:
                self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname=self.host)
        except BaseException:
            self.close()
            raise


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise requests.Timeout("public fetch total deadline exceeded")
    return remaining


def _connect(host, port, destinations, deadline, secure):
    for destination in destinations:
        connection = _PinnedConnection(host, port, destination, _remaining(deadline), secure)
        try:
            connection.connect()
            return connection
        except ssl.SSLError:
            connection.close()
            raise
        except OSError:
            connection.close()
            if destination == destinations[-1]:
                raise


def _read_body(response, allowed_types, deadline):
    content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type not in allowed_types:
        raise UnsafeURL(f"unsupported Content-Type: {content_type or 'missing'}")
    length = response.getheader("Content-Length")
    if length is not None:
        try:
            length = int(length)
        except ValueError as exc:
            raise UnsafeURL("invalid Content-Length") from exc
        if length < 0 or length > MAX_WIRE_BYTES:
            raise UnsafeURL("response exceeds wire body limit")
    encoding = response.getheader("Content-Encoding", "identity").strip().lower()
    if encoding not in ("identity", "gzip"):
        raise UnsafeURL("unsupported Content-Encoding")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
    wire_size, body = 0, bytearray()
    while True:
        _remaining(deadline)
        chunk = response.read(min(64 * 1024, MAX_WIRE_BYTES - wire_size + 1))
        if not chunk:
            break
        wire_size += len(chunk)
        if wire_size > MAX_WIRE_BYTES:
            raise UnsafeURL("response exceeds wire body limit")
        try:
            decoded = decoder.decompress(chunk, MAX_BODY_BYTES - len(body) + 1) if decoder else chunk
        except zlib.error as exc:
            raise UnsafeURL("invalid gzip response") from exc
        body.extend(decoded)
        if len(body) > MAX_BODY_BYTES or (decoder and decoder.unconsumed_tail):
            raise UnsafeURL("response exceeds decompressed body limit")
    if response.length not in (None, 0):
        raise UnsafeURL("incomplete response body")
    if decoder and (not decoder.eof or decoder.unused_data):
        raise UnsafeURL("incomplete or concatenated gzip response")
    _remaining(deadline)
    return bytes(body)


def _fetch_in_helper(url, deadline, allowed_hosts=None, allowed_types=PAGE_TYPES, headers=None):
    """The worker's entire network path. No sessions, environment proxies or auth."""
    budget = _TransferBudget()
    for hop in range(MAX_REDIRECTS + 1):
        _remaining(deadline)
        parsed, host, port = _parse_url(url)
        if allowed_hosts is not None and (parsed.scheme != "https" or port != 443 or host not in allowed_hosts):
            raise UnsafeURL("feed destination is outside its provider policy")
        destinations = _resolve(host, port)
        _remaining(deadline)
        connection = _connect(host, port, destinations, deadline, parsed.scheme == "https")
        connection.response_class = lambda *args, **kwargs: _LimitedResponse(*args, budget=budget, **kwargs)
        response = None
        try:
            request_headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Connection": "close",
                               "Accept": ", ".join(allowed_types), "Accept-Language": "de-AT,de;q=0.9,en;q=0.8"}
            for name, value in (headers or {}).items():
                if name.lower() not in ("accept", "accept-language", "user-agent"):
                    raise UnsafeURL("unsupported request header")
                request_headers[name] = value
            path = quote(urlunsplit(("", "", parsed.path or "/", parsed.query, "")), safe="/%:@!$&'()*+,;=?~-._")
            connection.request("GET", path, headers=request_headers)
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                if hop == MAX_REDIRECTS:
                    raise UnsafeURL(f"more than {MAX_REDIRECTS} redirects")
                location = response.getheader("Location")
                if not location:
                    raise UnsafeURL("redirect has no Location")
                url = urljoin(url, location)
                continue
            if not 200 <= response.status < 300:
                raise requests.HTTPError(f"HTTP {response.status} from public destination")
            body = _read_body(response, allowed_types, deadline)
            return {"url": url, "status": response.status, "headers": {"Content-Type": response.getheader("Content-Type")},
                    "body": base64.b64encode(body).decode("ascii")}
        except _TransferLimitExceeded as exc:
            raise UnsafeURL(str(exc)) from exc
        finally:
            try:
                if response is not None:
                    response.close()
            finally:
                connection.close()
    raise UnsafeURL("too many redirects")


def fetch_page(url: str, timeout: int = 15, *, allowed_hosts=None, allowed_types=PAGE_TYPES, headers=None) -> requests.Response:
    """Fetch with one deadline across helper startup, DNS and redirects.

    Return a buffered Requests response for existing .text callers. At most four
    helpers run per backend process; overload fails without queueing.
    """
    _parse_url(url)
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT:
        raise UnsafeURL(f"timeout must be greater than zero and at most {MAX_TIMEOUT} seconds")
    deadline = time.monotonic() + timeout
    if not _FETCH_SLOTS.acquire(blocking=False):
        raise requests.RequestException("public fetch capacity reached; retry later")
    try:
        payload = json.dumps(dict(url=url, deadline=deadline, allowed_hosts=allowed_hosts,
                                  allowed_types=allowed_types, headers=headers)).encode()
        if len(payload) > 32 * 1024:
            raise UnsafeURL("fetch options too large")
        # A file keeps stdout off an unbounded communicate() buffer.
        with tempfile.TemporaryFile() as output:
            with subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker"],
                                  stdin=subprocess.PIPE, stdout=output, stderr=subprocess.DEVNULL,
                                  env={**{key: value for key, value in os.environ.items()
                                          if key in ("PATH", "SYSTEMROOT", "WINDIR", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE")},
                                       "PYTHON_DOTENV_DISABLED": "1"}) as process:
                try:
                    process.communicate(payload, timeout=_remaining(deadline))
                except BaseException:
                    process.kill()
                    process.communicate()
                    raise
                if process.returncode:
                    raise requests.RequestException("public fetch helper failed")
            output.seek(0)
            encoded = output.read(_MAX_RESULT_BYTES + 1)
        if len(encoded) > _MAX_RESULT_BYTES:
            raise UnsafeURL("fetch helper response too large")
        result = json.loads(encoded)
        if "error" in result:
            error = {"unsafe": UnsafeURL, "timeout": requests.Timeout}.get(result["kind"], requests.RequestException)
            raise error(result["error"])
        response = requests.Response()
        response.status_code, response.url = result["status"], result["url"]
        response.headers.update(result["headers"])
        response._content = base64.b64decode(result["body"], validate=True)
        response._content_consumed = True
        response.encoding = requests.utils.get_encoding_from_headers(response.headers)
        _remaining(deadline)
        return response
    except subprocess.TimeoutExpired as exc:
        raise requests.Timeout("public fetch total deadline exceeded") from exc
    finally:
        _FETCH_SLOTS.release()


def _worker():
    if sys.platform != "win32":
        import resource
        resource.setrlimit(resource.RLIMIT_FSIZE, (_MAX_RESULT_BYTES, _MAX_RESULT_BYTES))
    try:
        options = json.loads(sys.stdin.buffer.read(32 * 1024 + 1))
        result = _fetch_in_helper(**options)
    except Exception as exc:
        kind = "unsafe" if isinstance(exc, UnsafeURL) else "timeout" if isinstance(exc, (requests.Timeout, TimeoutError)) else "network"
        result = {"kind": kind, "error": str(exc)[:1000]}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        _worker()
