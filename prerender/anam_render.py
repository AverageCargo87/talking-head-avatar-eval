#!/usr/bin/env python
"""PRERENDER THROUGH A CLOUD AVATAR (Anam): record the fixed part of a lesson once.

Why: the lesson reads the textbook with a FIXED text, identical for every student. Keeping a
live avatar for that means paying for every student separately (estimated 432-538 RUB per
40-minute lesson on the public tariffs of August 2026). Rendering it once (about 15 minutes
of speech per lesson, estimated ~200 RUB) and serving files costs nothing per student. The
live avatar stays only for answers to the child, and it is the same face and the same model,
so there is no seam at the switch (measured 2026-08-05: one engine 0.942, mixed engines
0.815-0.855; see avatar_metrics.identity).

What it does:
  1. gets speech as raw PCM16 16 kHz mono, exactly what the live lesson sends;
  2. streams it to the avatar through audio passthrough (the vendor's TTS is off, OUR voice
     speaks);
  3. records the synchronized video and audio frames coming back and writes an mp4;
  4. names clips the way the lesson looks for them: clip-<text hash>-<signature>.mp4 plus
     index.json (same djb2 text hash as prerender/clip-cache.mjs).

Speech source, one of:
  --tts-url URL   POST {"text","voice","speed","pcm":true} -> {"b64": "<PCM16 16 kHz mono>"}
  beats JSON with an "audio" file per beat (any format; converted with ffmpeg)

Usage (one probe line):
  ANAM_API_KEY=... python prerender/anam_render.py --avatar <avatar-id> --text "..." \
      --tts-url http://localhost:PORT/api/tts --out out/anam-probe

Status: built and run during the August 2026 avatar evaluation; this public version takes
its key from the environment only and was not re-run for this repository (it needs a paid
key). The vendor SDK is installed from PyPI (pip install anam), never vendored.

Billing notes that shaped the code:
  * Anam bills SESSION TIME, not audio length, and draws the lips at speech pace: rendering
    cannot be faster than real time, 15 minutes of speech is 15 minutes of tariff.
  * On the free tier a session is cut after 3 minutes. The script splits the work into
    batches under --cap and opens a new session per batch; there is no pause between
    sessions (checked: estimatedWaitSeconds = 0).
"""
import argparse
import asyncio
import base64
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clipcache import hash_text  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

PCM_BYTES_PER_SECOND = 32000  # 16 kHz * 2 bytes, mono


def speech_from_tts(text: str, voice: str, speed: float, url: str) -> bytes:
    body = json.dumps({"text": text, "voice": voice, "speed": speed, "pcm": True}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    if d.get("error") or not d.get("b64"):
        raise RuntimeError(f"speech synthesis failed: {d.get('error', 'empty answer')}")
    return base64.b64decode(d["b64"])


def speech_from_file(path: str) -> bytes:
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                       capture_output=True, check=True)
    return p.stdout


async def render_line(session, stream, pcm: bytes, path: pathlib.Path, tail: float) -> dict:
    """Send one line and write what the avatar returns into an mp4.

    The duration is known IN ADVANCE from the PCM itself: the SDK has no "finished
    speaking" event at all (checked against its event list), so we count ourselves.
    """
    seconds = len(pcm) / PCM_BYTES_PER_SECOND
    deadline = seconds + tail
    state = {"ffmpeg": None, "frames": 0}
    audio_frames: list = []
    t0 = time.monotonic()
    stop = asyncio.Event()
    tmp_video = path.with_suffix(".tmp.mp4")
    tmp_audio = path.with_suffix(".tmp.wav")

    # Do NOT accumulate frames: 768x1152 RGB is 2.6 MB per frame, a quarter of a minute at
    # 25 fps eats a gigabyte. Pipe them straight into ffmpeg; the encoder starts on the
    # first frame, when the frame size becomes known.
    async def video():
        async for frame in session.video_frames():
            if state["ffmpeg"] is None:
                state["ffmpeg"] = subprocess.Popen([
                    "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", f"{frame.width}x{frame.height}", "-r", "25", "-i", "pipe:0",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(tmp_video),
                ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                state["ffmpeg"].stdin.write(frame.to_ndarray(format="rgb24").tobytes())
            except (BrokenPipeError, OSError):
                stop.set()
                return
            state["frames"] += 1
            if time.monotonic() - t0 > deadline:
                stop.set()
                return

    async def audio():
        async for frame in session.audio_frames():   # audio is light, it can be accumulated
            audio_frames.append(frame)
            if stop.is_set():
                return

    # Send the whole line at once: the SDK buffers faster-than-real-time audio and renders
    # lip-sync at the correct pace. BOTH calls are COROUTINES. Without await they silently do
    # nothing: the clip comes out with the right length and the right face, but with a
    # SILENT track (-91 dB) and a closed mouth. It happened once.
    await stream.send_audio_chunk(pcm)
    await stream.end_sequence()     # without it the engine waits for more and the avatar freezes FOREVER

    try:
        await asyncio.wait_for(asyncio.gather(video(), audio()), timeout=deadline + 25)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass
    if state["ffmpeg"] is not None:
        try:
            state["ffmpeg"].stdin.close()
        except OSError:
            pass
        state["ffmpeg"].wait(timeout=120)
    if not state["frames"]:
        return {"speech_s": round(seconds, 2), "frames": 0, "video_s": 0, "bytes": 0}

    # Audio: raw samples -> wav. Encoding AAC through PyAV fails ("Invalid argument") on the
    # sample format WebRTC delivers; ffmpeg resamples and muxes in one call.
    has_audio = False
    if audio_frames:
        with wave.open(str(tmp_audio), "wb") as w:
            w.setnchannels(audio_frames[0].layout.nb_channels)
            w.setsampwidth(2)
            w.setframerate(audio_frames[0].sample_rate)
            for frame in audio_frames:
                w.writeframes(frame.to_ndarray().astype("<i2").tobytes())
        has_audio = tmp_audio.exists() and tmp_audio.stat().st_size > 44
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp_video)]
    cmd += (["-i", str(tmp_audio), "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", "-shortest"] if has_audio
            else ["-c:v", "copy"])
    subprocess.run(cmd + [str(path)], check=False, capture_output=True)
    for junk in (tmp_video, tmp_audio):
        try:
            junk.unlink()
        except OSError:
            pass
    return {"speech_s": round(seconds, 2), "frames": state["frames"], "video_s": round(state["frames"] / 25.0, 2),
            "bytes": path.stat().st_size if path.exists() else 0}


