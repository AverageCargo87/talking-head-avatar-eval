#!/usr/bin/env node
// Mock avatar runner as its own process: no SDK, no key, no model files. The lesson talks to
// it exactly as it talks to the real runner (runner/bithuman_runner.py).
//
//   MOCK_PORT=8090 node runner/mock-runner.mjs      # host via MOCK_HOST (default localhost)
//
// The engine itself (frames, face choice, talking/silent) lives in mock-core.mjs.
import http from 'node:http'
import { CORS, faces, handleMock } from './mock-core.mjs'

const PORT = +(process.env.MOCK_PORT || 8090)
const HOST = process.env.MOCK_HOST || 'localhost'

const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://mock.local')
  const sub = u.pathname.replace(/^\/+/, '')
  if (handleMock(req, res, sub, u.searchParams)) return
  res.writeHead(404, CORS)
  res.end('mock runner: not found')
})

server.listen(PORT, HOST, () => console.log(
  `mock avatar runner on http://${HOST}:${PORT} (/health /avatars /stream /push /keepalive), faces: ` +
  faces().map((f) => f.id).join(', ')))

for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { server.closeAllConnections?.(); server.close(); process.exit(0) })
