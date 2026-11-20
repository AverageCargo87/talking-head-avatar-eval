#!/usr/bin/env python3
"""Real avatar runner (bitHuman SDK) -> browser, WITHOUT LiveKit. Same contract as the mock.

Why this shape: the vendor had no browser SDK; its core yields frames as numpy BGR arrays
(``frame.bgr_image``, 25 fps), so delivery to the browser is ours. LiveKit turned out to be
unnecessary: this runner is a small aiohttp server with exactly the contract of
runner/mock-core.mjs, so the lesson switches between mock and real without a code change:

  GET  /health?avatar=id  -> {ok, mock:false, has_frame, avatar, avatars, ...billing fields}
  GET  /avatars           -> {avatars:[{id,name}]}
  GET  /stream?avatar=id  -> MJPEG (multipart/x-mixed-replace; boundary=frame)
  POST /push {b64,last}   -> PCM16 mono 16 kHz -> push_audio -> the avatar's lips move
  GET  /keepalive         -> keep the frame generator warm for 2 s (only near real speech)

The browser plays the audio itself (the same PCM); the runner serves video only.

Billing shaped almost every line below. This vendor bills RENDERED FRAMES, not speech, and
an early version ran the frame generator unconditionally: the avatar "breathed" into an
empty room and one evening cost 83,749 frames. The rules now, all independent:
  1) NO SPEECH, NO FRAMES: frames start when audio arrives and stop IDLE_TAIL seconds
     after it ends (the tail lets the mouth close on the last syllable). In pauses the
     avatar freezes on its last frame: cheaper than breathing, and honest.
  2) NO VIEWERS, NO FRAMES: the generator is stopped IDLE_GRACE seconds after the last
     /stream viewer leaves. A viewer is detected by the transport, not by an exception:
     browsers leave silently, so dead sockets get TCP keepalive and a write timeout.
  3) A HARD FRAME BUDGET per process (FRAME_BUDGET): when reached, generation stops until
     restart and /health says why. Better a frozen lesson than a silently drained balance.

This is the trimmed public version: an earlier revision also switched off the vendor's
host-side metering for its v2 models through private SDK internals; that part is omitted.
It needs the vendor SDK, an API secret and model files, so it is not exercised by the tests;
runner/contract_check.py checks any runner (mock or real) against the shared contract.

ENV:
  BITHUMAN_API_SECRET   vendor API secret (required)
  BITHUMAN_MODEL_DIR    folder with several .imx models (gives the lesson a face choice)
  BITHUMAN_MODEL_PATH   or a single .imx
  RUNNER_HOST, RUNNER_PORT   where to listen (default localhost:8090)
  JPEG_QUALITY          MJPEG quality 1..100 (default 80)
  IDLE_TAIL, IDLE_GRACE, WARM_MAX, FRAME_BUDGET, PUSH_CHUNK   see below
  WARMUP_WAV            optional 16 kHz mono wav pushed once after a face switch: the first
                        line after loading otherwise goes to "spinning up" the articulation
"""
import asyncio
import base64
import glob
import os
import time

import cv2
from aiohttp import web
from bithuman import AsyncBithuman

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}
JPEG_Q = int(os.environ.get("JPEG_QUALITY", "80"))
SECRET = os.environ.get("BITHUMAN_API_SECRET")
IDLE_TAIL = float(os.environ.get("IDLE_TAIL", "1.5"))       # seconds of frames after speech ends
IDLE_GRACE = float(os.environ.get("IDLE_GRACE", "8"))       # seconds to wait for a returning viewer
WARM_MAX = float(os.environ.get("WARM_MAX", "90"))          # keepalive only this close to real speech
FRAME_BUDGET = int(os.environ.get("FRAME_BUDGET", "30000"))  # ~30 credits on the cheapest model
PUSH_CHUNK = float(os.environ.get("PUSH_CHUNK", "0.04"))    # one avatar frame = 40 ms of audio

runtime = None
current = {"id": None}
latest = {"jpg": None, "last_audio": 0.0, "frames": 0, "warm_until": 0.0, "chose_at": 0.0}
drain_task = None
stop_timer = None
feeder = None
viewers = 0
switch_lock = asyncio.Lock()


def models():
    """id -> model path. A folder (several faces) wins over a single file."""
    out = {}
    folder = os.environ.get("BITHUMAN_MODEL_DIR")
    if folder:
        for p in sorted(glob.glob(os.path.join(folder, "*.imx"))):
            out[os.path.splitext(os.path.basename(p))[0]] = p
    one = os.environ.get("BITHUMAN_MODEL_PATH")
    if one and not out:
        out[os.path.splitext(os.path.basename(one))[0]] = one
    return out


