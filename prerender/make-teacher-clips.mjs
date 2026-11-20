#!/usr/bin/env node
// TEACHER PRERENDER: the lesson reads a FIXED text, so the talking-head video for it can be
// rendered ONCE and then simply played back.
//
// What that buys:
//   * the student downloads plain MP4s (hundreds of kilobytes), not a 13 MB 3D model, and
//     a weak laptop or tablet does not have to render WebGL;
//   * speech synthesis becomes a ONE-TIME cost too: the audio lives inside the clip, so
//     replaying a lesson costs nothing;
//   * a GPU is needed only on our side and only while preparing the lesson.
//
// Lip-sync is an external command (LIPSYNC_CMD), so the engine changes without touching
// the lesson: the default is an ffmpeg stub (portrait + audio + a slow "breathing" zoom),
// prerender/lipsync_run.py plugs in LatentSync, and anything else that takes
// {face} {audio} {out} works the same way.
//
// Clips are hash-addressed (see clip-cache.mjs): text hash for audio, text hash + render
// signature (face bytes + engine command) for video.
//
//   node prerender/make-teacher-clips.mjs --beats prerender/beats.example.json \
//        --face samples/portraits/lena.png --out out/clips --demo-tts
//
// Options:
//   --beats FILE    JSON: [{"say": "...", "page": 12, "kind": "read"}, ...] or {"beats": [...]}
//   --face FILE     teacher portrait (png/jpg); or TEACHER_FACE
//   --out DIR       output folder (clips + index.json)
//   --limit N       only the first N beats (a probe run: cache cleanup is skipped)
//   --demo-tts      offline placeholder speech (a modulated tone sized to the text)
//
// Environment:
//   LIPSYNC_CMD        per-beat command with {face} {audio} {out}; default: the ffmpeg stub
//   LIPSYNC_BATCH_CMD  batch command with {jobs} {face}: the engine gets ALL jobs at once and
//                      loads its weights once (see prerender/lipsync_batch.py)
//   TTS_URL            POST {"text","voice","speed"} -> audio bytes (mp3 or wav)
//   TTS_VOICE, TTS_SPEED
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import fs from 'node:fs'
import path from 'node:path'
import { CLIP_FILE, audioName, fillCmd, hashText, renderSignature, splitCmd, videoName } from './clip-cache.mjs'

const run = promisify(execFile)
const arg = (name, dflt) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : dflt }
const has = (name) => process.argv.includes(name)

const BEATS = arg('--beats')
const FACE = arg('--face', process.env.TEACHER_FACE)
const OUT = arg('--out')
const LIMIT = +arg('--limit', 0) || 0
const DEMO_TTS = has('--demo-tts')
if (!BEATS || !FACE || !OUT) {
  console.error('usage: make-teacher-clips.mjs --beats beats.json --face portrait.png --out DIR [--limit N] [--demo-tts]')
  process.exit(2)
}
if (!fs.existsSync(FACE)) { console.error('no face: ' + FACE); process.exit(1) }
if (!DEMO_TTS && !process.env.TTS_URL) {
  console.error('set TTS_URL (an endpoint that turns text into audio) or pass --demo-tts for offline placeholder speech')
  process.exit(2)
}

// Stub instead of lip-sync: portrait + audio + a slow breathing zoom. The lips do not move,
// but the clip is alive and the whole chain can be checked end to end.
const STUB = 'ffmpeg -y -v error -loop 1 -i "{face}" -i "{audio}" -filter_complex ' +
  '"[0:v]scale=512:512,zoompan=z=\'min(1.06,1+0.0006*on)\':d=1:s=512x512:fps=25[v]" ' +
  '-map "[v]" -map 1:a -c:v libx264 -preset veryfast -crf 26 -pix_fmt yuv420p -c:a aac -b:a 64k -shortest "{out}"'
const CMD = process.env.LIPSYNC_CMD || STUB
const BATCH = process.env.LIPSYNC_BATCH_CMD || ''
const SIG = renderSignature(fs.readFileSync(FACE), BATCH || CMD)

fs.mkdirSync(OUT, { recursive: true })
const raw = JSON.parse(fs.readFileSync(BEATS, 'utf8'))
let beats = (Array.isArray(raw) ? raw : raw.beats || []).map((b) => (typeof b === 'string' ? { say: b } : b))
beats = beats.filter((b) => String(b.say || '').trim())
if (LIMIT) beats = beats.slice(0, LIMIT)
console.log('beats to render: ' + beats.length)

function cachedAudio(h) {
  for (const ext of ['mp3', 'wav', 'ogg']) {
    const p = path.join(OUT, audioName(h, ext))
    if (fs.existsSync(p)) return p
  }
  return null
}

async function synthesize(text, h) {
  if (DEMO_TTS) {
    // ~14 characters per second of speech, as a 180 Hz tone pulsing at 4 Hz (syllable rate)
    const seconds = Math.max(1, Math.min(30, [...text].length / 14)).toFixed(2)
    const out = path.join(OUT, audioName(h, 'wav'))
    await run('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', `sine=frequency=180:duration=${seconds}:sample_rate=16000`,
      '-af', "volume='0.25+0.25*sin(2*PI*4*t)':eval=frame", '-ac', '1', out])
    return out
  }
  const r = await fetch(process.env.TTS_URL, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice: process.env.TTS_VOICE || 'default', speed: +(process.env.TTS_SPEED || 1) }),
  })
  if (!r.ok) throw new Error(`TTS answered ${r.status}`)
  const type = r.headers.get('content-type') || ''
  const ext = type.includes('wav') ? 'wav' : type.includes('ogg') ? 'ogg' : 'mp3'
  const out = path.join(OUT, audioName(h, ext))
  fs.writeFileSync(out, Buffer.from(await r.arrayBuffer()))
  return out
}

