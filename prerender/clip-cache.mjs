// Hash-addressed clip cache for prerendered talking-head lines.
//
// A clip is named by the HASH OF ITS TEXT, not by its position in the lesson: insert one
// line and position-based names all shift, while hash names keep every finished clip
// reusable. Speech synthesis costs money, so every edit should re-synthesize only what
// actually changed.
//
// The text hash alone is NOT enough. The picture also depends on the FACE and on the
// LIP-SYNC ENGINE: swap the portrait and the text stays the same, yet the cache must
// expire, or the lesson silently keeps showing the old face (this happened once). So the
// video name also carries a render signature: a hash of the face file bytes plus the engine
// command line. Audio does not depend on the face, so it stays keyed by text alone and a
// face change never pays for synthesis again.
//
//   audio: clip-<textHash>.<ext>
//   video: clip-<textHash>-<signature>.mp4
import { createHash } from 'node:crypto'

// djb2 variant (h * 33 XOR code point), unsigned 32-bit. The lesson page and
// prerender/clipcache.py compute exactly the same value: the page finds clips by it.
export function hashText(text) {
  let h = 5381
  for (const ch of String(text)) h = ((h * 33) ^ ch.codePointAt(0)) >>> 0
  return h.toString(16).padStart(8, '0')
}

export function hashBytes(buf) {
  let h = 5381
  for (const b of buf) h = ((h * 33) ^ b) >>> 0
  return h.toString(16).padStart(8, '0')
}

// What, besides the text, changes the PICTURE of a clip.
//
// SHA-256, not djb2. The first version took the top 6 hex digits of djb2 over
// (face bytes + engine command), and the unit test written for this repository caught a
// collision: in djb2 the LAST bytes of the input barely reach the high bits, so two
// commands that differ only at the end (say "--steps 20" vs "--steps 25") produced the same
// signature and would have served stale clips. The text hash stays djb2 because the lesson
// page computes it; the signature only lives in file names listed by index.json.
export function renderSignature(faceBytes, engineCommand) {
  return createHash('sha256').update(Buffer.from(faceBytes)).update(String(engineCommand)).digest('hex').slice(0, 6)
}

export const audioName = (h, ext) => `clip-${h}.${ext}`
export const videoName = (h, sig) => `clip-${h}-${sig}.mp4`
export const CLIP_FILE = /^clip-[0-9a-f]{8}(-[0-9a-f]{6})?\.(mp4|mp3|wav|ogg)$/

// Substitute {placeholders} in a command template.
export function fillCmd(template, values) {
  return Object.entries(values).reduce((s, [k, v]) => s.split(`{${k}}`).join(v), template)
}

// A command line cannot be split on spaces naively: a quoted ffmpeg filter graph contains
// spaces and quotes of its own.
export function splitCmd(s) {
  const out = []
  let cur = ''
  let q = null
  let started = false
  for (const ch of s) {
    if (q) { if (ch === q) q = null; else cur += ch; continue }
    if (ch === '"' || ch === "'") { q = ch; started = true; continue }
    if (ch === ' ' || ch === '\t' || ch === '\n') {
      if (started) out.push(cur)
      cur = ''; started = false; continue
    }
    cur += ch; started = true
  }
  if (started) out.push(cur)
  return out
}
