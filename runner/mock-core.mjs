// Mock avatar runner: the SAME HTTP contract as the real runner (runner/bithuman_runner.py),
// with no SDK, no key and no model files. One engine, two ways to mount it:
//   * as its own process: runner/mock-runner.mjs (a port, exactly like the real runner);
//   * inside any Node server: import { handleMock } and route a path prefix to it.
// The second way exists because of a real incident: a lesson was switched to the video
// teacher and showed an empty window simply because nobody had started the runner. With
// the mock always at hand, "no picture" means a real failure, not a forgotten process.
//
// Contract (shared with the real runner; checked by runner/contract_check.py):
//   GET  /health?avatar=id  -> { ok, mock, avatar, avatars, talking }
//   GET  /avatars           -> { avatars: [{ id, name }] }   (the face picker of the lesson)
//   GET  /stream?avatar=id  -> MJPEG (multipart/x-mixed-replace; boundary=frame)
//   POST /push {b64, last}  -> PCM16 mono 16 kHz; the mouth moves while it "plays"
//   GET  /keepalive         -> { ok }  (the real runner keeps its frame generator warm)
//
// Frames live in runner/faces/<id>/{talk0..talk4,blink}.jpg, drawn by make-mock-faces.mjs.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const DIR = process.env.MOCK_FACES_DIR || path.join(path.dirname(fileURLToPath(import.meta.url)), 'faces')
export const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
}

let talkingUntil = 0                 // ms timestamp until which we are "talking"
const cache = new Map()              // id -> { talk: [Buffer x5], blink: Buffer }

export function faces() {
  try { return JSON.parse(fs.readFileSync(path.join(DIR, 'faces.json'), 'utf8')) }
  catch { return [] }
}
const defaultFace = () => (faces()[0] || {}).id || ''

function framesOf(id) {
  if (cache.has(id)) return cache.get(id)
  const known = faces().map((f) => f.id)
  const key = known.includes(id) ? id : known[0]
  if (!key) throw new Error('no mock frames in ' + DIR + '; run: node runner/make-mock-faces.mjs')
  const rd = (n) => fs.readFileSync(path.join(DIR, key, n + '.jpg'))
  const set = { talk: [0, 1, 2, 3, 4].map((i) => rd('talk' + i)), blink: rd('blink') }
  cache.set(id, set)
  return set
}

export function pickFrame(set, tick, now = Date.now()) {
  if (now < talkingUntil) {
    // talking: the mouth opens on a sine (frames 1..4)
    const lvl = 1 + Math.round(Math.abs(Math.sin(tick * 0.9)) * 3)
    return set.talk[Math.min(4, lvl)]
  }
  if (tick % 34 === 0 || tick % 34 === 1) return set.blink   // silent: blink now and then
  return set.talk[0]
}

const json = (res, code, obj) => {
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', ...CORS })
  res.end(JSON.stringify(obj))
}

// sub: the path without its prefix ('health' | 'avatars' | 'stream' | 'push' | 'keepalive').
// Returns true when the request was handled.
export function handleMock(req, res, sub, query) {
  if (req.method === 'OPTIONS') { res.writeHead(204, CORS); res.end(); return true }
  const avatar = (query && query.get('avatar')) || defaultFace()

  if (req.method === 'GET' && sub === 'health') {
    let ok = true
    try { framesOf(avatar) } catch { ok = false }
    json(res, 200, { ok, mock: true, avatar, avatars: faces(), talking: Date.now() < talkingUntil })
    return true
  }
  if (req.method === 'GET' && sub === 'avatars') { json(res, 200, { avatars: faces(), mock: true }); return true }
  if (req.method === 'GET' && sub === 'keepalive') { json(res, 200, { ok: true, mock: true }); return true }

  if (req.method === 'GET' && sub === 'stream') {
    let set
    try { set = framesOf(avatar) } catch (e) { json(res, 500, { error: e.message }); return true }
    res.writeHead(200, {
      'Content-Type': 'multipart/x-mixed-replace; boundary=frame',
      'Cache-Control': 'no-store, no-cache', Connection: 'close', ...CORS,
    })
    let tick = 0
    const send = () => {
      const jpg = pickFrame(set, tick++)
      res.write(`--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${jpg.length}\r\n\r\n`)
      res.write(jpg)
      res.write('\r\n')
    }
    send()                                  // first frame immediately
    const iv = setInterval(send, 90)        // ~11 fps: enough to check, little traffic
    const stop = () => clearInterval(iv)
    req.on('close', stop); res.on('close', stop); req.on('error', stop)
    return true
  }

  if (req.method === 'POST' && sub === 'push') {
    let body = ''
    req.on('data', (c) => (body += c))
    req.on('end', () => {
      try {
        const p = JSON.parse(body || '{}')
        const bytes = p.b64 ? Buffer.byteLength(p.b64, 'base64') : 0
        if (!bytes) return json(res, 400, { error: 'no audio' })
        const sec = bytes / 2 / 16000            // PCM16 mono 16 kHz -> duration
        talkingUntil = Date.now() + Math.max(400, sec * 1000)
        json(res, 200, { ok: true, seconds: +sec.toFixed(2) })
      } catch (e) { json(res, 400, { error: e.message }) }
    })
    return true
  }
  return false
}
