"""The tests' network block: outside addresses fail at once, loopback works.

    python -m unittest tests.test_offline        (from the repo root)
"""

import os
import socket
import sys
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402


class OfflineConnect(unittest.TestCase):
    def test_outside_addresses_are_refused(self):
        for addr in [("93.184.216.34", 443), ("example.com", 80),
                     ("2606:2800:220:1::1", 443, 0, 0), ("10.0.0.1", 5432)]:
            self.assertFalse(offline_net.is_loopback(addr), addr)
        with unittest.mock.patch("socket.socket.connect", offline_net.connect):
            s = socket.socket()
            try:
                with self.assertRaisesRegex(RuntimeError, "offline in tests"):
                    s.connect(("93.184.216.34", 443))
            finally:
                s.close()

    def test_loopback_addresses_are_allowed(self):
        for addr in [("127.0.0.1", 1), ("localhost", 1), ("::1", 1, 0, 0),
                     ("127.5.5.5", 1), ("::ffff:127.0.0.1", 1, 0, 0)]:
            self.assertTrue(offline_net.is_loopback(addr), addr)

    def test_socketpair_still_works(self):
        # asyncio's event loop on Windows makes its self-pipe this way
        with unittest.mock.patch("socket.socket.connect", offline_net.connect):
            a, b = socket.socketpair()
            try:
                a.sendall(b"x")
                self.assertEqual(b.recv(1), b"x")
            finally:
                a.close()
                b.close()


if __name__ == "__main__":
    unittest.main()
