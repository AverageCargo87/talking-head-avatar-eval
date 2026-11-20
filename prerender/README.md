# Prerender: fixed lines rendered once, live only for answers

The lesson text is fixed, so the talking-head video for it can be rendered once and played as
files. Only answers to the student need a live avatar, and it must be the same engine and face
(see the identity seam in [docs/VENDOR_SELECTION.md](../docs/VENDOR_SELECTION.md)). Cost
reasoning: [docs/COST_MODEL.md](../docs/COST_MODEL.md).

Status: built and used to render test clips in August 2026; not deployed as a production feature.

| file | what it does |
|---|---|
| `make-teacher-clips.mjs` | beats JSON -> speech (TTS, cached by text hash) -> lip-sync command -> `clip-<hash>-<sig>.mp4` + `index.json` |
| `clip-cache.mjs` / `clipcache.py` | text hash (djb2, identical in JS and Python), render signature, clip names, command splitting |
| `lipsync_run.py` | LatentSync wrapper: portrait or idle clip + one line -> clip; plugs in as `LIPSYNC_CMD` |
| `lipsync_batch.py` | the same for a whole job list with ONE model load; plugs in as `LIPSYNC_BATCH_CMD` |
| `anam_render.py` | cloud-avatar prerender: PCM16 through audio passthrough, synchronized frames recorded to mp4, sessions split under the plan's cap |
| `beats.example.json` | four host lines for the demo |

## Run the offline demo

```bash
npm run prerender:demo     # placeholder speech + the ffmpeg stub: lips do not move, the chain does
npm run prerender:demo     # second run: everything comes from the cache, 0 characters synthesized
```

Swap the engine without touching the lesson:

```bash
LIPSYNC_CMD="python prerender/lipsync_run.py --face {face} --audio {audio} --out {out}" \
LATENTSYNC_DIR=/path/to/LatentSync TTS_URL=http://localhost:PORT/api/tts \
node prerender/make-teacher-clips.mjs --beats beats.json --face portrait.png --out out/clips
```

## Decisions and the incidents behind them

- **Hash-addressed, not numbered.** Insert one line and numbered clips all shift; hash names keep
  every finished clip reusable, and synthesis (money) is spent only on new text.
- **Text hash is not enough.** A new portrait with the same text must re-render, or the lesson
  shows the old face (it did once). Video names carry a render signature over the face bytes and
  the engine command; audio stays keyed by text, so a face change costs no new synthesis.
- **SHA-256 for the signature (found while building this repository).** The original signature
  was the top 6 hex digits of djb2. A unit test written here showed that in djb2 the last bytes
  barely reach the high bits: commands that differ only at the end (`--steps 20` vs `--steps 25`)
  collided and would have served stale clips. The text hash stays djb2 because the lesson page
  computes it.
- **Cleanup only on full runs.** A probe run with `--limit` once deleted 112 cached files with
  their paid speech. Now cleanup runs only on a full, error-free run and only touches files that
  match the clip name pattern.
- **One model load per lesson.** LatentSync costs about 37 s to load plus 1.9 s per diffusion
  step; 70 lines in separate processes waste about 43 minutes. `lipsync_batch.py` loads once.
- **Version and resolution are one decision.** LatentSync 1.5 pairs with the 256 config (8 GB of
  VRAM), 1.6 with the 512 config (18 GB, does not fit a 12 GB RTX 3060). A mismatched config loads
  without an error and silently paints rectangular patches on the cheeks. On 3.84 s of speech:
  v1.6/512 took 875 s, v1.5/256 about 75 s.
- **Delivery size.** The engine writes about 4.4 Mbit/s (14.6 MB for a 28 s line). Re-encoding to
  512 px at CRF 28 brought a line to about 1.1 MB with no visible difference in the lesson panel.
- **Anam passthrough gotchas** (all hit once): `send_audio_chunk` and `end_sequence` are coroutines,
  and without `await` the clip comes out silent at -91 dB with a closed mouth; without
  `end_sequence` the avatar waits forever; the avatar model must be pinned or an older 720x480
  model arrives; session replay is on by default (a 30-day recording) and is switched off; the
  SDK has no "finished speaking" event, so duration comes from the PCM length (32,000 bytes per
  second); frames go straight into ffmpeg (768x1152 RGB is 2.6 MB per frame).