// ---- for every beat: speech -> clip -------------------------------------------------
// Two render modes. Default: one process per line (LIPSYNC_CMD). Simple, but loading the
// lip-sync weights costs ~37 s per process, which is 43 minutes of idle time over 70 lines.
// With LIPSYNC_BATCH_CMD all speech is synthesized first and the engine receives the whole
// job list at once, loading its model ONE time.
const index = []
const todo = []
let chars = 0, reused = 0, made = 0, failed = 0
for (let i = 0; i < beats.length; i++) {
  const text = String(beats[i].say)
  const h = hashText(text)
  const mp4 = path.join(OUT, videoName(h, SIG))
  const row = { n: i + 1, h, page: beats[i].page ?? null, kind: beats[i].kind ?? null, file: videoName(h, SIG) }
  if (fs.existsSync(mp4)) { index.push({ ...row, bytes: fs.statSync(mp4).size }); reused++; continue }
  let audio = cachedAudio(h)
  if (!audio) {
    chars += [...text].length
    try { audio = await synthesize(text, h) }
    catch (e) { console.error(`  beat ${i + 1}: speech failed (${e.message})`); failed++; continue }
  }
  if (BATCH) { todo.push({ row, audio, mp4 }); continue }
  const [exe, ...args] = splitCmd(fillCmd(CMD, { face: FACE, audio, out: mp4 }))
  try { await run(exe, args, { maxBuffer: 1 << 24 }) }
  catch (e) { console.error(`  beat ${i + 1}: render failed: ${String(e.stderr || e).slice(0, 200)}`); failed++; continue }
  index.push({ ...row, bytes: fs.statSync(mp4).size }); made++
}

if (BATCH && todo.length) {
  const jobsFile = path.join(OUT, 'jobs.json')
  fs.writeFileSync(jobsFile, JSON.stringify(todo.map((t) => ({ audio: t.audio, out: t.mp4 })), null, 1))
  console.log(`  batch: ${todo.length} lines, the model loads once...`)
  const [exe, ...args] = splitCmd(fillCmd(BATCH, { jobs: jobsFile, face: FACE }))
  // Do NOT pass stdio:'inherit' here: it is a spawn option, not an execFile one. The process
  // would finish, but the promise would reject with an EMPTY error and the run would report
  // a failure while every clip is on disk (that happened once).
  try {
    const r = await run(exe, args, { maxBuffer: 1 << 26 })
    const tail = String(r.stdout || '').split('\n').filter((s) => s.trim()).slice(-3).join('\n  ')
    if (tail) console.log('  ' + tail)
  } catch (e) { console.error(`  batch failed: ${String(e.stderr || e.message || e).slice(0, 300)}`) }
  for (const t of todo) {
    if (!fs.existsSync(t.mp4)) { console.error(`  no clip for beat ${t.row.n}`); failed++; continue }
    index.push({ ...t.row, bytes: fs.statSync(t.mp4).size }); made++
  }
  index.sort((x, y) => x.n - y.n)
}
fs.writeFileSync(path.join(OUT, 'index.json'), JSON.stringify({ signature: SIG, beats: index }, null, 1))

// Leftovers from earlier runs (renamed or removed lines) are deleted, but ONLY on a full
// run: with --limit the index holds a handful of beats, and cleaning would wipe the cache of
// the whole lesson together with its paid-for speech (that once deleted 112 files).
// Only files that look like clips are ever touched.
let dropped = 0
if (!LIMIT && !failed) {
  const live = new Set(index.flatMap((b) => [b.file, ...['mp3', 'wav', 'ogg'].map((e) => audioName(b.h, e))]))
  for (const f of fs.readdirSync(OUT)) {
    if (CLIP_FILE.test(f) && !live.has(f)) { fs.unlinkSync(path.join(OUT, f)); dropped++ }
  }
}

const total = index.reduce((a, b) => a + b.bytes, 0)
console.log(`clips ${index.length}: rendered ${made}, from cache ${reused}` + (dropped ? `, removed ${dropped} stale` : '') +
  (failed ? `, FAILED ${failed}` : '') + (LIMIT ? ' (probe run: cache cleanup skipped)' : ''))
console.log(`render signature: ${SIG} (face ${path.basename(FACE)} + engine)`)
if (index.length) console.log(`lesson ${(total / 1048576).toFixed(1)} MB, ${(total / index.length / 1024) | 0} KB per line on average`)
console.log(`speech synthesized this run: ${chars} characters`)
console.log(`engine: ${BATCH ? 'batch lip-sync (model loads once)' : process.env.LIPSYNC_CMD ? 'external lip-sync (one process per line)' : 'ffmpeg stub (lips do not move)'}`)
process.exit(failed ? 1 : 0)