def load_work(a) -> list:
    if a.beats:
        raw = json.loads(pathlib.Path(a.beats).read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else raw.get("beats", [])
        work = [{"say": t if isinstance(t, str) else (t.get("say") or t.get("text") or ""),
                 "audio": None if isinstance(t, str) else t.get("audio"),
                 "page": None if isinstance(t, str) else t.get("page"),
                 "kind": None if isinstance(t, str) else t.get("kind")} for t in items]
    else:
        work = [{"say": a.text or "", "audio": a.audio, "page": None, "kind": None}]
    return [w for w in work if w["say"].strip()]


async def main(a):
    key = os.environ.get("ANAM_API_KEY")
    if not key:
        sys.exit("set ANAM_API_KEY in the environment (see .env.example)")
    from anam import AgentAudioInputConfig, AnamClient, PersonaConfig, SessionOptions

    work = load_work(a)
    if not work:
        sys.exit("nothing to render")
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    signature = f"anam-{a.model.replace('-', '')}-{hash_text(a.avatar)[:6]}"
    print(f"lines: {len(work)}, model {a.model}, signature {signature}")

    # Synthesize everything BEFORE opening a session: every second of a session is billed,
    # and waiting for the TTS inside it means paying for the wait.
    for i, w in enumerate(work, 1):
        if w["audio"]:
            w["pcm"] = speech_from_file(w["audio"])
        elif a.tts_url:
            w["pcm"] = speech_from_tts(w["say"], a.voice, a.speed, a.tts_url)
        else:
            sys.exit("no speech source: give --tts-url or an 'audio' file per beat")
        w["s"] = len(w["pcm"]) / PCM_BYTES_PER_SECOND
        w["h"] = hash_text(w["say"])
        w["file"] = f"clip-{w['h']}-{signature}.mp4"
        print(f"  {i}/{len(work)}: {w['s']:.1f} s")
    total = sum(w["s"] for w in work)
    print(f"speech total: {total / 60:.1f} min, the same amount of billed session time")

    # Split into batches under the session cap: 3 min on Free, 2 h on Growth.
    batches, cur, used = [], [], 0.0
    for w in work:
        if cur and used + w["s"] + a.tail > a.cap:
            batches.append(cur)
            cur, used = [], 0.0
        cur.append(w)
        used += w["s"] + a.tail
    if cur:
        batches.append(cur)
    print(f"sessions needed: {len(batches)} (cap {a.cap:.0f} s per session)")

    index, n = [], 0
    for bi, batch in enumerate(batches, 1):
        print(f"\n-- session {bi}/{len(batches)}: {len(batch)} lines")
        client = AnamClient(api_key=key, persona_config=PersonaConfig(
            avatar_id=a.avatar,
            avatar_model=a.model,           # pin it: without it an older model arrives at 720x480
            enable_audio_passthrough=True,  # vendor TTS off, our voice speaks
            max_session_length_seconds=int(a.cap) + 60,
        ))
        options = SessionOptions(
            video_quality="high", video_width=a.width, video_height=a.height,
            enable_session_replay=False,   # default is True: a 30-day recording. For a children's
                                           # lesson that is a personal-data question. Off.
        )
        async with client.connect(session_options=options) as session:
            stream = session.create_agent_audio_input_stream(
                AgentAudioInputConfig(encoding="pcm_s16le", sample_rate=16000, channels=1))
            for w in batch:
                n += 1
                t = time.monotonic()
                res = await render_line(session, stream, w["pcm"], out / w["file"], a.tail)
                print(f"  {n}/{len(work)} {w['file']}: speech {res['speech_s']} s -> video {res['video_s']} s, "
                      f"{res['frames']} frames, {res['bytes'] // 1024} KB, took {time.monotonic() - t:.1f} s")
                index.append({"n": n, "h": w["h"], "page": w["page"], "kind": w["kind"],
                              "file": w["file"], "bytes": res["bytes"]})

    (out / "index.json").write_text(json.dumps({"signature": signature, "beats": index}, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    print(f"\ndone: {len(index)} clips in {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--avatar", required=True, help="avatar id in your Anam account")
    p.add_argument("--model", default="cara-4")
    p.add_argument("--text", help="one line, for a probe")
    p.add_argument("--audio", help="audio file for --text (instead of --tts-url)")
    p.add_argument("--beats", help="JSON with the lesson lines")
    p.add_argument("--out", required=True)
    p.add_argument("--tts-url", help="speech endpoint returning PCM16 16 kHz as base64 JSON")
    p.add_argument("--voice", default="default")
    p.add_argument("--speed", type=float, default=0.95)
    p.add_argument("--width", type=int, default=768)
    p.add_argument("--height", type=int, default=1152)
    p.add_argument("--cap", type=float, default=150,
                   help="session cap in seconds: Free 180, Growth 7200. Default 150 leaves headroom on Free")
    p.add_argument("--tail", type=float, default=1.2, help="seconds recorded after the end of speech")
    asyncio.run(main(p.parse_args()))
