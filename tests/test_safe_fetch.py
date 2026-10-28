"""Synthetic public HTTP responses; in-memory TLS never reaches a network."""
import base64
import gzip
import io
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import requests
import safe_fetch as sf
import company_feeds as cf

PUBLIC = "93.184.215.14"
URL = "http://jobs.example.org/posting"
ANSWERS = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, 80))]


def reply(body=b"<html>Fictional engineer</html>", status=200, headers=None, chunked=False):
    headers = {"Content-Type": "text/html; charset=utf-8", **(headers or {})}
    if chunked:
        headers["Transfer-Encoding"] = "chunked"
        body = b"%x\r\n" % len(body) + body + b"\r\n0\r\n\r\n"
    return (f"HTTP/1.1 {status} Test\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n").encode() + body


class WireSocket:
    def __init__(self, wire):
        self.stream = io.BytesIO(wire)
        self.sent = bytearray()
        self.destinations = []
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, destination):
        self.destinations.append(destination)

    def sendall(self, data):
        self.sent.extend(data)

    def makefile(self, *args):
        return self.stream

    def close(self):
        self.closed = True


class TransportTest(unittest.TestCase):
    def fetch(self, wire, url=URL, **options):
        sock = WireSocket(wire)
        self.addCleanup(lambda: self.assertTrue(sock.closed))
        with patch.object(sf.socket, "socket", return_value=sock), \
             patch.object(sf.socket, "getaddrinfo", return_value=ANSWERS) as resolve:
            result = sf._fetch_in_helper(url, time.monotonic() + 5, **options)
        return result, sock, resolve

    def test_numeric_pinning_host_and_no_rebinding_or_ambient_state(self):
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1234", "NETRC": "/secret"}):
            result, sock, resolve = self.fetch(reply())
        self.assertIn(b"Fictional", base64.b64decode(result["body"]))
        self.assertEqual(sock.destinations, [(PUBLIC, 80)])
        resolve.assert_called_once_with("jobs.example.org", 80, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
        self.assertIn(b"Host: jobs.example.org\r\n", sock.sent)
        self.assertIn(b"User-Agent: Jobweaver/", sock.sent)
        for forbidden in (b"Authorization:", b"Cookie:", b"Proxy-Authorization:"):
            self.assertNotIn(forbidden, sock.sent)

    def test_all_answers_checked_before_any_socket(self):
        for bad in ("127.0.0.1", "169.254.169.254", "100.64.0.1", "224.0.0.1", "::ffff:127.0.0.1", "ff02::1"):
            family = socket.AF_INET6 if ":" in bad else socket.AF_INET
            with self.subTest(bad=bad), patch.object(sf.socket, "getaddrinfo", return_value=ANSWERS + [
                    (family, socket.SOCK_STREAM, 6, "", (bad, 80))]), patch.object(sf.socket, "socket") as make:
                with self.assertRaises(sf.UnsafeURL):
                    sf._fetch_in_helper(URL, time.monotonic() + 5)
                make.assert_not_called()

    def test_empty_dns_and_invalid_authorities_do_not_connect(self):
        urls = ("https://user:pw@jobs.example.org/", "http://[fe80::1%25eth0]/", "http://x:0/", "http://x:65536/",
                "http://x\\@public.example/", "http://x/\nsecret", "http://[::1", URL)
        for url in urls:
            with self.subTest(url=url), patch.object(sf.socket, "getaddrinfo", return_value=[]), \
                 patch.object(sf.socket, "socket") as make:
                with self.assertRaises(sf.UnsafeURL):
                    sf._fetch_in_helper(url, time.monotonic() + 5)
                make.assert_not_called()

    def test_public_mapped_ipv6_validates_embedded_ipv4(self):
        self.assertEqual(sf._public_address("::ffff:93.184.215.14"), ipaddress.ip_address("::ffff:5db8:d70e"))

    def test_redirects_revalidate_and_close_before_next_hop(self):
        first = WireSocket(reply(status=302, headers={"Location": "http://127.0.0.1/secret"}))
        with patch.object(sf.socket, "socket", return_value=first) as make, \
             patch.object(sf.socket, "getaddrinfo", return_value=ANSWERS):
            with self.assertRaises(sf.UnsafeURL):
                sf._fetch_in_helper(URL, time.monotonic() + 5)
        make.assert_called_once()
        self.assertTrue(first.closed)
        self.assertTrue(first.stream.closed)

    def test_each_redirect_gets_new_dns_validation(self):
        first = WireSocket(reply(status=302, headers={"Location": "/next"}))
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80))]
        with patch.object(sf.socket, "socket", return_value=first) as make, \
             patch.object(sf.socket, "getaddrinfo", side_effect=[ANSWERS, private]) as resolve:
            with self.assertRaises(sf.UnsafeURL):
                sf._fetch_in_helper(URL, time.monotonic() + 5)
        self.assertEqual(resolve.call_count, 2)
        make.assert_called_once()
        self.assertTrue(first.closed)

    def test_redirect_limit_and_relative_success(self):
        sockets = [WireSocket(reply(status=302, headers={"Location": "/next"})) for _ in range(6)]
        with patch.object(sf.socket, "socket", side_effect=sockets), \
             patch.object(sf.socket, "getaddrinfo", return_value=ANSWERS):
            with self.assertRaisesRegex(sf.UnsafeURL, "redirects"):
                sf._fetch_in_helper(URL, time.monotonic() + 5)
        self.assertTrue(all(s.closed and s.stream.closed for s in sockets))
        sockets = [WireSocket(reply(status=302, headers={"Location": "/next"})), WireSocket(reply())]
        with patch.object(sf.socket, "socket", side_effect=sockets), \
             patch.object(sf.socket, "getaddrinfo", return_value=ANSWERS):
            result = sf._fetch_in_helper(URL, time.monotonic() + 5)
        self.assertEqual(result["url"], "http://jobs.example.org/next")
        self.assertTrue(all(s.closed and s.stream.closed for s in sockets))

    def test_caps_wire_with_and_without_content_length_and_chunking(self):
        for headers, chunked in (({}, False), ({"Content-Length": "129"}, False), ({}, True)):
            with self.subTest(headers=headers, chunked=chunked), patch.object(sf, "MAX_WIRE_BYTES", 128):
                with self.assertRaisesRegex(sf.UnsafeURL, "wire body limit"):
                    self.fetch(reply(b"x" * 129, headers=headers, chunked=chunked))

    def test_gzip_expansion_is_bounded_and_normal_gzip_works(self):
        with patch.object(sf, "MAX_BODY_BYTES", 128):
            with self.assertRaisesRegex(sf.UnsafeURL, "decompressed body limit"):
                self.fetch(reply(gzip.compress(b"x" * 10000), headers={"Content-Encoding": "gzip"}))
        result, _, _ = self.fetch(reply(gzip.compress(b"<html>Fictional</html>"), headers={"Content-Encoding": "gzip"}))
        self.assertEqual(base64.b64decode(result["body"]), b"<html>Fictional</html>")
        for content in (b"invalid", gzip.compress(b"hello")[:-2], gzip.compress(b"a") + gzip.compress(b"b")):
            with self.subTest(content=content), self.assertRaises(sf.UnsafeURL):
                self.fetch(reply(content, headers={"Content-Encoding": "gzip"}))

    def test_total_transfer_cap_includes_chunk_extensions_trailers_and_headers(self):
        wires = [
            b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nTransfer-Encoding: chunked\r\n\r\n' +
            (b'1;' + b'x' * 60 + b'\r\na\r\n') * 20 + b'0\r\n\r\n',
            b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n' +
            (b'X-Trailer: ' + b'x' * 60 + b'\r\n') * 20 + b'\r\n',
            b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n' + (b'X-Header: ' + b'x' * 60 + b'\r\n') * 20 + b'\r\n',
        ]
        for wire in wires:
            with self.subTest(wire=wire[:80]), patch.object(sf, 'MAX_TRANSFER_BYTES', 512):
                with self.assertRaisesRegex(sf.UnsafeURL, 'total HTTP transfer limit'):
                    self.fetch(wire)

    def test_https_host_default_nondefault_ports_and_ipv6(self):
        for url, host in (("https://jobs.example.org/", b"jobs.example.org"),
                          ("https://jobs.example.org:80/", b"jobs.example.org:80"),
                          ("https://[2606:4700::1111]/", b"[2606:4700::1111]")):
            with self.subTest(url=url), patch.object(sf.ssl, 'create_default_context') as context:
                context.return_value.wrap_socket.side_effect = lambda sock, **kw: sock
                _, sock, _ = self.fetch(reply(), url=url)
                self.assertIn(b'Host: ' + host + b'\r\n', sock.sent)

    def test_response_policy_and_error_paths_close_connections(self):
        for headers in ({"Content-Type": "application/octet-stream"}, {"Content-Type": ""},
                        {"Content-Encoding": "br"}, {"Content-Length": "bad"}, {"Content-Length": "999"}):
            with self.subTest(headers=headers), self.assertRaises(sf.UnsafeURL):
                self.fetch(reply(headers=headers))
        with self.assertRaises(requests.HTTPError):
            self.fetch(reply(status=404))

    def test_feed_redirects_stay_on_exact_https_provider(self):
        for location in ("http://boards-api.greenhouse.io/next", "https://evil.example/jobs", "https://boards-api.greenhouse.io:444/next",
                         "https://127.0.0.1/jobs", "https://boards-api.greenhouse.io.evil.example/jobs"):
            with self.subTest(location=location), patch.object(sf.ssl, "create_default_context") as context:
                context.return_value.wrap_socket.side_effect = lambda sock, **kw: sock
                with self.assertRaisesRegex(sf.UnsafeURL, "provider policy"):
                    self.fetch(reply(status=302, headers={"Location": location}),
                               url="https://boards-api.greenhouse.io/jobs", allowed_hosts=("boards-api.greenhouse.io",))

    def test_ipv6_failure_can_fall_back_to_validated_ipv4(self):
        first, second = WireSocket(reply()), WireSocket(reply())
        first.connect = lambda destination: (_ for _ in ()).throw(OSError("IPv6 unavailable"))
        answers = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700::1111", 80))] + ANSWERS
        with patch.object(sf.socket, "socket", side_effect=[first, second]), \
             patch.object(sf.socket, "getaddrinfo", return_value=answers):
            result = sf._fetch_in_helper(URL, time.monotonic() + 5)
        self.assertIn("body", result)
        self.assertTrue(first.closed and second.closed)
        self.assertEqual(second.destinations, [(PUBLIC, 80)])