def avatar_list():
    return [{"id": k, "name": k.replace("_", " ").replace("-", " ")} for k in models()]


async def drain_frames(rt):
    """Background task: pull the endless run() generator and keep the freshest JPEG.

    Every frame from here costs money; the task lives only while speech (or a short warm-up)
    needs it. Never iterate run() inside an HTTP handler: it never ends.
    """
    async for frame in rt.run():
        if latest["frames"] >= FRAME_BUDGET:
            latest["budget_hit"] = True
            print(f"FRAME BUDGET {FRAME_BUDGET} reached: generation off until restart")
            break
        if getattr(frame, "has_image", False):
            ok, buf = cv2.imencode(".jpg", frame.bgr_image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
            if ok:
                # Do NOT re-time frames here. Forcing a strict 25 fps from the start of a line
                # once stretched 15.6 s of articulation over 24 s: the engine produces ~30 frames
                # per second of audio and the runner-side sync is already honest. Drift is born
                # LATER, in MJPEG delivery, and is handled in stream().
                latest["jpg"] = buf.tobytes()
                latest["frames"] += 1
        now = time.time()
        if now - latest["last_audio"] > IDLE_TAIL and now > latest["warm_until"]:
            print(f"frames stop: speech over (frames this process: {latest['frames']})")
            break


def start_frames(why="speech"):
    """Start frame generation. Called when AUDIO arrives, not when a viewer arrives."""
    global drain_task, stop_timer
    if stop_timer:
        stop_timer.cancel()
        stop_timer = None
    if latest.get("budget_hit") or runtime is None:
        return
    if drain_task is None or drain_task.done():
        drain_task = asyncio.create_task(drain_frames(runtime))
        print(f"frames start: {why} (viewers {viewers})")


async def stop_later():
    """Stop generation if nobody came back within IDLE_GRACE seconds."""
    global drain_task, stop_timer
    try:
        await asyncio.sleep(IDLE_GRACE)
    except asyncio.CancelledError:
        return
    if viewers <= 0 and drain_task:
        drain_task.cancel()
        await asyncio.gather(drain_task, return_exceptions=True)
        drain_task = None
        print("frames stopped: no viewers")
    stop_timer = None


async def warm_up():
    """Optional: push 1.5 s of real speech after a face switch, while the student looks at
    the loading screen. Silence does not spin up the articulation pipeline; speech does."""
    path = os.environ.get("WARMUP_WAV")
    if not path or runtime is None:
        return
    import wave
    try:
        with wave.open(path) as f:
            pcm = f.readframes(int(f.getframerate() * 1.5))
        step = int(16000 * 2 * PUSH_CHUNK)
        start_frames("warm-up after face switch")
        for i in range(0, len(pcm), step):
            await runtime.push_audio(pcm[i:i + step], 16000, last_chunk=(i + step >= len(pcm)))
            latest["last_audio"] = time.time()
            await asyncio.sleep(PUSH_CHUNK)
        await runtime.flush()
    except Exception as e:  # noqa: BLE001
        print("warm-up failed:", e)


async def use_avatar(aid):
    """Load (or switch) the face. The SDK holds one model per runtime; set_model switches
    in seconds where available, otherwise the runtime is recreated."""
    global runtime, drain_task
    known = models()
    if not known:
        raise RuntimeError("no models: set BITHUMAN_MODEL_DIR or BITHUMAN_MODEL_PATH")
    aid = aid if aid in known else next(iter(known))
    if aid == current["id"] and runtime is not None:
        return aid
    async with switch_lock:
        if aid == current["id"] and runtime is not None:
            return aid
        latest["chose_at"] = time.time()
        if drain_task:
            drain_task.cancel()
            await asyncio.gather(drain_task, return_exceptions=True)
            drain_task = None
        latest["jpg"] = None
        if runtime is not None and hasattr(runtime, "set_model"):
            try:
                r = runtime.set_model(known[aid])
                if asyncio.iscoroutine(r):
                    await r
                current["id"] = aid
                await warm_up()
                print(f"face (set_model): {aid}")
                return aid
            except Exception as e:  # noqa: BLE001
                print("set_model failed, recreating the runtime:", e)
        old, runtime = runtime, None
        if old is not None:
            for name in ("stop", "aclose", "close"):   # SDK versions name it differently
                fn = getattr(old, name, None)
                if fn:
                    try:
                        r = fn()
                        if asyncio.iscoroutine(r):
                            await r
                    except Exception:  # noqa: BLE001
                        pass
                    break
        runtime = await AsyncBithuman.create(model_path=known[aid], api_secret=SECRET)
        current["id"] = aid
        await warm_up()
        print(f"face: {aid}")
    return aid


async def health(request):
    aid = request.query.get("avatar")
    err = None
    if aid:
        try:
            await use_avatar(aid)
        except Exception as e:  # noqa: BLE001
            err = str(e)
    # The last fields are about MONEY, not health: is the frame counter running right now,
    # and how many frames has it billed. Look here first.
    return web.json_response({
        "ok": runtime is not None, "mock": False, "has_frame": latest["jpg"] is not None,
        "avatar": current["id"], "avatars": avatar_list(), "error": err,
        "talking": (time.time() - latest["last_audio"]) < IDLE_TAIL,
        "viewers": viewers, "frames_running": bool(drain_task and not drain_task.done()),
        "frames_this_process": latest["frames"], "frame_budget": FRAME_BUDGET,
        "budget_hit": bool(latest.get("budget_hit")),
    }, headers=CORS)


async def avatars(request):
    return web.json_response({"avatars": avatar_list(), "avatar": current["id"], "mock": False}, headers=CORS)


async def stream(request):
    """MJPEG: send the freshest frame. Many viewers just read the same buffer."""
    global viewers, stop_timer
    aid = request.query.get("avatar")
    if aid:
        try:
            await use_avatar(aid)
        except Exception as e:  # noqa: BLE001
            return web.json_response({"error": str(e)}, status=503, headers=CORS)
    resp = web.StreamResponse(status=200, headers={
        "Content-Type": "multipart/x-mixed-replace; boundary=frame", "Cache-Control": "no-store, no-cache", **CORS})
    await resp.prepare(request)
    # A write into a dead socket SUCCEEDS (it lands in the kernel buffer) and
    # transport.is_closing() stays False, so a killed client used to stay a "viewer" forever.
    # Short TCP keepalive makes the OS probe the connection and drop a dead one in ~11 s.
    try:
        sock = request.transport.get_extra_info("socket")
        if sock is not None:
            import socket as s
            sock.setsockopt(s.SOL_SOCKET, s.SO_KEEPALIVE, 1)
            for name, val in (("TCP_KEEPIDLE", 5), ("TCP_KEEPINTVL", 3), ("TCP_KEEPCNT", 2)):
                if hasattr(s, name):
                    sock.setsockopt(s.IPPROTO_TCP, getattr(s, name), val)
    except Exception as e:  # noqa: BLE001
        print("socket keepalive not enabled:", e)
    viewers += 1
    # Deliberately NO frame start here: "just opened the page" must cost nothing.
    # Send a frame only when it CHANGED, plus a one-per-second heartbeat. Sending every 40 ms
    # regardless flooded the link with duplicates while the face was silent; speech frames
    # then arrived late, and the lag GREW along a line (measured: 24 fps out of the runner,
    # 18 fps at the client, lips over a second behind by the end of a long line).
    last, last_sent = None, 0.0
    try:
        while True:
            if request.transport is None or request.transport.is_closing():
                break
            jpg = latest["jpg"]
            now = time.monotonic()
            if jpg is not None and (jpg is not last or now - last_sent > 1.0):
                last, last_sent = jpg, now
                try:   # a write to a dead or very slow socket can HANG; treat it as gone
                    await asyncio.wait_for(resp.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"), timeout=5)
                except asyncio.TimeoutError:
                    print("viewer not reading for 5 s: counted as gone")
                    break
            await asyncio.sleep(1 / 50)   # poll often, send rarely
    except (asyncio.CancelledError, ConnectionResetError, ConnectionError):
        pass
    finally:
        viewers -= 1
        # The last viewer left: nobody is watching the unfinished line, stop paying for it.
        if viewers <= 0 and feeder is not None and not feeder.done():
            feeder.cancel()
        if viewers <= 0 and stop_timer is None:
            stop_timer = asyncio.create_task(stop_later())
    return resp


async def push(request):
    """PCM16 mono 16 kHz -> push_audio in speech-paced chunks -> flush. Answers at once."""
    global feeder
    if runtime is None and models():
        try:
            await use_avatar(next(iter(models())))
        except Exception as e:  # noqa: BLE001
            return web.json_response({"error": f"face did not load: {e}"}, status=503, headers=CORS)
    if runtime is None:
        return web.json_response({"error": "runtime not ready"}, status=503, headers=CORS)
    data = await request.json()
    pcm = base64.b64decode(data.get("b64", "") or "")
    if not pcm:
        return web.json_response({"error": "no audio"}, status=400, headers=CORS)
    if feeder and not feeder.done():
        feeder.cancel()                       # a new line cancels the unfinished one
    latest["last_audio"] = time.time()
    start_frames("speech")                    # THIS is where spending starts, and only here
    feeder = asyncio.create_task(feed(pcm))
    # Answer immediately: the lesson waits for this response before playing the audio, so a
    # request held for the whole line would mean silence for the whole line.
    return web.json_response({"ok": True, "seconds": round(len(pcm) / 2 / 16000, 2)}, headers=CORS)


async def feed(pcm):
    """Feed PCM AT SPEECH PACE.

    Pushing a whole line at once let the engine (115 fps on our server) chew 15 s of speech in
    4 s: the lips finished early while the browser kept playing audio, drift reached ten
    seconds. 0.2 s chunks gave only ~5 distinct frames per second. One avatar frame is 40 ms
    of audio, so 40 ms chunks, each sent when it is due, keep the picture continuous.
    """
    step = int(16000 * 2 * PUSH_CHUNK)
    i, t0 = 0, time.monotonic()
    try:
        while i < len(pcm):
            chunk = pcm[i:i + step]
            i += step
            await runtime.push_audio(chunk, 16000, last_chunk=(i >= len(pcm)))
            latest["last_audio"] = time.time()
            ahead = (i / 2 / 16000) - (time.monotonic() - t0)   # sleep until this chunk is due
            if ahead > 0:
                await asyncio.sleep(ahead)
        await runtime.flush()
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        print("audio feed broke:", e)


async def keepalive(request):
    """Keep the generator alive for 2 s WITHOUT audio: honest pre-warming.

    Warming with silence through /push was poison: every push cancels the unfinished line
    and closes it (last_chunk + flush), so the speech that followed stopped opening the
    mouth (three runs each: mouth range 12.85/13.53/7.94 without, 1.01/12.85/0.00 with).
    Why warm at all: the generator takes 2-4 s to start; on a warm runner the mouth moves
    0.05-0.35 s after the audio, on a cold one 1.7-4.8 s. Limits: only with viewers, only
    within WARM_MAX seconds of real speech or a face choice, and never touching last_audio.
    """
    if runtime is None:
        return web.json_response({"error": "runtime not ready"}, status=503, headers=CORS)
    if viewers <= 0:
        return web.json_response({"ok": False, "why": "no viewers"}, headers=CORS)
    since = time.time() - max(latest["last_audio"], latest["chose_at"])
    if since > WARM_MAX:
        return web.json_response({"ok": False, "why": f"silent for {int(since)} s"}, headers=CORS)
    latest["warm_until"] = time.time() + 2.0
    start_frames("warm-up without audio")
    return web.json_response({"ok": True, "frames": latest["frames"]}, headers=CORS)


async def preflight(request):
    return web.Response(status=204, headers=CORS)


async def main():
    known = models()
    if not SECRET or not known:
        raise SystemExit("set BITHUMAN_API_SECRET and BITHUMAN_MODEL_DIR (or BITHUMAN_MODEL_PATH)")
    # A face that fails to load is skipped instead of crash-looping the service: under a
    # supervisor every failed load attempt may itself be billed.
    for aid in known:
        try:
            await use_avatar(aid)
            break
        except Exception as e:  # noqa: BLE001
            print(f"face {aid} failed to load, skipping: {str(e)[:200]}")
    if runtime is None:
        print("no face loaded: serving HTTP anyway so /health can say why")
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/avatars", avatars)
    app.router.add_get("/stream", stream)
    app.router.add_post("/push", push)
    app.router.add_get("/keepalive", keepalive)
    app.router.add_route("OPTIONS", "/{tail:.*}", preflight)
    runner = web.AppRunner(app)
    await runner.setup()
    host = os.environ.get("RUNNER_HOST", "localhost")
    port = int(os.environ.get("RUNNER_PORT", "8090"))
    await web.TCPSite(runner, host, port).start()
    print(f"avatar runner on http://{host}:{port} (/health /avatars /stream /push /keepalive), faces: {', '.join(known)}")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
