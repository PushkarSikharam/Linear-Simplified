"""The outbound HTTP client keeps provider connections open and reuses them.

A fresh TLS connection to Azure Speech cost more than the speech itself (0.15 to 0.45 s against
about 0.2 s for a whole reply on a warm connection). These tests run a real local server, so they
exercise real sockets: reuse, a connection the server dropped while idle, timeouts and errors.
"""
from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import http_client


class Recorder(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive, as providers speak
    server: "LocalServer"

    def do_POST(self):  # noqa: N802 - the stdlib's name
        drop = self.server.drop_after_reply  # decided before replying, so the test cannot race it
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server.requests.append((self.client_address[1], self.path, body,
                                     self.headers.get("X-Test")))
        if self.path.startswith("/slow"):
            time.sleep(0.5)
        status = 429 if self.path.startswith("/limited") else 200
        reply = b"refused" if status == 429 else b"audio:" + body
        self.send_response(status)
        self.send_header("Content-Length", str(len(reply)))
        if self.path.startswith("/close"):
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(reply)
        if drop:
            self.close_connection = True

    def log_message(self, *args):  # quiet
        pass


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Recorder)
        self.requests: list[tuple[int, str, bytes, str | None]] = []
        self.drop_after_reply = False


class HttpClientTest(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"PIXEL_BLOCK_EXTERNAL_HTTP": "false"})
        env.start()
        self.addCleanup(env.stop)
        http_client.close_idle_connections()
        self.addCleanup(http_client.close_idle_connections)
        self.server = LocalServer()
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def post(self, path: str, body: bytes = b"hello", timeout: float = 2.0):
        return http_client.post(f"{self.base}{path}", headers={"X-Test": "yes"}, body=body,
                                timeout_seconds=timeout)

    def ports(self) -> list[int]:
        return [port for port, *_ in self.server.requests]

    def test_a_second_call_reuses_the_open_connection(self):
        first, second = self.post("/speak"), self.post("/speak")
        self.assertEqual((first.status, second.status), (200, 200))
        self.assertEqual(len(set(self.ports())), 1, "the second request opened a new connection")

    def test_the_request_arrives_intact(self):
        response = self.post("/v1beta/models/x:generate?alt=sse", body=b"payload")
        self.assertEqual(response.body, b"audio:payload")
        _, path, body, header = self.server.requests[0]
        self.assertEqual((path, body, header), ("/v1beta/models/x:generate?alt=sse", b"payload", "yes"))

    def test_an_error_status_is_returned_not_raised(self):
        response = self.post("/limited")
        self.assertEqual((response.status, response.body, response.ok), (429, b"refused", False))

    def test_a_connection_the_server_dropped_while_idle_is_replaced_once(self):
        self.server.drop_after_reply = True
        self.assertEqual(self.post("/speak").status, 200)
        self.server.drop_after_reply = False
        time.sleep(0.1)  # the server has closed its side; our pool still holds the connection
        self.assertEqual(self.post("/speak").status, 200)
        self.assertEqual(len(self.server.requests), 2, "the request must be sent exactly once")
        self.assertEqual(len(set(self.ports())), 2)

    def test_a_connection_marked_close_is_not_reused(self):
        self.post("/close")
        self.post("/speak")
        self.assertEqual(len(set(self.ports())), 2)

    def test_an_old_idle_connection_is_not_reused(self):
        self.post("/speak")
        with patch.object(http_client, "MAX_IDLE_SECONDS", 0.0):
            time.sleep(0.01)
            self.post("/speak")
        self.assertEqual(len(set(self.ports())), 2)

    def test_a_slow_answer_times_out_and_is_never_retried(self):
        with self.assertRaises(http_client.ProviderTimeout):
            self.post("/slow", timeout=0.1)
        time.sleep(0.6)
        self.assertEqual(len(self.server.requests), 1, "a timed-out request must not be sent twice")

    def test_a_reused_connection_honours_the_new_timeout(self):
        self.post("/speak", timeout=5.0)
        with self.assertRaises(http_client.ProviderTimeout):
            self.post("/slow", timeout=0.1)

    def test_nothing_listening_is_a_typed_provider_failure(self):
        """Linux refuses at once (unreachable); Windows retries until the timeout. Either way the
        caller gets a provider error it handles, never a raw socket exception."""
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free_port = probe.getsockname()[1]
        with self.assertRaises((http_client.ProviderUnreachable, http_client.ProviderTimeout)):
            http_client.post(f"http://127.0.0.1:{free_port}/", headers={}, body=b"", timeout_seconds=1.0)

    def test_only_http_and_https_urls_are_accepted(self):
        for url in ("ftp://example.com/x", "file:///etc/passwd", "https:///no-host"):
            with self.subTest(url=url):
                with self.assertRaises(http_client.ProviderUnreachable):
                    http_client.post(url, headers={}, body=b"", timeout_seconds=1.0)

    def test_blocking_still_stops_every_call_before_any_connection(self):
        with patch.dict(os.environ, {"PIXEL_BLOCK_EXTERNAL_HTTP": "true"}):
            with self.assertRaises(http_client.ExternalCallBlocked):
                self.post("/speak")
        self.assertEqual(self.server.requests, [])

    def test_concurrent_calls_each_get_their_own_connection(self):
        results: list[int] = []

        def call():
            results.append(self.post("/speak").status)

        threads = [threading.Thread(target=call) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results, [200] * 6)
        self.assertEqual(len(self.server.requests), 6)


if __name__ == "__main__":
    unittest.main()
