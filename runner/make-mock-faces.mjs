#!/usr/bin/env node
// Draws placeholder faces for the mock runner: one folder per face, six frames in each
// (talk0..talk4: mouth from closed to wide open; blink).
//
// Why: the lesson got a FACE PICKER for the video teacher, while the real vendor faces need
// a paid key. Until a key exists the picker still has to be tested on something: the mock
// serves these frames and behaves exactly like the real runner. The frames are flat on
// purpose, so nobody mistakes the mock for a real avatar.
//
//   npm install            # playwright-core (uses the installed Google Chrome, or CHROME_PATH)
//   node runner/make-mock-faces.mjs
//   -> runner/faces/<id>/{talk0..talk4,blink}.jpg + runner/faces/faces.json
//
// The generated frames are committed, so the mock runs without this step.
import { chromium } from 'playwright-core'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), 'faces')

// Five teachers that do not look alike: hair, skin, clothes, glasses, beard.
// Order = order in the lesson's face picker.
const FACES = [
  { id: 'anya', name: 'Anya, dark bob', skin: '#E8BE99', hair: '#5B3A2A', style: 'bob', cloth: '#46687C', bg: '#1B2430' },
  { id: 'vera', name: 'Vera, bun and glasses', skin: '#F0CDAE', hair: '#C9A24B', style: 'bun', cloth: '#4E7A5E', bg: '#1E2A28', glasses: true },
  { id: 'viktor', name: 'Viktor, beard', skin: '#D9A87C', hair: '#2E2A28', style: 'short', cloth: '#5A5560', bg: '#232028', beard: true },
  { id: 'zarina', name: 'Zarina, long hair', skin: '#B98058', hair: '#1F1A20', style: 'long', cloth: '#7A3B4A', bg: '#241E26' },
  { id: 'oleg', name: 'Oleg, grey hair', skin: '#E3C0A4', hair: '#C8C4BE', style: 'short', cloth: '#6B5233', bg: '#262218', glasses: true },
]

const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : { channel: 'chrome' })
const page = await browser.newPage({ viewport: { width: 400, height: 440 } })
await page.setContent('<canvas id=c width=360 height=400></canvas>')

