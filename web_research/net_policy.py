"""Public-web destination policy for Alfred's future research service.

This module only decides whether a destination is allowed. It makes no
network connections itself (resolution goes through an injectable resolver).

It is ONE layer of defence. The research container must also be blocked from
private networks at the network level, because application checks can have
bugs and a compromised process can ignore them.
"""

import ipaddress
import re
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http": 80, "https": 443}  # scheme -> default port
ALLOWED_PORTS = {80, 443}
MAX_URL_LENGTH = 2048

# Names that point at the local machine or the home network (NAS, router).
BLOCKED_NAME_SUFFIXES = (".localhost", ".local", ".lan", ".home", ".internal", ".home.arpa", ".corp")
BLOCKED_NAMES = {"localhost"}

# Global unicast IPv6 lives in 2000::/3. Everything else (loopback, unique-local,
# link-local, multicast, NAT64 64:ff9b::/96, IPv4-compatible ::/96) is refused.
IPV6_GLOBAL_UNICAST = ipaddress.ip_network("2000::/3")

# One DNS label: letters, digits, and hyphens, not starting or ending with a hyphen.
HOSTNAME_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


class BlockedDestination(ValueError):
    """Raised when a URL, hostname, or address is not an allowed public destination."""


def check_ip(address):
    """Return the parsed address if it is public; raise BlockedDestination otherwise."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        raise BlockedDestination(f"not an IP address: {address!r}") from None

    if ip.version == 6:
        if ip.scope_id:
            raise BlockedDestination("scoped IPv6 addresses are not allowed")
        # ::ffff:10.0.0.1 is really 10.0.0.1; judge the embedded IPv4 address.
        if ip.ipv4_mapped is not None:
            return check_ip(str(ip.ipv4_mapped))
        if ip not in IPV6_GLOBAL_UNICAST:
            raise BlockedDestination(f"non-public address: {ip}")

    # is_global excludes private, loopback, link-local (including the
    # 169.254.169.254 metadata service), carrier-grade NAT, documentation and
    # reserved ranges. Multicast is checked separately because some multicast
    # ranges count as "global".
    if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        raise BlockedDestination(f"non-public address: {ip}")
    return ip


def check_url(url):
    """Validate a URL's form. Return (hostname, port). Does not resolve DNS."""
    if not isinstance(url, str) or not url:
        raise BlockedDestination("URL must be a non-empty string")
    if len(url) > MAX_URL_LENGTH:
        raise BlockedDestination(f"URL is longer than {MAX_URL_LENGTH} characters")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise BlockedDestination("URL contains whitespace or control characters")
    # Parsers disagree about backslashes (some treat them as "/"), which lets a URL
    # look like one host to this check and another to the HTTP library.
    if "\\" in url:
        raise BlockedDestination("URL contains a backslash")

    try:
        parts = urlsplit(url)
        port = parts.port  # Raises ValueError for non-numeric or out-of-range ports.
    except ValueError:
        raise BlockedDestination("URL could not be parsed") from None

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise BlockedDestination(f"scheme not allowed: {scheme or '(none)'}")
    if parts.username is not None or parts.password is not None:
        raise BlockedDestination("URLs containing credentials are not allowed")

    hostname = (parts.hostname or "").rstrip(".")
    if not hostname:
        raise BlockedDestination("URL has no hostname")

    if port is None:
        port = ALLOWED_SCHEMES[scheme]
    if port not in ALLOWED_PORTS:
        raise BlockedDestination(f"port not allowed: {port}")

    # An IP literal such as https://10.0.0.1/ or https://[::1]/ is judged directly.
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return check_hostname(hostname), port
    check_ip(hostname)
    return hostname, port


def check_hostname(hostname):
    """Validate a DNS name (not an IP literal). Return its ASCII (IDNA) form."""
    try:
        ascii_name = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise BlockedDestination("hostname is not a valid international domain name") from None
    if not all(HOSTNAME_LABEL.fullmatch(label) for label in ascii_name.split(".")):
        raise BlockedDestination(f"hostname contains characters not allowed in a hostname: {ascii_name}")

    if ascii_name in BLOCKED_NAMES or ascii_name.endswith(BLOCKED_NAME_SUFFIXES):
        raise BlockedDestination(f"local network name not allowed: {ascii_name}")
    # Single-label names ("nas", "router") resolve through the home network.
    if "." not in ascii_name:
        raise BlockedDestination(f"single-label hostname not allowed: {ascii_name}")
    # Shorthand numeric forms such as 2130706433 or 0x7f.1 can still reach
    # 127.0.0.1 through some resolvers, so refuse names that are all digits/hex.
    labels = ascii_name.split(".")
    if all(label.isdigit() or label.startswith("0x") for label in labels):
        raise BlockedDestination(f"numeric hostname not allowed: {ascii_name}")
    return ascii_name


def resolve_public(hostname, port, resolver=socket.getaddrinfo):
    """Resolve a hostname and return its addresses only if ALL of them are public.

    Rejecting the whole host when any address is private stops a DNS answer
    from mixing a public address with a LAN one. The caller must connect to
    one of the returned addresses (not re-resolve the name), so a second DNS
    lookup cannot swap in a private address (DNS rebinding).
    """
    try:
        results = resolver(hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise BlockedDestination(f"could not resolve hostname: {hostname}") from None

    addresses = []
    for _family, _type, _proto, _canonname, sockaddr in results:
        ip = check_ip(sockaddr[0])
        if ip not in addresses:
            addresses.append(ip)
    if not addresses:
        raise BlockedDestination(f"hostname has no addresses: {hostname}")
    return addresses
