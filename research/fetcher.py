"""Fetch one public web page for Alfred's future research service.

R3a: URL checks, an explicit proxy, timeouts, and a size limit.
R3b: redirects are followed by hand, and every new address is checked first.
Content types are not checked yet (R3c).

The fetcher runs on the isolated network, where it cannot look up names.
The proxy resolves names and refuses private addresses; this module checks the
URL itself (scheme, port, local names) with net_policy before anything is sent.
"""

import ipaddress
import time
import zlib
from dataclasses import dataclass

import httpx

from net_policy import BlockedDestination, check_url

# The proxy container's name on the isolated network.
PROXY_URL = "http://proxy:4750"

CONNECT_TIMEOUT_SECONDS = 10.0  # Matches the proxy's own connect timeout.
READ_TIMEOUT_SECONDS = 10.0     # Longest wait for the next piece of data.
TOTAL_TIMEOUT_SECONDS = 20.0    # Whole download, so a slow trickle can't run forever.
MAX_BYTES = 2_000_000           # Counted after decompression.
USER_AGENT = "Alfred-research/0.1 (+https://github.com/MaxAxe0/Alfred)"
ACCEPT_ENCODING = "gzip, deflate"  # The only compression _read_limited can unpack.
DEFAULT_PORTS = {"http": 80, "https": 443}
MAX_REDIRECTS = 5
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class FetchError(Exception):
    """Raised when a page could not be fetched."""


class FetchBlocked(FetchError):
    """Raised when a URL or destination is refused by policy or by the proxy."""


@dataclass(frozen=True)
class FetchResult:
    url: str               # Where the page actually came from, after any redirects.
    status: int
    content_type: str
    body: bytes
    redirects: tuple = ()  # Earlier addresses that redirected, in order.


def make_client(transport=None):
    """Build the HTTP client. Tests pass a fake transport; real use goes through the proxy."""
    if transport is None:
        transport = httpx.HTTPTransport(proxy=PROXY_URL, retries=0)
    return httpx.Client(
        transport=transport,
        trust_env=False,         # Ignore http_proxy and similar settings; the proxy is set above.
        follow_redirects=False,  # Every redirect must be checked first (R3b).
        timeout=httpx.Timeout(
            connect=CONNECT_TIMEOUT_SECONDS,
            read=READ_TIMEOUT_SECONDS,
            write=READ_TIMEOUT_SECONDS,
            pool=CONNECT_TIMEOUT_SECONDS,
        ),
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": ACCEPT_ENCODING},
    )


def fetch(url, client=None):
    """Fetch one page and return a FetchResult, or raise FetchError/FetchBlocked."""
    request_url = _prepare(url)

    own_client = client is None
    if own_client:
        client = make_client()
    deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS  # Covers every hop together.
    redirects = []
    try:
        while True:
            with client.stream("GET", request_url) as response:
                next_url = _redirect_target(response, request_url)
                if next_url is None:
                    _check_status(response)
                    _check_declared_size(response)
                    body = _read_limited(response, deadline)
                    return FetchResult(
                        url=str(request_url),
                        status=response.status_code,
                        content_type=response.headers.get("content-type", ""),
                        body=body,
                        redirects=tuple(redirects),
                    )
            # A redirect. Its body is never read; the new address is checked before it is used.
            if len(redirects) == MAX_REDIRECTS:
                raise FetchError(f"more than {MAX_REDIRECTS} redirects")
            if time.monotonic() > deadline:
                raise FetchError(f"fetch took longer than {TOTAL_TIMEOUT_SECONDS:g} seconds")
            redirects.append(str(request_url))
            request_url = _prepare_redirect(next_url, request_url)
    except httpx.ProxyError as error:
        # An https:// tunnel the proxy refused (for example a private address).
        raise FetchBlocked(f"refused by proxy: {error}") from None
    except httpx.TimeoutException:
        raise FetchError(f"timed out fetching {url}") from None
    except zlib.error:
        raise FetchError(f"could not decompress {url}") from None
    except httpx.HTTPError as error:
        raise FetchError(f"could not fetch {url}: {error}") from None
    finally:
        if own_client:
            client.close()


