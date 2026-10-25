"""Run from the project folder: python -m unittest discover -s research -v

These checks make no network connections. Each test builds a fake website
(httpx.MockTransport) that answers however the test needs.
"""

import codecs
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


def site(pages):
    """A fake website with several pages: {url: (status, headers)}. Records every URL contacted.

    Pages not listed answer 404. Bodies are small HTML unless the headers say otherwise.
    """
    contacted = []

    def handler(request):
        url = str(request.url)
        contacted.append(url)
        status, headers = pages.get(url, (404, {}))
        headers = dict(headers)  # A copy, so repeat visits see the same page.
        body = headers.pop("_body", b"<p>page</p>")
        return httpx.Response(status, stream=httpx.ByteStream(body),
                              headers={"content-type": "text/html", **headers})

    handler.contacted = contacted
    return handler


def moved(location, status=302):
    return (status, {"location": location})


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


class RedirectTests(unittest.TestCase):
    def test_follows_a_redirect_to_a_public_page(self):
        handler = site({
            "https://example.com/old": moved("https://example.com/new", 301),
            "https://example.com/new": (200, {}),
        })
        result = fetch("https://example.com/old", client=fake_site(handler))
        self.assertEqual(result.url, "https://example.com/new")
        self.assertEqual(result.redirects, ("https://example.com/old",))
        self.assertEqual(handler.contacted, ["https://example.com/old", "https://example.com/new"])

    def test_every_redirect_status_is_followed(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                handler = site({
                    "https://example.com/a": moved("https://example.com/b", status),
                    "https://example.com/b": (200, {}),
                })
                self.assertEqual(fetch("https://example.com/a", client=fake_site(handler)).status, 200)

    def test_relative_destinations_are_resolved(self):
        handler = site({
            "https://example.com/a/b": moved("../c"),
            "https://example.com/c": moved("//other.example/d"),
            "https://other.example/d": (200, {}),
        })
        result = fetch("https://example.com/a/b", client=fake_site(handler))
        self.assertEqual(result.url, "https://other.example/d")
        self.assertEqual(len(result.redirects), 2)

    def test_redirects_to_forbidden_places_are_never_contacted(self):
        for location in (
            "http://192.168.1.1/admin",          # router
            "//192.168.1.1/",                    # same, written relative to the scheme
            "https://localhost/",
            "https://nas/",
            "https://169.254.169.254/latest/",   # cloud metadata
            "https://example.com:8080/",         # odd port: the gap the proxy leaves
            "https://example.com\\@192.168.1.1/",
            "ftp://example.com/",
            "https://user:pw@example.com/",
        ):
            with self.subTest(location=location):
                handler = site({"https://example.com/": moved(location)})
                with self.assertRaisesRegex(FetchBlocked, "redirect"):
                    fetch("https://example.com/", client=fake_site(handler))
                self.assertEqual(handler.contacted, ["https://example.com/"])

    def test_a_bad_hop_later_in_the_chain_is_refused(self):
        handler = site({
            "https://example.com/1": moved("https://example.com/2"),
            "https://example.com/2": moved("http://192.168.1.1/"),
        })
        with self.assertRaises(FetchBlocked):
            fetch("https://example.com/1", client=fake_site(handler))
        self.assertNotIn("http://192.168.1.1/", handler.contacted)

    def test_https_to_http_downgrade_refused(self):
        handler = site({"https://example.com/": moved("http://example.com/")})
        with self.assertRaisesRegex(FetchBlocked, "https to http"):
            fetch("https://example.com/", client=fake_site(handler))
        self.assertEqual(handler.contacted, ["https://example.com/"])

    def test_http_to_https_upgrade_allowed(self):
        handler = site({
            "http://example.com/": moved("https://example.com/", 301),
            "https://example.com/": (200, {}),
        })
        self.assertEqual(fetch("http://example.com/", client=fake_site(handler)).url, "https://example.com/")

    def test_too_many_redirects(self):
        handler = site({"https://example.com/loop": moved("https://example.com/loop")})
        with self.assertRaisesRegex(FetchError, "more than 5 redirects"):
            fetch("https://example.com/loop", client=fake_site(handler))
        self.assertEqual(len(handler.contacted), 6)  # The first request plus 5 redirects.

    def test_five_redirects_are_allowed(self):
        pages = {f"https://example.com/{i}": moved(f"https://example.com/{i + 1}") for i in range(5)}
        pages["https://example.com/5"] = (200, {})
        result = fetch("https://example.com/0", client=fake_site(site(pages)))
        self.assertEqual(len(result.redirects), 5)

    def test_redirect_without_a_destination(self):
        handler = site({"https://example.com/": (302, {})})
        with self.assertRaisesRegex(FetchError, "without a destination"):
            fetch("https://example.com/", client=fake_site(handler))

    def test_redirect_page_body_is_not_downloaded(self):
        # A redirect with a body far over the size limit: reading it would raise "larger than".
        huge = b"x" * (fetcher.MAX_BYTES + 1)
        handler = site({
            "https://example.com/": (302, {"location": "/next", "_body": huge}),
            "https://example.com/next": (200, {}),
        })
        self.assertEqual(fetch("https://example.com/", client=fake_site(handler)).status, 200)

    def test_deadline_covers_the_whole_chain(self):
        clock = itertools.count(0, 15)  # Each reading 15 s later: the second hop passes 20 s.
        handler = site({
            "https://example.com/a": moved("https://example.com/b"),
            "https://example.com/b": moved("https://example.com/c"),
            "https://example.com/c": (200, {}),
        })
        with mock.patch.object(fetcher.time, "monotonic", side_effect=lambda: next(clock)):
            with self.assertRaisesRegex(FetchError, "longer than 20 seconds"):
                fetch("https://example.com/a", client=fake_site(handler))


def typed(content_type, body=b"<p>hello</p>"):
    """A handler answering with this Content-Type header (None = no header at all)."""
    def handler(request):
        headers = {} if content_type is None else {"content-type": content_type}
        return httpx.Response(200, stream=httpx.ByteStream(body), headers=headers)
    return handler


class ContentTypeTests(unittest.TestCase):
    def test_text_types_are_accepted(self):
        for content_type in ("text/html", "text/plain", "application/xhtml+xml",
                             "Text/HTML; Charset=UTF-8", "text/html;charset=utf-8; foo=bar"):
            with self.subTest(content_type=content_type):
                fetch("https://example.com/", client=fake_site(typed(content_type)))

    def test_other_types_are_refused(self):
        for content_type in ("image/png", "application/pdf", "application/json",
                             "application/octet-stream", "video/mp4", "text/htmlx"):
            with self.subTest(content_type=content_type):
                with self.assertRaisesRegex(FetchError, "unsupported content type"):
                    fetch("https://example.com/", client=fake_site(typed(content_type)))

    def test_missing_content_type_is_refused(self):
        for content_type in (None, "", "; charset=utf-8"):
            with self.subTest(content_type=content_type):
                with self.assertRaisesRegex(FetchError, "did not say"):
                    fetch("https://example.com/", client=fake_site(typed(content_type)))

    def test_refused_types_are_not_downloaded(self):
        # Reading this body would raise "larger than"; refusing by type must happen first.
        huge = b"x" * (fetcher.MAX_BYTES + 1)
        with self.assertRaisesRegex(FetchError, "unsupported content type"):
            fetch("https://example.com/", client=fake_site(typed("application/zip", huge)))


class DecodingTests(unittest.TestCase):
    def decode(self, body, content_type="text/html"):
        result = fetch("https://example.com/", client=fake_site(typed(content_type, body)))
        return result.text, result.encoding

    def test_utf8_by_default(self):
        self.assertEqual(self.decode("café ☕".encode("utf-8")), ("café ☕", "utf-8"))

    def test_header_charset_is_used(self):
        text, encoding = self.decode("café".encode("cp1252"), "text/html; charset=windows-1252")
        self.assertEqual((text, encoding), ("café", "cp1252"))

    def test_latin1_and_ascii_labels_mean_windows_1252(self):
        # 0x93/0x94 are curly quotes in windows-1252 but invisible control codes in latin-1.
        for label in ("iso-8859-1", "latin1", "us-ascii"):
            with self.subTest(label=label):
                self.assertEqual(self.decode(b"\x93hi\x94", f"text/html; charset={label}")[0], "“hi”")

    def test_meta_charset_is_used_when_the_header_has_none(self):
        for meta in (b'<meta charset="shift_jis">', b"<META CHARSET=shift_jis>",
                     b'<meta http-equiv="Content-Type" content="text/html; charset=shift_jis">'):
            with self.subTest(meta=meta):
                text, encoding = self.decode(meta + "日本".encode("shift_jis"))
                self.assertTrue(text.endswith("日本"))
                self.assertEqual(encoding, "shift_jis")

    def test_header_wins_over_meta(self):
        body = b'<meta charset="shift_jis">' + "café".encode("utf-8")
        self.assertEqual(self.decode(body, "text/html; charset=utf-8")[1], "utf-8")

    def test_meta_is_ignored_for_plain_text(self):
        self.assertEqual(self.decode(b'<meta charset="shift_jis"> hi', "text/plain")[1], "utf-8")

    def test_meta_only_counts_in_the_first_1024_bytes(self):
        body = b" " * 1024 + b'<meta charset="shift_jis">'
        self.assertEqual(self.decode(body)[1], "utf-8")

    def test_byte_order_mark_wins_and_is_removed(self):
        body = codecs.BOM_UTF8 + "café".encode("utf-8")
        self.assertEqual(self.decode(body, "text/html; charset=windows-1252"), ("café", "utf-8"))
        self.assertEqual(self.decode(codecs.BOM_UTF16_LE + "hi".encode("utf-16-le"))[0], "hi")

    def test_unknown_or_non_text_encodings_fall_back_to_utf8(self):
        for label in ("no-such-encoding", "base64", "rot13"):
            with self.subTest(label=label):
                self.assertEqual(self.decode(b"hello", f"text/html; charset={label}"), ("hello", "utf-8"))

    def test_invalid_bytes_are_replaced_not_fatal(self):
        self.assertEqual(self.decode(b"ok \xff\xfe there")[0], "ok �� there")

    def test_body_bytes_are_kept_alongside_the_text(self):
        result = fetch("https://example.com/", client=fake_site(typed("text/html", b"<p>x</p>")))
        self.assertEqual((result.body, result.text), (b"<p>x</p>", "<p>x</p>"))


class LimitTests(unittest.TestCase):
    def test_declared_size_too_large(self):
        handler = page(**{"content-length": str(fetcher.MAX_BYTES + 1)})
        with self.assertRaisesRegex(FetchError, "larger than"):
            fetch("https://example.com/", client=fake_site(handler))

    def test_body_larger_than_limit_without_a_declared_size(self):
        def handler(request):
            # A generator body has no Content-Length, so only the running count can stop it.
            return httpx.Response(200, content=(b"x" * 100 for _ in range(5)),
                                  headers={"content-type": "text/html"})
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
            return httpx.Response(200, content=in_pieces(bomb),
                                  headers={"content-encoding": "gzip", "content-type": "text/html"})

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
