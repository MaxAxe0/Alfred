"""Run from the project folder: python -m unittest discover -s research -v

These checks make no network connections. Each test builds a fake website
(httpx.MockTransport) that answers however the test needs.
"""

import gzip
import itertools
import tracemalloc
import unittest
import zlib
from unittest import mock

import httpx

import fetcher
from fetcher import FetchBlocked, FetchError, fetch, make_client


def fake_site(handler):
    """A client whose 'internet' is the given function: request in, response out."""
    return make_client(transport=httpx.MockTransport(handler))


def page(body=b"<p>hello</p>", status=200, **headers):
    """Build a handler that always answers with the same response, and records requests."""
    seen = []

    def handler(request):
        seen.append(request)
        # A stream, like a real network response. (content=bytes would count as already read.)
        return httpx.Response(status, stream=httpx.ByteStream(body),
                              headers={"content-type": "text/html", **headers})

    handler.seen = seen
    return handler


class UrlCheckTests(unittest.TestCase):
    def test_refused_urls_never_reach_the_network(self):
        handler = page()
        for url in (
            "http://192.168.1.1/", "http://localhost/", "http://nas/",
            "https://example.com:8080/", "ftp://example.com/", "https://user:pw@example.com/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(FetchBlocked):
                    fetch(url, client=fake_site(handler))
        self.assertEqual(handler.seen, [])

    def test_url_httpx_cannot_parse_is_refused_cleanly(self):
        # net_policy's IDNA codec quietly drops the zero-width space; httpx rejects the name.
        handler = page()
        with self.assertRaisesRegex(FetchBlocked, "invalid URL"):
            fetch("https://exa​mple.com/", client=fake_site(handler))
        self.assertEqual(handler.seen, [])

    def test_parser_disagreement_is_refused(self):
        # Pretend net_policy approved a different host than the one httpx would contact.
        handler = page()
        with mock.patch.object(fetcher, "check_url", return_value=("other.example", 443)):
            with self.assertRaisesRegex(FetchBlocked, "disagree"):
                fetch("https://example.com/", client=fake_site(handler))
        self.assertEqual(handler.seen, [])

    def test_port_disagreement_is_refused(self):
        handler = page()
        with mock.patch.object(fetcher, "check_url", return_value=("example.com", 80)):
            with self.assertRaisesRegex(FetchBlocked, "disagree"):
                fetch("https://example.com/", client=fake_site(handler))
        self.assertEqual(handler.seen, [])

    def test_equivalent_spellings_still_match(self):
        for url in ("https://Example.COM./", "https://example.com:443/", "https://bücher.example/",
                    "https://1.1.1.1/", "http://example.com:80/x?y=1"):
            with self.subTest(url=url):
                fetch(url, client=fake_site(page()))


class ResponseTests(unittest.TestCase):
    def test_successful_fetch(self):
        result = fetch("https://example.com/", client=fake_site(page()))
        self.assertEqual(result.status, 200)
        self.assertEqual(result.body, b"<p>hello</p>")
        self.assertEqual(result.content_type, "text/html")
        self.assertEqual(result.url, "https://example.com/")

    def test_identifies_itself(self):
        handler = page()
        fetch("https://example.com/", client=fake_site(handler))
        self.assertEqual(handler.seen[0].headers["user-agent"], fetcher.USER_AGENT)

    def test_redirects_are_not_followed_yet(self):
        handler = page(status=302, location="http://192.168.1.1/")
        with self.assertRaisesRegex(FetchError, "not followed"):
            fetch("https://example.com/", client=fake_site(handler))
        self.assertEqual(len(handler.seen), 1)

    def test_server_error(self):
        with self.assertRaisesRegex(FetchError, "HTTP 500"):
            fetch("https://example.com/", client=fake_site(page(status=500)))

    def test_proxy_refusal_of_plain_http(self):
        handler = page(status=407, **{"x-smokescreen-error": "denied by rule 'Deny: Private Range'"})
        with self.assertRaisesRegex(FetchBlocked, "Private Range"):
            fetch("http://example.com/", client=fake_site(handler))

    def test_proxy_refusal_of_https_tunnel(self):
        def handler(request):
            raise httpx.ProxyError("407 Request Rejected by Proxy", request=request)
        with self.assertRaises(FetchBlocked):
            fetch("https://example.com/", client=fake_site(handler))


class LimitTests(unittest.TestCase):
    def test_declared_size_too_large(self):
        handler = page(**{"content-length": str(fetcher.MAX_BYTES + 1)})
        with self.assertRaisesRegex(FetchError, "larger than"):
            fetch("https://example.com/", client=fake_site(handler))

    def test_body_larger_than_limit_without_a_declared_size(self):
        def handler(request):
            # A generator body has no Content-Length, so only the running count can stop it.
            return httpx.Response(200, content=(b"x" * 100 for _ in range(5)))
        with mock.patch.object(fetcher, "MAX_BYTES", 250):
            with self.assertRaisesRegex(FetchError, "larger than 250"):
                fetch("https://example.com/", client=fake_site(handler))

    def test_total_deadline(self):
        # Each clock reading is 30 seconds later than the last, so the 20-second deadline passes.
        clock = itertools.count(0, 30)
        with mock.patch.object(fetcher.time, "monotonic", side_effect=lambda: next(clock)):
            with self.assertRaisesRegex(FetchError, "longer than 20 seconds"):
                fetch("https://example.com/", client=fake_site(page()))

    def test_timeout_becomes_fetch_error(self):
        def handler(request):
            raise httpx.ReadTimeout("no data", request=request)
        with self.assertRaisesRegex(FetchError, "timed out"):
            fetch("https://example.com/", client=fake_site(handler))

    def test_connection_failure_becomes_fetch_error(self):
        def handler(request):
            raise httpx.ConnectError("refused", request=request)
        with self.assertRaisesRegex(FetchError, "could not fetch"):
            fetch("https://example.com/", client=fake_site(handler))


def gzip_bomb(megabytes):
    """Compress `megabytes` of zeros without ever holding them all in memory."""
    compressor = zlib.compressobj(9, wbits=31)  # 31 = gzip format
    megabyte = b"\0" * 1_000_000
    return b"".join(compressor.compress(megabyte) for _ in range(megabytes)) + compressor.flush()


def in_pieces(data, size=65536):
    """Deliver bytes in network-sized pieces, with no declared length."""
    return (data[i:i + size] for i in range(0, len(data), size))


class CompressionTests(unittest.TestCase):
    def test_gzip_page_is_decompressed(self):
        handler = page(body=gzip.compress(b"<p>hello</p>"), **{"content-encoding": "gzip"})
        result = fetch("https://example.com/", client=fake_site(handler))
        self.assertEqual(result.body, b"<p>hello</p>")

    def test_deflate_page_is_decompressed(self):
        handler = page(body=zlib.compress(b"<p>hello</p>"), **{"content-encoding": "deflate"})
        result = fetch("https://example.com/", client=fake_site(handler))
        self.assertEqual(result.body, b"<p>hello</p>")

    def test_only_supported_compression_is_requested(self):
        handler = page()
        fetch("https://example.com/", client=fake_site(handler))
        self.assertEqual(handler.seen[0].headers["accept-encoding"], "gzip, deflate")

    def test_unsupported_compression_refused(self):
        handler = page(**{"content-encoding": "br"})
        with self.assertRaisesRegex(FetchError, "unsupported content encoding"):
            fetch("https://example.com/", client=fake_site(handler))

    def test_corrupt_compressed_data(self):
        handler = page(body=b"not really gzip", **{"content-encoding": "gzip"})
        with self.assertRaisesRegex(FetchError, "could not decompress"):
            fetch("https://example.com/", client=fake_site(handler))

    def test_compression_bomb_stopped_without_a_memory_spike(self):
        # 200 MB of zeros shrinks to about 200 KB. Before this fix, one 64 KB piece
        # expanded to about 67 MB in memory before the size check could run.
        bomb = gzip_bomb(200)

        def handler(request):
            return httpx.Response(200, content=in_pieces(bomb), headers={"content-encoding": "gzip"})

        tracemalloc.start()
        try:
            with self.assertRaisesRegex(FetchError, "larger than"):
                fetch("https://example.com/", client=fake_site(handler))
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 3 * fetcher.MAX_BYTES)  # Bounded by the limit, not the bomb.


class ClientSetupTests(unittest.TestCase):
    def test_default_client_ignores_environment_and_redirects(self):
        client = make_client()
        try:
            self.assertFalse(client.trust_env)
            self.assertFalse(client.follow_redirects)
            self.assertEqual(client.timeout.connect, fetcher.CONNECT_TIMEOUT_SECONDS)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
