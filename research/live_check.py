"""R3d live check: real fetches through the real proxy, from the isolated network.

Run inside the fetcher container, from the project folder:
    docker compose -f research/compose.yaml run --rm fetcher

Each check prints PASS, FAIL, or NOT TESTED. NOT TESTED means an outside
service the check depends on (httpbin.org, nip.io) didn't cooperate, so the
check proves nothing either way.
"""

import os
import sys
import time
from urllib.parse import quote

import httpx

from fetcher import FetchBlocked, FetchError, fetch, make_client

ROUTER_IP = os.environ.get("ROUTER_IP", "192.168.1.1")
HTTPBIN = "https://httpbin.org"


def redirect_to(target):
    """A real public page that answers with a redirect to `target`."""
    return f"{HTTPBIN}/redirect-to?url={quote(target, safe='')}"


# (label, url, expected outcome, text the message must contain, outside service it relies on)
CHECKS = [
    ("public page (https)", "https://example.com/", "ok", None, None),
    ("public page (http)", "http://example.com/", "ok", None, None),
    ("real redirect chain", "http://wikipedia.org/", "ok", None, "wikipedia.org"),
    ("URL straight to router", f"http://{ROUTER_IP}/", "blocked", "non-public", None),
    ("redirect to router", redirect_to(f"http://{ROUTER_IP}/"), "blocked", "redirect to", "httpbin.org"),
    ("redirect to port 8080", redirect_to("https://example.com:8080/"), "blocked", "port not allowed", "httpbin.org"),
    ("redirect to metadata", redirect_to("http://169.254.169.254/latest/"), "blocked", "redirect to", "httpbin.org"),
    ("redirect https -> http", redirect_to("http://example.com/"), "blocked", "https to http", "httpbin.org"),
    ("image refused by type", f"{HTTPBIN}/image/png", "error", "unsupported content type", "httpbin.org"),
    ("DNS trick, proxy refuses", f"http://{ROUTER_IP}.nip.io/", "blocked", "refused by proxy", "nip.io"),
]


def outcome_of(url, client=None):
    """Return (outcome, message): 'ok', 'blocked', or 'error'."""
    try:
        result = fetch(url, client=client)
    except FetchBlocked as error:
        return "blocked", str(error)
    except FetchError as error:
        return "error", str(error)
    chain = " -> ".join(result.redirects + (result.url,))
    return "ok", f"{result.status}, {len(result.body):,} bytes, {result.encoding}; {chain}"


def looks_like_outside_trouble(message):
    """The outside service failed (server error, timeout) rather than our checks deciding."""
    return any(sign in message for sign in ("HTTP 5", "timed out", "could not fetch", "longer than"))


def judge(expected, must_contain, relies_on, outcome, message):
    if outcome == expected and (must_contain is None or must_contain in message):
        return "PASS"
    if relies_on and outcome == "error" and looks_like_outside_trouble(message):
        return f"NOT TESTED ({relies_on} didn't cooperate)"
    return "FAIL"


def main():
    failures = 0
    for label, url, expected, must_contain, relies_on in CHECKS:
        outcome, message = outcome_of(url)
        verdict = judge(expected, must_contain, relies_on, outcome, message)
        failures += verdict == "FAIL"
        print(f"{verdict:<11} {label:<26} expected {expected:<8} got {outcome}: {message[:110]}")
        time.sleep(0.3)  # Stay under the proxy's rate limit.

    # Skipping the proxy: a client with no proxy at all. The isolated network has no other exit.
    direct = make_client(transport=httpx.HTTPTransport(retries=0))
    outcome, message = outcome_of("https://example.com/", client=direct)
    direct.close()
    verdict = judge("error", "could not fetch", None, outcome, message)
    failures += verdict == "FAIL"
    print(f"{verdict:<11} {'skipping the proxy':<26} expected {'error':<8} got {outcome}: {message[:110]}")

    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
