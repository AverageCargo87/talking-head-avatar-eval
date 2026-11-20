# Avatar runner: one HTTP contract, a mock and a real implementation

The lesson talks to "a runner" over five endpoints. The mock implements them with drawn frames and
no dependencies; the real runner implements them on top of a vendor SDK. The lesson cannot tell
them apart, which is the point: the avatar layer has to be replaceable in a day, not wired into
the lesson.

| endpoint | contract |
|---|---|
| `GET /health?avatar=id` | `{ok, mock, avatar, avatars, talking, ...}`; the real runner adds billing fields (viewers, frames running, frames this process, budget) |
| `GET /avatars` | `{avatars: [{id, name}]}`: the lesson's face picker |
| `GET /stream?avatar=id` | MJPEG, `multipart/x-mixed-replace; boundary=frame` |
| `POST /push {b64, last}` | PCM16 mono 16 kHz; answers at once with `{ok, seconds}`, the mouth moves for that long |
| `GET /keepalive` | keeps the frame generator warm for 2 s (real runner: only near real speech) |

```bash
node runner/mock-runner.mjs                               # MOCK_PORT=8090 by default
python runner/contract_check.py http://localhost:8090     # 7 checks; run it against either runner
```

| file | what it is |
|---|---|
| `mock-core.mjs` | the mock engine; mount it in any Node server or run it through `mock-runner.mjs` |
| `mock-runner.mjs` | the mock as its own process |
| `make-mock-faces.mjs`, `faces/` | five flat placeholder faces x six frames, labelled MOCK so nobody mistakes them for a real avatar (frames are committed) |
| `bithuman_runner.py` | the real runner, trimmed for publication: env-only configuration, no vendor internals |
| `contract_check.py` | the shared contract as executable checks (`tests/test_runner_contract.py` runs it against the mock) |

Why the mock exists: a lesson was once switched to the video teacher and showed an empty window
only because nobody had started the runner. With the mock always available, "no picture" means a
real failure.

The real runner's design is mostly about money, because its vendor bills rendered frames: no
speech no frames, no viewers no frames, a hard frame budget, audio fed at speech pace in 40 ms
chunks (one avatar frame), MJPEG frames sent only when changed plus a 1 s heartbeat (sending
duplicates made lips drift more than a second behind on long lines), and TCP keepalive plus a
write timeout so dead browsers stop counting as viewers. Details in the file's comments and in
[docs/COST_MODEL.md](../docs/COST_MODEL.md).
