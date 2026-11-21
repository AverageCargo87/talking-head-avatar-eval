#!/usr/bin/env python3
"""Is a vendor reachable from HERE? A probe that proves it can see a block before it reports.

    python tools/reachability_probe.py --control https://blocked.example/ --control-expect 421 \
        https://api.vendor-a.example/ https://api.vendor-b.example/

Run it ON the vantage point that matters (a server in the target country, a home connection),
never through a VPN laptop. For every URL it records DNS, TCP connect, TLS handshake time and
the HTTP status. Any HTTP answer, even 401/403/404 from the vendor's real API, means the route
is open; DNS failures, TLS resets and timeouts mean closed.

The control is the point: an endpoint KNOWN to be blocked from this vantage point. If the control
does not come back blocked (an expected status such as 421/451/403, or ``fail`` for any network
failure), the whole run is marked untrustworthy: a probe that cannot see a known block cannot be
trusted to report an open route. Standard library only; JSON with --json.
"""
import argparse
import http.client
import json
import socket
import ssl
import sys
import time
from urllib.parse import urlparse


def probe(url: str, timeout: float = 10.0) -> dict:
    u = urlparse(url)
    host = u.hostname
    port = u.port or (443 if u.scheme == "https" else 80)
    res = {"url": url, "dns_s": None, "tcp_s": None, "tls_s": None, "status": None, "error": None}
    t0 = time.monotonic()
    try:
        addrs = [ai[4] for ai in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]
        res["dns_s"] = round(time.monotonic() - t0, 3)
    except OSError as e:
        res["error"] = f"dns: {e.__class__.__name__}"
        return res
    try:
        # Try every resolved address in order, as browsers do: a host whose first
        # record is an unreachable IPv6 address is still open over IPv4.
        sock, last = None, None
        for addr in addrs:
            t1 = time.monotonic()
            try:
                sock = socket.create_connection(addr[:2], timeout=timeout)
                res["tcp_s"] = round(time.monotonic() - t1, 3)
                break
            except OSError as e:
                last = e
        if sock is None:
            raise last
        if u.scheme == "https":
            t2 = time.monotonic()
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            res["tls_s"] = round(time.monotonic() - t2, 3)
            conn = http.client.HTTPSConnection(host, port, timeout=timeout)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.sock = sock
        conn.request("GET", u.path or "/", headers={"User-Agent": "reachability-probe", "Host": host})
        res["status"] = conn.getresponse().status
        conn.close()
    except (OSError, ssl.SSLError, http.client.HTTPException) as e:
        res["error"] = f"{e.__class__.__name__}: {str(e)[:80]}"
    return res


def control_blocked(res: dict, expect: str) -> bool:
    if expect == "fail":
        return res["status"] is None
    return res["status"] is not None and str(res["status"]) in expect.split(",")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--control", required=True, help="URL known to be blocked from this vantage point")
    ap.add_argument("--control-expect", default="fail",
                    help="what 'blocked' looks like: comma-separated HTTP statuses, or 'fail' (default)")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    control = probe(a.control, a.timeout)
    trusted = control_blocked(control, a.control_expect)
    rows = [probe(u, a.timeout) for u in a.urls]
    for r in rows:
        r["open"] = r["status"] is not None
    if a.json:
        print(json.dumps({"control": control, "control_blocked": trusted, "results": rows}, indent=1))
    else:
        state = "BLOCKED as expected" if trusted else "NOT blocked: this run cannot be trusted"
        print(f"control {a.control}: {control['status'] or control['error']} -> {state}")
        for r in rows:
            timing = f"tcp {r['tcp_s']} s, tls {r['tls_s']} s" if r["tcp_s"] is not None else ""
            print(f"  {'OPEN  ' if r['open'] else 'CLOSED'} {r['url']}  {r['status'] or r['error']}  {timing}")
    return 0 if trusted else 2


if __name__ == "__main__":
    sys.exit(main())
