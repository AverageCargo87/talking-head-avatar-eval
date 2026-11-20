import { test } from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'
import { faces, handleMock, pickFrame } from '../mock-core.mjs'

const PORT = 41602

test('committed mock faces are listed', () => {
  const list = faces()
  assert.equal(list.length, 5)
  for (const f of list) assert.ok(f.id && f.name)
})

test('pickFrame: closed mouth and periodic blink when silent', () => {
  const set = { talk: ['t0', 't1', 't2', 't3', 't4'], blink: 'b' }
  assert.equal(pickFrame(set, 0, 0), 'b')
  assert.equal(pickFrame(set, 5, 0), 't0')
})

test('push makes the mock talk for the duration of the audio', async () => {
  const server = http.createServer((req, res) => {
    const u = new URL(req.url, 'http://mock.local')
    if (!handleMock(req, res, u.pathname.slice(1), u.searchParams)) { res.writeHead(404); res.end() }
  })
  await new Promise((r) => server.listen(PORT, 'localhost', r))
  try {
    const base = `http://localhost:${PORT}`
    const pcm = Buffer.alloc(16000 * 2 * 2)            // 2 s of silence, PCM16 mono 16 kHz
    const r = await fetch(base + '/push', { method: 'POST', body: JSON.stringify({ b64: pcm.toString('base64') }) })
    assert.deepEqual(await r.json(), { ok: true, seconds: 2 })
    const h = await (await fetch(base + '/health')).json()
    assert.equal(h.mock, true)
    assert.equal(h.talking, true)
    const bad = await fetch(base + '/push', { method: 'POST', body: '{}' })
    assert.equal(bad.status, 400)
  } finally {
    server.closeAllConnections?.()
    await new Promise((r) => server.close(r))
  }
})