def _prepare(url):
    """Run every URL check and return the httpx URL to request. Refused URLs never reach the network."""
    try:
        checked_host, checked_port = check_url(url)
    except BlockedDestination as error:
        raise FetchBlocked(str(error)) from None
    # Let httpx read the URL now, so one it can't parse is refused before any connection.
    try:
        request_url = httpx.URL(url)
    except httpx.InvalidURL as error:
        raise FetchBlocked(f"invalid URL: {error}") from None
    # Two parsers can disagree about tricky URLs. Only connect where net_policy approved.
    if not _same_destination(checked_host, checked_port, request_url):
        raise FetchBlocked("URL checker and HTTP library disagree about the destination")
    return request_url


def _redirect_target(response, current_url):
    """Return the absolute address a redirect points to, or None if this isn't a redirect."""
    if response.status_code not in REDIRECT_STATUSES:
        return None
    location = response.headers.get("location")
    if not location:
        raise FetchError(f"redirect (HTTP {response.status_code}) without a destination")
    try:
        # Resolves relative destinations such as "/new" or "//other.example/" against the current page.
        return str(current_url.join(location))
    except httpx.InvalidURL as error:
        raise FetchBlocked(f"invalid redirect destination: {error}") from None


def _prepare_redirect(next_url, current_url):
    """Check a redirect destination exactly like a first URL, plus refuse https -> http."""
    try:
        request_url = _prepare(next_url)
    except FetchBlocked as error:
        raise FetchBlocked(f"redirect to {next_url} refused: {error}") from None
    # Dropping encryption would let anyone on the path alter the page, so refuse it.
    if current_url.scheme == "https" and request_url.scheme == "http":
        raise FetchBlocked(f"redirect from https to http refused: {next_url}")
    return request_url


def _same_destination(checked_host, checked_port, request_url):
    """True if httpx will connect to the host and port that net_policy approved."""
    try:
        host = request_url.raw_host.decode("ascii").lower().rstrip(".")
    except UnicodeDecodeError:
        return False
    port = request_url.port or DEFAULT_PORTS.get(request_url.scheme)
    try:
        same_host = ipaddress.ip_address(host) == ipaddress.ip_address(checked_host)
    except ValueError:
        same_host = host == checked_host
    return same_host and port == checked_port


def _check_status(response):
    if response.status_code == 407:
        # A plain http:// request the proxy refused. Smokescreen explains why in this header.
        reason = response.headers.get("x-smokescreen-error", "no reason given")
        raise FetchBlocked(f"refused by proxy: {reason}")
    if not 200 <= response.status_code < 300:
        raise FetchError(f"server answered HTTP {response.status_code}")


def _check_declared_size(response):
    """Refuse early if the server says the page is too big. Servers can lie; see _read_limited."""
    try:
        declared = int(response.headers.get("content-length", ""))
    except ValueError:
        return
    if declared > MAX_BYTES:
        raise FetchError(f"page is larger than {MAX_BYTES} bytes")


def _read_limited(response, deadline):
    """Read and decompress the body in small steps, stopping at the size limit or the deadline.

    httpx's own decompression can turn one 64 KB network piece into tens of MB at
    once, so the raw bytes are decompressed here with a cap on every step.
    """
    decoder = _decoder_for(response.headers.get("content-encoding", ""))
    body = bytearray()
    for raw in response.iter_raw():
        if time.monotonic() > deadline:
            raise FetchError(f"fetch took longer than {TOTAL_TIMEOUT_SECONDS:g} seconds")
        if decoder is None:
            _append_limited(body, raw)
            continue
        data = raw
        while data:
            # Never ask for more than one byte past the limit; that's enough to know it's too big.
            _append_limited(body, decoder.decompress(data, MAX_BYTES - len(body) + 1))
            data = decoder.unconsumed_tail
    if decoder is not None:
        _append_limited(body, decoder.flush(MAX_BYTES - len(body) + 1))
    return bytes(body)


def _decoder_for(content_encoding):
    encoding = content_encoding.strip().lower()
    if encoding in ("", "identity"):
        return None
    if encoding in ("gzip", "x-gzip", "deflate"):
        return zlib.decompressobj(wbits=47)  # 47 accepts both gzip and zlib headers.
    raise FetchError(f"unsupported content encoding: {encoding}")


def _append_limited(body, piece):
    body.extend(piece)
    if len(body) > MAX_BYTES:
        raise FetchError(f"page is larger than {MAX_BYTES} bytes")
