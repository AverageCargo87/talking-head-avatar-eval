import { test } from 'node:test'
import assert from 'node:assert/strict'
import { CLIP_FILE, fillCmd, hashBytes, hashText, renderSignature, splitCmd, videoName } from '../clip-cache.mjs'

test('hashText is stable, 8 hex chars, code-point based', () => {
  assert.equal(hashText(''), '00001505')            // 5381
  assert.match(hashText('Привет! Я Лена.'), /^[0-9a-f]{8}$/)
  assert.equal(hashText('abc'), hashText('abc'))
  assert.notEqual(hashText('abc'), hashText('abd'))
  // an astral character is ONE code point, not two UTF-16 units
  assert.notEqual(hashText('\u{1F600}'), hashText('\uD83D') + hashText('\uDE00'))
})

test('hashBytes over raw bytes', () => {
  assert.equal(hashBytes(Buffer.alloc(0)), '00001505')
  assert.notEqual(hashBytes(Buffer.from([1, 2, 3])), hashBytes(Buffer.from([1, 2, 4])))
})

test('render signature changes with the face and with the engine, not with nothing', () => {
  const face = Buffer.from('face-a')
  const s1 = renderSignature(face, 'engine-1')
  assert.equal(s1, renderSignature(Buffer.from('face-a'), 'engine-1'))
  assert.notEqual(s1, renderSignature(Buffer.from('face-b'), 'engine-1'))
  assert.notEqual(s1, renderSignature(face, 'engine-2'))
  assert.equal(s1.length, 6)
})

test('regression: commands differing only in their last characters get different signatures', () => {
  // the original top-24-bits-of-djb2 signature collided on exactly this
  const face = Buffer.from('portrait bytes')
  const base = 'python lipsync_run.py --face {face} --audio {audio} --out {out} --steps 2'
  const sigs = new Set(['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'].map((d) => renderSignature(face, base + d)))
  assert.equal(sigs.size, 10)
  const top6 = (b) => hashBytes(b).slice(0, 6)
  const djb = new Set(['0', '1', '2'].map((d) => top6(Buffer.concat([face, Buffer.from(base + d)]))))
  assert.equal(djb.size, 1, 'documents why djb2 top bits were replaced')
})

test('clip names match the cleanup pattern, foreign files do not', () => {
  assert.ok(CLIP_FILE.test(videoName('0a1b2c3d', 'abcdef')))
  assert.ok(CLIP_FILE.test('clip-0a1b2c3d.mp3'))
  assert.ok(!CLIP_FILE.test('index.json'))
  assert.ok(!CLIP_FILE.test('notes.mp4'))
})

test('splitCmd keeps quoted filter graphs whole', () => {
  const cmd = 'ffmpeg -i "a b.png" -filter_complex "[0:v]zoompan=z=\'min(1.06,1+0.0006*on)\':d=1[v]" -map "[v]" out.mp4'
  assert.deepEqual(splitCmd(cmd), ['ffmpeg', '-i', 'a b.png', '-filter_complex',
    "[0:v]zoompan=z='min(1.06,1+0.0006*on)':d=1[v]", '-map', '[v]', 'out.mp4'])
  assert.deepEqual(splitCmd('a "" b'), ['a', '', 'b'])
})

test('fillCmd substitutes every occurrence', () => {
  assert.equal(fillCmd('{a} {b} {a}', { a: 'x', b: 'y' }), 'x y x')
})
