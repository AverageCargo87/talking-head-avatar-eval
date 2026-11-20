#!/usr/bin/env python3
"""Resumable, parallel downloader for the weight list in local/weights.txt.

    python local/download_weights.py local/weights.txt --root /path/to/ComfyUI [--threads 12]

Each file is cut into 16 MB ranges; worker threads take ranges from a shared queue, a range
that stalls for more than 4 minutes is dropped and re-queued, and finished ranges stay on disk,
so an interrupted run resumes where it stopped. Written for a slow, flaky link where a
single-stream download of tens of gigabytes kept dying.

Set HF_ENDPOINT to use a Hugging Face mirror; standard HTTPS_PROXY variables are honoured.
"""
import argparse
import os
import queue
import threading
import time
import urllib.request

CHUNK = 16 << 20
STALL = 240


def opener():
    o = urllib.request.build_opener()  # honours HTTPS_PROXY / NO_PROXY from the environment
    o.addheaders = [("User-Agent", "weights-downloader")]
    return o


def rewrite(url: str) -> str:
    mirror = os.environ.get("HF_ENDPOINT")
    if mirror and url.startswith("https://huggingface.co/"):
        return mirror.rstrip("/") + "/" + url.split("https://huggingface.co/", 1)[1]
    return url


def size_of(op, url: str) -> int:
    for attempt in range(20):
        try:
            r = op.open(urllib.request.Request(url, method="HEAD"), timeout=60)
            return int(r.headers["Content-Length"])
        except Exception as e:  # noqa: BLE001
            print("HEAD retry", attempt, type(e).__name__, flush=True)
            time.sleep(3)
    raise SystemExit(f"no size for {url}")


def fetch(url: str, out: str, threads: int) -> None:
    if os.path.exists(out):
        print("exists", out, flush=True)
        return
    op = opener()
    total = size_of(op, url)
    parts = out + ".chunks"
    os.makedirs(parts, exist_ok=True)
    n = (total + CHUNK - 1) // CHUNK
    q: "queue.Queue[int]" = queue.Queue()
    for i in range(n):
        f = os.path.join(parts, f"{i:05d}")
        want = min(CHUNK, total - i * CHUNK)
        if not (os.path.exists(f) and os.path.getsize(f) == want):
            q.put(i)
    done = [sum(os.path.getsize(os.path.join(parts, x)) for x in os.listdir(parts) if not x.endswith(".t"))]

    def worker():
        while True:
            try:
                i = q.get_nowait()
            except queue.Empty:
                return
            a = i * CHUNK
            b = min(total, a + CHUNK) - 1
            tmp = os.path.join(parts, f"{i:05d}.t")
            t0, got = time.time(), 0
            try:
                req = urllib.request.Request(url, headers={"Range": f"bytes={a}-{b}"})
                with op.open(req, timeout=30) as r, open(tmp, "wb") as f:
                    while True:
                        c = r.read(256 << 10)
                        if not c:
                            break
                        f.write(c)
                        got += len(c)
                        if time.time() - t0 > STALL:
                            raise TimeoutError("range stalled")
                if got != b - a + 1:
                    raise IOError(f"range {got} != {b - a + 1}")
                os.replace(tmp, os.path.join(parts, f"{i:05d}"))
                done[0] += got
            except Exception as e:  # noqa: BLE001
                print("retry range", i, type(e).__name__, str(e)[:80], flush=True)
                q.put(i)
                time.sleep(2)

    pool = [threading.Thread(target=worker, daemon=True) for _ in range(threads)]
    for t in pool:
        t.start()
    t0, d0 = time.time(), done[0]
    while any(t.is_alive() for t in pool):
        time.sleep(30)
        rate = (done[0] - d0) / max(time.time() - t0, 1) / 1e6
        print(f"{os.path.basename(out)}: {done[0] / 1e9:.2f}/{total / 1e9:.2f} GB, {rate:.1f} MB/s", flush=True)
    with open(out + ".tmp", "wb") as f:
        for i in range(n):
            with open(os.path.join(parts, f"{i:05d}"), "rb") as s:
                f.write(s.read())
    if os.path.getsize(out + ".tmp") != total:
        raise SystemExit("size mismatch after assembly")
    os.replace(out + ".tmp", out)
    for x in os.listdir(parts):
        os.remove(os.path.join(parts, x))
    os.rmdir(parts)
    print("DONE", out, flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("list")
    ap.add_argument("--root", required=True, help="ComfyUI folder; paths in the list are relative to it")
    ap.add_argument("--threads", type=int, default=12)
    a = ap.parse_args()
    for line in open(a.list, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        url, rel = line.split(" ", 1)
        out = os.path.join(a.root, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        fetch(rewrite(url), out, a.threads)
    print("ALL DOWNLOADED", flush=True)


if __name__ == "__main__":
    main()