const drawn = await page.evaluate((faces) => {
  const c = document.getElementById('c'), x = c.getContext('2d')
  const rr = (X, Y, W, H, R) => { x.beginPath(); x.moveTo(X + R, Y)
    x.arcTo(X + W, Y, X + W, Y + H, R); x.arcTo(X + W, Y + H, X, Y + H, R)
    x.arcTo(X, Y + H, X, Y, R); x.arcTo(X, Y, X + W, Y, R); x.closePath() }
  const dark = (hex, k) => { const n = parseInt(hex.slice(1), 16)
    const r = Math.round(((n >> 16) & 255) * k), g = Math.round(((n >> 8) & 255) * k), b = Math.round((n & 255) * k)
    return `rgb(${r},${g},${b})` }

  function draw(f, open, blink) {
    x.fillStyle = f.bg; x.fillRect(0, 0, 360, 400)
    // long hair lies BEHIND the head and shoulders: draw it first
    if (f.style === 'long') { x.fillStyle = dark(f.hair, 0.92)
      x.beginPath(); x.ellipse(180, 210, 104, 150, 0, 0, 6.283); x.fill() }
    x.fillStyle = f.cloth                                            // shoulders
    x.beginPath(); x.ellipse(180, 470, 140, 165, 0, 0, 6.283); x.fill()
    x.fillStyle = dark(f.skin, 0.88); rr(158, 244, 44, 62, 16); x.fill()   // neck
    x.fillStyle = f.skin                                             // head and ears
    x.beginPath(); x.ellipse(180, 186, 78, 92, 0, 0, 6.283); x.fill()
    x.beginPath(); x.ellipse(104, 192, 12, 16, 0, 0, 6.283); x.fill()
    x.beginPath(); x.ellipse(256, 192, 12, 16, 0, 0, 6.283); x.fill()
    x.fillStyle = f.hair                                             // hair style
    if (f.style === 'bob') {
      x.beginPath(); x.ellipse(180, 152, 82, 76, 0, Math.PI, 0); x.fill()
      x.fillRect(98, 148, 26, 84); x.fillRect(236, 148, 26, 84)
    } else if (f.style === 'bun') {
      x.beginPath(); x.ellipse(180, 150, 80, 70, 0, Math.PI, 0); x.fill()
      x.beginPath(); x.arc(180, 74, 30, 0, 6.283); x.fill()
    } else if (f.style === 'short') {
      x.beginPath(); x.ellipse(180, 156, 80, 68, 0, Math.PI, 0); x.fill()
      rr(104, 150, 12, 30, 6); x.fill(); rr(244, 150, 12, 30, 6); x.fill()   // temples, not squares
    } else {
      x.beginPath(); x.ellipse(180, 150, 82, 74, 0, Math.PI, 0); x.fill()
      // strands go BEHIND the face outline and are rounded: flush with the cheek they made the face square
      rr(92, 148, 24, 120, 12); x.fill(); rr(244, 148, 24, 120, 12); x.fill()
    }
    // the beard follows the JAW LINE: rectangles on the sides made the face square
    if (f.beard) { x.fillStyle = dark(f.hair, 1.05)
      x.beginPath(); x.moveTo(112, 188)
      x.quadraticCurveTo(122, 272, 180, 280); x.quadraticCurveTo(238, 272, 248, 188)
      x.quadraticCurveTo(216, 220, 180, 220); x.quadraticCurveTo(144, 220, 112, 188)
      x.fill()
      x.beginPath(); x.ellipse(180, 214, 34, 11, 0, 0, 6.283); x.fill() }   // moustache
    x.strokeStyle = dark(f.hair, 0.9); x.lineWidth = 6; x.lineCap = 'round'   // brows
    x.beginPath(); x.moveTo(136, 152); x.lineTo(170, 148); x.stroke()
    x.beginPath(); x.moveTo(190, 148); x.lineTo(224, 152); x.stroke()
    if (blink) { x.strokeStyle = '#3A2E28'; x.lineWidth = 5                   // eyes
      x.beginPath(); x.moveTo(138, 176); x.lineTo(168, 176); x.stroke()
      x.beginPath(); x.moveTo(192, 176); x.lineTo(222, 176); x.stroke()
    } else {
      for (const ex of [153, 207]) {
        x.fillStyle = '#FFFFFF'; x.beginPath(); x.ellipse(ex, 176, 15, 12, 0, 0, 6.283); x.fill()
        x.fillStyle = '#26313D'; x.beginPath(); x.arc(ex + 2, 176, 6.5, 0, 6.283); x.fill()
        x.fillStyle = 'rgba(255,255,255,.85)'; x.beginPath(); x.arc(ex + 4.5, 173, 2.2, 0, 6.283); x.fill()
      }
    }
    x.strokeStyle = dark(f.skin, 0.78); x.lineWidth = 4                      // nose
    x.beginPath(); x.moveTo(181, 182); x.lineTo(175, 208); x.stroke()
    // mouth: open 0..4, from closed lips to a wide "a"
    const k = open / 4, mw = 44 + k * 10, mh = 5 + k * 30
    x.fillStyle = '#7A2630'
    x.beginPath(); x.ellipse(180, 232 + mh * 0.18, mw / 2, mh / 2, 0, 0, 6.283); x.fill()
    if (open >= 2) { x.fillStyle = '#F4EDE6'
      x.beginPath(); x.ellipse(180, 232 - mh * 0.28, mw / 2 - 5, Math.min(7, mh * 0.18), 0, 0, 6.283); x.fill() }
    if (open >= 3) { x.fillStyle = '#B84653'
      x.beginPath(); x.ellipse(180, 232 + mh * 0.30, mw / 2 - 9, mh * 0.20, 0, 0, 6.283); x.fill() }
    if (f.glasses) { x.strokeStyle = '#2B2B31'; x.lineWidth = 4                // glasses on top
      x.beginPath(); x.ellipse(153, 176, 26, 21, 0, 0, 6.283); x.stroke()
      x.beginPath(); x.ellipse(207, 176, 26, 21, 0, 0, 6.283); x.stroke()
      x.beginPath(); x.moveTo(179, 174); x.lineTo(181, 174); x.stroke()
      x.beginPath(); x.moveTo(127, 172); x.lineTo(108, 168); x.stroke()
      x.beginPath(); x.moveTo(233, 172); x.lineTo(252, 168); x.stroke() }
    // a "this is a mock" badge, so nobody takes it for a real avatar
    x.fillStyle = 'rgba(255,255,255,.10)'; rr(14, 14, 96, 30, 10); x.fill()
    x.fillStyle = 'rgba(255,255,255,.72)'; x.font = '600 15px Segoe UI, sans-serif'; x.textAlign = 'left'
    x.fillText('MOCK', 34, 34)
    return c.toDataURL('image/jpeg', 0.84)
  }

  const out = {}
  for (const f of faces) {
    out[f.id] = { name: f.name, frames: {} }
    for (let i = 0; i <= 4; i++) out[f.id].frames['talk' + i] = draw(f, i, false)
    out[f.id].frames.blink = draw(f, 0, true)
  }
  return out
}, FACES)

let n = 0
for (const [id, f] of Object.entries(drawn)) {
  const dir = path.join(OUT, id)
  fs.mkdirSync(dir, { recursive: true })
  for (const [frame, url] of Object.entries(f.frames)) {
    fs.writeFileSync(path.join(dir, frame + '.jpg'), Buffer.from(url.split(',')[1], 'base64'))
    n++
  }
  console.log('  ' + id.padEnd(8) + ' ' + f.name)
}
// the face list sits next to the frames: the mock serves it to the browser as /avatars
fs.writeFileSync(path.join(OUT, 'faces.json'), JSON.stringify(FACES.map(({ id, name }) => ({ id, name })), null, 2) + '\n')
console.log(`${n} frames, ${FACES.length} faces -> ${OUT}`)
await browser.close()
