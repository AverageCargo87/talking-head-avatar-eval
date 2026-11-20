"""The probe must distinguish open from closed and refuse to trust a run whose control is open."""
import http.server
import os
import socket
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from reachability_probe import control_blocked, main, probe  # noqa: E402

OPEN_PORT = 41603


class Answer421(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        code = 421 if self.path.startswith("/blocked") else 404
        self.send_response(code)
        self.end_headers()

    def log_message(self, *args):
        pass


def free_closed_port():
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]          # released on exit: nothing listens there


def test_probe_open_closed_and_control():
    server = http.server.HTTPServer(("localhost", OPEN_PORT), Answer421)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        opened = probe(f"http://localhost:{OPEN_PORT}/api", timeout=3)
        assert opened["status"] == 404 and opened["tcp_s"] is not None     # a live 404 = open route
        closed = probe(f"http://localhost:{free_closed_port()}/", timeout=3)
        assert closed["status"] is None and closed["error"]
        ctl = probe(f"http://localhost:{OPEN_PORT}/blocked", timeout=3)
        assert control_blocked(ctl, "421") and not control_blocked(ctl, "fail")
        assert main(["--control", f"http://localhost:{OPEN_PORT}/blocked", "--control-expect", "421",
                     f"http://localhost:{OPEN_PORT}/x"]) == 0
        # a control that answers normally means the probe cannot see blocks: untrusted run
        assert main(["--control", f"http://localhost:{OPEN_PORT}/fine", "--control-expect", "421",
                     f"http://localhost:{OPEN_PORT}/x"]) == 2
    finally:
        server.shutdown()
        server.server_close()