class HelperTest(unittest.TestCase):
    def test_real_helper_rejects_private_address_and_has_no_server_side_effect(self):
        with self.assertRaisesRegex(sf.UnsafeURL, "non-public"):
            sf.fetch_page("http://127.0.0.1/secret")

    def test_hard_deadline_cancels_dns_slow_headers_and_body_and_reaps_child(self):
        real_popen = subprocess.Popen
        for phase in ("dns", "headers", "body"):
            # The real worker and parent deadline run unchanged. Substitute only
            # network primitives; no external destination can be contacted.
            code = """
import safe_fetch as sf, time, io, socket
phase = PHASE
class Trickle(io.RawIOBase):
    def readable(self): return True
    def readinto(self, buffer):
        time.sleep(.02)
        buffer[0] = 65
        return 1
class Sock:
    def settimeout(self, timeout): pass
    def connect(self, addr): pass
    def sendall(self, data): pass
    def close(self): pass
    def makefile(self, *args):
        if phase == 'headers': return io.BufferedReader(Trickle())
        class Body(io.BytesIO):
            def read(self, n=-1):
                time.sleep(.02)
                return b'x'
        return Body(b'HTTP/1.1 200 OK\\r\\nContent-Type: text/html\\r\\n\\r\\n')
def resolve(*args, **kwargs):
    if phase == 'dns': time.sleep(60)
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.215.14', 80))]
sf.socket.getaddrinfo = resolve
sf.socket.socket = lambda *args: Sock()
sf._worker()
""".replace("PHASE", repr(phase))
            children = []
            def launch(command, **kwargs):
                self.assertNotIn("FICTIONAL_API_KEY", kwargs["env"])
                self.assertEqual(kwargs["env"]["PYTHON_DOTENV_DISABLED"], "1")
                child = real_popen([sys.executable, "-c", code], **kwargs)
                children.append(child)
                return child
            start = time.monotonic()
            with self.subTest(phase=phase), patch.dict(os.environ, {"FICTIONAL_API_KEY": "not-a-real-key"}), \
                 patch.object(sf.subprocess, "Popen", side_effect=launch):
                with self.assertRaises(requests.Timeout):
                    sf.fetch_page(URL, timeout=.6)
            elapsed = time.monotonic() - start
            self.assertGreaterEqual(elapsed, .4)
            self.assertLess(elapsed, 2.0)
            self.assertIsNotNone(children[0].poll())
            self.assertTrue(sf._FETCH_SLOTS.acquire(blocking=False))
            sf._FETCH_SLOTS.release()

    def test_capacity_and_timeout_validation_create_no_children(self):
        with patch.object(sf.subprocess, "Popen") as launch:
            for timeout in (0, -1, 41, float("inf"), float("nan"), "15"):
                with self.assertRaises(sf.UnsafeURL):
                    sf.fetch_page(URL, timeout=timeout)
            for _ in range(4):
                self.assertTrue(sf._FETCH_SLOTS.acquire(blocking=False))
            try:
                with self.assertRaisesRegex(requests.RequestException, "capacity"):
                    sf.fetch_page(URL)
            finally:
                for _ in range(4):
                    sf._FETCH_SLOTS.release()
            launch.assert_not_called()

    def test_bounded_helper_result_preserves_text_api(self):
        real_popen = subprocess.Popen
        payload = {"url": URL, "status": 200, "headers": {"Content-Type": "text/html; charset=utf-8"},
                   "body": base64.b64encode("<html>Fictional Fırat</html>".encode()).decode()}
        def launch(command, **kwargs):
            return real_popen([sys.executable, "-c", "import sys; sys.stdin.read(); print(" + repr(json.dumps(payload)) + ")"], **kwargs)
        with patch.object(sf.subprocess, "Popen", side_effect=launch):
            result = sf.fetch_page(URL)
        self.assertEqual(result.text, "<html>Fictional Fırat</html>")
        self.assertEqual(result.status_code, 200)

    def test_worker_deadline_error_retains_timeout_type(self):
        real_popen = subprocess.Popen
        def launch(command, **kwargs):
            return real_popen([sys.executable, "-c",
                               "import safe_fetch as sf; sf.time.monotonic = lambda: float('inf'); sf._worker()"], **kwargs)
        with patch.object(sf.subprocess, "Popen", side_effect=launch):
            with self.assertRaisesRegex(requests.Timeout, "total deadline"):
                sf.fetch_page(URL)


class TLSIdentityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.cert, cls.key = (str(Path(cls.temp.name) / name) for name in ("cert.pem", "key.pem"))
        # Fictional throwaway key and certificate, generated locally with no network.
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=jobs.example.org", "-addext", "subjectAltName=DNS:jobs.example.org",
                        "-keyout", cls.key, "-out", cls.cert], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def handshake(self, hostname):
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(self.cert, self.key)
        names = []
        server_context.set_servername_callback(lambda sock, name, context: names.append(name))
        client_context = ssl.create_default_context(cafile=self.cert)
        self.assertTrue(client_context.check_hostname)
        self.assertEqual(client_context.verify_mode, ssl.CERT_REQUIRED)
        sock = WireSocket(b"")
        class MemoryTLSContext:
            # The real default trust/hostname context performs an OpenSSL TLS
            # handshake through memory buffers. No socket syscalls are required.
            def wrap_socket(self, raw_socket, server_hostname):
                incoming, outgoing, server_in, server_out = (ssl.MemoryBIO() for _ in range(4))
                client_tls = client_context.wrap_bio(incoming, outgoing, server_hostname=server_hostname)
                server_tls = server_context.wrap_bio(server_in, server_out, server_side=True)
                client_done = server_done = False
                for _ in range(20):
                    try:
                        client_tls.do_handshake()
                        client_done = True
                    except ssl.SSLWantReadError:
                        pass
                    server_in.write(outgoing.read())
                    try:
                        server_tls.do_handshake()
                        server_done = True
                    except ssl.SSLWantReadError:
                        pass
                    incoming.write(server_out.read())
                    if client_done and server_done:
                        return raw_socket
                raise AssertionError("TLS handshake did not finish")
        connection = sf._PinnedConnection(hostname, 443, (socket.AF_INET, (PUBLIC, 443)), 2, True)
        try:
            with patch.object(sf.socket, "socket", return_value=sock), \
                 patch.object(sf.ssl, "create_default_context", return_value=MemoryTLSContext()):
                connection.connect()
        finally:
            connection.close()
        self.assertTrue(sock.closed)
        self.assertEqual(sock.destinations, [(PUBLIC, 443)])
        return names

    def test_actual_tls_accepts_original_hostname_and_transmits_sni(self):
        names = self.handshake("jobs.example.org")
        self.assertEqual(names, ["jobs.example.org"])

    def test_actual_tls_rejects_wrong_hostname(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.handshake("wrong.example.org")


class ProviderPolicyTest(unittest.TestCase):
    def test_identifiers_cannot_inject_an_authority_or_path(self):
        for connector in cf.READERS:
            for identifier in ("user@127.0.0.1", "x/../../secret", "x:8443", "x?query", "x#fragment", "x%2fsecret", "x\\host"):
                with self.subTest(connector=connector, identifier=identifier):
                    fetch = unittest.mock.Mock()
                    with self.assertRaises(cf.FeedError):
                        cf.READERS[connector]({"connector": connector, "identifier": identifier}, fetch)
                    fetch.assert_not_called()

    def test_fictional_json_and_xml_readers_supply_exact_provider_policy(self):
        cases = [("greenhouse", "example", "boards-api.greenhouse.io", '{"jobs": []}', sf.JSON_TYPES),
                 ("smartrecruiters", "Example", "api.smartrecruiters.com", '{"content": [], "totalFound": 0}', sf.JSON_TYPES),
                 ("personio", "example", "example.jobs.personio.de", "<workzag-jobs/>", sf.XML_TYPES),
                 ("successfactors_rss", "careers.example.org", "careers.example.org", "<rss><channel/></rss>", sf.XML_TYPES)]
        for connector, identifier, host, body, types in cases:
            with self.subTest(connector=connector):
                def fetch(url, **kwargs):
                    self.assertTrue(url.startswith("https://" + host + "/"))
                    self.assertEqual(kwargs, {"allowed_hosts": (host,), "allowed_types": types})
                    return body
                self.assertEqual(cf.READERS[connector]({"connector": connector, "identifier": identifier}, fetch), [])

    def test_feed_http_requires_policy_and_uses_bounded_transport(self):
        with self.assertRaises(cf.FeedError):
            cf.http_fetch("https://evil.example/feed")
        for kind, body in (("application/json", b'{"jobs": []}'), ("application/xml", b"<workzag-jobs/>")):
            with self.subTest(kind=kind), patch.object(sf.ssl, "create_default_context") as context:
                context.return_value.wrap_socket.side_effect = lambda sock, **kw: sock
                sock = WireSocket(reply(body, headers={"Content-Type": kind}))
                with patch.object(sf.socket, "socket", return_value=sock), patch.object(sf.socket, "getaddrinfo", return_value=ANSWERS):
                    result = sf._fetch_in_helper("https://example.org/feed", time.monotonic() + 5,
                                                 allowed_hosts=("example.org",), allowed_types=sf.JSON_TYPES + sf.XML_TYPES)
                self.assertEqual(base64.b64decode(result["body"]), body)
                self.assertTrue(sock.closed)


if __name__ == "__main__":
    unittest.main()
