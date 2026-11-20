// End-to-end: beats -> placeholder speech -> ffmpeg stub "lip-sync" -> hash-addressed clips.
// Needs ffmpeg on PATH; skipped otherwise.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const SCRIPT = path.join(HERE, '..', 'make-teacher-clips.mjs')
const hasFfmpeg = spawnSync('ffmpeg', ['-version']).status === 0

function makeFace(file, color) {
  execFileSync('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', `color=c=${color}:s=256x256`, '-frames:v', '1', file])
}

function render(args) {
  const env = { ...process.env }
  delete env.LIPSYNC_CMD
  delete env.LIPSYNC_BATCH_CMD
  delete env.TTS_URL
  const r = spawnSync(process.execPath, [SCRIPT, ...args, '--demo-tts'], { encoding: 'utf8', env })
  assert.equal(r.status, 0, r.stderr + r.stdout)
  return r.stdout
}

test('prerender caches by text hash and re-renders only on face change', { skip: !hasFfmpeg && 'ffmpeg missing' }, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'prerender-'))
  try {
    const beats = path.join(dir, 'beats.json')
    fs.writeFileSync(beats, JSON.stringify({ beats: [{ say: 'Line one.' }, { say: 'Line two, a little longer.' }] }))
    const faceA = path.join(dir, 'a.png')
    const faceB = path.join(dir, 'b.png')
    makeFace(faceA, 'red')
    makeFace(faceB, 'blue')
    const out = path.join(dir, 'clips')

    const first = render(['--beats', beats, '--face', faceA, '--out', out])
    assert.match(first, /rendered 2, from cache 0/)
    const index = JSON.parse(fs.readFileSync(path.join(out, 'index.json'), 'utf8'))
    assert.equal(index.beats.length, 2)
    for (const b of index.beats) assert.ok(fs.existsSync(path.join(out, b.file)))

    const second = render(['--beats', beats, '--face', faceA, '--out', out])
    assert.match(second, /rendered 0, from cache 2/)
    assert.match(second, /synthesized this run: 0 characters/)

    // new face: video re-rendered, audio reused (no synthesis), stale clips removed
    const third = render(['--beats', beats, '--face', faceB, '--out', out])
    assert.match(third, /rendered 2, from cache 0, removed 2 stale/)
    assert.match(third, /synthesized this run: 0 characters/)

    // a probe run must never delete anything
    fs.writeFileSync(beats, JSON.stringify([{ say: 'Line one.' }]))
    const before = fs.readdirSync(out).length
    render(['--beats', beats, '--face', faceB, '--out', out, '--limit', '1'])
    assert.equal(fs.readdirSync(out).length, before)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})
