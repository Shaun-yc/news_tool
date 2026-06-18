import socket
import unittest

from services.url_security import validate_public_url


def resolve_to(address):
    return lambda hostname, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]


class UrlSecurityTests(unittest.TestCase):
    def test_validate_public_url_allows_public_address(self):
        validate_public_url("https://www.example.com/news/1", resolver=resolve_to("93.184.216.34"))

    def test_validate_public_url_rejects_private_address(self):
        with self.assertRaisesRegex(ValueError, "內部網路"):
            validate_public_url("http://internal.example", resolver=resolve_to("127.0.0.1"))

    def test_validate_public_url_rejects_non_http_scheme(self):
        with self.assertRaisesRegex(ValueError, "HTTP"):
            validate_public_url("file:///etc/passwd")


if __name__ == "__main__":
    unittest.main()
