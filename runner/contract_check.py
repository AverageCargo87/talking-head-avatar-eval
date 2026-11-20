#!/usr/bin/env python3
"""Check an avatar runner (mock or real) against the shared HTTP contract.

    python runner/contract_check.py http://localhost:8090

The lesson must be able to swap the mock for the real runner without a code change, so
both are held to the same checks: /health, /avatars, the first MJPEG frame of /stream,
/push with half a second of PCM16 and /keepalive. Standard library only.
"""
import base64
import json
import sys
import urllib.error
import urllib.request

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never route localhost via a proxy


def get_json(url, timeout=10):
    with OPENER.open(url, timeout=timeout) as r:
        return r.status, json.loads(r.read())


def post_json(url, body, timeout=10):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def first_mjpeg_frame(url, timeout=10, limit=1 << 20):
    with OPENER.open(url, timeout=timeout) as r:
        ctype = r.headers.get("Content-Type", "")
        buf = b""
        while len(buf) < limit:
            chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
            if not chunk:
                break
            buf += chunk
            start = buf.find(b"\xff\xd8")
            end = buf.find(b"\xff\xd9", start + 2) if start >= 0 else -1
            if start >= 0 and end > start:
                return ctype, buf[start:end + 2]
    return ctype, None


def check(base):
    base = base.rstrip("/")
    results = []

    def ok(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    status, h = get_json(base + "/health")
    ok("GET /health answers 200 with ok and mock flags", status == 200 and "ok" in h and "mock" in h, json.dumps(h)[:120])
    status, av = get_json(base + "/avatars")
    faces = av.get("avatars", [])
    ok("GET /avatars lists faces as {id, name}", status == 200 and faces and all("id" in f and "name" in f for f in faces),
       f"{len(faces)} faces")
    face = faces[0]["id"] if faces else ""
    ctype, jpg = first_mjpeg_frame(f"{base}/stream?avatar={face}")
    ok("GET /stream is MJPEG with boundary=frame", ctype.startswith("multipart/x-mixed-replace") and "boundary=frame" in ctype, ctype)
    ok("GET /stream delivers a JPEG frame", jpg is not None and len(jpg) > 1000, f"{len(jpg or b'')} bytes")
    pcm = b"\x00\x00" * 8000                     # 0.5 s of PCM16 mono 16 kHz
    status, p = post_json(base + "/push", {"b64": base64.b64encode(pcm).decode(), "last": True})
    ok("POST /push accepts PCM16 and reports its duration", status == 200 and abs(p.get("seconds", 0) - 0.5) < 0.01, json.dumps(p))
    status, p = post_json(base + "/push", {"b64": ""})
    ok("POST /push rejects empty audio with 400", status == 400, json.dumps(p))
    status, k = get_json(base + "/keepalive")
    ok("GET /keepalive answers 200", status == 200 and "ok" in k, json.dumps(k)[:120])
    return results


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    results = check(sys.argv[1])
    for name, passed, detail in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}  ({detail})")
    sys.exit(0 if all(p for _, p, _ in results) else 1)


if __name__ == "__main__":
    main()
