"""Run from the project folder: python -m unittest discover -s research -v

These checks make no network connections; DNS is replaced by a fake resolver.
"""

import socket
import unittest

import net_policy
from net_policy import BlockedDestination, check_ip, check_url, resolve_public


def fake_resolver(*addresses):
    """Build a stand-in for socket.getaddrinfo that returns fixed addresses."""
    def resolver(hostname, port, type=0):
        if not addresses:
            raise socket.gaierror("name not found")
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port))
            for a in addresses
        ]
    return resolver


class AddressTests(unittest.TestCase):
    def test_public_addresses_allowed(self):
        for address in ("93.184.215.14", "1.1.1.1", "2606:4700:4700::1111"):
            with self.subTest(address=address):
                check_ip(address)

    def test_private_and_special_addresses_blocked(self):
        blocked = (
            "127.0.0.1", "127.255.255.254",          # loopback
            "10.0.0.1", "172.16.5.4", "192.168.1.1",  # home/LAN, router, NAS
            "169.254.169.254",                        # cloud metadata (link-local)
            "100.64.0.1",                             # carrier-grade NAT
            "0.0.0.0", "255.255.255.255",             # unspecified, broadcast
            "224.0.0.251", "239.255.255.250",         # multicast (mDNS, SSDP)
            "192.0.2.1", "198.18.0.1", "240.0.0.1",   # documentation, benchmarking, reserved
            "::1", "::", "fe80::1", "fc00::1", "fd12:3456::1", "ff02::1",
            "::ffff:192.168.1.1", "::ffff:127.0.0.1", # IPv4-mapped IPv6
            "64:ff9b::a00:1",                         # NAT64 form of 10.0.0.1
            "::a00:1",                                # IPv4-compatible form
            "2001:db8::1",                            # documentation
            "fe80::1%eth0",                           # scoped link-local
        )
        for address in blocked:
            with self.subTest(address=address):
                with self.assertRaises(BlockedDestination):
                    check_ip(address)

    def test_non_address_blocked(self):
        with self.assertRaises(BlockedDestination):
            check_ip("example.com")


class UrlTests(unittest.TestCase):
    def test_ordinary_urls_allowed(self):
        self.assertEqual(check_url("https://example.com/page?q=1"), ("example.com", 443))
        self.assertEqual(check_url("http://Example.COM./"), ("example.com", 80))
        self.assertEqual(check_url("https://example.com:443/"), ("example.com", 443))
        self.assertEqual(check_url("https://bücher.example/"), ("xn--bcher-kva.example", 443))

    def test_disallowed_forms_blocked(self):
        blocked = (
            "", "file:///etc/passwd", "ftp://example.com/", "javascript:alert(1)",
            "gopher://example.com/", "example.com", "//example.com/",
            "https://user:pass@example.com/", "https://user@example.com/",
            "https://example.com:8080/", "https://example.com:22/", "https://example.com:99999/",
            "https://example.com:abc/", "https://exa mple.com/", "https://example.com/\n",
            "https://" + "a" * 2050 + ".com/",
        )
        for url in blocked:
            with self.subTest(url=url):
                with self.assertRaises(BlockedDestination):
                    check_url(url)

    def test_local_names_blocked(self):
        for url in (
            "http://localhost/", "http://LOCALHOST./", "http://app.localhost/",
            "http://nas/", "http://router/", "http://printer.local/",
            "http://nas.lan/", "http://host.docker.internal/", "http://box.home.arpa/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(BlockedDestination):
                    check_url(url)

    def test_ip_literals_and_numeric_tricks_blocked(self):
        for url in (
            "http://127.0.0.1/", "http://[::1]/", "http://[::ffff:10.0.0.1]/",
            "http://169.254.169.254/latest/meta-data/", "http://192.168.1.1/",
            "http://2130706433/", "http://0x7f000001/", "http://127.1/", "http://0x7f.0.0.1/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(BlockedDestination):
                    check_url(url)

    def test_backslashes_and_bad_hostname_characters_blocked(self):
        for url in (
            "https://example.com\\@192.168.1.1/",   # httpx reads this host as 192.168.1.1
            "https://example.com\\.192.168.1.1/",
            "https://example.com/path\\x",
            "https://ex_ample.com/",
            "https://example.com%40192.168.1.1/",
            "https://-example.com/",
            "https://example-.com/",
            "https://example..com/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(BlockedDestination):
                    check_url(url)

    def test_public_ip_literal_allowed(self):
        self.assertEqual(check_url("https://1.1.1.1/"), ("1.1.1.1", 443))


class ResolutionTests(unittest.TestCase):
    def test_public_answers_returned_once_each(self):
        resolver = fake_resolver("93.184.215.14", "93.184.215.14", "2606:4700::1")
        addresses = resolve_public("example.com", 443, resolver=resolver)
        self.assertEqual([str(a) for a in addresses], ["93.184.215.14", "2606:4700::1"])

    def test_any_private_answer_blocks_the_host(self):
        # A name that resolves to a public AND a LAN address must be refused entirely.
        resolver = fake_resolver("93.184.215.14", "192.168.1.10")
        with self.assertRaises(BlockedDestination):
            resolve_public("evil.example", 443, resolver=resolver)

    def test_public_name_pointing_at_metadata_blocked(self):
        with self.assertRaises(BlockedDestination):
            resolve_public("metadata.example", 80, resolver=fake_resolver("169.254.169.254"))

    def test_resolution_failure_blocked(self):
        with self.assertRaises(BlockedDestination):
            resolve_public("missing.example", 443, resolver=fake_resolver())

    def test_default_resolver_is_the_system_resolver(self):
        # Documents the real default without making a network call.
        self.assertIs(resolve_public.__defaults__[0], socket.getaddrinfo)


if __name__ == "__main__":
    unittest.main()
